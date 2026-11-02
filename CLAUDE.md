# Developing Legion Go Guards

Instructions for an AI coding agent working on this repository. Read [CONTRIBUTING.md](CONTRIBUTING.md) first.
Personal or machine-specific rules go in `CLAUDE.local.md` (ignored by git).

- The guards are read-only monitors: never add code that changes hardware, power, fan or firmware settings.
- Don't test against the user's real logs or config; use the tests. Never commit logs, state or `config.toml`.
- Decky's bundled Python leaks `LD_LIBRARY_PATH`: child processes in `decky-plugin/main.py` go through `_env()`.
- The plugin follows the owner's plugin template (same as Extra Life): ⚙ cog in the Quick Access title opening the
  full page, About tab (creator credits, update check against GitHub's latest release with the update command and
  a copy button), release and source one-line installers, `uninstall.sh` installed next to the program. Keep it.
- Commits: `topic: message` (guards, plugin, install, docs, ci, repo). Update CHANGELOG.md for anything users notice.
