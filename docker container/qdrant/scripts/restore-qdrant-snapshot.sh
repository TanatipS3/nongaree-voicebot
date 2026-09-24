#!/bin/sh
set -eu

QDRANT_URL="${QDRANT_URL:-http://qdrant:6333}"
QDRANT_COLLECTION="${QDRANT_COLLECTION:-thai_tax_kb}"
SNAPSHOT_PATH="${SNAPSHOT_PATH:-/snapshots/thai_tax_kb.snapshot.tar.gz}"
UPLOAD_PATH="${SNAPSHOT_PATH}"

echo "Waiting for Qdrant at ${QDRANT_URL}..."
until curl -fsS "${QDRANT_URL}/collections" >/dev/null; do
  sleep 2
done

if curl -fsS "${QDRANT_URL}/collections/${QDRANT_COLLECTION}" >/dev/null 2>&1; then
  echo "Qdrant collection ${QDRANT_COLLECTION} already exists; skipping snapshot restore."
  exit 0
fi

if [ "${SNAPSHOT_PATH##*.}" = "gz" ]; then
  UPLOAD_PATH="/tmp/${QDRANT_COLLECTION}.snapshot"
  echo "Decompressing ${SNAPSHOT_PATH} to ${UPLOAD_PATH}..."
  gzip -dc "${SNAPSHOT_PATH}" > "${UPLOAD_PATH}"
fi

echo "Restoring ${QDRANT_COLLECTION} from ${SNAPSHOT_PATH}..."
curl -fsS \
  -X POST \
  "${QDRANT_URL}/collections/${QDRANT_COLLECTION}/snapshots/upload?priority=snapshot" \
  -F "snapshot=@${UPLOAD_PATH}"

echo
echo "Verifying restored collection..."
curl -fsS "${QDRANT_URL}/collections/${QDRANT_COLLECTION}"
echo
