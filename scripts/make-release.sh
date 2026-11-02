#!/usr/bin/env bash
# Build the release assets into release/ (run by .github/workflows/release.yml on a version tag; also works locally):
#   legion-go-guards.tar.gz   guards, units, tests, installers and the prebuilt Decky plugin (no Node needed)
#   get-release.sh            the one-line installer that downloads and checks the archive
#   SHA256SUMS                checksums of both
# Asset names carry no version, so https://github.com/<repo>/releases/latest/download/<name> always works.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/release"
cd "$ROOT"

VERSION="$(python3 -c 'import json; print(json.load(open("decky-plugin/package.json"))["version"])')"
if [[ -n "${1:-}" && "${1#v}" != "$VERSION" ]]; then
    echo "tag $1 doesn't match version $VERSION (decky-plugin/package.json)" >&2; exit 1
fi

if [[ ! -f decky-plugin/dist/index.js || "${SKIP_PLUGIN_BUILD:-0}" != 1 ]]; then
    (cd decky-plugin && corepack pnpm install --frozen-lockfile && corepack pnpm run typecheck && corepack pnpm run build)
fi

rm -rf "$OUT"
STAGE="$OUT/stage/legion-go-guards"
mkdir -p "$STAGE/decky-plugin/dist"
cp -r guards systemd tests "$STAGE/"
cp install.sh uninstall.sh config.example.toml LICENSE README.md CHANGELOG.md "$STAGE/"
cp decky-plugin/plugin.json decky-plugin/package.json decky-plugin/main.py decky-plugin/install.sh "$STAGE/decky-plugin/"
cp decky-plugin/dist/index.js "$STAGE/decky-plugin/dist/"
find "$STAGE" -name __pycache__ -prune -exec rm -rf {} +
echo "$VERSION" > "$STAGE/VERSION"
tar -C "$OUT/stage" --owner=0 --group=0 -czf "$OUT/legion-go-guards.tar.gz" legion-go-guards
cp get-release.sh "$OUT/"
rm -rf "$OUT/stage"
(cd "$OUT" && sha256sum legion-go-guards.tar.gz get-release.sh > SHA256SUMS)
echo "Legion Go Guards $VERSION release assets in $OUT:"
ls -l "$OUT"
