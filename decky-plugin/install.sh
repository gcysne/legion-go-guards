#!/usr/bin/env bash
# Build the Decky plugin and copy it to ~/homebrew/plugins/legion-go-guards.
# Needs Decky Loader installed and Node.js >= 20 (PATH or ~/.local/opt/node/bin).
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
PLUGINS="$HOME/homebrew/plugins"
DEST="$PLUGINS/legion-go-guards"

[[ -d "$PLUGINS" ]] || { echo "Decky Loader not found ($PLUGINS missing); skipping plugin." >&2; exit 0; }
[[ -d "$HOME/.local/opt/node/bin" ]] && export PATH="$HOME/.local/opt/node/bin:$PATH"
command -v node >/dev/null || { echo "Node.js not found; cannot build the plugin." >&2; exit 1; }
export COREPACK_ENABLE_DOWNLOAD_PROMPT=0

cd "$SRC"
corepack pnpm install --frozen-lockfile --silent
corepack pnpm run --silent typecheck
corepack pnpm run --silent build

if [[ -e "$DEST" && ! -w "$DEST" ]]; then
    echo "$DEST is not writable (installed by Decky as root?). Remove it with: sudo rm -rf '$DEST'" >&2
    exit 1
fi
rm -rf "$DEST.new"
mkdir -p "$DEST.new/dist"
cp plugin.json package.json main.py LICENSE "$DEST.new/"
cp dist/index.js "$DEST.new/dist/"
rm -rf "$DEST"
mv "$DEST.new" "$DEST"
echo "Plugin installed to $DEST. Decky reloads it automatically; if not, restart Steam or run: sudo systemctl restart plugin_loader"
