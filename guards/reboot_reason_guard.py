#!/usr/bin/env python3
"""reboot-reason-guard: explain every shutdown that was not a normal user
request, and keep a log of kernel/GPU/memory/crash events for debugging games.

Once per boot it classifies how the PREVIOUS boot ended, from:
  - the AMD firmware reset reason the kernel prints at boot
    ("x86/amd: Previous system reset reason [0x...]: ...", FCH S5 status),
  - the end of the previous boot's journal (logind "will reboot/power off now!",
    kernel panic/oops/thermal/GPU messages),
  - the last heartbeat thermal-guard wrote in that boot (battery, AC, temps, game),
  - new kdumpst / steamos-log-submitter crash dumps.

While running it follows the journal and the crash-dump folders and logs
GPU hangs/resets/faults, kernel oopses/lockups, machine-check errors, OOM
kills and process crashes, each with a snapshot (temps, power, TDP, game).
"""

import argparse
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import guardlib as g
from thermal_guard import is_thermal_message

# arch/x86/kernel/cpu/amd.c, s5_reset_reason_txt[] (kernel 6.16+)
RESET_REASONS = {
    0: "thermal pin BP_THERMTRIP_L was tripped",
    1: "power button was pressed for 4 seconds",
    2: "shutdown pin was tripped",
    4: "remote ASF power off command was received",
    9: "internal CPU thermal limit was tripped",
    16: "system reset pin BP_SYS_RST_L was tripped",
    17: "software issued PCI reset",
    18: "software wrote 0x4 to reset control register 0xCF9",
    19: "software wrote 0x6 to reset control register 0xCF9",
    20: "software wrote 0xE to reset control register 0xCF9",
    21: "ACPI power state transition occurred",
    22: "keyboard reset pin KB_RST_L was tripped",
    23: "internal CPU shutdown event occurred",
    24: "system failed to boot before failed boot timer expired",
    25: "hardware watchdog timer expired",
    26: "remote ASF reset command was received",
    27: "an uncorrected error caused a data fabric sync flood event",
    29: "FCH and MP1 failed warm reset handshake",
    30: "a parity error occurred",
    31: "a software sync flood event occurred",
}
THERMAL_BITS = {0, 9}
HW_FAULT_BITS = {23, 27, 29, 30, 31}
RESET_RE = re.compile(r"Previous system reset reason \[0x([0-9a-fA-F]+)\]")

# (kind, severity, notify, pattern). Order matters: first match wins.
EVENT_RULES = [
    ("kernel_panic", "critical", True, r"Kernel panic"),
    ("lockup", "error", True, r"soft lockup|hard LOCKUP|blocked for more than \d+ seconds|rcu_\w+ (self-)?detected stalls"),
    ("kernel_oops", "error", True, r"\bOops\b|kernel BUG at|\bBUG: |general protection fault"),
    ("machine_check", "critical", True, r"mce: \[Hardware Error\]|Machine check events logged|\[Hardware Error\]"),
    ("pcie_error", "warning", False, r"PCIe Bus Error|AER: .*error"),
    ("gpu_hang", "error", True, r"amdgpu.*(ring \S+ timeout|GPU reset|gpu_recover|GPU recovery|soft recovered|device wedged|GPU hang)"),
    ("gpu_hang", "error", True, r"\*ERROR\*.*(flip_done timed out|hw_done or flip_done timed out)"),
    ("gpu_fault", "error", False, r"amdgpu.*(page fault|PROTECTION_FAULT|\[gfxhub\]|\[mmhub\])"),
    ("gpu_device_lost", "error", False, r"VK_ERROR_DEVICE_LOST"),
    ("gpu_error", "warning", False, r"amdgpu.*\*ERROR\*|\[drm\] \*ERROR\*"),
    ("devcoredump", "error", True, r"devcoredump|amdgpu.*coredump"),
    ("oom_kill", "error", True, r"Out of memory: Killed process|oom-kill:|earlyoom.*(sending SIG|killing process)"),
    ("process_crash", "warning", False, r"Process \d+ \(.+?\) of user \d+ (dumped core|terminated abnormally without)"),
]
EVENT_RULES = [(k, s, n, re.compile(p, re.I)) for k, s, n, p in EVENT_RULES]
# Known-harmless lines that match the rules above.
EVENT_IGNORE = re.compile(r"Command line:|ras ta ucode|ring \S+ uses VM inv eng", re.I)

