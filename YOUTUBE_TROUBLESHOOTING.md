# YouTube / yt-dlp recovery (HTR-X)

The log provided shows `LOGIN_REQUIRED`, `No video formats found`, and explicitly says the YouTube cookies are no longer valid. This is not a missing FFmpeg or Deno installation error. Deno is detected and yt-dlp's EJS challenge provider is loaded, but YouTube rejects the current session.

1. Export a fresh `cookies.txt` from a browser where YouTube is signed in. Use a private/incognito window for the export if possible, and do not share the file publicly.
2. Upload the new file through the bot's cookie settings. Confirm the bot reports the newly normalized file path and cookie count.
3. On the VPS, from the project directory, run:
   ```bash
   ./venv/bin/python -m pip install -U "yt-dlp[default]" curl-cffi
   ./venv/bin/yt-dlp --version
   /usr/local/bin/deno --version
   ```
4. Restart and inspect logs:
   ```bash
   systemctl restart cantarellabots_bot.service
   journalctl -u cantarellabots_bot.service -n 150 --no-pager
   ```
5. If fresh cookies still produce `LOGIN_REQUIRED`, test another authorized network/IP or wait before retrying. YouTube can reject datacenter IPs and may require a PO token for some player clients. Do not repeatedly retry the same invalid cookie file.

`KeyboardInterrupt` during the systemd stop sequence usually indicates Python received the configured SIGINT. The important symptom is that the process did not exit within systemd's stop timeout; this deploy script sets a bounded `TimeoutStopSec`, but if shutdown still hangs inspect child processes started by `start.sh` and ensure it uses `exec` for the Python process.
