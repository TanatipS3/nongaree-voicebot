# Nong Aree Voicebot Company Docker Handoff

Use this document when sending the deploy package to the supervisor or company.

Thai version:

```text
COMPANY_DOCKER_HANDOFF_TH.md
```

The company should download the GitHub Release package, fill in `.env`, load the Docker images, and run `docker compose`.

This handoff does not require them to build from source code.

## Latest Source Build From GitHub

If the supervisor has pulled the `Max` branch from GitHub and wants the newest UI/avatar, use this path instead of the old release image package:

```bash
git checkout Max
git pull
cp "docker container/.env.example" "docker container/.env"
# edit docker container/.env and fill real company values
docker compose up --build -d
```

Open:

```text
http://localhost:3000
```

This rebuilds `nongaree-voicebot-web:latest` from the current source code, including the static Aree avatar at `public/avatar/aree_cutout.png`. If an older machine still shows the eye avatar, remove or rebuild the old image:

```bash
docker compose down
docker compose up --build -d
```

## 1. What To Send To The Company

Send this release page first. It is the easiest link because it shows the package file, checksum file, and release notes in one place:

```text
https://github.com/TheerapatGunthog/nongaree-voicebot/releases/tag/nongaree-voicebot-image-deploy-20260629-132329
```

If they want the package file directly, send this link instead:

```text
https://github.com/TheerapatGunthog/nongaree-voicebot/releases/download/nongaree-voicebot-image-deploy-20260629-132329/nongaree-voicebot-image-deploy-20260629-132329.tar.gz
```

Optional checksum file, used only to verify the download was not corrupted:

```text
https://github.com/TheerapatGunthog/nongaree-voicebot/releases/download/nongaree-voicebot-image-deploy-20260629-132329/SHA256SUMS.txt
```

The repository is private, so the person downloading must have GitHub access to this repository or the release asset.

## 2. What The Company Downloads

Download this file from the release page:

```text
nongaree-voicebot-image-deploy-20260629-132329.tar.gz
```

This is the deploy package. It contains:

- Prebuilt Docker image tar files for the web UI and agent
- Docker Compose file
- Qdrant/RAG snapshot
- `.env.example`
- Startup scripts
- README instructions

It does not contain real API keys or secrets.

## 3. What They Run After Downloading

Run these commands in the folder where the `.tar.gz` file was downloaded:

```bash
tar -xzf nongaree-voicebot-image-deploy-20260629-132329.tar.gz
cd nongaree-voicebot-image-deploy-20260629-132329
cp .env.example .env
```

Now open `.env` and replace every placeholder value with the real company values:

```text
LiveKit URL, API key, and API secret
LLM endpoint, model, and key
STT endpoint, model, and key
TTS endpoint, model, and key
Embedding endpoint, model, and key
```

After `.env` is filled, load the images and start the bot:

```bash
./load-images.sh
docker compose up -d
```

Open:

```text
http://localhost:3000
```

## 4. What Must Be Ready Before It Works

The target machine must have:

- Docker installed and running
- Network access to the company LiveKit server
- Network access to the configured LLM, STT, TTS, and embedding endpoints
- Port `3000` available for the web UI
- Port `6333` available for Qdrant

The bot will not work if `.env` is still placeholder values.

## 5. Quick Health Check

After startup:

```bash
docker compose ps
docker compose logs -f qdrant-restore
docker compose logs -f agent
docker compose logs -f web
```

Verify RAG/Qdrant:

```bash
curl http://localhost:6333/collections/thai_tax_kb
```

Expected result includes:

```text
points_count: 1311
```

## Important Notes

- The release package does not contain real secrets.
- The company must fill `.env` before running.
- The package includes the RAG/Qdrant snapshot.
- The package includes the prebuilt `web` and `agent` Docker images.
- The repository itself does not contain the large image tar files; they are stored as GitHub Release assets.
