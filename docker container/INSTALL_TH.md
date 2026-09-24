# คู่มือติดตั้ง Nongaree Voicebot แบบ Docker

เอกสารนี้อธิบายวิธีติดตั้งและรัน Nongaree Voicebot จากไฟล์แพ็กเกจใน GitHub Release แบบละเอียดทีละขั้นตอน

แพ็กเกจนี้ทำไว้สำหรับส่งมอบให้บริษัทใช้งาน โดยเครื่องปลายทางไม่ต้อง build source code เอง ต้องมีเพียง Docker, ไฟล์แพ็กเกจจาก Release, และค่า runtime จริงในไฟล์ `.env`

## 1. ต้องดาวน์โหลดไฟล์อะไร

เปิดหน้า GitHub Release:

```text
https://github.com/TheerapatGunthog/nongaree-voicebot/releases/tag/nongaree-voicebot-image-deploy-20260629-132329
```

ดาวน์โหลดไฟล์นี้:

```text
nongaree-voicebot-image-deploy-20260629-132329.tar.gz
```

ห้ามใช้ไฟล์ `Source code (zip)` หรือ `Source code (tar.gz)` ที่ GitHub สร้างให้อัตโนมัติสำหรับการ deploy เพราะไฟล์นั้นไม่มี Docker images ที่ export ไว้

ไฟล์เสริมที่แนะนำให้ดาวน์โหลด:

```text
SHA256SUMS.txt
```

ไฟล์ checksum ใช้ตรวจว่าไฟล์ที่ดาวน์โหลดมาไม่เสียและไม่ถูกแก้ไขระหว่างทาง

## 2. ในแพ็กเกจมีอะไรบ้าง

เมื่อแตกไฟล์แล้ว จะได้โฟลเดอร์:

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

ไฟล์ใน `images/` คือ Docker image ที่ build ไว้แล้ว:

- `nongaree-voicebot-web.tar`: หน้าเว็บ Next.js
- `nongaree-voicebot-agent.tar`: Python LiveKit voice agent

ไฟล์ Qdrant snapshot คือฐานข้อมูล RAG:

- Qdrant collection: `thai_tax_kb`
- จำนวน indexed points ที่คาดหวัง: `1,311`

แพ็กเกจนี้ไม่มี API key จริงหรือ production secret อยู่ข้างใน

## 3. เครื่องปลายทางต้องมีอะไรบ้าง

เครื่องที่จะรันต้องมี:

- Docker ติดตั้งแล้ว
- ใช้คำสั่ง `docker compose` ได้
- network เข้าถึง LiveKit server ของบริษัทได้
- network เข้าถึง LLM endpoint ของบริษัทได้
- network เข้าถึง STT endpoint ของบริษัทได้
- network เข้าถึง TTS endpoint ของบริษัทได้
- network เข้าถึง embedding endpoint ของบริษัทได้
- port `3000` ว่าง สำหรับหน้าเว็บ
- port `6333` ว่าง สำหรับ Qdrant

ถ้า port `3000` หรือ `6333` ถูกใช้งานอยู่แล้ว ให้แก้ port mapping ใน `docker-compose.yml` ก่อนเริ่มระบบ

## 4. ขั้นตอนติดตั้ง

เปิด terminal ในโฟลเดอร์ที่ดาวน์โหลดไฟล์ release package ไว้

แตกไฟล์:

```bash
tar -xzf nongaree-voicebot-image-deploy-20260629-132329.tar.gz
cd nongaree-voicebot-image-deploy-20260629-132329
```

สร้างไฟล์ `.env` สำหรับ runtime:

```bash
cp .env.example .env
```

เปิดไฟล์ `.env` แล้วแทนค่า placeholder ทุกตัวด้วยค่าจริงของบริษัท

ค่าที่ต้องใส่ให้ครบ:

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

ในไฟล์ `.env.example` จะมีค่า legacy compatibility บางตัว เช่น `OPENAI_API_KEY`, `OPENAI_MODEL`, และ `BASE_URL` อยู่ด้วย สำหรับแพ็กเกจ Docker bot นี้ ค่าที่สำคัญจริงคือ LiveKit, LLM, STT, TTS, embedding, และ Qdrant ตามรายการด้านบน

ค่าต่อไปนี้ให้คงไว้ตามนี้ได้ ถ้า environment ของบริษัทไม่ได้ต้องการเปลี่ยน:

```text
QDRANT_URL=http://qdrant:6333
QDRANT_COLLECTION=thai_tax_kb
RAG_ENABLED=true
RAG_SCORE_THRESHOLD=0.75
RAG_TOP_K=8
NEXT_PUBLIC_SHOW_SESSION_HISTORY=true
```

โหลด Docker images ที่อยู่ในแพ็กเกจ:

```bash
./load-images.sh
```

เริ่ม service ทั้งหมด:

```bash
docker compose up -d
```

เปิดหน้า bot:

