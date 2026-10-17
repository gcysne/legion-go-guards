"""Decky backend for legion-go-guards.

The guards write one JSON file per alert into
~/.local/state/legion-go-guards/toasts/ when Desktop Mode is not up. The
frontend polls pop_toasts() every few seconds; each poll also refreshes the
"decky-alive" file, which tells the guards that Game Mode toasts work.
Runs as the normal user (no "root" flag in plugin.json).
"""

import json
import os
import re
import subprocess
import time
from pathlib import Path

import decky

HOME = Path(decky.DECKY_USER_HOME)
STATE = HOME / ".local/state/legion-go-guards"
TOASTS = STATE / "toasts"
ALIVE = STATE / "decky-alive"
CONFIG = HOME / ".config/legion-go-guards/config.toml"
MAX_TOASTS = 4


def _env():
    uid = os.getuid()
    env = dict(os.environ, HOME=str(HOME), XDG_RUNTIME_DIR=f"/run/user/{uid}",
               DBUS_SESSION_BUS_ADDRESS=f"unix:path=/run/user/{uid}/bus")
    env["PATH"] = f"{HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin"
    # PyInstaller (Decky) sets this; it breaks the system python3 used by the guards.
    env.pop("LD_LIBRARY_PATH", None)
    return env


def _log_dir():
    try:
        m = re.search(r'^log_dir\s*=\s*"([^"]+)"', CONFIG.read_text(), re.M)
        if m:
            return Path(os.path.expanduser(m.group(1).replace("~", str(HOME), 1)))
    except OSError:
        pass
    return STATE / "logs"


class Plugin:
    async def pop_toasts(self):
        STATE.mkdir(parents=True, exist_ok=True)
        ALIVE.touch()
        out = []
        for f in sorted(TOASTS.glob("*.json")):
            try:
                out.append(json.loads(f.read_text()))
            except (OSError, ValueError):
                pass
            f.unlink(missing_ok=True)
        if len(out) > MAX_TOASTS:
            extra = out[MAX_TOASTS - 1:]
            out = out[:MAX_TOASTS - 1] + [{
                "title": f"{len(extra)} more guard alerts",
                "body": "Open Legion Go Guards in the Quick Access Menu",
                "critical": any(t.get("critical") for t in extra)}]
        return out

    async def get_status(self):
        services = {}
        for unit in ("thermal-guard", "reboot-reason-guard"):
            r = subprocess.run(["systemctl", "--user", "is-active", unit],
                               capture_output=True, text=True, env=_env())
            services[unit] = r.stdout.strip() or "unknown"
        events = []
        try:
            lines = (_log_dir() / "events.jsonl").read_text().splitlines()[-8:]
            for line in reversed(lines):
                e = json.loads(line)
                events.append({k: e.get(k, "") for k in ("time", "severity", "kind", "summary")})
        except (OSError, ValueError):
            pass
        return {"services": services, "events": events}

    async def test_alerts(self):
        """Runs the real notification path: guard -> spool -> toast."""
        r = subprocess.run([str(HOME / ".local/bin/thermal-guard"), "--test-notify"],
                           capture_output=True, text=True, env=_env(), timeout=30)
        return f"exit {r.returncode} {r.stderr.strip()[-200:]}"

    async def _main(self):
        TOASTS.mkdir(parents=True, exist_ok=True)
        decky.logger.info("legion-go-guards toasts ready (%s)", TOASTS)

    async def _unload(self):
        ALIVE.unlink(missing_ok=True)  # guards fall back to queueing for Desktop Mode

    async def _uninstall(self):
        ALIVE.unlink(missing_ok=True)
