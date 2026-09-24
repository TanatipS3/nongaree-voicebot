#!/bin/zsh
cd /Users/max/Documents/RD/nongaree-voicebot || exit 1

CERTIFI_BUNDLE="$(python3 - <<'PY'
import certifi
print(certifi.where())
PY
)"
export SSL_CERT_FILE="$CERTIFI_BUNDLE"
export REQUESTS_CA_BUNDLE="$CERTIFI_BUNDLE"

echo "Opening standalone Nongaree bot demo..."
python3 local_bot_demo.py

echo
echo "Demo stopped. Press any key to close this terminal."
read -k 1
