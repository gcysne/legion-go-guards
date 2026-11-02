# Legion Go Guards

Two small user services for a Lenovo Legion Go (Z1 Extreme) running SteamOS. They warn
about thermal problems, explain every shutdown that wasn't a normal user request, and
keep a log of kernel, GPU and crash events to help with debugging and tuning games.
A Decky Loader plugin shows the alerts as Game Mode toasts and lists events and boots.

- Python 3 standard library only, using the SteamOS host Python. Nothing to install
  system-wide; the only root step is copying the Decky plugin into Decky's folder.
- Everything lives in the home folder, so it survives SteamOS updates.
- Read-only: the services never change hardware settings.

## thermal-guard

- Checks the CPU (`k10temp` Tctl) and GPU (`amdgpu` edge) temperatures every 5 s.
  - **Warning** when either stays at or above 90 °C for 10 s.
  - **Critical** at 97 °C or above for two readings in a row. Critical alerts repeat
    every 5 min while it stays that hot.
  - When the temperature drops back below 85 °C, it logs the episode's length and peak.
- Follows the kernel log for thermal messages: critical trip, PROCHOT, amdgpu
  over-temperature.
- Every 30 s it saves a snapshot: temperatures, socket power, GPU clock, TDP, platform
  profile, battery, AC and the running game. If the machine dies abruptly,
  reboot-reason-guard reads the last snapshot to work out why.

The Legion Go doesn't expose a fan speed sensor on SteamOS, so the guard watches
temperatures rather than the fan.

## reboot-reason-guard

**Once per boot** it classifies how the previous boot ended:

| Category | Evidence |
|---|---|
| `thermal_shutdown_hw` | AMD firmware reset reason: THERMTRIP or internal CPU thermal limit |
| `thermal_shutdown_kernel` | kernel critical-temperature message before the shutdown |
| `kernel_panic` | kdumpst dump saved, or panic in the log (SteamOS reboots on panic) |
| `watchdog_reset` / `hardware_fault` | reset reason: watchdog, sync flood, parity, CPU shutdown |
| `forced_power_off` | reset reason: power button held 4 s |
| `died_in_suspend` | log ends after "will suspend" with no resume |
| `battery_depleted` | last snapshot shows ≤3 % on battery |
| `suspected_thermal` | last snapshot shows ≥ critical temperature |
| `unclean_shutdown` | log ends with no shutdown request (crash, hang, power loss) |
| `normal_reboot` / `normal_power_off` | logind "The system will reboot / power off now!" |

Every boot gets a line in `boot-history.log`. Anything other than `normal_*` is
logged as an event and triggers an alert.

**While running** it follows the journal and the crash-dump folders, and logs:

- GPU: ring timeouts, resets/recovery, page faults, `VK_ERROR_DEVICE_LOST`, DRM errors,
  devcoredumps
- kernel: panic, oops, BUG, soft/hard lockups, RCU stalls, machine-check (MCE) errors,
  PCIe AER errors
- memory: OOM kills (kernel and earlyoom)
- crashes: process core dumps (games included) and new files in kdumpst and
  `/var/lib/steamos-log-submitter/{pending,failed,uploaded}/{kdump,gpu,devcoredump,earlyoom,minidump}`

Every event is logged with the same snapshot, including the running game (Steam AppId
and name; non-Steam shortcuts show the executable name). Identical messages within
60 s are counted instead of repeated.

`reboot-reason-guard --analyze-all` classifies every boot in the journal without logging
anything.

## Notifications

- **Desktop Mode:** KDE notification plus a sound.
- **Game Mode:** a Steam toast via the included Decky plugin, plus a sound. Without the
  plugin it's sound only.
- **Neither available** (e.g. at boot before Steam has loaded): the alert is queued and
  shown as soon as Desktop Mode or the Decky plugin is up.

### Decky plugin (`decky-plugin/`)

When Desktop Mode isn't running, the guards write each alert as a JSON file to
`~/.local/state/legion-go-guards/toasts/`. The plugin's frontend polls the backend every
3 s and shows new files as Steam toasts. Each poll also refreshes `decky-alive`, which is
how the guards know toasts will be seen. The plugin runs as the normal user.

Its Quick Access panel shows the service status and recent events, and has a **Send test
alerts** button that runs the full path (guard → spool → toast). The **⚙ cog** in its
title opens the full page: **Events** (the last 200), **Boot history** (how every boot
ended) and **About** (version, update check, credits).

- Only important events alert you: thermal warnings, abnormal shutdowns, panics,
  lockups, MCE, GPU hangs, OOM kills and severe dumps. Everything else is only logged.

Test with `thermal-guard --test-notify`.

## Requirements

- Lenovo Legion Go (Z1 Extreme) with SteamOS 3.7+. Other AMD handhelds may work but are
  untested: the sensor names and thresholds are the Legion Go's.
- Python 3.11+ (ships with SteamOS). Your user must be able to read the system journal
  (the default `deck` user can).
- [Decky Loader](https://decky.xyz) for Game Mode toasts (optional: without it, Game Mode
  alerts are sound only).
- Installed for you when needed, only to build the plugin from source: Node.js (official
  build, checksum verified, `~/.cache/legion-go-guards/node`).

## Install

In **Desktop Mode**, open Konsole and run **one** of these:

**From the latest release** (recommended: a tested version, the Decky plugin comes
prebuilt):

