#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$(readlink -f "$0")")"
PYTHON="$(pwd)/venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  echo "ERROR: venv Python not found. Run ./deploy.vps first."
  exit 1
fi

"$PYTHON" -m py_compile config.py || {
  echo "ERROR: config.py has a Python syntax error; fix it before starting the bot."
  exit 1
}
"$PYTHON" - <<'PY'
import config
required = ("BOT_TOKEN", "OWNER_ID", "TELEGRAM_API", "TELEGRAM_HASH")
missing = [k for k in required if not hasattr(config, k) or getattr(config, k) in (None, "")]
if missing:
    raise SystemExit("ERROR: Missing config values: " + ", ".join(missing))
if config.BOT_TOKEN == "PUT_YOUR_BOT_TOKEN_HERE":
    raise SystemExit("ERROR: Set your real BOT_TOKEN in config.py")
if config.TELEGRAM_HASH == "PUT_YOUR_TELEGRAM_API_HASH_HERE":
    raise SystemExit("ERROR: Set your real TELEGRAM_HASH in config.py")
if not isinstance(config.OWNER_ID, int) or not isinstance(config.TELEGRAM_API, int) or config.TELEGRAM_API <= 0:
    raise SystemExit("ERROR: OWNER_ID and TELEGRAM_API must be valid integers")
PY

python update.py
exec "$PYTHON" -m bot
