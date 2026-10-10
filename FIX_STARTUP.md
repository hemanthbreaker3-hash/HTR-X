# Startup crash fix

- `start.sh` now uses the project's virtual-environment Python explicitly.
- The automatic `update.py` run is disabled during normal service restarts. Set `RUN_UPDATE=1` only when intentionally updating the checkout and dependencies.
- The obsolete PyPI `asyncio` dependency was removed; `asyncio` is built into Python.
- `pymongo` is pinned to `>=4.9` for the async client API used by `update.py`.
- `deploy.vps` now waits for network-online and uses a less aggressive restart policy.

After copying the project to the VPS, run `sudo bash deploy.vps` from the project directory. If it still fails, inspect the Python traceback with:

```bash
sudo journalctl -u cantarellabots_bot.service -n 150 --no-pager
```

Do not publish `config.py`: it contains credentials. Rotate the Telegram bot token and MongoDB password if this archive or its secrets have been shared outside a trusted private environment.
