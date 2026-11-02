#!/usr/bin/env bash
# Remove legion-go-guards. Logs and config are kept unless --purge is given.
#
#   ./uninstall.sh [--purge]
set -euo pipefail

systemctl --user disable --now thermal-guard.service reboot-reason-guard.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/thermal-guard.service" \
      "$HOME/.config/systemd/user/reboot-reason-guard.service" \
      "$HOME/.local/bin/thermal-guard" "$HOME/.local/bin/reboot-reason-guard"
rm -rf "$HOME/.local/lib/legion-go-guards"
systemctl --user daemon-reload

PLUGIN="$HOME/homebrew/plugins/legion-go-guards"
if [[ -d "$PLUGIN" ]]; then
    echo "Removing the Decky plugin (Decky owns that folder: needs your password)"
    sudo ${SUDO_ASKPASS:+-A} -p "[sudo] password to remove the Legion Go Guards Decky plugin: " \
        sh -c 'rm -rf "$1" && { systemctl restart plugin_loader 2>/dev/null || true; }' _ "$PLUGIN" \
        || echo "Couldn't remove $PLUGIN; delete it as root." >&2
fi

if [[ "${1:-}" == "--purge" ]]; then
    rm -rf "$HOME/.config/legion-go-guards" "${XDG_STATE_HOME:-$HOME/.local/state}/legion-go-guards"
    echo "Removed config and state. Logs in a custom log_dir (if set) were not touched."
else
    echo "Removed. Config (~/.config/legion-go-guards) and logs kept; use --purge to delete them."
fi
if [[ -d "$HOME/legion-go-guards/.git" ]]; then
    echo "The git clone ~/legion-go-guards (if you installed from source) can be deleted now: rm -rf ~/legion-go-guards"
fi
