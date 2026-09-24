# Nongaree Voicebot Docker Image Package

This folder is the no-source-code deployment package for Nongaree Voicebot.

## Latest Source Build Note

If the supervisor pulled the `Max` branch from GitHub and wants the latest source version, run from the repository root instead:

```bash
cp "docker container/.env.example" "docker container/.env"
# edit docker container/.env and fill real company values
docker compose up --build -d
```

This rebuilds the web image from current source and includes the Aree picture avatar at `public/avatar/aree_cutout.png`.

Full step-by-step installation instructions are available in this folder:

```text
INSTALL_EN.md
INSTALL_TH.md
README_TH.md
```

It runs prebuilt Docker images and does not require the customer to receive the app source code.

## Download The Ready Package

For company handoff, use the GitHub Release page first. This page is the easiest link to send because it contains both downloadable files and the release notes:

```text
https://github.com/TheerapatGunthog/nongaree-voicebot/releases/tag/nongaree-voicebot-image-deploy-20260629-132329
```

On that page, download this package:

```text
nongaree-voicebot-image-deploy-20260629-132329.tar.gz
```

Do not use GitHub's automatic `Source code (zip)` or `Source code (tar.gz)` files for deployment. Those files are source snapshots and do not include the exported Docker images.

If a direct download link is needed, use:

```text
https://github.com/TheerapatGunthog/nongaree-voicebot/releases/download/nongaree-voicebot-image-deploy-20260629-132329/nongaree-voicebot-image-deploy-20260629-132329.tar.gz
```

Optional checksum file, used only to verify the downloaded archive:

```text
https://github.com/TheerapatGunthog/nongaree-voicebot/releases/download/nongaree-voicebot-image-deploy-20260629-132329/SHA256SUMS.txt
```

The release archive contains the Docker image tar files. The repository folder itself only contains the template and scripts.

## Included

- `web` container: Next.js frontend on `http://localhost:3000`
- `agent` container: Python LiveKit voice agent
- `qdrant` container: local Qdrant vector database
- `qdrant-restore` one-shot container: restores the bundled RAG snapshot
- Bundled RAG snapshot: `qdrant/snapshots/thai_tax_kb.snapshot.tar.gz`
- `load-images.sh`: loads exported Docker images from `images/*.tar`

The bundled RAG snapshot restores the `thai_tax_kb` collection with 1,311 indexed points.

## Still Required

The package includes the bot code and RAG database, but it does not include the external AI model servers. The company must provide reachable endpoints and credentials for:

- LiveKit
- LLM
- STT
- TTS
- Embedding API

These are configured in `.env`.

## Customer Install

Step 1: download this file from the GitHub Release page:

```text
nongaree-voicebot-image-deploy-20260629-132329.tar.gz
```

Step 2: open a terminal in the folder where the file was downloaded, then unpack it:

```bash
tar -xzf nongaree-voicebot-image-deploy-20260629-132329.tar.gz
cd nongaree-voicebot-image-deploy-20260629-132329
```

Step 3: create the runtime env file from the template:

```bash
cp .env.example .env
```

Step 4: edit `.env` and replace all placeholder values with real company values.

Required values include:

- LiveKit URL, API key, and API secret
- LLM endpoint, model, and key
- STT endpoint, model, and key
- TTS endpoint, model, and key
- Embedding endpoint, model, and key

Step 5: load the prebuilt Docker images:

```bash
./load-images.sh
```

Step 6: start the services:

```bash
docker compose up -d
```

Step 7: open the bot UI:

```text
http://localhost:3000
```

If `.env` still contains placeholder values, the containers may start but the bot will not connect to LiveKit or the AI services correctly.

## Check Status

```bash
docker compose ps
docker compose logs -f qdrant-restore
docker compose logs -f agent
docker compose logs -f web
```

Verify Qdrant restored the bundled RAG collection:

```bash
curl http://localhost:6333/collections/thai_tax_kb
```

Expected collection count:

```text
points_count: 1311
```

## Reset RAG Data

To force a clean restore from the bundled snapshot:

```bash
docker compose down -v
docker compose up -d
```

## Notes

- GitHub contains `.env.example` only. Do not commit real `.env` secrets.
- GitHub does not contain `images/*.tar` because the Docker image exports are large runtime artifacts.
- The customer package includes `images/*.tar`, but `.env` contains placeholder values only.
- Fill the real `.env` values only on the deployment machine or through the company's approved secret-management process.
- If their LLM/STT/TTS/embedding services run on the same host as Docker, use `host.docker.internal` URLs in `.env`.

## Handoff Machine: Recreate This Archive

This section is only for the person preparing the handoff package, not the customer.

First make sure these prebuilt images exist locally:

```bash
docker image inspect nongaree-voicebot-web:latest
docker image inspect nongaree-voicebot-agent:latest
```

Then run this from the repository root:

```bash
./docker\ container/package-image-deploy.sh
```

The generated archive is written outside the repository under `/Users/max/Documents/RD`.
