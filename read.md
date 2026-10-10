<div align="center">

<img src="docs/CBML-banner.jpg" alt="HTR-X Banner" width="100%" />

# ⚡ HTR-X — Premium Mirror & Leech Bot

**A powerful Telegram automation engine for downloading, mirroring, leeching, and media processing.**

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)
[![Heroku](https://img.shields.io/badge/Deploy-Heroku-430098?style=for-the-badge&logo=heroku&logoColor=white)](HEROKU_DEPLOY.md)
[![License](https://img.shields.io/badge/License-GPL--3.0-6E40C9?style=for-the-badge)](LICENSE)

**Quick links:** [Features](#-premium-features) · [Requirements](#-before-you-deploy) · [Heroku](#-deploy-on-heroku) · [VPS](#-one-command-vps-deployment) · [Docker](#-docker-deployment) · [Configuration](#-configuration) · [Troubleshooting](#-troubleshooting)

</div>

---

## ✨ Premium features

### Download and transfer
- **Mirror and leech:** Download from supported URLs and upload to Telegram or configured cloud destinations.
- **Torrent support:** Aria2 and qBittorrent integrations where installed and enabled.
- **Video and social downloads:** yt-dlp support for compatible sites and formats.
- **Usenet:** SABnzbd integration where configured.
- **Cloud storage:** Google Drive and rclone-based destinations, depending on your configuration.
- **Task controls:** Queue/task management and command flags supported by the installed bot version.

### Media processing
- **FFmpeg tools:** Optional conversion, encoding, compression, and watermark workflows.
- **Audio and subtitle tools:** Inspect and manage available streams when supported by the source file and installed FFmpeg build.
- **Archive handling:** Extraction and processing of supported archives.
- **Naming and metadata:** Custom filenames, captions, and thumbnails through supported commands/settings.

> Feature availability depends on your `config.py`, installed system packages, cloud credentials, Telegram limits, and the selected hosting plan. Hardware acceleration is not guaranteed on shared cloud dynos.

## 🧰 Before you deploy

Prepare the following:

- A Telegram bot token from [@BotFather](https://t.me/BotFather).
- Telegram API ID and API hash from [my.telegram.org](https://my.telegram.org).
- Your numeric Telegram user ID for `OWNER_ID`.
- A reachable MongoDB connection if your configuration uses MongoDB.
- A Linux VPS for the recommended full-featured setup, or a compatible Heroku container dyno for a limited cloud deployment.
- Any optional cloud-drive, rclone, debrid, or helper-bot credentials required by your configuration.

**Security:** Never commit real bot tokens, Telegram API hashes, database URLs, session strings, or cloud credentials to a public repository. If credentials have been exposed, revoke or rotate them before deployment.

## ☁️ Deploy on Heroku

See the complete guide in [`HEROKU_DEPLOY.md`](HEROKU_DEPLOY.md).

### Deployment overview

1. Fork or push this project to a GitHub repository you control.
2. Create a Heroku app and select the **Container** stack.
3. Review `config.py` and configure your own credentials securely before starting the worker.
4. Deploy the worker image and scale it to one instance.
5. Inspect logs and confirm that the bot, download engines, and required services start correctly.

```bash
heroku login
heroku stack:set container -a YOUR_APP_NAME
heroku container:login
heroku container:push worker -a YOUR_APP_NAME
heroku container:release worker -a YOUR_APP_NAME
heroku ps:scale worker=1 -a YOUR_APP_NAME
heroku logs --tail -a YOUR_APP_NAME
```

Use **one worker** unless the project has been explicitly configured for multi-instance task coordination. Multiple workers can duplicate Telegram updates or tasks.

### Heroku uptime and limitations

Heroku can restart dynos during normal platform operations; no README, script, or keep-alive ping can guarantee zero restarts or prevent platform enforcement. For a continuously running bot, use an eligible paid always-on dyno and keep the app within Heroku's acceptable-use rules. This bot's download, torrent, FFmpeg, disk, and network workloads may exceed small dyno limits. Heroku's local filesystem is ephemeral, so store important files externally.

A **true one-click Heroku deploy button** is not included yet because this project currently relies on `config.py` and does not provide a verified environment-variable-only setup for all required settings. Avoid a button that appears to deploy successfully but starts with missing or incorrect credentials.

## 🚀 One-command VPS deployment

Recommended for the full set of download engines and media tools. Use a fresh supported Ubuntu/Debian VPS and review the deployment script before running it. The included `deploy.vps` script installs system packages and creates a systemd service named `cantarellabots_bot`.

```bash
sudo apt-get update
sudo apt-get install -y git
sudo git clone https://github.com/hemanthbreaker3-hash/HTR-X.git /root/HTR-X
cd /root/HTR-X
sudo chmod +x deploy.vps start.sh setpkgs.sh tunnel.sh
sudo ./deploy.vps
```

If the repository URL or branch differs, replace it with your own repository URL. Before starting the service, configure your own values in `config.py` and make sure the file does not contain credentials copied from someone else's deployment.

### VPS service commands

```bash
# Check service status
sudo systemctl status cantarellabots_bot --no-pager

# Follow live logs
sudo journalctl -u cantarellabots_bot -f

# Restart after configuration changes
sudo systemctl restart cantarellabots_bot

# Stop the bot
sudo systemctl stop cantarellabots_bot

# Start the bot
sudo systemctl start cantarellabots_bot
```

The installer expects root privileges and installs system dependencies. Review `deploy.vps` first; do not run deployment scripts from repositories you do not trust.

## 🐳 Docker deployment

From the project root, review `docker-compose.yml`, `Dockerfile`, and `config.py` before building. Ensure persistent volumes and required environment/config files are correctly mapped for your setup.

```bash
docker compose config
docker compose up -d --build
docker compose logs -f
```

To stop the stack:

```bash
docker compose down
```

## ⚙️ Configuration

The main configuration file is `config.py`. Required settings commonly include:

| Setting | Purpose |
|---|---|
| `BOT_TOKEN` | Telegram bot token |
| `OWNER_ID` | Numeric Telegram user ID of the owner |
| `TELEGRAM_API` | Telegram API ID |
| `TELEGRAM_HASH` | Telegram API hash |
| `DATABASE_URL` | MongoDB URI if database-backed features are enabled |
| `AUTHORIZED_CHATS` | Optional authorized chat IDs, according to this version's config format |
| `STREAM_TOKENS` | Optional stream-bot token configuration |
| `HELPER_TOKENS` | Optional helper-bot tokens |
| `ENABLE_ENCODE` | Enable or disable encoding features |
| `ENABLE_COMPRESS` | Enable or disable compression features |
| `ENABLE_WATERMARK` | Enable or disable watermark features |

Check the comments and defaults in `config.py` for the complete list and expected formats. Do not assume that Heroku Config Vars override `config.py`; this repository version must explicitly read environment variables for that behavior.

## 🩺 Troubleshooting

### Service exits immediately

```bash
sudo journalctl -u cantarellabots_bot -n 200 --no-pager
```

Check Python syntax, missing dependencies, `config.py`, and the startup script. Fix the first traceback before investigating later errors.

### `OWNER_ID` or configuration errors

Use your own numeric Telegram user ID and verify that each Python assignment in `config.py` has a valid value. For example:

```python
OWNER_ID = 123456789
```

Do not leave an assignment incomplete, such as `OWNER_ID =`.

### Heroku worker is not running

```bash
heroku ps -a YOUR_APP_NAME
heroku logs --tail -a YOUR_APP_NAME
```

Confirm that the worker is scaled to one, the image release succeeded, configuration is valid, and the selected dyno has sufficient resources.

### Download or media tools are unavailable

Check whether the required binary is installed and on `PATH` (`ffmpeg`, `aria2c`, `qbittorrent-nox`, `rclone`, `yt-dlp`, or `sabnzbd`). Some features require separate credentials or services.

## 🤝 Contributing and support

- Review existing issues and logs before opening a bug report.
- Include the exact command, relevant traceback, deployment type, and Python/runtime version.
- **Remove tokens, session strings, database credentials, and private download links from logs before sharing them.**
- Follow the repository's license and the rules of the services you connect.

## 📄 License

This project is distributed under the license in [`LICENSE`](LICENSE). Review it before redistributing or deploying modified copies.

---

<div align="center">

**HTR-X • Mirror smarter. Manage tasks cleanly.**

</div>

## Owner and Sudo Troubleshooting

- Set `OWNER_ID` to the numeric Telegram user ID, not a username. The startup loader normalizes it to an integer so string values from `config.py` and Heroku Config Vars compare correctly.
- Set `SUDO_USERS` as space-separated numeric IDs, for example `123456789 987654321`.
- The owner and sudo commands are available in private chat as well as authorized chats. A user authorized in the database can use supported commands in DM.
- After changing Config Vars, restart the worker and inspect logs for configuration or handler errors.
- `/addsudo USER_ID` and `/rmsudo USER_ID` accept numeric IDs; they can also target a user by replying to that user's message.
