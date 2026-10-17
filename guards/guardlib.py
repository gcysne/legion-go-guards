"""Shared helpers for the Legion Go guards: config, event log, notifications,
sensor reads and a "what is the machine doing right now" snapshot.

Standard library only (runs on the SteamOS host Python, no installs needed).
"""

import glob
import json
import os
import re
import shutil
import subprocess
import time
import tomllib
from pathlib import Path

HOME = Path.home()
CONFIG_PATH = HOME / ".config/legion-go-guards/config.toml"
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", HOME / ".local/state")) / "legion-go-guards"

DEFAULTS = {
    "log_dir": str(STATE_DIR / "logs"),
    "notify": {
        "desktop": True,          # KDE notification (Desktop Mode) / alerts at all
        "decky": True,            # Steam toast via the Decky plugin (Game Mode)
        "sound": True,            # alert sound (works in Game Mode too)
        "sound_warning": "/usr/share/sounds/freedesktop/stereo/dialog-warning.oga",
        "sound_critical": "/usr/share/sounds/oxygen/stereo/Oxygen-Sys-App-Error-Critical.ogg",
    },
    "thermal": {
        "poll_seconds": 5,
        "warn_c": 90.0,           # CPU Tctl / GPU edge, sustained
        "critical_c": 97.0,       # a few degrees under the ~100 C limit
        "sustain_seconds": 10,
        "hysteresis_c": 5.0,
        "renotify_minutes": 5,
        "heartbeat_seconds": 30,
    },
    "system": {
        "scan_dumps_seconds": 30,
        "aggregate_seconds": 60,  # identical messages within this window are counted, not repeated
    },
}


def _merge(base, over):
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def load_config():
    cfg = DEFAULTS
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            cfg = _merge(DEFAULTS, tomllib.load(f))
    cfg["log_dir"] = os.path.expanduser(cfg["log_dir"])
    return cfg


# ---------------------------------------------------------------- event log

