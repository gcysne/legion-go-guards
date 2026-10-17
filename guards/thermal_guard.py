#!/usr/bin/env python3
"""thermal-guard: warn about high temperatures and kernel thermal events.

- Polls CPU (Tctl) and GPU (edge) temperatures. A temperature at or above
  warn_c for sustain_seconds starts a "hot episode" (warning); at or above
  critical_c it escalates (critical, repeated every renotify_minutes).
  The episode ends when the temperature drops below warn_c - hysteresis_c,
  and its duration and peak are logged.
- Follows the kernel log for thermal messages (critical trip, PROCHOT, ...).
- Writes a heartbeat (snapshot of temps/power/battery/game) every
  heartbeat_seconds. reboot-reason-guard reads the last heartbeat of the
  previous boot to explain an abrupt power-off.
"""

import argparse
import json
import re
import sys
import threading
import time

import guardlib as g

THERMAL_PATTERNS = [
    re.compile(p, re.I) for p in (
        r"critical temperature reached",
        r"thermal.*(emergency|shutting down|shutdown|overheat)",
        r"\bPROCHOT\b",
        r"temperature above threshold",
        r"amdgpu.*(over.?temp|thermal).*(alert|critical|shutdown|throttl)",
        r"(hardware|hw) thermal (trip|shutdown)",
    )
]
# Boot-time chatter that would otherwise match.
THERMAL_IGNORE = re.compile(r"Registered thermal governor|registered as thermal_zone|Thermal Zone \[\w+\] \(\d+ C\)$", re.I)


def is_thermal_message(msg):
    return not THERMAL_IGNORE.search(msg) and any(p.search(msg) for p in THERMAL_PATTERNS)


class ThermalMonitor:
    def __init__(self, cfg, log, notifier):
        self.t = cfg["thermal"]
        self.log, self.notify = log, notifier
        self.level = "normal"
        self.above_since = None
        self.crit_count = 0
        self.episode = None
        self.last_notify = 0.0

    def step(self, now, temps):
        vals = {k: v for k, v in temps.items() if k in ("cpu_c", "gpu_c") and v is not None}
        if not vals:
            return
        sensor, temp = max(vals.items(), key=lambda kv: kv[1])
        warn, crit = self.t["warn_c"], self.t["critical_c"]
        label = "CPU" if sensor == "cpu_c" else "GPU"

        if self.episode:
            if temp > self.episode["peak_c"]:
                self.episode.update(peak_c=temp, peak_sensor=label, peak_context=g.snapshot())
            if temp < warn - self.t["hysteresis_c"]:
                dur = now - self.episode["start"]
                self.log.write("hot_episode_end", "info",
                               f"temperatures back to normal after {dur/60:.1f} min, peak {self.episode['peak_sensor']} "
                               f"{self.episode['peak_c']:.0f}C (max level {self.episode['max_level']})",
                               duration_s=round(dur), peak_c=self.episode["peak_c"],
                               context=self.episode["peak_context"])
                self.episode, self.level, self.above_since, self.crit_count = None, "normal", None, 0
                return

        if temp >= crit:
            self.crit_count += 1
        else:
            self.crit_count = 0
        if temp >= warn:
            self.above_since = self.above_since or now
        elif not self.episode:
            self.above_since = None

        if self.crit_count >= 2 and self.level != "critical":
            self._escalate(now, "critical", label, temp)
        elif self.level == "critical" and self.crit_count >= 2 and \
                now - self.last_notify >= self.t["renotify_minutes"] * 60:
            self._escalate(now, "critical", label, temp, repeat=True)
        elif self.level == "normal" and self.above_since and \
                now - self.above_since >= self.t["sustain_seconds"]:
            self._escalate(now, "warning", label, temp)

    def _escalate(self, now, level, label, temp, repeat=False):
        ctx = g.snapshot()
        if not self.episode:
            self.episode = {"start": now, "peak_c": temp, "peak_sensor": label,
                            "peak_context": ctx, "max_level": level}
        self.episode["max_level"] = level
        self.level, self.last_notify = level, now
        limit = self.t["critical_c"] if level == "critical" else self.t["warn_c"]
        summary = f"{label} at {temp:.0f}C (limit {limit:.0f}C)" + (" - still critical" if repeat else "")
        self.log.write("hot_" + level, level, summary, temp_c=temp, sensor=label, context=ctx)
        body = g.format_context(ctx)
        self.notify.send(f"{'CRITICAL: ' if level == 'critical' else ''}{label} temperature {temp:.0f}C",
                         body, critical=(level == "critical"))


def write_heartbeat(boot_id):
    ctx = g.snapshot()
    ctx["time"] = time.time()
    path = g.STATE_DIR / f"heartbeat-{boot_id}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(ctx, default=str))
    tmp.replace(path)


def prune_heartbeats(keep=20):
    files = sorted(g.STATE_DIR.glob("heartbeat-*.json"), key=lambda p: p.stat().st_mtime)
    for p in files[:-keep]:
        p.unlink(missing_ok=True)


def kernel_watch(log, notifier):
    proc = g.follow_journal("-k")
    for line in proc.stdout:
        try:
            msg = g.message(json.loads(line))
        except ValueError:
            continue
        if is_thermal_message(msg):
            log.write("kernel_thermal", "critical", msg.strip()[:300], context=g.snapshot())
            notifier.send("Kernel thermal event", msg.strip()[:200], critical=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--once", action="store_true", help="print one snapshot and exit")
    ap.add_argument("--test-notify", action="store_true", help="send a test warning and critical alert")
    ap.add_argument("--warn", type=float, help="override warn_c (testing)")
    ap.add_argument("--critical", type=float, help="override critical_c (testing)")
    a = ap.parse_args()

    cfg = g.load_config()
    if a.warn is not None:
        cfg["thermal"]["warn_c"] = a.warn
    if a.critical is not None:
        cfg["thermal"]["critical_c"] = a.critical

    if a.once:
        print(json.dumps(g.snapshot(), indent=2, default=str))
        return 0
    log, notifier = g.EventLog(cfg, "thermal-events"), g.Notifier(cfg, "thermal-guard")
    if a.test_notify:
        notifier.send("thermal-guard test (warning)", "If you can read this, warnings work.")
        time.sleep(2)
        notifier.send("thermal-guard test (critical)", "If you can read this, critical alerts work.", critical=True)
        return 0

    boot_id = g.current_boot_id()
    t = cfg["thermal"]
    print(f"thermal-guard started: warn {t['warn_c']}C, critical {t['critical_c']}C, "
          f"log {log.text}", flush=True)
    threading.Thread(target=kernel_watch, args=(log, notifier), daemon=True).start()

    mon = ThermalMonitor(cfg, log, notifier)
    last_hb = 0.0
    prune_heartbeats()
    while True:
        now = time.monotonic()
        mon.step(now, g.read_temps())
        if now - last_hb >= t["heartbeat_seconds"]:
            write_heartbeat(boot_id)
            notifier.flush()
            last_hb = now
        time.sleep(t["poll_seconds"])


if __name__ == "__main__":
    sys.exit(main())