ACTION_RE = re.compile(r"The system will (reboot|power off|halt|suspend|hibernate|suspend-then-hibernate|kexec|soft-reboot) now!")
RESUMED_RE = re.compile(r"Operation '(suspend|hibernate|suspend-then-hibernate)' finished")
POWER_KEY_LONG_RE = re.compile(r"Power key pressed long")

DUMP_DIRS = [Path("/home/.steamos/offload/var/kdumpst"), Path("/var/crash/kdumpst")] + [
    Path("/var/lib/steamos-log-submitter") / state / kind
    for state in ("pending", "failed", "uploaded")
    for kind in ("kdump", "gpu", "devcoredump", "earlyoom", "minidump")
]
SEVERE_DUMPS = ("kdump", "kdumpst", "gpu", "devcoredump")


OWN_UNITS = {"thermal-guard.service", "reboot-reason-guard.service"}


def is_own_record(rec):
    """Our own log lines echo matched messages; reading them back would loop."""
    return (rec.get("_SYSTEMD_USER_UNIT") in OWN_UNITS or rec.get("_SYSTEMD_UNIT") in OWN_UNITS
            or rec.get("_PID") == str(os.getpid()))


def classify_event(msg):
    if EVENT_IGNORE.search(msg):
        return None
    for kind, sev, notify, rx in EVENT_RULES:
        if rx.search(msg):
            return kind, sev, notify
    return None


# --------------------------------------------------------- boot analysis

def list_boots():
    """Oldest first; systemd 257 prints one JSON array."""
    out = subprocess.run(["journalctl", "--no-pager", "--list-boots", "-o", "json"],
                         capture_output=True, text=True).stdout
    try:
        return json.loads(out)
    except ValueError:
        return []


def reset_reason(boot_id):
    for rec in g.journal_json("-k", "-b", boot_id, "-n", "5000"):
        m = RESET_RE.search(g.message(rec))
        if m:
            value = int(m.group(1), 16)
            bits = {b for b in range(32) if value >> b & 1}
            return value, bits, [RESET_REASONS[b] for b in sorted(bits) if b in RESET_REASONS]
    return None, set(), []


def scan_boot_end(boot_id, tail=4000):
    """Facts about how a boot ended, from its last journal entries."""
    facts = {"action": None, "resumed_after_action": False, "power_key_long": False,
             "thermal": [], "severe": [], "last_entry": None}
    for rec in g.journal_json("-b", boot_id, "-n", str(tail)):
        if is_own_record(rec):
            continue
        msg = g.message(rec)
        ts = int(rec.get("__REALTIME_TIMESTAMP", 0)) / 1e6
        facts["last_entry"] = ts
        m = ACTION_RE.search(msg)
        if m:
            facts["action"], facts["resumed_after_action"] = m.group(1), False
        elif RESUMED_RE.search(msg):
            facts["resumed_after_action"] = True
        if POWER_KEY_LONG_RE.search(msg):
            facts["power_key_long"] = True
        if rec.get("_TRANSPORT") == "kernel" and is_thermal_message(msg):
            facts["thermal"].append(msg.strip()[:200])
        ev = classify_event(msg)
        if ev and ev[1] in ("critical", "error"):
            facts["severe"].append(f"{ev[0]}: {msg.strip()[:200]}")
    facts["severe"] = facts["severe"][-8:]
    facts["thermal"] = facts["thermal"][-5:]
    return facts


def new_dumps_since(t0):
    found = []
    for d in DUMP_DIRS:
        try:
            for p in d.iterdir():
                if p.stat().st_mtime >= t0:
                    found.append(str(p))
        except OSError:
            continue
    return found


def load_heartbeat(boot_id):
    try:
        return json.loads((g.STATE_DIR / f"heartbeat-{boot_id}.json").read_text())
    except (OSError, ValueError):
        return None


