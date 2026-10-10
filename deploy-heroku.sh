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
