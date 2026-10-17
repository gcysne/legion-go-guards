# legion-go-guards

Two small user services for a Lenovo Legion Go (Z1 Extreme) running SteamOS. They warn
about thermal problems, explain every shutdown that wasn't a normal user request, and
keep a log of kernel, GPU and crash events to help with debugging and tuning games.

- Python 3 standard library only, using the SteamOS host Python. Nothing to install
  system-wide and no sudo.
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
- **Game Mode:** sound only, because Steam's UI doesn't show desktop notifications. The
  notification is queued and shown the next time Desktop Mode is up.
- Only important events alert you: thermal warnings, abnormal shutdowns, panics,
  lockups, MCE, GPU hangs, OOM kills and severe dumps. Everything else is only logged.

Test with `thermal-guard --test-notify`.

## Install

```bash
git clone git@github.com:gcysne/legion-go-guards.git
cd legion-go-guards
./install.sh                       # logs in ~/.local/state/legion-go-guards/logs
./install.sh --log-dir ~/somewhere # or choose the log folder
```

The installer runs the tests, copies the scripts to `~/.local/lib/legion-go-guards`,
adds `thermal-guard` and `reboot-reason-guard` to `~/.local/bin`, installs the user units
and starts them. Run it again to update.

Settings are in `~/.config/legion-go-guards/config.toml`; see `config.example.toml`.

## Logs

These are written to `log_dir` and never committed (see `.gitignore`):

- `thermal-events.log`, `system-events.log`: one readable line per event
- `boot-history.log`: one line per boot with its classification
- `events.jsonl`: every event as JSON, for analysis

The service output is also in `journalctl --user -u thermal-guard -u reboot-reason-guard`.

## Uninstall

```bash
./uninstall.sh          # keeps config and logs
./uninstall.sh --purge  # deletes config and state too
```

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
