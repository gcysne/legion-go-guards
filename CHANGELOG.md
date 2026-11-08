# Changelog

## Unreleased

- Fixed: the About tab's update check failed with a certificate error (CERTIFICATE_VERIFY_FAILED): Decky's bundled
  Python doesn't find the system's CA certificates, so the plugin now loads them itself. A failed check is retried
  the next time About opens instead of being cached.

## 0.1.0-alpha (2026-11-03)

First public version.

- `thermal-guard`: warns at 90 °C (sustained) and 97 °C (critical) on CPU Tctl or GPU edge, follows kernel thermal
  messages, saves a snapshot every 30 s (temperatures, power, clocks, TDP, profile, battery, running game).
- `reboot-reason-guard`: classifies how every boot ended (firmware reset reason, kernel panic, thermal shutdown,
  forced power off, died in suspend, battery depleted...) and logs GPU, kernel, OOM and crash events with the
  running game.
- Alerts: KDE notification in Desktop Mode, Steam toast in Game Mode (Decky plugin), sound; queued when neither is
  available.
- Decky plugin: service status, recent events, test alerts; ⚙ cog opens Events, Boot history and About (credits,
  update check: "New version available" with the update command and a copy button).
- Install from the latest release (`get-release.sh`, prebuilt plugin, checksum verified) or from source (`get.sh`);
  `uninstall.sh` also removes the Decky plugin. Releases are built by a GitHub workflow on version tags.
- Fixed: reboot-reason-guard crashed in a loop after an abnormal shutdown.
- Pull requests: automatic security scan (rejects binaries, prompt injection, obfuscated code, unofficial
  downloads...; warns on risky commands) and an advisory AI security review; code owner and branch ruleset.