class EventLog:
    """Writes each event twice: a readable line in <name>.log and a JSON line
    in events.jsonl (shared by all guards, for later analysis)."""

    def __init__(self, cfg, name):
        self.dir = Path(cfg["log_dir"])
        self.dir.mkdir(parents=True, exist_ok=True)
        self.text = self.dir / f"{name}.log"
        self.jsonl = self.dir / "events.jsonl"
        self.source = name

    def write(self, kind, severity, summary, **details):
        ts = time.strftime("%Y-%m-%d %H:%M:%S%z")
        rec = {"time": ts, "source": self.source, "kind": kind,
               "severity": severity, "summary": summary, **details}
        line = f"{ts} [{severity.upper():8}] {kind}: {summary}"
        ctx = details.get("context")
        if ctx:
            line += "  | " + format_context(ctx)
        with open(self.text, "a") as f:
            f.write(line + "\n")
        with open(self.jsonl, "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        print(line, flush=True)  # also lands in the user journal
        return rec


def format_context(ctx):
    parts = []
    for key, fmt in (("cpu_c", "CPU {:.0f}C"), ("gpu_c", "GPU {:.0f}C"),
                     ("socket_w", "{:.1f}W"), ("tdp_w", "TDP {}W"),
                     ("gpu_mhz", "GPU {}MHz"), ("profile", "{}"),
                     ("battery", "bat {}%"), ("ac", "AC {}")):
        if ctx.get(key) is not None:
            parts.append(fmt.format(ctx[key]))
    game = ctx.get("game")
    if game:
        parts.append(f"game: {game.get('name') or '?'} ({game.get('appid')})")
    return ", ".join(parts)


# ------------------------------------------------------------ notifications

def desktop_mode_active():
    """True when the KDE desktop is up (notifications visible).
    In Game Mode there is no notification daemon the Steam UI shows."""
    return subprocess.run(["pgrep", "-u", str(os.getuid()), "-x", "plasmashell"],
                          capture_output=True).returncode == 0


TOAST_DIR = STATE_DIR / "toasts"
DECKY_ALIVE = STATE_DIR / "decky-alive"
DECKY_ALIVE_SECONDS = 20


def decky_alive():
    """True while the Decky plugin frontend is polling (Game Mode toasts work)."""
    try:
        return time.time() - DECKY_ALIVE.stat().st_mtime < DECKY_ALIVE_SECONDS
    except OSError:
        return False


class Notifier:
    """Plays a sound right away, then shows the alert where it can be seen:
    a KDE notification in Desktop Mode, a Steam toast (via the Decky plugin)
    in Game Mode, otherwise queues it until one of those is available."""

    def __init__(self, cfg, app_name):
        self.cfg = cfg["notify"]
        self.app = app_name
        self.queue_file = STATE_DIR / f"{app_name}.pending.json"
        STATE_DIR.mkdir(parents=True, exist_ok=True)

    def send(self, title, body, critical=False):
        if self.cfg.get("sound"):
            self._sound(critical)
        if not self.cfg.get("desktop"):
            return
        if self._show(title, body, critical):
            return
        q = self._load_queue()
        q.append({"time": time.strftime("%Y-%m-%d %H:%M"), "title": title,
                  "body": body, "critical": critical})
        self.queue_file.write_text(json.dumps(q[-50:]))

    def flush(self):
        q = self._load_queue()
        if not q:
            return
        if len(q) == 1:
            e = q[0]
            ok = self._show(f"{e['title']} (at {e['time']})", e["body"], e["critical"])
        else:
            body = "\n".join(f"{e['time']}  {e['title']}" for e in q[-10:])
            ok = self._show(f"{len(q)} guard alerts while you were away", body,
                            any(e["critical"] for e in q))
        if ok:
            self.queue_file.unlink(missing_ok=True)

    def _show(self, title, body, critical):
        if desktop_mode_active() and self._popup(title, body, critical):
            return True
        if self.cfg.get("decky", True) and decky_alive():
            return self._toast(title, body, critical)
        return False

    def _toast(self, title, body, critical):
        try:
            TOAST_DIR.mkdir(parents=True, exist_ok=True)
            path = TOAST_DIR / f"{time.time_ns()}-{os.getpid()}.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"title": title, "body": body, "critical": critical}))
            tmp.replace(path)  # atomic: the plugin only reads *.json
            return True
        except OSError:
            return False

    def _load_queue(self):
        try:
            return json.loads(self.queue_file.read_text())
        except (OSError, ValueError):
            return []

    def _popup(self, title, body, critical):
        if not shutil.which("notify-send"):
            return False
        cmd = ["notify-send", "--app-name", self.app, "--icon",
               "dialog-error" if critical else "dialog-warning",
               "--urgency", "critical" if critical else "normal", title, body]
        try:
            return subprocess.run(cmd, capture_output=True, timeout=10).returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False

    def _sound(self, critical):
        path = self.cfg["sound_critical" if critical else "sound_warning"]
        if os.path.exists(path) and shutil.which("paplay"):
            subprocess.Popen(["paplay", path], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)


# ------------------------------------------------------------------ sensors

def _read(path, cast=str):
    try:
        with open(path) as f:
            return cast(f.read().strip())
    except (OSError, ValueError):
        return None


def hwmon(name):
    for d in glob.glob("/sys/class/hwmon/hwmon*"):
        if _read(f"{d}/name") == name:
            return d
    return None


def read_temps():
    """CPU (k10temp Tctl) and GPU (amdgpu edge) in Celsius."""
    out = {}
    for key, name in (("cpu_c", "k10temp"), ("gpu_c", "amdgpu"), ("acpi_c", "acpitz")):
        d = hwmon(name)
        v = _read(f"{d}/temp1_input", int) if d else None
        out[key] = v / 1000 if v is not None else None
    return out


def snapshot():
    """Temperatures, power, limits, battery and the running game."""
    ctx = read_temps()
    gpu = hwmon("amdgpu")
    if gpu:
        p = _read(f"{gpu}/power1_average", int) or _read(f"{gpu}/power1_input", int)
        ctx["socket_w"] = p / 1e6 if p else None
        f = _read(f"{gpu}/freq1_input", int)
        ctx["gpu_mhz"] = f // 1_000_000 if f else None
    ctx["tdp_w"] = _read("/sys/class/firmware-attributes/lenovo-wmi-other-0/attributes/ppt_pl1_spl/current_value", int)
    ctx["profile"] = _read("/sys/firmware/acpi/platform_profile")
    ctx["battery"] = _read("/sys/class/power_supply/BATT/capacity", int)
    ac = _read("/sys/class/power_supply/ACAD/online", int)
    ctx["ac"] = None if ac is None else bool(ac)
    ctx["game"] = running_game()
    return ctx


# ------------------------------------------------------------ running game

_STEAM = HOME / ".local/share/Steam"


def _library_paths():
    paths = [_STEAM]
    vdf = _STEAM / "steamapps/libraryfolders.vdf"
    try:
        for m in re.finditer(r'"path"\s+"([^"]+)"', vdf.read_text()):
            paths.append(Path(m.group(1)))
    except OSError:
        pass
    return paths


def app_name(appid):
    for lib in _library_paths():
        acf = lib / f"steamapps/appmanifest_{appid}.acf"
        try:
            m = re.search(r'"name"\s+"([^"]+)"', acf.read_text(errors="replace"))
            if m:
                return m.group(1)
        except OSError:
            continue
    return None


def running_game():
    """Steam starts every game (Steam or non-Steam) through
    `reaper SteamLaunch AppId=<id> -- <command>`."""
    for cmdline in glob.glob("/proc/[0-9]*/cmdline"):
        try:
            with open(cmdline, "rb") as f:
                args = f.read().split(b"\0")
        except OSError:
            continue
        if not args or not args[0].endswith(b"reaper") or b"SteamLaunch" not in args:
            continue
        appid = next((a.split(b"=", 1)[1].decode() for a in args if a.startswith(b"AppId=")), None)
        if not appid or appid == "0":
            continue
        name = app_name(appid)
        if not name:  # non-Steam shortcut: use the executable name
            try:
                exe = args[args.index(b"--") + 1:]
                exe = [a for a in exe if a.lower().endswith((b".exe", b".sh", b".appimage"))] or exe
                name = os.path.basename(exe[-1].decode(errors="replace")) if exe else None
            except ValueError:
                pass
        return {"appid": appid, "name": name}
    return None


# ---------------------------------------------------------------- journal

def journal_json(*args):
    """Run journalctl with -o json and yield the parsed records."""
    proc = subprocess.run(["journalctl", "--no-pager", "-o", "json", *args],
                          capture_output=True, text=True)
    for line in proc.stdout.splitlines():
        try:
            yield json.loads(line)
        except ValueError:
            continue


def message(rec):
    m = rec.get("MESSAGE")
    if isinstance(m, list):  # journald stores non-UTF-8 messages as byte arrays
        m = bytes(m).decode(errors="replace")
    return m if isinstance(m, str) else ""  # null for oversized/missing messages


def follow_journal(*args):
    """Start `journalctl -f` on new entries only; returns the Popen."""
    return subprocess.Popen(["journalctl", "--no-pager", "-f", "-n", "0", "-o", "json", *args],
                            stdout=subprocess.PIPE, text=True, bufsize=1)


def current_boot_id():
    return _read("/proc/sys/kernel/random/boot_id", lambda s: s.replace("-", ""))