```bash
curl -fsSL https://github.com/gcysne/legion-go-guards/releases/latest/download/get-release.sh | bash
```

It downloads `legion-go-guards.tar.gz` from the latest
[release](https://github.com/gcysne/legion-go-guards/releases), checks it against the
release's `SHA256SUMS`, and runs its installer.

**From the source code** (latest development version, kept as a git clone):

```bash
curl -fsSL https://raw.githubusercontent.com/gcysne/legion-go-guards/main/get.sh | bash
```

It clones the project into `~/legion-go-guards` and runs its installer. Prefer to read
before running? Same thing by hand:

```bash
git clone https://github.com/gcysne/legion-go-guards.git ~/legion-go-guards
cd ~/legion-go-guards
./install.sh                       # logs in ~/.local/state/legion-go-guards/logs
./install.sh --log-dir ~/somewhere # or choose the log folder
```

The installer runs the tests, then puts everything in your home folder (it survives
SteamOS updates). It asks for your password once, only to copy the plugin into Decky's
folder (`~/homebrew/plugins` belongs to root).

| What | Where |
|---|---|
| Guards | `~/.local/lib/legion-go-guards/` |
| `thermal-guard`, `reboot-reason-guard` commands | `~/.local/bin/` |
| User services (enabled and started) | `~/.config/systemd/user/{thermal-guard,reboot-reason-guard}.service` |
| Settings | `~/.config/legion-go-guards/config.toml` (see `config.example.toml`) |
| Logs and state | `~/.local/state/legion-go-guards/` (logs: `log_dir` in the settings) |
| Decky plugin | `~/homebrew/plugins/legion-go-guards/` |

Options: `--log-dir DIR`, `--no-start`, `--no-plugin`. With a one-liner:
`... | bash -s -- --no-plugin`.

**Or let Claude do it.** If you use Claude Code (for example through
[Sidequest](https://github.com/gcysne/sidequest)), give it this prompt:

> Install this for me: https://github.com/gcysne/legion-go-guards

> **Note for AI agents:** read this README first. Run it in Desktop Mode: clone into
> `~/legion-go-guards` and run `./install.sh`. The only root step is copying the Decky
> plugin into `~/homebrew/plugins`: explain it and let the user enter the password
> (`sudo -A` with a graphical askpass, e.g. `SUDO_ASKPASS=/usr/bin/ksshaskpass`).

### First steps

In Game Mode, open Quick Access (<kbd>…</kbd>) → **Legion Go Guards** → **Send test
alerts**: you should hear the alert sound and see two toasts. From a terminal:
`thermal-guard --test-notify`.

### Update

The guards aren't in the Decky store, so Decky doesn't offer their updates. Instead,
the plugin's **About** tab (⚙ cog) checks GitHub at most twice a day and shows **New
version available** with the command to run. To update, run the release command again
in Desktop Mode:

```bash
curl -fsSL https://github.com/gcysne/legion-go-guards/releases/latest/download/get-release.sh | bash
```

With a git clone: `cd ~/legion-go-guards && git pull && ./install.sh`. Settings and logs
are kept.

## Logs

These are written to `log_dir` and never committed (see `.gitignore`):

- `thermal-events.log`, `system-events.log`: one readable line per event
- `boot-history.log`: one line per boot with its classification
- `events.jsonl`: every event as JSON, for analysis

The service output is also in `journalctl --user -u thermal-guard -u reboot-reason-guard`.

## Uninstall

In **Desktop Mode**, in Konsole:

```bash
~/.local/lib/legion-go-guards/uninstall.sh            # stop and remove the services, commands and Decky plugin
~/.local/lib/legion-go-guards/uninstall.sh --purge    # ...and also settings, state and logs
```

This works however you installed it (`./uninstall.sh` in a git clone does the same). It
asks for your password once, to remove the plugin from Decky's folder.

- The guards never changed any hardware or system setting, so there is nothing to restore.
- **Without `--purge`**, `~/.config/legion-go-guards` and the logs are kept.
- Logs in a custom `log_dir` outside `~/.local/state` are never deleted: remove that folder
  yourself if you want.
- If you installed from source, also delete the clone: `rm -rf ~/legion-go-guards`.

## Limitations

- The firmware reset reason needs a kernel that prints it (`x86/amd: Previous system reset
  reason`). The SteamOS 6.18 kernel does; the earlier 6.16 kernel didn't.
- Panic details depend on SteamOS's kdumpst capturing them (pstore RAM). Without a dump,
  a panic shows up as `unclean_shutdown`.
- A hard power loss leaves no trace; the last snapshot (battery, temperature) is the best
  available clue.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## Credits

- **Gabriel Cysne** ([github.com/gcysne](https://github.com/gcysne),
  [linkedin.com/in/gcysne](https://www.linkedin.com/in/gcysne)): creator and lead. He had
  the idea, sets the project's direction and design, and tests every build on real
  hardware.
- Code written by Claude (Anthropic's Claude Code), working with Gabriel Cysne.
- Everyone who reports problems and tests on other devices:
  [contributors](https://github.com/gcysne/legion-go-guards/graphs/contributors).
- Built on [Decky Loader](https://decky.xyz), systemd and Python.

Legion Go Guards is a community project, not affiliated with or endorsed by Lenovo, AMD or
Valve. It only reads sensors and logs; it never changes fan, power or firmware settings.

## License

MIT. See [LICENSE](LICENSE). Contributions welcome: [CONTRIBUTING.md](CONTRIBUTING.md).
