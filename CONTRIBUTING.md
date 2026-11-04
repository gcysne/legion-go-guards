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

## Pull request checks

Only the maintainer pushes to `main`; every other change comes as a pull request, reviewed by the code owner
(`.github/CODEOWNERS`). Each pull request gets two automatic security checks:

- **PR security scan** (required, `.github/security/pr_scan.py`): reads what the pull request adds and **rejects it
  upfront** (closes it) on binaries or archives, prompt injection or hidden Unicode, obfuscated, encoded or minified
  code, long numeric or encoded arrays, downloads or installs from sources not listed in
  `.github/security/allowed-sources.txt`, piping downloads into a shell, reverse shells, miners, exfiltration
  endpoints, sudoers or setuid changes, destructive commands on `/` or `~`, package install hooks, and changes to
  `.github/` or `CODEOWNERS`. Risky commands such as `rm -rf`, `sudo`, process kills or credential paths are
  reported as warnings in a review for the maintainer to check.
- **AI security review** (advisory, `.github/security/ai_review.py`): Claude reads the diff as text, with no tools,
  and comments on anything malicious or unsafe the pattern scan can't see.

Needs a tool from a new source? Say so in the pull request: the maintainer decides whether it goes on the allowed
list. False positive? Explain it in a comment; the maintainer can add the `security-reviewed` label.
