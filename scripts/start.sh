#!/usr/bin/env bash
# Start the bot (uvicorn) and the ngrok tunnel together for local development.
#
# Usage: scripts/start.sh
# Reads NGROK_DOMAIN from .env (ENV_FILE overrides the path). PORT defaults to 8000.
# Ctrl+C stops both processes.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"
PORT="${PORT:-8000}"
UVICORN="${UVICORN:-$ROOT/.venv/bin/uvicorn}"

fail() {
    echo "Error: $1" >&2
    exit 1
}

[[ -f "$ENV_FILE" ]] || fail "$ENV_FILE not found. Copy .env.example to .env and fill it in."

# Read only NGROK_DOMAIN instead of sourcing .env, so no other value is executed or exported.
NGROK_DOMAIN="$(grep -E '^[[:space:]]*NGROK_DOMAIN=' "$ENV_FILE" | tail -n 1 | cut -d= -f2- || true)"
NGROK_DOMAIN="$(printf '%s' "$NGROK_DOMAIN" | tr -d '"'"'"' \r' | sed -e 's#^https\?://##' -e 's#/*$##')"

[[ -n "$NGROK_DOMAIN" ]] || fail "NGROK_DOMAIN is empty in $ENV_FILE. Put your static ngrok domain there."
[[ "$NGROK_DOMAIN" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] || fail "NGROK_DOMAIN '$NGROK_DOMAIN' is not a valid domain."
[[ "$PORT" =~ ^[0-9]+$ ]] || fail "PORT must be a number."
command -v ngrok >/dev/null 2>&1 || fail "ngrok is not installed or not in PATH."
[[ -x "$UVICORN" ]] || fail "$UVICORN not found. Create the virtual environment first (see README)."

cd "$ROOT"

"$UVICORN" bot.main:app --port "$PORT" &
UVICORN_PID=$!
trap 'kill "$UVICORN_PID" 2>/dev/null || true; wait "$UVICORN_PID" 2>/dev/null || true' EXIT

# Wait for the bot before opening the tunnel, so Meta never reaches a dead port.
for _ in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
        break
    fi
    kill -0 "$UVICORN_PID" 2>/dev/null || fail "The bot stopped while starting. Check the error above."
    sleep 1
done
curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 || fail "The bot did not answer on port $PORT after 30 seconds."

echo "Bot running on port $PORT. Webhook URL for Meta: https://$NGROK_DOMAIN/webhook"
ngrok http --url="$NGROK_DOMAIN" "$PORT"
