#!/bin/zsh
cd /Users/max/Documents/RD/nongaree-voicebot || exit 1

echo "Starting Nongaree LiveKit voice agent..."
echo "This uses agent.py and the graph retrieve node."
CERTIFI_BUNDLE="$(python3 - <<'PY'
import certifi
print(certifi.where())
PY
)"
export SSL_CERT_FILE="$CERTIFI_BUNDLE"
export REQUESTS_CA_BUNDLE="$CERTIFI_BUNDLE"
python3 agent.py dev

echo
echo "Agent stopped. Press any key to close this terminal."
read -k 1
