# คู่มือส่งมอบ Docker สำหรับ Nong Aree Voicebot

ใช้เอกสารนี้สำหรับส่งแพ็กเกจ deploy ให้ supervisor หรือบริษัท

วิธีใช้งานโดยรวมคือ บริษัทดาวน์โหลดไฟล์จาก GitHub Release, สร้างไฟล์ `.env`, ใส่ค่า endpoint/key จริง, โหลด Docker images, แล้วรัน `docker compose`

แพ็กเกจนี้ไม่ต้อง build จาก source code

## วิธีรันเวอร์ชันล่าสุดจาก GitHub

ถ้า supervisor pull branch `Max` จาก GitHub แล้วต้องการ UI/avatar ล่าสุด ให้ใช้วิธีนี้แทน release package เก่า:

```bash
git checkout Max
git pull
cp "docker container/.env.example" "docker container/.env"
# เปิด docker container/.env แล้วใส่ค่าจริงของบริษัท
docker compose up --build -d
```

เปิดหน้า bot:

```text
http://localhost:3000
```

วิธีนี้จะ rebuild `nongaree-voicebot-web:latest` จาก source code ปัจจุบัน และจะใช้รูป avatar อารีล่าสุดที่ `public/avatar/aree_cutout.png`

ถ้าเครื่องเก่ายังเห็น avatar ตา robot แปลว่ายังใช้ Docker image เก่า ให้ rebuild ใหม่:

```bash
docker compose down
docker compose up --build -d
```

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

ไฟล์นี้คือแพ็กเกจสำหรับ deploy จริง ภายในมี:

- Docker image ที่ build ไว้แล้วสำหรับ web UI และ agent
- ไฟล์ `docker-compose.yml`
- Qdrant/RAG snapshot
- ไฟล์ตัวอย่าง `.env.example`
- script สำหรับโหลด image
- README วิธีรัน

แพ็กเกจนี้ไม่มี API key จริงหรือ secret จริงอยู่ข้างใน

## 3. หลังดาวน์โหลดแล้วต้องรันอะไร

ให้เปิด terminal ใน folder ที่ดาวน์โหลดไฟล์ `.tar.gz` ไว้ แล้วรัน:

```bash
tar -xzf nongaree-voicebot-image-deploy-20260629-132329.tar.gz
cd nongaree-voicebot-image-deploy-20260629-132329
cp .env.example .env
```

จากนั้นเปิดไฟล์ `.env` แล้วแทนค่า placeholder ทั้งหมดด้วยค่าจริงของบริษัท

ค่าที่ต้องใส่ใน `.env` คือ:

```text
LiveKit URL, API key, และ API secret
LLM endpoint, model, และ key
STT endpoint, model, และ key
TTS endpoint, model, และ key
Embedding endpoint, model, และ key
```

หลังจากใส่ค่า `.env` ครบแล้ว ให้โหลด Docker images และเริ่มระบบ:

```bash
./load-images.sh
docker compose up -d
```

เปิดหน้า bot ได้ที่:

```text
http://localhost:3000
```

## 4. เครื่องที่จะรันต้องเตรียมอะไรบ้าง

เครื่องปลายทางต้องมี:

- Docker ติดตั้งแล้วและกำลังทำงาน
- network ที่เข้าถึง LiveKit server ของบริษัทได้
- network ที่เข้าถึง LLM, STT, TTS, และ embedding endpoint ที่ตั้งไว้ใน `.env` ได้
- port `3000` ว่าง สำหรับ web UI
- port `6333` ว่าง สำหรับ Qdrant

ถ้า `.env` ยังเป็นค่า placeholder อยู่ container อาจ start ได้ แต่ bot จะยังเชื่อมต่อ LiveKit หรือ AI services ไม่ถูกต้อง

## 5. วิธีเช็กว่าระบบขึ้นถูกต้องไหม

หลัง start แล้ว ให้เช็กสถานะ container:

```bash
docker compose ps
docker compose logs -f qdrant-restore
docker compose logs -f agent
docker compose logs -f web
```

เช็กว่า Qdrant/RAG ถูก restore แล้ว:

```bash
curl http://localhost:6333/collections/thai_tax_kb
```

ผลลัพธ์ควรมี:

```text
points_count: 1311
```

## 6. ถ้าต้องการ reset RAG/Qdrant ใหม่

ใช้คำสั่งนี้เพื่อล้าง volume แล้ว restore จาก snapshot ใหม่:

```bash
docker compose down -v
docker compose up -d
```

## หมายเหตุสำคัญ

- Release package ไม่มี real secrets
- บริษัทต้องสร้างและแก้ `.env` เองก่อนรันจริง
- แพ็กเกจนี้มี RAG/Qdrant snapshot รวมอยู่แล้ว
- แพ็กเกจนี้มี prebuilt Docker images ของ `web` และ `agent` รวมอยู่แล้ว
- GitHub repository ไม่มีไฟล์ image tar ขนาดใหญ่โดยตรง ไฟล์ใหญ่ถูกเก็บเป็น GitHub Release asset
- ถ้า LLM/STT/TTS/embedding services อยู่บนเครื่องเดียวกับ Docker ให้ใช้ URL แบบ `host.docker.internal` ใน `.env`

## สรุปขั้นตอนสั้นที่สุด

```bash
tar -xzf nongaree-voicebot-image-deploy-20260629-132329.tar.gz
cd nongaree-voicebot-image-deploy-20260629-132329
cp .env.example .env
# แก้ .env ให้เป็นค่าจริงของบริษัทก่อน
./load-images.sh
docker compose up -d
```

จากนั้นเปิด:

```text
http://localhost:3000
```