def classify_boot_end(bits, facts, heartbeat, dumps, critical_c=97.0):
    """Returns (category, severity, explanation)."""
    action = facts["action"]
    clean_request = action in ("reboot", "power off", "halt", "kexec", "soft-reboot")
    died_in_suspend = action in ("suspend", "hibernate", "suspend-then-hibernate") and not facts["resumed_after_action"]
    panic_dump = any("kdump" in d for d in dumps)  # kdumpst folder or log-submitter kdump/

    if bits & THERMAL_BITS:
        return "thermal_shutdown_hw", "critical", "firmware thermal trip: " + "; ".join(
            RESET_REASONS[b] for b in sorted(bits & THERMAL_BITS))
    if facts["thermal"]:
        return "thermal_shutdown_kernel", "critical", "kernel thermal event before shutdown: " + facts["thermal"][-1]
    if panic_dump or any(s.startswith("kernel_panic") for s in facts["severe"]):
        return "kernel_panic", "critical", "kernel panic (kdumpst saved a dump)" if panic_dump else "kernel panic in log"
    if 25 in bits:
        return "watchdog_reset", "critical", RESET_REASONS[25]
    if bits & HW_FAULT_BITS:
        return "hardware_fault", "critical", "; ".join(RESET_REASONS[b] for b in sorted(bits & HW_FAULT_BITS))
    if clean_request:
        return "normal_" + action.replace(" ", "_"), "info", f"requested {action}" + (
            " (power button held)" if facts["power_key_long"] else "")
    if 1 in bits:
        return "forced_power_off", "warning", "power button held 4 s (forced off)"
    hb_hot = heartbeat and max(heartbeat.get("cpu_c") or 0, heartbeat.get("gpu_c") or 0) >= critical_c
    hb_low = heartbeat and heartbeat.get("ac") is False and (heartbeat.get("battery") or 100) <= 3
    if died_in_suspend:
        why = "battery ran out while suspended" if hb_low else "did not resume from " + action
        return "died_in_suspend", "error", why
    if hb_low:
        return "battery_depleted", "error", f"battery at {heartbeat.get('battery')}% on battery power"
    if hb_hot:
        return "suspected_thermal", "critical", "abrupt end while running hot (last heartbeat)"
    return "unclean_shutdown", "error", "log ends without a shutdown request (crash, hang, or power loss)"


def analyze(prev_id, next_id, critical_c=97.0):
    value, bits, reasons = reset_reason(next_id) if next_id else (None, set(), [])
    facts = scan_boot_end(prev_id)
    hb = load_heartbeat(prev_id)
    t0 = facts["last_entry"] - 600 if facts["last_entry"] else time.time() - 3600
    dumps = new_dumps_since(t0) if next_id == g.current_boot_id() else []
    cat, sev, why = classify_boot_end(bits, facts, hb, dumps, critical_c)
    return {
        "boot_id": prev_id, "category": cat, "severity": sev, "explanation": why,
        "reset_reason": f"0x{value:08x}" if value is not None else None,
        "reset_reason_text": reasons,
        "ended": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(facts["last_entry"])) if facts["last_entry"] else None,
        "last_action": facts["action"], "kernel_events": facts["severe"] + facts["thermal"],
        "dumps": dumps, "last_heartbeat": hb,
    }


def boot_check(cfg, log, notifier, history):
    state_file = g.STATE_DIR / "reboot-reason-guard.json"
    try:
        state = json.loads(state_file.read_text())
    except (OSError, ValueError):
        state = {"analyzed": []}
    boots = list_boots()
    if len(boots) < 2:
        return
    prev, cur = boots[-2]["boot_id"], boots[-1]["boot_id"]
    if prev in state["analyzed"]:
        return
    r = analyze(prev, cur, cfg["thermal"]["critical_c"])
    with open(history, "a") as f:
        f.write(f"{r['ended']}  {r['category']:24} {r['explanation']}  [reset {r['reset_reason']}] boot {prev[:8]}\n")
    if r["severity"] != "info":
        hb = r["last_heartbeat"] or {}
        log.write("abnormal_shutdown", r["severity"], f"previous boot ended {r['ended']}: {r['category']} - {r['explanation']}",
                  **{k: v for k, v in r.items() if k != "last_heartbeat"}, context=hb)
        notifier.send(f"Last shutdown was not normal: {r['category'].replace('_', ' ')}",
                      f"{r['explanation']} (at {r['ended']})", critical=(r["severity"] == "critical"))
    state["analyzed"] = (state["analyzed"] + [prev])[-50:]
    state_file.write_text(json.dumps(state))


