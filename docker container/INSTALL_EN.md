# Nongaree Voicebot Installation Guide

This document explains how to install and run the Nongaree Voicebot Docker package from the GitHub Release.

The package is designed for company handoff. The receiver does not need to build the source code. They only need Docker, the release package, and the correct runtime values in `.env`.

## 1. What To Download

Open the GitHub Release page:

```text
https://github.com/TheerapatGunthog/nongaree-voicebot/releases/tag/nongaree-voicebot-image-deploy-20260629-132329
```

Download this file:

```text
nongaree-voicebot-image-deploy-20260629-132329.tar.gz
```

Do not use GitHub's automatic `Source code (zip)` or `Source code (tar.gz)` downloads for deployment. They do not include the exported Docker images.

Optional but recommended:

```text
SHA256SUMS.txt
```

The checksum file is only used to verify that the downloaded package is complete and unchanged.

## 2. What Is Inside The Package

After unpacking, the package contains:

```text
nongaree-voicebot-image-deploy-20260629-132329/
  docker-compose.yml
  load-images.sh
  .env.example
  .env
  README.md
  README_TH.md
  INSTALL_EN.md
  INSTALL_TH.md
  images/
    nongaree-voicebot-web.tar
    nongaree-voicebot-agent.tar
  qdrant/
    snapshots/
      thai_tax_kb.snapshot.tar.gz
    scripts/
      restore-qdrant-snapshot.sh
```

The two files in `images/` are prebuilt Docker images:

- `nongaree-voicebot-web.tar`: Next.js web UI
- `nongaree-voicebot-agent.tar`: Python LiveKit voice agent

The Qdrant snapshot contains the RAG knowledge base:

- Qdrant collection: `thai_tax_kb`
- Expected indexed points: `1,311`

The package does not contain real API keys or production secrets.

## 3. Requirements On The Target Machine

The target machine must have:

- Docker installed
- Docker Compose available through `docker compose`
- Network access to the company LiveKit server
- Network access to the company LLM endpoint
- Network access to the company STT endpoint
- Network access to the company TTS endpoint
- Network access to the company embedding endpoint
- Port `3000` available for the web UI
- Port `6333` available for Qdrant

If another service already uses port `3000` or `6333`, change the port mapping in `docker-compose.yml` before starting.

## 4. Install Steps

Open a terminal in the folder where the release package was downloaded.

Unpack the package:

```bash
tar -xzf nongaree-voicebot-image-deploy-20260629-132329.tar.gz
cd nongaree-voicebot-image-deploy-20260629-132329
```

Create the runtime environment file:

```bash
cp .env.example .env
```

Open `.env` in a text editor and replace every placeholder value with the real company value.

Required values:

```text
LIVEKIT_URL
LIVEKIT_API_KEY
LIVEKIT_API_SECRET

LLM_BASE_URL
LLM_API_KEY
LLM_MODEL
LLM_MODELS
ROUTER_MODEL
GENERATE_MODEL
TEXT_GENERATE_MODEL

STT_BASE_URL
STT_API_KEY
STT_MODEL

TTS_BASE_URL
TTS_API_KEY
TTS_MODEL
TTS_VOICE

EMBEDDING_BASE_URL
EMBEDDING_API_KEY
EMBEDDING_MODEL

QDRANT_COLLECTION
RAG_SCORE_THRESHOLD
RAG_TOP_K
```

The `.env.example` file also contains a few legacy compatibility values such as `OPENAI_API_KEY`, `OPENAI_MODEL`, and `BASE_URL`. For this Docker bot handoff, the important runtime values are the LiveKit, LLM, STT, TTS, embedding, and Qdrant values listed above.

Keep these default values unless the deployment environment requires a change:

```text
QDRANT_URL=http://qdrant:6333
QDRANT_COLLECTION=thai_tax_kb
RAG_ENABLED=true
RAG_SCORE_THRESHOLD=0.75
RAG_TOP_K=8
NEXT_PUBLIC_SHOW_SESSION_HISTORY=true
```

Load the prebuilt Docker images:

```bash
./load-images.sh
```

Start all services:

```bash
docker compose up -d
```

Open the bot UI:

```text
http://localhost:3000
```

## 5. Verify The Deployment

Check that all containers are running:

```bash
docker compose ps
```

You should see services similar to:

```text
qdrant
qdrant-restore
web
agent
```

Check Qdrant restore:

```bash
docker compose logs qdrant-restore
```

Expected result: the restore container completes successfully.

Check the RAG collection:

```bash
curl http://localhost:6333/collections/thai_tax_kb
```

Expected result includes approximately:

```text
points_count: 1311
```

Check web logs:

```bash
docker compose logs -f web
```

Check agent logs:

```bash
docker compose logs -f agent
```

Expected behavior:

- Open `http://localhost:3000`
- The bot connects to the LiveKit room
- The bot greets the user
- The user can type a question
- The user can hold the mic button and speak
- The right-side answer detail panel updates
- The session history panel keeps the current session questions and answers

## 6. Common Problems And Fixes

### The page opens but the bot does not greet

Check:

```bash
docker compose logs -f agent
docker compose logs -f web
```

Likely causes:

- `LIVEKIT_URL` is wrong
- `LIVEKIT_API_KEY` or `LIVEKIT_API_SECRET` is wrong
- The LiveKit server cannot dispatch the agent
- The target machine cannot reach the LiveKit server

### The bot connects but cannot answer

Check:

```bash
docker compose logs -f agent
```

Likely causes:

- LLM endpoint is not reachable
- `LLM_API_KEY` is wrong
- `LLM_MODEL` is not available on the configured server
- Embedding endpoint is not reachable
- Qdrant restore did not complete

### Microphone does not work

Check:

- Browser microphone permission is allowed
- The page is opened over a valid origin. For local testing, `http://localhost:3000` is acceptable in modern browsers.
- STT endpoint and key are correct if using server-side STT

### TTS does not speak

Check:

- `TTS_BASE_URL`
- `TTS_API_KEY`
- `TTS_MODEL`
- `TTS_VOICE`
- Browser audio output is not muted

### Qdrant has no collection

Run:

```bash
docker compose logs qdrant-restore
```

If needed, force a clean restore:

```bash
docker compose down -v
docker compose up -d
```

This deletes the local Qdrant Docker volume and restores from the bundled snapshot again.

## 7. Stop And Restart

Stop services:

```bash
docker compose down
```

Start services again:

```bash
docker compose up -d
```

View logs:

```bash
docker compose logs -f
```

## 8. Security Notes

- Do not commit a real `.env` file to GitHub.
- The release package includes placeholder `.env` values only.
- The company must put real keys into `.env` on the deployment machine.
- If sharing a filled `.env`, use a secure internal channel only.
- The Docker images include the application runtime, but not production API keys.

## 9. Final Quick Start

```bash
tar -xzf nongaree-voicebot-image-deploy-20260629-132329.tar.gz
cd nongaree-voicebot-image-deploy-20260629-132329
cp .env.example .env
# Edit .env and fill real company values first.
./load-images.sh
docker compose up -d
docker compose ps
```

Open:

```text
http://localhost:3000
```
