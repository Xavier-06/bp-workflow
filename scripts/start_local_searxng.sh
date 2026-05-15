#!/bin/zsh
set -euo pipefail

WORKSPACE="/Users/xavier/WorkBuddy/20260409155327/ir_runtime"
SOURCE_DIR="/Users/xavier/Downloads/searxng-master"
PYTHON_BIN="$WORKSPACE/tools/searxng/.venv/bin/python"
LOG_FILE="$WORKSPACE/tools/searxng/searxng-local.log"
PID_FILE="$WORKSPACE/tools/searxng/searxng-local.pid"
HOST="127.0.0.1"
PORT="8888"
SEARXNG_SECRET_VALUE="dev-secret-key-12345"
SSL_CERT_FILE_VALUE="/opt/homebrew/etc/openssl@3/cert.pem"
REQUESTS_CA_BUNDLE_VALUE="/opt/homebrew/etc/openssl@3/cert.pem"
CURL_CA_BUNDLE_VALUE="/opt/homebrew/etc/openssl@3/cert.pem"
SSL_CERT_DIR_VALUE="/opt/homebrew/etc/openssl@3/certs"

healthcheck() {
  "$PYTHON_BIN" - <<'PY'
import json
import sys
import urllib.request

checks = [
    ("home", "http://127.0.0.1:8888/", "text/html"),
    ("json", "http://127.0.0.1:8888/search?q=OpenAI&format=json", "application/json"),
]
for name, url, expected in checks:
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            content_type = resp.headers.get_content_type()
            body = resp.read()
        if expected not in content_type:
            print(f"{name}: bad content-type {content_type}")
            sys.exit(1)
        if name == "json":
            data = json.loads(body)
            print(f"{name}: ok results={len(data.get('results', []) or [])}")
        else:
            print(f"{name}: ok")
    except Exception as exc:
        print(f"{name}: fail {exc}")
        sys.exit(1)
PY
}

status() {
  if [[ -f "$PID_FILE" ]]; then
    local pid
    pid=$(cat "$PID_FILE")
    if ps -p "$pid" >/dev/null 2>&1; then
      echo "running pid=$pid"
      return 0
    fi
  fi
  echo "not running"
  return 1
}

start() {
  mkdir -p "$(dirname "$LOG_FILE")"
  if status >/dev/null 2>&1; then
    echo "already running"
    return 0
  fi
  : > "$LOG_FILE"
  cd "$SOURCE_DIR"
  nohup env \
    SEARXNG_SECRET="$SEARXNG_SECRET_VALUE" \
    SEARXNG_BIND_ADDRESS="$HOST" \
    SEARXNG_PORT="$PORT" \
    SSL_CERT_FILE="$SSL_CERT_FILE_VALUE" \
    REQUESTS_CA_BUNDLE="$REQUESTS_CA_BUNDLE_VALUE" \
    CURL_CA_BUNDLE="$CURL_CA_BUNDLE_VALUE" \
    SSL_CERT_DIR="$SSL_CERT_DIR_VALUE" \
    "$PYTHON_BIN" -m searx.webapp >> "$LOG_FILE" 2>&1 < /dev/null &
  echo $! > "$PID_FILE"
  status
  for _ in {1..12}; do
    if healthcheck >/dev/null 2>&1; then
      healthcheck
      return 0
    fi
    sleep 2
  done
  echo "healthcheck failed after startup"
  exit 1
}

stop() {
  if [[ -f "$PID_FILE" ]]; then
    local pid
    pid=$(cat "$PID_FILE")
    if ps -p "$pid" >/dev/null 2>&1; then
      kill "$pid"
      sleep 1
    fi
    rm -f "$PID_FILE"
  fi
  pkill -f 'searx.webapp' >/dev/null 2>&1 || true
  echo "stopped"
}

restart() {
  stop
  start
}

show_env() {
  "$PYTHON_BIN" - <<PY
import certifi, h2, httpx, sys
print('sys.executable=', sys.executable)
print('httpx.__file__=', httpx.__file__)
print('h2.__file__=', h2.__file__)
print('certifi.where=', certifi.where())
PY
}

cmd="${1:-start}"
case "$cmd" in
  start) start ;;
  stop) stop ;;
  restart) restart ;;
  status) status ;;
  healthcheck) healthcheck ;;
  show-env) show_env ;;
  *)
    echo "usage: $0 {start|stop|restart|status|healthcheck|show-env}"
    exit 1
    ;;
esac
