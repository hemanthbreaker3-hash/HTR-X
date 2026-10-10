# HTR-X — Heroku Container Deployment

This project uses the repository Dockerfile and runs as a **worker**. The bot does not need a web endpoint to receive Telegram updates.

## Uptime: avoid sleeping

- Scale a worker process, not an idle web dyno: `heroku ps:scale worker=1 -a YOUR_APP_NAME`.
- Choose a paid, always-on dyno size appropriate for the workload. Eco workers do not sleep due to web inactivity, but Eco dynos use a monthly shared hours allowance; when that allowance is exhausted, dynos can be stopped for the rest of the month.
- Heroku can still restart dynos during maintenance, deploys, crashes, or platform events. No code can guarantee zero restarts or prevent Heroku policy enforcement.
- This bot runs download/media services that can exceed small dyno CPU, RAM, disk, or network limits. A suitably sized VPS is generally better for heavy torrenting, FFmpeg, and large files.
- The filesystem is ephemeral. Do not store the only copy of important files on a dyno.

## 1. Prepare repository and app

Push this project to a GitHub repository you control, then create a Heroku app in the dashboard. Install the Heroku CLI and authenticate.

```bash
heroku login
heroku apps:info -a YOUR_APP_NAME
heroku stack:set container -a YOUR_APP_NAME
```

## 2. Set required Config Vars

The configuration loader now reads environment variables after loading safe defaults from `config.py`, so Heroku Config Vars override file values. Set at least these values in **Heroku Dashboard → Settings → Config Vars** (or use the CLI):

```bash
heroku config:set BOT_TOKEN='YOUR_BOT_TOKEN' -a YOUR_APP_NAME
heroku config:set OWNER_ID='123456789' -a YOUR_APP_NAME
heroku config:set TELEGRAM_API='YOUR_API_ID' -a YOUR_APP_NAME
heroku config:set TELEGRAM_HASH='YOUR_API_HASH' -a YOUR_APP_NAME
heroku config:set DATABASE_URL='YOUR_MONGODB_URI' -a YOUR_APP_NAME
```

`DATABASE_URL` is required for the database-backed setup used by this project. If you use a different database configuration, follow the source project's requirements. Add any optional credentials your enabled features need as Config Vars. Do not put secrets in Git or in public issue reports.

## 3. Build and release the worker

Run these commands from the repository root: 

```bash
heroku container:login
heroku container:push worker -a YOUR_APP_NAME
heroku container:release worker -a YOUR_APP_NAME
heroku ps:scale worker=1 -a YOUR_APP_NAME
heroku ps -a YOUR_APP_NAME
heroku logs --tail -a YOUR_APP_NAME
```

Run one worker unless you have verified that task queues, schedulers, and Telegram update handling are safe across multiple instances.

## 4. Updates and restart controls

After pushing code changes to your repository, rebuild and release the container with the commands in step 3. To restart the worker manually:

```bash
heroku dyno:restart worker -a YOUR_APP_NAME
```

Check status and logs:

```bash
heroku ps -a YOUR_APP_NAME
heroku logs --tail -a YOUR_APP_NAME
heroku releases -a YOUR_APP_NAME
```

## 5. One-command deploy helper

After the app is created and Config Vars are set, save the following as `deploy-heroku.sh` on your machine and run `bash deploy-heroku.sh YOUR_APP_NAME`. It builds and releases the worker image; it cannot create billing/payment approval or guarantee zero platform restarts.

```bash
#!/usr/bin/env bash
set -Eeuo pipefail
APP_NAME="${1:?Usage: bash deploy-heroku.sh YOUR_APP_NAME}"
heroku container:login
heroku stack:set container -a "$APP_NAME"
heroku container:push worker -a "$APP_NAME"
heroku container:release worker -a "$APP_NAME"
heroku ps:scale worker=1 -a "$APP_NAME"
heroku ps -a "$APP_NAME"
heroku logs --tail -a "$APP_NAME"
```

## Troubleshooting

- **Missing config:** check Config Vars spelling and confirm all five required values are set.
- **Worker not running:** use `heroku ps -a YOUR_APP_NAME` and `heroku logs --tail -a YOUR_APP_NAME`.
- **Out of memory / task killed:** use a larger dyno or move the workload to a VPS.
- **Data disappears after restart:** use external persistent storage; dyno files are temporary.
- **Service sleeps/stops:** confirm you scaled `worker=1`, your plan is always-on, and you have not exhausted the Eco hours pool. Platform restarts can still happen.
