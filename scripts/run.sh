#!/usr/bin/env bash
# Runs the bot in the foreground using the project's virtualenv.
# systemd calls this script; you can also run it by hand: ./run.sh
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if [[ ! -x venv/bin/python ]]; then
  echo "Virtualenv not found. Run: bash setup.sh" >&2
  exit 1
fi

# Running by hand while the service is up would start a second copy of the bot,
# and both would answer every command. (Under systemd, stdin is not a terminal.)
if [[ -t 0 ]] && systemctl is-active --quiet bertbot 2>/dev/null; then
  echo "The bertbot service is already running." >&2
  echo "Stop it first with: sudo systemctl stop bertbot" >&2
  exit 1
fi

# exec replaces this shell with Python so systemd tracks the bot process directly
exec venv/bin/python bot.py