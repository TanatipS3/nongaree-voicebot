#!/bin/sh
set -eu

echo "Checking required Docker package files..."
test -f docker-compose.yml
test -f .env.example
test -x load-images.sh
test -d images
test -f qdrant/snapshots/thai_tax_kb.snapshot.tar.gz
test -x qdrant/scripts/restore-qdrant-snapshot.sh

echo "Checking compose configuration..."
if [ ! -f .env ]; then
  cp .env.example .env
  created_env=1
else
  created_env=0
fi

docker compose config >/dev/null

if [ "${REQUIRE_IMAGES:-0}" = "1" ]; then
  test -f images/nongaree-voicebot-web.tar
  test -f images/nongaree-voicebot-agent.tar
fi

if [ "$created_env" = "1" ]; then
  rm -f .env
fi

echo "Docker package structure is valid."
