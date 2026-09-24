#!/usr/bin/env bash
set -euo pipefail

for image_tar in images/*.tar; do
  echo "Loading ${image_tar}"
  docker load -i "${image_tar}"
done
