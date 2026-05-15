#!/bin/bash
# Shared workspace environment bootstrap for launchd/CLI scripts.

export PATH="/Users/xavier/WorkBuddy/20260409155327/ir_runtime/bin:/Users/xavier/go/bin:/opt/homebrew/bin:/opt/homebrew/Cellar/node/25.7.0/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export HOME="/Users/xavier"
export SSL_CERT_FILE="/opt/homebrew/etc/openssl@3/cert.pem"
export REQUESTS_CA_BUNDLE="/opt/homebrew/etc/openssl@3/cert.pem"
export CURL_CA_BUNDLE="/opt/homebrew/etc/openssl@3/cert.pem"
export SSL_CERT_DIR="/opt/homebrew/etc/openssl@3/certs"

CRED_FILE="/Users/xavier/WorkBuddy/20260409155327/ir_runtime/.credentials/investment-research.env"
if [ -f "$CRED_FILE" ]; then
  set -a
  . "$CRED_FILE"
  set +a
fi