# ------------------------------------------------------------ live watch

def journal_reader(q):
    proc = g.follow_journal()
    for line in proc.stdout:
        try:
            q.put(json.loads(line))
        except ValueError:
            continue


class DumpWatcher:
    def __init__(self):
        self.file = g.STATE_DIR / "seen-dumps.json"
        try:
            self.seen = set(json.loads(self.file.read_text()))
            self.first_run = False
        except (OSError, ValueError):
            self.seen, self.first_run = set(), True

    def scan(self):
        current = set()
        for d in DUMP_DIRS:
            try:
                current |= {str(p) for p in d.iterdir()}
            except OSError:
                continue
        new = [] if self.first_run else sorted(current - self.seen)
        # uploaded/failed are the same dump moving folders: match on file name
        seen_names = {os.path.basename(p) for p in self.seen}
        new = [p for p in new if os.path.basename(p) not in seen_names]
        self.seen, self.first_run = current, False
        self.file.write_text(json.dumps(sorted(current)))
        return new


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--analyze-all", action="store_true", help="classify every boot in the journal and print (no logging)")
    ap.add_argument("--boot-check-only", action="store_true", help="run the previous-boot check and exit")
    a = ap.parse_args()
    cfg = g.load_config()

    if a.analyze_all:
        boots = list_boots()
        for prev, nxt in zip(boots, boots[1:] + [None]):
            if nxt is None:
                print(f"{prev['boot_id'][:8]}  (current boot)")
                break
            r = analyze(prev["boot_id"], nxt["boot_id"], cfg["thermal"]["critical_c"])
            print(f"{prev['boot_id'][:8]}  ended {r['ended']}  {r['category']:24} {r['explanation']}  "
                  f"[reset {r['reset_reason']}: {', '.join(r['reset_reason_text'])}]")
            for e in r["kernel_events"]:
                print(f"            {e}")
        return 0

    log = g.EventLog(cfg, "system-events")
    notifier = g.Notifier(cfg, "reboot-reason-guard")
    history = Path(cfg["log_dir"]) / "boot-history.log"
    boot_check(cfg, log, notifier, history)
    if a.boot_check_only:
        return 0

    print(f"reboot-reason-guard watching journal and crash dumps, log {log.text}", flush=True)
    q = queue.Queue()
    threading.Thread(target=journal_reader, args=(q,), daemon=True).start()
    dumps = DumpWatcher()
    dumps.scan()
    window = cfg["system"]["aggregate_seconds"]
    recent = {}  # key -> [first_seen, extra_count, kind, severity]
    last_scan = time.monotonic()

    while True:
        try:
            rec = q.get(timeout=5)
        except queue.Empty:
            rec = None
        now = time.monotonic()
        if rec and not is_own_record(rec):
            msg = g.message(rec)
            ev = classify_event(msg)
            if ev:
                kind, sev, notify = ev
                key = (kind, re.sub(r"\d+", "#", msg)[:120])
                if key in recent and now - recent[key][0] < window:
                    recent[key][1] += 1
                else:
                    recent[key] = [now, 0, kind, sev]
                    ctx = g.snapshot()
                    src = rec.get("SYSLOG_IDENTIFIER") or rec.get("_COMM") or "?"
                    log.write(kind, sev, f"[{src}] {msg.strip()[:400]}", context=ctx)
                    if notify:
                        notifier.send(f"{kind.replace('_', ' ')}", msg.strip()[:200], critical=(sev == "critical"))
        for key, (first, extra, kind, sev) in list(recent.items()):
            if now - first >= window:
                if extra:
                    log.write(kind, sev, f"previous message repeated {extra} more times in {window}s: {key[1]}")
                del recent[key]
        if now - last_scan >= cfg["system"]["scan_dumps_seconds"]:
            last_scan = now
            notifier.flush()
            for path in dumps.scan():
                severe = any(f"/{k}" in path for k in SEVERE_DUMPS)
                log.write("crash_dump", "error" if severe else "info", path, context=g.snapshot())
                if severe:
                    notifier.send("Crash dump saved", path, critical=False)


if __name__ == "__main__":
    sys.exit(main())
