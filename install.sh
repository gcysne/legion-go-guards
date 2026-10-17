#!/usr/bin/env bash
# Install (or update) legion-go-guards for the current user.
# Everything goes in the home folder, so it survives SteamOS updates. No sudo.
#
#   ./install.sh [--log-dir DIR] [--no-start]
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
LIB="$HOME/.local/lib/legion-go-guards"
BIN="$HOME/.local/bin"
UNITS="$HOME/.config/systemd/user"
CONF_DIR="$HOME/.config/legion-go-guards"
LOG_DIR=""
START=1

while [[ $# -gt 0 ]]; do
    case "$1" in
        --log-dir) LOG_DIR="$2"; shift 2 ;;
        --no-start) START=0; shift ;;
        -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 1 ;;
    esac
done

python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' \
    || { echo "python3 >= 3.11 is required (tomllib)" >&2; exit 1; }
journalctl -k -n 1 -q >/dev/null 2>&1 \
    || echo "warning: this user cannot read the system journal (needs group wheel, adm or systemd-journal)" >&2

echo "Running tests..."
python3 -m unittest discover -s "$SRC/tests" -q

mkdir -p "$LIB" "$BIN" "$UNITS" "$CONF_DIR"
install -m 644 "$SRC"/guards/guardlib.py "$LIB/"
install -m 755 "$SRC"/guards/thermal_guard.py "$SRC"/guards/reboot_reason_guard.py "$LIB/"
ln -sf "$LIB/thermal_guard.py" "$BIN/thermal-guard"
ln -sf "$LIB/reboot_reason_guard.py" "$BIN/reboot-reason-guard"
install -m 644 "$SRC"/systemd/thermal-guard.service "$SRC"/systemd/reboot-reason-guard.service "$UNITS/"

if [[ ! -f "$CONF_DIR/config.toml" ]]; then
    cp "$SRC/config.example.toml" "$CONF_DIR/config.toml"
    echo "Created $CONF_DIR/config.toml"
fi
if [[ -n "$LOG_DIR" ]]; then
    sed -i "s|^log_dir = .*|log_dir = \"$LOG_DIR\"|" "$CONF_DIR/config.toml"
    echo "Log dir set to $LOG_DIR"
fi

systemctl --user daemon-reload
if [[ $START -eq 1 ]]; then
    systemctl --user enable thermal-guard.service reboot-reason-guard.service
    systemctl --user restart thermal-guard.service reboot-reason-guard.service
    sleep 2
    systemctl --user --no-pager --lines=3 status thermal-guard.service reboot-reason-guard.service || true
fi
echo "Installed. Logs: $(python3 -c "import sys; sys.path.insert(0, '$LIB'); import guardlib; print(guardlib.load_config()['log_dir'])")"
