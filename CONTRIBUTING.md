# Contributing

Thanks for helping. Problems and ideas: [issues](https://github.com/gcysne/legion-go-guards/issues). Code: a pull
request against `main`.

## Layout

| Path | What |
|---|---|
| `guards/` | `guardlib.py` (config, logging, notifications, sensors) and the two services |
| `systemd/` | user units |
| `tests/` | `python3 -m unittest discover -s tests` (the installer runs them too) |
| `decky-plugin/` | Decky plugin: `main.py` backend, `src/` frontend (TypeScript/React), `install.sh` |
| `install.sh`, `uninstall.sh`, `get.sh`, `get-release.sh` | installers |
| `scripts/make-release.sh`, `.github/workflows/` | CI and releases |

## Rules

- Python standard library only, 3.11+, the SteamOS host Python. The guards are **read-only**: they never change
  hardware, power, fan or firmware settings.
- Never commit logs, state or a real `config.toml` (`.gitignore` keeps them out): they contain details of the
  machine they came from.
- Thresholds and sensor names are the Legion Go's; support for another device goes behind a detection, not a
  replacement.
- Checks before a pull request: the tests, `shellcheck -S warning` on the shell scripts, and
  `pnpm run typecheck && pnpm run build` in `decky-plugin/`.

## Releases

1. Set the version in `decky-plugin/package.json` and give it a section in `CHANGELOG.md` (`## <version>`: it
   becomes the release notes).
2. Commit, then `git tag v<version> && git push origin v<version>`.
3. `.github/workflows/release.yml` runs the tests, builds `legion-go-guards.tar.gz` (with the prebuilt plugin),
   `get-release.sh` and `SHA256SUMS` (`scripts/make-release.sh`) and publishes them as the **latest** release.
   Never mark it as a pre-release: the plugin's update check and `releases/latest/download/...` only see the latest
   release.
