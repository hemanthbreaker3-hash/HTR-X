#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "$(readlink -f "$0")")"
PYTHON_BIN="${PYTHON_BIN:-$PWD/venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3 || command -v python)"
fi
if [[ -z "${PYTHON_BIN:-}" || ! -x "$PYTHON_BIN" ]]; then
  echo "ERROR: Python interpreter not found. Create venv with: python3 -m venv venv" >&2
  exit 127
fi

# Updating source code and packages on every systemd restart can overwrite local
# changes and make a failing service loop. Run update.py only when explicitly asked.
if [[ "${RUN_UPDATE:-0}" == "1" ]]; then
  "$PYTHON_BIN" update.py
fi

exec "$PYTHON_BIN" -u -m bot
