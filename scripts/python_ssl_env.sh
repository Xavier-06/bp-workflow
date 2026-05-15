#!/bin/bash
# Workspace-local SSL environment for Python / requests / curl_cffi / Scrapling on this Mac
export SSL_CERT_FILE="/opt/homebrew/etc/openssl@3/cert.pem"
export REQUESTS_CA_BUNDLE="/opt/homebrew/etc/openssl@3/cert.pem"
export CURL_CA_BUNDLE="/opt/homebrew/etc/openssl@3/cert.pem"
export SSL_CERT_DIR="/opt/homebrew/etc/openssl@3/certs"
