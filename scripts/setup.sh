#!/usr/bin/env bash
# One-time setup for the counter bot on an Ubuntu server (e.g. Oracle Cloud).
# Run from the folder that contains bot.py:   bash setup.sh
# Safe to re-run: it reuses the venv and .env, refreshes the service, and restarts the bot.
set -euo pipefail

SERVICE_NAME="bertbot"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_USER="$(id -un)"

if [[ ! -f "$APP_DIR/bot.py" ]]; then
  echo "bot.py not found in $APP_DIR. Put setup.sh and run.sh next to bot.py." >&2
  exit 1
fi

echo "==> Installing system packages"
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv

if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "Python 3.10+ is required (found: $(python3 --version)). Use Ubuntu 22.04 or newer." >&2
  exit 1
fi

echo "==> Creating virtualenv and installing dependencies"
if [[ ! -d "$APP_DIR/venv" ]]; then
  python3 -m venv "$APP_DIR/venv"
fi
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install discord.py python-dotenv

echo "==> Configuring .env"
if [[ ! -f "$APP_DIR/.env" ]]; then
  read -rsp "Paste your Discord bot token (input hidden): " TOKEN
  echo
  if [[ -z "$TOKEN" ]]; then
    echo "No token entered, aborting." >&2
    exit 1
  fi
  (umask 077 && printf 'DISCORD_TOKEN=%s\n' "$TOKEN" > "$APP_DIR/.env")
else
  echo ".env already exists, leaving it alone."
fi
chmod 600 "$APP_DIR/.env"

if grep -q '^TEST_GUILD_ID' "$APP_DIR/.env"; then
  echo "WARNING: .env contains TEST_GUILD_ID. Commands will only sync to that test server." >&2
  echo "         Remove that line for production, then: sudo systemctl restart $SERVICE_NAME" >&2
fi

chmod +x "$APP_DIR/run.sh"

echo "==> Installing systemd service ($SERVICE_NAME)"
sudo tee "/etc/systemd/system/${SERVICE_NAME}.service" > /dev/null <<EOF
[Unit]
Description=Counter Discord bot
After=network-online.target
Wants=network-online.target

[Service]
User=${RUN_USER}
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/run.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

sleep 2
echo
systemctl --no-pager --lines=0 status "$SERVICE_NAME" || true
echo
echo "Done. Useful commands:"
echo "  journalctl -u $SERVICE_NAME -f        # live logs"
echo "  sudo systemctl restart $SERVICE_NAME  # after updating bot.py"
echo "  sudo systemctl stop $SERVICE_NAME     # stop the bot"