```text
http://localhost:3000
```

## 5. วิธีตรวจว่าระบบขึ้นถูกต้อง

เช็กว่า container ทำงานอยู่:

```bash
docker compose ps
```

ควรเห็น service ประมาณนี้:

```text
qdrant
qdrant-restore
web
agent
```

เช็กว่า Qdrant restore สำเร็จ:

```bash
docker compose logs qdrant-restore
```

ผลลัพธ์ที่คาดหวังคือ restore container ทำงานจบสำเร็จ

เช็ก RAG collection:

```bash
curl http://localhost:6333/collections/thai_tax_kb
```

ผลลัพธ์ควรมีค่าประมาณนี้:

```text
points_count: 1311
```

เช็ก log ของ web:

```bash
docker compose logs -f web
```

เช็ก log ของ agent:

```bash
docker compose logs -f agent
```

พฤติกรรมที่ควรได้:

- เปิด `http://localhost:3000`
- bot เชื่อมต่อเข้า LiveKit room ได้
- bot กล่าวทักทายผู้ใช้
- ผู้ใช้พิมพ์คำถามได้
- ผู้ใช้กดค้างปุ่มไมค์แล้วพูดได้
- กล่องรายละเอียดคำตอบด้านขวาอัปเดต
- กล่องประวัติใน session เก็บคำถามและคำตอบของ session ปัจจุบัน

## 6. ปัญหาที่พบบ่อยและวิธีตรวจ

### หน้าเว็บเปิดได้ แต่ bot ไม่ทักทาย

ตรวจ log:

```bash
docker compose logs -f agent
docker compose logs -f web
```

สาเหตุที่เป็นไปได้:

- `LIVEKIT_URL` ไม่ถูกต้อง
- `LIVEKIT_API_KEY` หรือ `LIVEKIT_API_SECRET` ไม่ถูกต้อง
- LiveKit server dispatch agent ไม่ได้
- เครื่องปลายทางเข้าถึง LiveKit server ไม่ได้

### bot เชื่อมต่อได้ แต่ตอบคำถามไม่ได้

ตรวจ log:

```bash
docker compose logs -f agent
```

สาเหตุที่เป็นไปได้:

- LLM endpoint เข้าถึงไม่ได้
- `LLM_API_KEY` ไม่ถูกต้อง
- `LLM_MODEL` ไม่มีอยู่บน server ที่ตั้งไว้
- embedding endpoint เข้าถึงไม่ได้
- Qdrant restore ไม่สำเร็จ

### ไมค์ใช้งานไม่ได้

ตรวจสิ่งต่อไปนี้:

- browser อนุญาต microphone permission แล้ว
- เปิดหน้าเว็บจาก origin ที่ browser อนุญาต สำหรับ local test ใช้ `http://localhost:3000` ได้
- ถ้าใช้ server-side STT ให้ตรวจ `STT_BASE_URL`, `STT_API_KEY`, และ `STT_MODEL`

### bot ไม่มีเสียงพูด

ตรวจสิ่งต่อไปนี้:

- `TTS_BASE_URL`
- `TTS_API_KEY`
- `TTS_MODEL`
- `TTS_VOICE`
- output audio ของ browser หรือเครื่องไม่ได้ mute

### Qdrant ไม่มี collection

รัน:

```bash
docker compose logs qdrant-restore
```

ถ้าต้องการ restore ใหม่แบบสะอาด:

```bash
docker compose down -v
docker compose up -d
```

คำสั่งนี้จะลบ Docker volume ของ Qdrant แล้ว restore ใหม่จาก snapshot ที่มากับแพ็กเกจ

## 7. วิธีหยุดและเริ่มใหม่

หยุด service:

```bash
docker compose down
```

เริ่ม service ใหม่:

```bash
docker compose up -d
```

ดู log รวม:

```bash
docker compose logs -f
```

## 8. หมายเหตุด้านความปลอดภัย

- ห้าม commit ไฟล์ `.env` ที่มี key จริงขึ้น GitHub
- Release package มีเฉพาะค่า placeholder ใน `.env`
- บริษัทต้องใส่ key จริงใน `.env` บนเครื่อง deploy เอง
- ถ้าต้องส่งไฟล์ `.env` ที่กรอกค่าแล้ว ต้องส่งผ่านช่องทางภายในที่ปลอดภัยเท่านั้น
- Docker images มี runtime ของระบบ แต่ไม่มี production API keys

## 9. สรุปคำสั่งแบบสั้นที่สุด

```bash
tar -xzf nongaree-voicebot-image-deploy-20260629-132329.tar.gz
cd nongaree-voicebot-image-deploy-20260629-132329
cp .env.example .env
# แก้ .env แล้วใส่ค่าจริงของบริษัทก่อน
./load-images.sh
docker compose up -d
docker compose ps
```

เปิดหน้าเว็บ:

```text
http://localhost:3000
```
