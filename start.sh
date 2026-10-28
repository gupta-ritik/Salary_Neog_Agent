#!/bin/sh
set -eu

cd /app/frontend
node server.js &
FRONTEND_PID=$!

cd /app/backend
uvicorn api:api --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

cleanup() {
    kill "$FRONTEND_PID" "$BACKEND_PID" 2>/dev/null || true
    wait "$FRONTEND_PID" "$BACKEND_PID" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

while kill -0 "$FRONTEND_PID" 2>/dev/null &&
      kill -0 "$BACKEND_PID" 2>/dev/null; do
    sleep 2
done

exit 1