# Nongaree Agent

LiveKit voice agent with LumoFace avatar integration.

## Setup

**1. Install dependencies**

```bash
pip install -r requirements.txt
```

**2. Configure environment**

```bash
cp .env.example .env
# Edit .env with your credentials
```

**3. Download Silero VAD model** (auto-downloaded on first run)

```bash
python agent.py download-files
```

**4. Run the agent**

```bash
python agent.py dev
```

## Docker Install for Company Handoff

## Latest GitHub Source Build / รันเวอร์ชันล่าสุดจาก GitHub

If the supervisor pulls the `Max` branch and wants the newest UI/avatar, use the root Docker Compose file. This builds the web and agent images from the current source code instead of reusing an older exported image package.

ถ้า supervisor pull branch `Max` แล้วต้องการ UI/avatar ล่าสุด ให้ใช้ไฟล์ Docker Compose ที่ root ของ repo วิธีนี้จะ build web และ agent image จาก source code ปัจจุบัน ไม่ใช้ image เก่าที่ export ไว้ก่อนหน้า

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

This path includes the static Aree picture avatar from `public/avatar/aree_cutout.png`.

วิธีนี้จะใช้รูป avatar อารีล่าสุดจาก `public/avatar/aree_cutout.png`

Docker handoff files are in `docker container/`.

For the company-facing install guide, use:

- English: `docker container/README.md`
- Thai: `docker container/README_TH.md`
- Short root handoff guide: `COMPANY_DOCKER_HANDOFF.md`
- Short root handoff guide in Thai: `COMPANY_DOCKER_HANDOFF_TH.md`

The company should download the ready GitHub Release package, not build the source code from this repository.

Release page:

```text
https://github.com/TheerapatGunthog/nongaree-voicebot/releases/tag/nongaree-voicebot-image-deploy-20260629-132329
```

The Docker package runs two services:

- `web`: Next.js frontend on `http://localhost:3000`
- `agent`: Python LiveKit voice agent worker
- `qdrant`: local Qdrant vector database with the bundled `thai_tax_kb` RAG snapshot
- `qdrant-restore`: one-shot restore job that imports the bundled `thai_tax_kb` snapshot on first run

Requirements on the target machine:

- Docker Engine or Docker Desktop with Docker Compose
- Reachable LiveKit server
- Reachable OpenAI-compatible LLM, STT, and TTS services
- Reachable embedding API for query embeddings

Company install flow:

```bash
tar -xzf nongaree-voicebot-image-deploy-20260629-132329.tar.gz
cd nongaree-voicebot-image-deploy-20260629-132329
cp .env.example .env
```

Edit `.env` and fill in the LiveKit, LLM, STT, TTS, and embedding values. The Qdrant service and `thai_tax_kb` collection are bundled in the release package. Do not commit or send real secrets in `.env`.

Load the prebuilt images and run:

```bash
./load-images.sh
docker compose up -d
```

Open:

```text
http://localhost:3000
```

View logs:

```bash
docker compose logs -f web
docker compose logs -f agent
docker compose logs -f qdrant-restore
```

Stop:

```bash
docker compose down
```

If the LLM/STT/TTS/Qdrant services run on the Docker host machine, use `host.docker.internal` in `docker container/.env` as shown in `docker container/.env.example`. The compose file maps that hostname on Linux with `host-gateway`.

To force a clean RAG restore, stop and remove the Qdrant volume before starting again:

```bash
docker compose down -v
docker compose up -d
```

## Services

| Service | Default URL          | Env prefix |
|---------|----------------------|------------|
| STT     | http://localhost:6001/v1 | `STT_`  |
| LLM     | http://localhost:8001/v1 | `LLM_`  |
| TTS     | http://localhost:8003/v1 | `TTS_`  |

All three services must expose an OpenAI-compatible API.

## Project Docs

Additional project notes live in `docs/`:

- `docs/PROJECT_STRUCTURE.md` — repository layout and runtime flows
- `docs/DETAILED_PREVIEW_HANDOFF.md` — detailed preview implementation handoff
- `docs/QA_QUERY_EXPECTATIONS.md` — supervisor QA queries and expected outputs

## Emotion Detection

After each LLM response, the agent sends an emotion tag over the LiveKit data channel:

```
[EMOTION:happy]   # happy / ยินดี / สำเร็จ
[EMOTION:sad]     # sorry / ขอโทษ / ผิดพลาด
[EMOTION:wow]     # wow / amazing / ไม่น่าเชื่อ
[EMOTION:angry]   # error / ล้มเหลว
[EMOTION:idle]    # default
```

The frontend `VoiceRoom` component listens for these events and updates the LumoFace avatar accordingly.
