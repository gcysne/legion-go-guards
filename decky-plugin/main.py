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
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import decky

HOME = Path(decky.DECKY_USER_HOME)
STATE = HOME / ".local/state/legion-go-guards"
TOASTS = STATE / "toasts"
ALIVE = STATE / "decky-alive"
CONFIG = HOME / ".config/legion-go-guards/config.toml"
MAX_TOASTS = 4

REPO = "gcysne/legion-go-guards"
RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASE_INSTALL = f"curl -fsSL https://github.com/{REPO}/releases/latest/download/get-release.sh | bash"
UPDATE_CACHE = STATE / "update-check.json"
CHECK_HOURS = 12


def _version():
    try:
        return json.loads((Path(__file__).resolve().parent / "package.json").read_text())["version"]
    except (OSError, ValueError, KeyError):
        return "0.0.0"


def _version_key(text):
    """Semver order (a release sorts after its pre-releases)."""
    main, _, pre = str(text or "").strip().lstrip("vV").partition("-")
    nums = [int(m.group()) if (m := re.match(r"\d+", x)) else 0 for x in main.split(".")]
    nums = (nums + [0, 0, 0])[:3]
    if not pre:
        return (*nums, 1, ())
    return (*nums, 0, tuple((0, int(x), "") if x.isdigit() else (1, 0, x) for x in pre.split(".")))


def _now():
    return datetime.now(timezone.utc)


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


def _check_release(force):
    current = _version()
    try:
        cached = json.loads(UPDATE_CACHE.read_text())
    except (OSError, ValueError):
        cached = {}
    try:
        fresh = _now() - datetime.fromisoformat(cached["checked"]) < timedelta(hours=CHECK_HOURS)
    except (KeyError, ValueError, TypeError):
        fresh = False
    if force or not fresh or cached.get("current") != current:
        cached = {"checked": _now().isoformat(timespec="seconds"), "current": current}
        try:
            req = urllib.request.Request(RELEASE_API, headers={"User-Agent": f"legion-go-guards/{current}",
                                                               "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=15) as r:
                rel = json.loads(r.read())
            cached.update(latest=str(rel.get("tag_name", "")).lstrip("vV"), url=rel.get("html_url", ""),
                          notes=(rel.get("body") or "")[:1500])
        except urllib.error.HTTPError as e:
            cached["error"] = "no release published yet" if e.code == 404 else f"GitHub answered {e.code}"
        except (urllib.error.URLError, OSError, ValueError) as e:
            cached["error"] = f"couldn't reach GitHub ({getattr(e, 'reason', e)})"
        try:
            STATE.mkdir(parents=True, exist_ok=True)
            UPDATE_CACHE.write_text(json.dumps(cached))
        except OSError:
            pass
    out = dict(cached, current=current, command=RELEASE_INSTALL)
    out["newer"] = bool(out.get("latest")) and _version_key(out["latest"]) > _version_key(current)
    return out


def _tail(path, n):
    try:
        return path.read_text(errors="replace").splitlines()[-n:]
    except OSError:
        return []


class Plugin:
    async def plugin_info(self):
        return {"version": _version()}

    async def update_check(self, force=False):
        import asyncio
        return await asyncio.get_running_loop().run_in_executor(None, _check_release, bool(force))

    async def get_events(self, limit=100):
        events = []
        for line in reversed(_tail(_log_dir() / "events.jsonl", int(limit))):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            events.append({k: e.get(k, "") for k in ("time", "severity", "kind", "summary", "source")})
        return events

    async def get_boot_history(self, limit=50):
        return list(reversed(_tail(_log_dir() / "boot-history.log", int(limit))))

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
