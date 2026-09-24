#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
template_dir="${repo_root}/docker container"
out_root="/Users/max/Documents/RD"
stamp="$(date +%Y%m%d-%H%M%S)"
pkg="${out_root}/nongaree-voicebot-image-deploy-${stamp}"
archive="${pkg}.tar.gz"

mkdir -p "${pkg}/images" "${pkg}/qdrant"

cp "${template_dir}/docker-compose.yml" "${pkg}/docker-compose.yml"
cp "${template_dir}/load-images.sh" "${pkg}/load-images.sh"
cp "${template_dir}/README.md" "${pkg}/README.md"
cp "${template_dir}/README_TH.md" "${pkg}/README_TH.md"
cp "${template_dir}/INSTALL_EN.md" "${pkg}/INSTALL_EN.md"
cp "${template_dir}/INSTALL_TH.md" "${pkg}/INSTALL_TH.md"
cp "${template_dir}/.env.example" "${pkg}/.env.example"
cp "${template_dir}/.env.example" "${pkg}/.env"
chmod +x "${pkg}/load-images.sh"
chmod 600 "${pkg}/.env"

cp -R "${template_dir}/qdrant/snapshots" "${pkg}/qdrant/"
cp -R "${template_dir}/qdrant/scripts" "${pkg}/qdrant/"

docker image inspect nongaree-voicebot-web:latest >/dev/null
docker image inspect nongaree-voicebot-agent:latest >/dev/null

docker save -o "${pkg}/images/nongaree-voicebot-web.tar" nongaree-voicebot-web:latest
docker save -o "${pkg}/images/nongaree-voicebot-agent.tar" nongaree-voicebot-agent:latest

tar -C "${out_root}" -czf "${archive}" "$(basename "${pkg}")"

echo "Created ${archive}"
echo "This archive uses placeholder env values. Replace .env before customer deployment."
