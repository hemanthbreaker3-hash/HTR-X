# HTR-X Laptop Deployment Guide (Windows)

This guide covers Windows 10/11 first. Windows 7 is legacy and is not a reliable target for the full current HTR-X dependency stack: modern Python packages, TLS, FFmpeg builds, and browser/runtime dependencies may no longer support it. If you must use Windows 7, use the WSL/Linux VPS option or a separate supported Linux machine rather than assuming the latest dependencies will install.

## Method 1 — Run directly on Windows (recommended for testing)

1. Install **64-bit Python 3.11.x** from https://www.python.org/downloads/release/python-3119/ (for Windows 7, Python 3.8 is the last official Python line, but HTR-X's current dependencies are not guaranteed to support it).
2. During setup, tick **Add python.exe to PATH**.
3. Install Git for Windows from https://git-scm.com/download/win, then open **Git Bash**.
4. Clone your repository:
   ```bash
   git clone https://github.com/hemanthbreaker3-hash/HTR-X.git
   cd HTR-X
   ```
   If you are using a downloaded ZIP, extract it and open a terminal in the extracted `HTR-X-Main` folder instead.
5. Create and activate a virtual environment:
   ```bash
   py -3.11 -m venv .venv
   source .venv/Scripts/activate
   python -m pip install --upgrade pip setuptools wheel
   ```
   In Windows Command Prompt, activate with `.venv\Scripts\activate.bat`; in PowerShell use `.\.venv\Scripts\Activate.ps1`.
6. Install the Windows dependency list:
   ```bash
   pip install -r requirements_win.txt
   ```
   Some Linux-only packages or native tools may still fail on Windows. Fix the first actual error rather than repeatedly reinstalling everything.
7. Copy `.env.example` to `config.env` if the project expects `config.env`, then fill in required values such as `BOT_TOKEN`, `TELEGRAM_API`, `TELEGRAM_HASH`, `OWNER_ID`, and `DATABASE_URL` (if using MongoDB). Do not share this file.
8. Install required external tools supported by your chosen features (especially FFmpeg; optionally aria2/qBittorrent/rclone). Add their executable folders to PATH.
9. Start from the project root:
   ```bash
   python -m bot
   ```
   Keep this terminal open. Press `Ctrl+C` to stop.

## Method 2 — Windows with Docker Desktop

1. Install Docker Desktop for a supported Windows version: https://www.docker.com/products/docker-desktop/.
2. Start Docker Desktop and wait until it reports that the engine is running.
3. Put `config.env` in the project root and verify its required variables.
4. From PowerShell in the project folder, build and start:
   ```powershell
   docker compose build
   docker compose up -d
   docker compose logs -f
   ```
5. Stop with `docker compose down`.

Docker Desktop does not support every old Windows release. If your Windows version cannot run a current Docker Desktop, use Method 3 or 4.

## Method 3 — Deploy from the laptop to a Linux VPS over SSH

This is the best option if the laptop runs Windows 7 or cannot install the Linux dependencies.

1. Get a Linux VPS with Python/build tools and the required download utilities.
2. Open an SSH terminal (Git Bash/Windows Terminal or PuTTY) and connect:
   ```bash
   ssh root@YOUR_SERVER_IP
   ```
3. On the VPS, install Git and clone the repository:
   ```bash
   apt update
   apt install -y git python3 python3-venv python3-pip ffmpeg
   git clone https://github.com/hemanthbreaker3-hash/HTR-X.git
   cd HTR-X
   ```
4. Follow the repository's Linux deploy script only after reviewing it:
   ```bash
   chmod +x deploy.vps start.sh
   ./deploy.vps
   ```
   If the repository uses a different script name or directory, check `ls` first. Do not run `cd HTX-X`; the expected folder name is normally `HTR-X`.
5. Configure `config.env` securely, then check the service/logs using the instructions printed by the deploy script.
6. Close the laptop if you want—the bot continues running on the VPS.

## Method 4 — Run HTR-X inside a Linux virtual machine (VM)

1. Install VirtualBox on a supported host OS: https://www.virtualbox.org/.
2. Create an Ubuntu Server VM with adequate disk/RAM and network access.
3. Install Git, Python, FFmpeg, and other required system packages inside Ubuntu.
4. Clone the repo and run the Linux deployment steps from Method 3.
5. Keep the VM running while the bot is needed. This consumes the laptop's power and resources.

## Common checks

- Run commands from the repository root (the folder containing `bot/`, `config.py`, and `requirements.txt`).
- Use one bot process/worker unless the application is explicitly configured for coordinated multi-worker execution.
- If startup fails, copy the **first traceback/error** from the terminal. Later errors can be consequences of the first one.
- Windows 7 is unsupported for many current dependencies. Do not assume `pip install -r requirements_win.txt` will succeed on Windows 7.
- A laptop is not a 24/7 host if it sleeps, loses internet, or powers off.
