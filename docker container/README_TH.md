# คู่มือส่งมอบและติดตั้ง Docker สำหรับ Nong Aree Voicebot

ใช้เอกสารนี้สำหรับส่งแพ็กเกจ deploy ให้ supervisor หรือบริษัท เอกสารนี้รวมทั้งภาพรวมการส่งมอบและขั้นตอนติดตั้งแบบละเอียดไว้ในไฟล์เดียว

## หมายเหตุสำหรับการรันเวอร์ชันล่าสุดจาก GitHub

ถ้า supervisor pull branch `Max` จาก GitHub แล้วต้องการเวอร์ชันล่าสุด ให้รันจาก root ของ repository:

```bash
cp "docker container/.env.example" "docker container/.env"
# เปิด docker container/.env แล้วใส่ค่าจริงของบริษัท
docker compose up --build -d
```

วิธีนี้จะ rebuild web image จาก source ปัจจุบัน และใช้รูป avatar อารีที่ `public/avatar/aree_cutout.png`

วิธีใช้งานโดยรวมคือ บริษัทดาวน์โหลดไฟล์จาก GitHub Release, แตกไฟล์แพ็กเกจ, สร้างไฟล์ `.env`, ใส่ค่า endpoint/key จริง, โหลด Docker images, แล้วรัน `docker compose`

แพ็กเกจนี้ไม่ต้อง build จาก source code บนเครื่องปลายทาง

## 1. ควรส่งลิงก์ไหนให้บริษัท

แนะนำให้ส่งลิงก์ GitHub Release นี้ก่อน เพราะในหน้านี้มีทั้งไฟล์แพ็กเกจ, checksum, และรายละเอียด release อยู่รวมกัน:

```text
https://github.com/TheerapatGunthog/nongaree-voicebot/releases/tag/nongaree-voicebot-image-deploy-20260629-132329
```

ถ้าต้องการลิงก์ดาวน์โหลดไฟล์แพ็กเกจโดยตรง ให้ใช้ลิงก์นี้:

```text
https://github.com/TheerapatGunthog/nongaree-voicebot/releases/download/nongaree-voicebot-image-deploy-20260629-132329/nongaree-voicebot-image-deploy-20260629-132329.tar.gz
```

ไฟล์ checksum เป็นไฟล์เสริม ใช้สำหรับตรวจว่าไฟล์ที่ดาวน์โหลดมาไม่เสียหรือไม่ถูกเปลี่ยน:

```text
https://github.com/TheerapatGunthog/nongaree-voicebot/releases/download/nongaree-voicebot-image-deploy-20260629-132329/SHA256SUMS.txt
```

repository นี้เป็น private repository ดังนั้นคนที่จะดาวน์โหลดต้องมีสิทธิ์เข้าถึง GitHub repository หรือ GitHub Release asset นี้ก่อน

## 2. บริษัทต้องดาวน์โหลดไฟล์อะไร

ให้ดาวน์โหลดไฟล์นี้จากหน้า Release:

```text
nongaree-voicebot-image-deploy-20260629-132329.tar.gz
```

ห้ามใช้ไฟล์ `Source code (zip)` หรือ `Source code (tar.gz)` ที่ GitHub สร้างให้อัตโนมัติสำหรับการ deploy เพราะไฟล์นั้นเป็น source snapshot และไม่มี Docker images ที่ export ไว้

ไฟล์เสริมที่แนะนำให้ดาวน์โหลด:

```text
SHA256SUMS.txt
```

ไฟล์ checksum ใช้ตรวจว่าไฟล์ที่ดาวน์โหลดมาไม่เสียและไม่ถูกแก้ไขระหว่างทาง

## 3. ในแพ็กเกจมีอะไรบ้าง

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

แพ็กเกจนี้ไม่มี API key จริงหรือ production secret อยู่ข้างใน มีเพียงค่า placeholder ใน `.env.example` และ `.env`

## 4. เครื่องปลายทางต้องมีอะไรบ้าง

เครื่องที่จะรันต้องมี:

- Docker ติดตั้งแล้วและกำลังทำงาน
- ใช้คำสั่ง `docker compose` ได้
- network เข้าถึง LiveKit server ของบริษัทได้
- network เข้าถึง LLM endpoint ของบริษัทได้
- network เข้าถึง STT endpoint ของบริษัทได้
- network เข้าถึง TTS endpoint ของบริษัทได้
- network เข้าถึง embedding endpoint ของบริษัทได้
- port `3000` ว่าง สำหรับหน้าเว็บ
- port `6333` ว่าง สำหรับ Qdrant

ถ้า port `3000` หรือ `6333` ถูกใช้งานอยู่แล้ว ให้แก้ port mapping ใน `docker-compose.yml` ก่อนเริ่มระบบ

ถ้า LLM/STT/TTS/embedding services อยู่บนเครื่องเดียวกับ Docker ให้ใช้ URL แบบ `host.docker.internal` ใน `.env` ตามตัวอย่างใน `.env.example`

## 5. ขั้นตอนติดตั้ง

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

## 6. วิธีตรวจว่าระบบขึ้นถูกต้อง

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

## 7. ปัญหาที่พบบ่อยและวิธีตรวจ

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

## 8. วิธีหยุดและเริ่มใหม่

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

## 9. วิธี reset RAG/Qdrant ใหม่

ใช้คำสั่งนี้เมื่อต้องการล้าง volume แล้ว restore จาก snapshot ใหม่:

```bash
docker compose down -v
docker compose up -d
```

หลังจากนั้นตรวจ collection อีกครั้ง:

```bash
curl http://localhost:6333/collections/thai_tax_kb
```

## 10. หมายเหตุด้านความปลอดภัย

- ห้าม commit ไฟล์ `.env` ที่มี key จริงขึ้น GitHub
- Release package มีเฉพาะค่า placeholder ใน `.env`
- บริษัทต้องใส่ key จริงใน `.env` บนเครื่อง deploy เอง
- ถ้าต้องส่งไฟล์ `.env` ที่กรอกค่าแล้ว ต้องส่งผ่านช่องทางภายในที่ปลอดภัยเท่านั้น
- Docker images มี runtime ของระบบ แต่ไม่มี production API keys
- GitHub repository ไม่มีไฟล์ image tar ขนาดใหญ่โดยตรง ไฟล์ใหญ่ถูกเก็บเป็น GitHub Release asset

## 11. สรุปคำสั่งแบบสั้นที่สุด

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
