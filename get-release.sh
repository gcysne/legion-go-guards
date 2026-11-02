#!/usr/bin/env bash
# Install or update Legion Go Guards from the latest GitHub release (no git, no Node.js needed):
#
#   curl -fsSL https://github.com/gcysne/legion-go-guards/releases/latest/download/get-release.sh | bash
#   ... | bash -s -- --no-plugin        # install.sh options
#
# Downloads legion-go-guards.tar.gz and SHA256SUMS from the same release, checks the checksum, unpacks it to a temporary
# folder and runs its install.sh. Settings and logs are kept.
set -euo pipefail
REPO="${GUARDS_REPO_SLUG:-gcysne/legion-go-guards}"
BASE="https://github.com/$REPO/releases/${GUARDS_RELEASE:-latest}/download"
[[ "${GUARDS_RELEASE:-latest}" != latest ]] && BASE="https://github.com/$REPO/releases/download/$GUARDS_RELEASE"
BASE="${GUARDS_RELEASE_BASE:-$BASE}"      # testing: a local mirror of the release assets

for tool in curl tar sha256sum python3; do
    command -v "$tool" >/dev/null || { echo "$tool is required (it ships with SteamOS)." >&2; exit 1; }
done
mkdir -p "$HOME/.cache/legion-go-guards"
WORK="$(mktemp -d "$HOME/.cache/legion-go-guards/release.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

echo "- downloading Legion Go Guards from $BASE"
curl -fsSL --retry 3 -o "$WORK/legion-go-guards.tar.gz" "$BASE/legion-go-guards.tar.gz"
curl -fsSL --retry 3 -o "$WORK/SHA256SUMS" "$BASE/SHA256SUMS"
echo "- checking the download"
(cd "$WORK" && grep ' legion-go-guards.tar.gz$' SHA256SUMS | sha256sum -c --quiet -) \
    || { echo "Checksum mismatch: nothing was installed." >&2; exit 1; }
tar -C "$WORK" -xzf "$WORK/legion-go-guards.tar.gz"
echo "- Legion Go Guards $(cat "$WORK/legion-go-guards/VERSION")"
cd "$WORK/legion-go-guards"
# Piped from curl, stdin is this script: give install.sh the terminal (for the sudo password prompt).
if [[ ! -t 0 ]] && { : </dev/tty; } 2>/dev/null; then
    ./install.sh "$@" </dev/tty
else
    ./install.sh "$@"
fi
