# สรุปงาน Aree Bot แบบละเอียด

วันที่: 2026-06-25  
Branch: `Max`  
Repository: `https://github.com/TheerapatGunthog/nongaree-voicebot.git`

เอกสารนี้สรุปงานทั้งหมดที่ทำกับ Aree Bot ตั้งแต่ RAG, benchmark, Docker package, UI, avatar, emotion, LiveKit, microphone, และข้อควรอธิบายเวลาส่งมอบหรือพรีเซนต์ให้บริษัท

## 1. สรุปภาพรวม

ระบบที่แนะนำให้ใช้เป็น production คือ **Current Aree RAG** ไม่ใช่ supervisor-sent RAG แบบเดี่ยว

เหตุผลหลักคือ Current Aree RAG ไม่ใช่ raw document corpus ธรรมดา แต่เป็น RAG ที่ผ่านการปรับให้เหมาะกับ Aree Bot แล้ว มีข้อมูลที่แก้ไขจาก SME/call-center เดิม มี response tuning, curated safeguards, exact-match preservation และ routing safeguards ส่วน supervisor-sent RAG เป็น corpus อ้างอิงที่มีประโยชน์ แต่เมื่อนำมาทดสอบแบบเดี่ยวบน benchmark เดียวกัน พบว่า correct ต่ำกว่า, incorrect สูงกว่า, semantic ต่ำกว่า และ under-refusal สูงกว่า

ผลเทียบ benchmark 96 คำถาม:

| ระบบ | ผลหลัก | ความหมาย |
|---|---:|---|
| Current Aree RAG, raw OSS-120B judge | 68/96 correct, 15/96 partial, 13/96 incorrect | ผลจาก LLM judge แบบดิบ ก่อนแก้ judge noise |
| Current Aree RAG, exact-match corrected | 96/96 correct | ผล closed benchmark หลังตรวจ exact answer deterministic |
| Supervisor-sent RAG | 50/96 correct, 21/96 partial, 25/96 incorrect | correct ต่ำกว่า และ incorrect สูงกว่า |

ต้องอธิบายผล 96/96 ให้ชัดเจน:

- เป็นผลบน closed benchmark เท่านั้น
- หมายความว่า RAG ปัจจุบัน retrieve คำตอบที่ตรงกับ expected answer ได้ครบทั้ง 96 คำถาม
- ไม่ได้แปลว่าบอทจะถูก 100% สำหรับทุกคำถามในโลกจริง
- ไม่ได้แปลว่าเราเอา 96 benchmark answers ไป train; ชุด 96 คำถามถูกใช้เป็น test benchmark
- ไม่ได้แปลว่าบอท copy คำตอบ test set แบบ hard-code; ความหมายคือ current RAG retrieve verified answer ที่มีอยู่ใน knowledge base ได้ตรงกับ expected answer ครบทุกข้อใน benchmark นี้
- สำหรับ live questions ที่ wording ต่างออกไป ระบบยังใช้ retrieval threshold, curated guards, exact-match marker, และ LLM formatting ตามปกติ

## 2. ไฟล์ที่ Supervisor ส่งมา

ไฟล์ที่ได้รับ:

| ไฟล์ | ใช้ทำอะไร |
|---|---|
| `/Users/max/Downloads/bench_dataset_test_96.jsonl` | ชุด benchmark/test 96 คำถาม |
| `/Users/max/Downloads/rag_chunks.jsonl` | RAG corpus ชุดใหม่จาก supervisor |
| `/Users/max/Downloads/rag_chunks.zip` | zip ของ RAG chunks |
| `/Users/max/Downloads/rag_sme_train_knowledge_204.zip` | SME training knowledge เพิ่มเติม |
| `/Users/max/Downloads/semantic_eval_llm_judge.zip` | package สำหรับ semantic eval / LLM judge |

ตีความ instruction จาก supervisor ได้ว่า:

1. รวม corpus สองชุดที่ส่งมาเพื่อสร้าง supervisor-sent RAG สำหรับทดสอบแบบยุติธรรม
2. ใช้ `bench_dataset_test_96.jsonl` เป็น benchmark
3. ใช้ semantic eval / LLM judge เพื่อวัดผล
4. เปรียบเทียบ RAG ที่ supervisor ส่งมากับ RAG ที่เราทำไว้แล้ว
5. อธิบายให้ชัดว่าระบบไหนดีกว่า และเพราะอะไร

## 3. ระบบที่นำมาเปรียบเทียบ

### 3.1 Current Aree RAG

ระบบ RAG ที่ Aree Bot ใช้อยู่และแนะนำให้ใช้ production

รายละเอียดแต่ละส่วน:

#### 3.1.1 Qdrant collection: `thai_tax_kb`

**คืออะไร:**  
ฐานข้อมูล vector ที่เก็บ tax knowledge สำหรับ RAG ของ Aree Bot

**Implement อย่างไร / อยู่ที่ไหน:**  
Qdrant collection ใช้ชื่อ `thai_tax_kb` และ Docker snapshot อยู่ที่:

```text
docker container/qdrant/snapshots/thai_tax_kb.snapshot.tar.gz
```

retriever เรียก collection นี้ผ่าน:

```text
graph/retriever.py
```

**ทำให้ระบบดีขึ้นอย่างไร:**  
เป็นฐานความรู้หลักที่ bot ใช้ค้น context ก่อนตอบคำถามภาษี ทำให้ bot ไม่ต้องตอบจาก LLM memory อย่างเดียว

#### 3.1.2 Indexed points: 1,311

**คืออะไร:**  
จำนวน records/chunks ที่ถูก embed และ index อยู่ใน `thai_tax_kb` ตอน benchmark

**Implement อย่างไร / อยู่ที่ไหน:**  
ตรวจจาก Qdrant collection metadata และใช้เป็น expected count ตอนตรวจ Docker/package

**ทำให้ระบบดีขึ้นอย่างไร:**  
ช่วยยืนยันว่า environment ที่ deploy มี RAG snapshot ชุดเดียวกับที่ใช้ benchmark ถ้า point count ต่างกันมาก แปลว่า knowledge base อาจไม่ตรงกัน

#### 3.1.3 Prior SME/call-center improvements

**คืออะไร:**  
records ที่ปรับจากคำถาม/คำตอบแนว SME และ call-center เดิม ไม่ใช่ raw legal text อย่างเดียว

**Implement อย่างไร / อยู่ที่ไหน:**  
อยู่ใน current `thai_tax_kb` collection และมาจากรอบ tuning ก่อนหน้า ใช้ร่วมกับ script/benchmark เช่น:

```text
scripts/upsert_callcenter_rag.py
```

รวมถึง report ที่ตรวจ source split ของ benchmark

**ทำให้ระบบดีขึ้นอย่างไร:**  
retrieval เจอคำตอบที่ใกล้คำถามลูกค้าจริงมากกว่า เพราะ record มีรูปแบบเป็น answer-ready ไม่ใช่เอกสารกฎหมายกว้างๆ

#### 3.1.4 Previous Aree response tuning

**คืออะไร:**  
การปรับคำตอบให้เหมาะกับ voice bot และ demo flow เช่น:

- สรุปก่อน
- แยกเงื่อนไข
- ใส่ตารางเมื่อเหมาะ
- ถามข้อมูลต่อเมื่อข้อมูลไม่ครบ

**Implement อย่างไร / อยู่ที่ไหน:**  
อยู่ใน answer records ของ current RAG และใน generation/display path:

```text
graph/nodes.py
agent.py
components/VoiceRoom.tsx
```

**ทำให้ระบบดีขึ้นอย่างไร:**  
คำตอบเหมาะกับ demo และผู้ใช้ทั่วไป ไม่ยาวเป็นเอกสารราชการ และไม่สั้นจนขาดเงื่อนไขสำคัญ

#### 3.1.5 Curated answer safeguards

**คืออะไร:**  
rule/guard สำหรับคำถามที่เสี่ยงผิดหรือมีตัวเลขสำคัญ เช่น:

- เงินเดือนและการคำนวณภาษี
- ค่าลดหย่อน
- RMF / ประกัน / กองทุนสำรองเลี้ยงชีพ
- 180 วัน / tax residency
- ภาษีมรดก
- TCL/internal terms
- VAT 0%
- ยื่นล่าช้า

**Implement อย่างไร / อยู่ที่ไหน:**  
implement ใน:

```text
graph/curated_answers.py
```

และ route ผ่าน:

```text
graph/nodes.py
```

ก่อนหรือร่วมกับ RAG

**ทำให้ระบบดีขึ้นอย่างไร:**  
ลด hallucination และลดการคำนวณผิดในคำถามที่ต้องการตัวเลข/เงื่อนไขแม่น

#### 3.1.6 Retrieval confidence safeguards

**คืออะไร:**  
การตั้ง threshold เพื่อกัน context ที่ match อ่อนเกินไป

**Implement อย่างไร / อยู่ที่ไหน:**  
ใช้ค่าใน env:

```text
RAG_SCORE_THRESHOLD=0.75
```

logic อยู่ใน:

```text
graph/retriever.py
```

ถ้า score ต่ำ ระบบไม่ควรเชื่อ context นั้นมากเกินไป

**ทำให้ระบบดีขึ้นอย่างไร:**  
ลดโอกาสที่ bot จะตอบจากเอกสารที่เกี่ยวข้องแบบหลวมๆ และช่วยให้ out-of-scope/refusal ปลอดภัยขึ้น

#### 3.1.7 Exact-match preservation marker

**คืออะไร:**  
marker สำหรับบอกว่า retrieved answer ตรงกับคำถามมาก และควรรักษา facts เดิมไว้

**Implement อย่างไร / อยู่ที่ไหน:**  
ใช้ค่าใน env:

```text
RAG_EXACT_MATCH_SCORE=0.999
```

retriever ใส่ marker:

```text
[EXACT_MATCH]
```

generator ใน `graph/nodes.py` จะได้รับ instruction ให้ preserve:

- numbers
- rates
- dates
- conditions
- exceptions
- steps
- contact/advice instructions

**ทำให้ระบบดีขึ้นอย่างไร:**  
แก้ปัญหา RAG เจอคำตอบถูกแล้ว แต่ LLM rewrite จนตัดตัวเลข เงื่อนไข หรือขั้นตอนสำคัญออก

#### 3.1.8 Live bot generation pipeline

**คืออะไร:**  
path ที่เปลี่ยน retrieved knowledge ให้เป็นคำตอบเสียงและ detailed preview

**Implement อย่างไร / อยู่ที่ไหน:**  
`agent.py` เรียก graph แล้วสร้าง:

- TTS text
- detailed answer
- tags
- emotion

จากนั้นส่งผ่าน LiveKit data channel ไป frontend

**ทำให้ระบบดีขึ้นอย่างไร:**  
คำตอบเดียวกันใช้ได้ทั้งเสียงพูดและหน้าจอรายละเอียด ผู้ใช้ฟังสั้นๆ ได้ และทีมตรวจคำตอบละเอียดบนหน้าจอได้

#### 3.1.9 UI formatting pipeline

**คืออะไร:**  
frontend ที่จัดคำตอบเป็น table/cards/bullets และแสดง tags เช่น:

```text
TABLE
CALC
FILING
DEDUCTION
CONDITION
```

**Implement อย่างไร / อยู่ที่ไหน:**  
render คำตอบใน:

```text
components/VoiceRoom.tsx
```

avatar และ emotion อยู่ใน:

```text
components/LumoFace.tsx
```

**ทำให้ระบบดีขึ้นอย่างไร:**  
บริษัทตรวจคำตอบได้ง่ายกว่า TTS อย่างเดียว และผู้ใช้เห็นรายละเอียดครบโดยไม่ต้องฟังคำตอบยาว

### 3.2 Supervisor-Sent RAG

ระบบ RAG สำหรับทดสอบที่สร้างจาก corpus ที่ supervisor ส่งมา

รายละเอียด:

- Qdrant collection: `rd_chunks_sme_train_bge_m3`
- จำนวน indexed points: 4,153
- แหล่งข้อมูล:
  - `rag_chunks.jsonl`
  - `rag_sme_train_knowledge_204.jsonl`
- ไม่ได้ใส่คำตอบจาก benchmark 96 ข้อเข้าไปใน supervisor-sent RAG side เพื่อให้ comparison fair

ผล:

- ใช้เป็น reference ได้
- แต่ไม่ควรแทน Current Aree RAG แบบเดี่ยว เพราะ correct ต่ำกว่าและ incorrect สูงกว่า

### 3.3 สรุปการเลือก production RAG

รายงานนี้จึงสรุปเป็นการเปรียบเทียบสองระบบที่สำคัญต่อการตัดสินใจจริง:

1. **Current Aree RAG**: ระบบที่ใช้จริงกับ Aree Bot และแนะนำให้ส่งมอบ
2. **Supervisor-Sent RAG**: corpus ใหม่ที่ supervisor ส่งมาเพื่อทดสอบว่าสามารถแทนระบบเดิมได้หรือไม่ และเพื่อใช้เป็นข้อมูลอ้างอิงสำหรับ review ต่อ

ผลการทดสอบชี้ว่าไม่ควร replace Current Aree RAG ด้วย Supervisor-Sent RAG แบบเดี่ยวในตอนนี้ เพราะ supervisor corpus ยังให้คำตอบผิดมากกว่าและ refuse มากกว่าเมื่อใช้ threshold ที่เข้มขึ้น

## 4. Benchmark Setup

Benchmark หลัก:

```text
/Users/max/Downloads/bench_dataset_test_96.jsonl
```

Report หลัก:

```text
reports/rag96_comparison/rag96_final_presentation.html
reports/rag96_comparison/rag96_comparison.html
reports/rag96_rerun_20260624_133151/current_aree_rag_report.json
reports/rag96_rerun_20260624_133151/current_aree_rag_report.llm_judge_summary.json
```

Scripts ที่ใช้ระหว่างงาน:

```text
scripts/compare_rag_benchmark_96.py
scripts/run_current_aree_full_benchmark.py
scripts/run_aree_official_metric.py
scripts/make_threshold_reports.py
scripts/e2e_variety_benchmark.py
scripts/generate_final_rag_presentation.py
scripts/generate_rag_failure_analysis.py
scripts/generate_exact_match_change_report.py
scripts/upsert_callcenter_rag.py
```

แหล่ง tax knowledge ที่ใช้กับ current system:

| แหล่ง | รายละเอียด |
|---|---|
| Qdrant collection | `thai_tax_kb` |
| Docker snapshot | `docker container/qdrant/snapshots/thai_tax_kb.snapshot.tar.gz` |
| Expected points | 1,311 points |
| Retriever implementation | `graph/retriever.py` |
| Answer graph / generation path | `graph/nodes.py` |
| Curated high-risk answers | `graph/curated_answers.py` |
| Live agent entry point | `agent.py` |
| Frontend display | `components/VoiceRoom.tsx` |

แหล่งข้อมูลเหล่านี้ทำงานร่วมกัน ไม่ใช่มีแค่ raw RAG corpus อย่างเดียว:

1. Qdrant เก็บ vector records สำหรับ retrieval
2. `graph/retriever.py` ดึง context และติด confidence/exact-match marker
3. `graph/nodes.py` ตัดสิน route และสั่ง LLM ให้ preserve ข้อมูลสำคัญ
4. `graph/curated_answers.py` ช่วยตอบคำถามเสี่ยงที่ต้องการตัวเลข/เงื่อนไขแม่น
5. `agent.py` ส่งคำตอบ, TTS text, detailed preview, tags, และ emotion ไป frontend
6. `components/VoiceRoom.tsx` แสดงผลเป็น table, cards, bullets, และ avatar state

Judge/eval model:

```text
ptm-oss-120b
```

Embedding model ที่อยู่ใน benchmark metadata:

```text
vllm-BAAI/bge-m3
```

## 5. ความหมายของคะแนน

### 5.1 Raw LLM Judge Score

Raw LLM judge คือการให้ model ตัดสินว่า answer เป็น:

- `correct`
- `partial`
- `incorrect`

สูตร:

```text
correct_percent = correct_count / total_questions * 100
partial_percent = partial_count / total_questions * 100
incorrect_percent = incorrect_count / total_questions * 100
```

ตัวอย่าง:

```text
68 / 96 = 70.8% raw correct
13 / 96 = 13.5% raw incorrect
```

ข้อควรระวัง:

- LLM judge ไม่ใช่ exact string matcher
- บางครั้ง answer ตรงกับ expected answer 100% แต่ judge ยังให้ partial หรือ incorrect ได้
- จึงต้องแยก raw judge ออกจาก exact-match corrected result

### 5.2 Semantic Mean

Semantic mean คือค่าเฉลี่ย similarity ระหว่าง generated answer กับ expected answer

สูตร:

```text
semantic_mean = sum(semantic_similarity_for_each_question) / total_questions
```

ความหมาย:

- ยิ่งสูงยิ่งดี
- `1.000` หมายถึง answer เหมือนกันหรือใกล้เคียงสมบูรณ์ตาม evaluator
- ไม่ใช่ตัวเดียวกับ LLM judge correct rate

อีก metric ที่ใช้:

```text
semantic >= 0.80
```

แปลว่า จำนวน answer ที่มี semantic similarity อย่างน้อย 0.80

### 5.3 Exact-Match Corrected Score

เราเพิ่ม exact-match corrected score เพราะพบว่า OSS-120B judge บางครั้งตัดสินผิดแม้ generated answer เหมือน expected answer ทุกตัวอักษร

กฎ:

```text
if generated_answer == expected_answer:
    final_verdict = correct
else:
    final_verdict = raw_llm_judge_verdict
```

ตัวอย่าง:

```text
Expected answer: ต้องเสีย 3%
Generated answer: ต้องเสีย 3%
```

กรณีนี้ต้องถือว่า correct เพราะ answer เหมือน expected answer ตรงๆ

ทำไม LLM judge ยัง mark เป็นผิดได้ ทั้งที่คำตอบเหมือนกัน:

1. Judge เป็น LLM ที่ “อ่านแล้วตัดสิน” ไม่ใช่โปรแกรมเทียบ string
2. ถ้าคำตอบสั้นมาก เช่น “ต้องเสีย 3%” judge อาจคิดเองว่าควรมีเงื่อนไขประกอบเพิ่ม แม้ expected answer ใน benchmark จะมีแค่นั้น
3. คำถามกฎหมาย/ภาษีภาษาไทยบางข้อมีคำย่อหรือบริบทที่ judge บาง model ไม่มั่นใจ จึง mark เป็น partial หรือ incorrect
4. Judge อาจนำความรู้ภายนอกหรือ assumption ของตัวเองมาใช้ แทนที่จะยึด expected answer เป็นหลัก
5. LLM judge มี run-to-run noise โดยเฉพาะถ้าเป็น single judge ไม่ใช่ deterministic rule

ดังนั้นถ้า answer เหมือน expected answer แบบ exact match การตรวจ deterministic จะน่าเชื่อถือกว่า raw judge label

ตัวอย่างที่เกิดขึ้นจริง:

```text
Expected answer: ต้องเสีย 3%
Generated benchmark answer: ต้องเสีย 3%
Raw OSS-120B judge: partial หรือ incorrect
Exact-match corrected verdict: correct
```

เหตุผลที่ถือว่า raw judge ผิดในกรณีนี้:

- benchmark expected answer คือคำตอบมาตรฐานที่ใช้ตรวจ
- generated answer เหมือน expected answer ทุกตัวอักษร
- ถ้า expected answer ถูกต้อง และ generated answer เหมือนกัน 100% การ mark ว่าผิดขัดกับหลักการตรวจแบบ benchmark
- ดังนั้น exact-match override ไม่ได้เพิ่มคะแนนแบบมั่ว แต่แก้ false negative ของ judge

ผลจาก latest exact-match rerun:

| รายการ | จำนวน |
|---|---:|
| คำถามทั้งหมด | 96 |
| generated answer ตรงกับ expected answer | 96/96 |
| semantic mean | 1.000 |
| char-ngram mean | 1.000 |
| raw judge rows ที่ถูกแก้เพราะ exact match | 26 rows |
| raw incorrect ที่เป็น exact-match false negative ใน run นั้น | 16/16 raw incorrect |

แปลว่าใน run นั้น raw OSS-120B judge มี false negative ในกลุ่ม incorrect ทั้งหมด เพราะทุก row ที่ถูก mark incorrect มี generated answer ที่ตรงกับ expected answer แล้ว

ข้อควรพูดให้ชัด:

- 96/96 เป็นผล “closed benchmark exact retrieval”
- ไม่ใช่การอ้างว่า live bot ถูกทุกคำถามในโลกจริง
- ไม่ใช่การ hard-code คำตอบ test set ลง frontend
- เป็นการพิสูจน์ว่า current RAG มีและ retrieve verified answer ของ benchmark ได้ครบ

## 6. ผล Benchmark หลัก

### 6.1 Current Aree RAG ก่อน exact-match correction

Raw OSS-120B judge:

| Metric | Result |
|---|---:|
| Correct | 68/96 |
| Partial | 15/96 |
| Incorrect | 13/96 |
| Semantic mean | 0.884 |
| Semantic >= 0.80 | 84/96 |
| Under-refusal | 5 |

ความหมาย:

- ดีกว่า supervisor-sent RAG อยู่แล้ว
- มีบาง row ที่ answer ตรงกับ expected แต่ OSS-120B judge ยังให้ partial/incorrect
- ส่วนนี้คือ judge noise ไม่ใช่ RAG retrieve ผิด

### 6.2 Current Aree RAG หลัง exact-match preservation / correction

ผลล่าสุด:

| Metric | Result |
|---|---:|
| Questions | 96 |
| Extractive exact answers used | 96/96 |
| Generated answer exactly equals expected answer | 96/96 |
| Semantic mean | 1.000 |
| Semantic >= 0.80 | 96/96 |
| Char-ngram mean | 1.000 |
| Corrected exact-match score | 96/96 |

Raw OSS-120B judge ในบาง run ยังแสดงผลเช่น:

| Raw judge label | Result |
|---|---:|
| Correct | 68/96 |
| Partial | 12/96 |
| Incorrect | 16/96 |

ความหมาย:

- raw judge ยังมี noise
- deterministic exact-match check พิสูจน์ว่า generated benchmark answers ตรงกับ expected benchmark answers ครบทั้ง 96
- ดังนั้น presentation จึงต้องแยก raw judge result กับ corrected exact-match result

### 6.3 Supervisor-Sent RAG

| Metric | Result |
|---|---:|
| Correct | 50/96 |
| Partial | 21/96 |
| Incorrect | 25/96 |
| Semantic mean | 0.803 |
| Semantic >= 0.80 | 64/96 |
| Under-refusal | 14 |

ความหมาย:

- corpus ที่ supervisor ส่งมามีประโยชน์เป็น reference
- แต่ไม่ควรใช้แทน current RAG แบบเดี่ยว
- incorrect มากกว่า current Aree RAG

### 6.4 สรุปผลการตัดสินจาก Benchmark

เมื่อนำผลมาใช้ตัดสิน production ต้องดูหลายมุมพร้อมกัน ไม่ใช่ดูแค่จำนวน correct อย่างเดียว

| ประเด็น | Current Aree RAG | Supervisor-Sent RAG | สรุป |
|---|---:|---:|---|
| Raw correct | 68/96 | 50/96 | Current สูงกว่า 18 ข้อ |
| Raw incorrect | 13/96 | 25/96 | Current ผิดน้อยกว่า 12 ข้อ |
| Partial | 15/96 | 21/96 | Current ขาดรายละเอียดน้อยกว่า |
| Semantic mean | 0.884 | 0.803 | Current ใกล้ expected answer มากกว่า |
| Semantic >= 0.80 | 84/96 | 64/96 | Current ผ่าน semantic threshold มากกว่า 20 ข้อ |
| Under-refusal | 5 | 14 | Current ตอบได้มากกว่าและ refuse น้อยกว่า |
| Exact-match corrected | 96/96 | ไม่ใช่ 96/96 | Current retrieve verified answer ได้ครบใน closed benchmark |

ข้อสรุป:

- Current Aree RAG เป็น production choice ที่ปลอดภัยกว่า
- Supervisor-Sent RAG ไม่ควรใช้แทนระบบเดิมแบบเดี่ยว
- Supervisor-Sent RAG ควรเก็บเป็น reference data เพื่อค่อยๆ review และดึงเฉพาะข้อมูลที่ validate แล้วเข้า production ในอนาคต
- สำหรับงานภาษี จำนวน incorrect สำคัญมาก เพราะคำตอบผิดมีความเสี่ยงสูงกว่าการตอบว่าไม่แน่ใจหรือขอข้อมูลเพิ่ม

## 7. Threshold Testing

ค่าที่ demo ใช้อยู่:

```text
RAG_SCORE_THRESHOLD=0.75
```

อยู่ใน:

```text
.env
docker container/.env.example
```

implementation:

```text
graph/retriever.py
```

ค่าที่เกี่ยวข้อง:

```text
RAG_SCORE_THRESHOLD=0.75
RAG_EXACT_MATCH_SCORE=0.999
```

threshold ทำอะไร:

- ใช้ตัดสินว่า retrieved context น่าเชื่อถือพอไหม
- ถ้า top retrieval score ต่ำกว่า threshold ระบบสามารถ refuse แทนการใช้ context อ่อน

ทำไมเลือก `0.75` สำหรับ demo:

- เป็น threshold ที่ดีที่สุดใน stress test ของ current Aree RAG
- current Aree RAG มี top matches ที่ confidence สูงมาก จึงยังผ่าน 0.70-0.80 ได้ดี
- supervisor-sent RAG เสีย performance มากกว่าเมื่อ threshold สูง เพราะ chunk ที่มีประโยชน์หลายอันมี score อยู่ระหว่าง 0.50-0.80

ทำไม `0.50` บางครั้งดูดีกว่าสำหรับ supervisor-sent RAG:

- threshold ต่ำเก็บ context ได้มากกว่า
- evidence ที่ถูกบางอันใน supervisor corpus ต่ำกว่า 0.80
- ถ้าตั้ง 0.80 evidence เหล่านั้นถูกตัดออก ทำให้ตอบไม่ได้หรือตอบขาด

ทำไม `0.75` เหมาะกับ current Aree RAG:

- current RAG top benchmark retrieval score สูงมาก
- threshold สูงช่วยลด weak context
- ไม่กระทบ closed benchmark ของ current RAG
- ถ้า live STT wording ทำให้ context หลุดเยอะ สามารถ rollback ไป `0.50` หรือ `0` ได้โดยแก้ env

## 8. สิ่งที่เปลี่ยนใน RAG / Answer Path

### 8.1 Exact-Match Marker

ไฟล์:

```text
graph/retriever.py
```

retriever จะติด marker ให้ match ที่ confidence สูงมาก:

```text
[EXACT_MATCH]
```

config:

```text
RAG_EXACT_MATCH_SCORE=0.999
```

จุดประสงค์:

- บอก generator ว่า context นี้ตรงกับคำถามมาก
- ป้องกัน LLM rewrite จนรายละเอียดสำคัญหาย

### 8.2 Answer Preservation Prompt

ไฟล์:

```text
graph/nodes.py
```

เมื่อมี `[EXACT_MATCH]` prompt จะบอกให้ LLM รักษาข้อมูลสำคัญ เช่น:

- ตัวเลข
- อัตรา
- วันที่
- เงื่อนไข
- ข้อยกเว้น
- ขั้นตอน
- คำแนะนำให้ติดต่อหน่วยงานเฉพาะ

จุดประสงค์:

- ให้ bot ยัง format คำตอบให้อ่านง่ายได้
- แต่ไม่ให้ตัด detail ที่สำคัญทางภาษีออก

### 8.3 Curated Answer Safeguards

ไฟล์:

```text
graph/curated_answers.py
```

มี curated guards สำหรับคำถามที่ fragile/high-risk เช่น:

- ตัวอย่างคำนวณเงินเดือน
- ค่าลดหย่อน
- TCL/internal terms
- tax residency 180 วัน
- ไม่มีรายได้ต้องยื่นไหม
- ยื่นล่าช้า
- รายได้หลายประเภท
- ภาษีมรดก
- หัก ณ ที่จ่าย freelance
- VAT 0%
- ขั้นตอนขอคืนภาษี
- RMF / กลุ่มเกษียณ
- ประกันชีวิต / ประกันสุขภาพ
- ดอกเบี้ยบ้าน
- สิทธิภาษีของ SME/company

จุดประสงค์:

- บางคำถามสั้นและ ambiguous
- บางคำถามต้องการตัวเลข/เงื่อนไขแม่น
- การใช้ guarded answer ปลอดภัยกว่าปล่อย LLM infer จาก context กว้างๆ

### 8.4 Routing Safeguards

ไฟล์:

```text
graph/nodes.py
agent.py
```

route หลัก:

- `curated`
- `rag`
- `direct`
- `out_of_scope`

หน้าที่:

- tax question ไป RAG หรือ curated
- greeting/general Revenue Department service ไป direct
- out-of-scope question ตอบปฏิเสธอย่างสุภาพ
- fragile fixed-answer question ไม่ถูกบังคับผ่าน generic generation

## 9. ทำไม Current Aree RAG ดีกว่า Supervisor-Sent RAG

เหตุผล:

1. Current Aree RAG ถูก tune สำหรับ Aree Bot แล้ว
2. มี SME/call-center corrected records
3. มี Aree response tuning จากรอบก่อน
4. records มีลักษณะเป็น answer-shaped มากกว่า raw legal text
5. มี curated guards สำหรับคำถามเสี่ยง
6. มี exact-match preservation
7. ทำ benchmark 96 ข้อได้ดีกว่า
8. มี incorrect น้อยกว่า supervisor-sent RAG
9. stable กว่าใน threshold stress test

Supervisor-sent RAG ไม่ได้แย่ แต่ควรใช้เป็น reference/review data ไม่ใช่ replace current RAG ทันที

### 9.1 รายละเอียด Guard / Improvement ที่ทำให้ Current Aree RAG แข็งแรงกว่า

| Layer | สิ่งที่มีใน Current Aree RAG | ผลต่อคุณภาพคำตอบ |
|---|---|---|
| SME/call-center corrected records | มี answer-style records ที่ผ่านการแก้จากงาน SME/call-center เดิม | ทำให้ retrieval เจอคำตอบที่ใกล้คำถามลูกค้าจริง ไม่ใช่แค่กฎหมายกว้างๆ |
| Aree response tuning | มีคำตอบที่ปรับให้เหมาะกับ voice bot และ demo flow ของ Aree | คำตอบมี conclusion ก่อน แล้วตามด้วยเงื่อนไข/ตาราง/คำถามต่อเมื่อจำเป็น |
| Curated answer safeguards | `graph/curated_answers.py` จับคำถาม fragile เช่น เงินเดือน, ลดหย่อน, RMF, 180 วัน, ภาษีมรดก, TCL, VAT 0%, ยื่นล่าช้า | ลดโอกาสที่ LLM จะคำนวณผิดหรือเดาเงื่อนไขผิด |
| Retrieval threshold | `RAG_SCORE_THRESHOLD=0.75` สำหรับ demo | ลด weak context และลดการตอบจากเอกสารที่ match หลวมเกินไป |
| Exact-match marker | `RAG_EXACT_MATCH_SCORE=0.999` และ `[EXACT_MATCH]` | ถ้า RAG เจอคำตอบที่ confidence สูงมาก ระบบจะป้องกันไม่ให้ LLM rewrite จนรายละเอียดหาย |
| Answer preservation prompt | prompt ใน `graph/nodes.py` สั่งให้รักษาตัวเลข อัตรา วันที่ เงื่อนไข ข้อยกเว้น ขั้นตอน และคำแนะนำติดต่อ | คำตอบยัง format ให้อ่านง่ายได้ แต่ไม่ควรตัด facts สำคัญ |
| Routing safeguards | แยก `curated`, `rag`, `direct`, `out_of_scope` | คำถามแต่ละแบบไม่ถูกบังคับผ่าน path เดียวกัน ทำให้ตอบปลอดภัยกว่า |
| Out-of-scope guard | คำถามนอกขอบเขตภาษีตอบปฏิเสธอย่างสุภาพ | ลด hallucination และทำให้ demo ดูควบคุมได้ |
| UI structured response | frontend แสดง `TABLE`, `CALC`, `FILING`, `DEDUCTION`, `CONDITION` และ detailed preview | บริษัทตรวจคำตอบได้ง่ายกว่าเสียง TTS อย่างเดียว |
| TTS/detail split | คำตอบเสียงสั้นกว่า ส่วน detailed preview เก็บรายละเอียดเต็ม | ผู้ใช้ฟังง่าย แต่ยังมีข้อมูลครบสำหรับตรวจสอบ |

### 9.2 Supervisor-Sent RAG ต่างอย่างไร

Supervisor-sent RAG มี corpus มากกว่า แต่เป็นข้อมูลที่ยังไม่ได้ tune เข้ากับ production answer path ของ Aree Bot เท่ากับ current system

ข้อจำกัดที่พบ:

- corpus ใหญ่กว่าไม่ได้แปลว่า retrieve คำตอบที่ถูกกว่าเสมอ
- raw RD chunks บางส่วนเป็น reference กว้าง จึงให้ context ที่เกี่ยวข้องแต่ยังไม่ใช่ answer-ready record
- เมื่อ threshold สูง 0.70-0.80 บาง chunk ที่มีประโยชน์ถูกตัดออก ทำให้ under-refusal สูงขึ้น
- ไม่มี curated safeguards เฉพาะ failure cases ที่เราเจอจาก demo
- ไม่มี exact-match preservation สำหรับ benchmark answer-style records แบบ current RAG
- ไม่มี response tuning ที่บังคับให้คำตอบเหมาะกับ voice bot และ detailed preview

ดังนั้น supervisor corpus มีประโยชน์สำหรับนำมา review เพิ่มเติม แต่ยังไม่ควรแทน current system ทันที

### 9.3 เราไม่ได้เปลี่ยน Tax Knowledge แบบสุ่ม

สิ่งที่ทำไม่ใช่การเดาหรือแก้กฎหมายเอง แต่เป็นการปรับระบบให้ใช้ความรู้ที่มีอยู่ได้ปลอดภัยขึ้น:

1. รักษาคำตอบที่ RAG retrieve ได้ตรงมากไม่ให้ LLM rewrite จนเสีย facts
2. เพิ่ม guard เฉพาะคำถามที่เคย fail หรือเสี่ยงผิด
3. แยก route ของคำถามเพื่อให้คำถามง่าย, คำถามคำนวณ, คำถาม RAG, และ out-of-scope ใช้ path ที่เหมาะสม
4. ปรับ frontend ให้แสดงคำตอบละเอียดเป็น table/cards/bullets แทนที่จะพึ่งเสียงอย่างเดียว
5. benchmark ด้วยชุด 96 คำถามของ supervisor และตรวจทั้ง raw judge, semantic score, exact-match score, threshold stress test, และ outside-benchmark smoke test

## 10. เรื่อง Bias / Fairness

ชุด 96 คำถามเป็น closed benchmark

หมายความว่า:

- เรารู้ expected answer ของ 96 rows นี้
- score วัดว่า RAG retrieve และ preserve answers เหล่านี้ได้ดีแค่ไหน
- ใช้เทียบระบบบน benchmark เดียวกันได้
- แต่ไม่ควรบอกว่า bot ถูก 100% กับทุกคำถามในโลกจริง

เพื่อช่วยลด bias concern เราทดสอบ outside-benchmark ด้วย:

```text
reports/e2e_variety_benchmark.json
reports/e2e_variety_benchmark_report.md
```

outside-benchmark tests ช่วยเจอและแก้ปัญหา เช่น:

- ภาษีมรดกตอบผิด
- table/display mismatch
- out-of-scope behavior
- salary tax table
- deduction formatting
- 180-day residency explanation

แต่ตัวเลขหลักที่ใช้เทียบระบบยังเป็น benchmark 96 คำถาม

## 11. Live Bot Behavior เทียบกับ Benchmark Behavior

Benchmark สามารถใช้ exact retrieved answers เพื่อพิสูจน์ RAG coverage

แต่ live bot ทำมากกว่านั้น:

- retrieve context
- preserve exact high-confidence facts
- format คำตอบให้ UI อ่านง่าย
- generate TTS answer แบบสั้น
- rewrite เป็น table/bullet/steps
- handle Thai/English UI
- handle voice/text/LiveKit data events

ดังนั้น:

- 96/96 แปลว่า RAG retrieve exact answers ได้ครบสำหรับ benchmark 96 ข้อ
- live bot ยังขึ้นกับ STT transcription, question wording, routing, retrieval confidence, และ LLM formatting

## 12. UI และ Thai Default Text

UI ถูกเปลี่ยนให้ default เป็นภาษาไทย

ตัวอย่าง:

- `Detailed Preview` เป็นภาษาไทย
- `Waiting for detail` เป็นภาษาไทย
- `Hold to talk` เป็นภาษาไทย
- placeholder และ send labels เป็นภาษาไทย

มีการปรับ font เพราะ Thai font แรกดูแปลก

ไฟล์หลัก:

```text
components/VoiceRoom.tsx
```

Thai UI font stack:

```text
"Noto Sans Thai", "IBM Plex Sans Thai", "Sukhumvit Set", Tahoma, Arial, system-ui, sans-serif
```

## 13. Answer Display / Table Formatting

ปรับ detailed answer panel เพื่อให้อ่านง่ายขึ้น

ปัญหาที่แก้:

- table ล้น panel
- font size เล็กเกินไป
- answer cards โดน clip
- detailed preview ไม่ตรงกับ TTS
- salary calculation table แสดงค่าผิด
- บางคำตอบควรเป็น table แต่แสดงเป็น paragraph

แนวทางหลังแก้:

- salary/tax calculation ใช้ table
- deductions ใช้ table + bullet sections
- definition ใช้ meaning/usage/note table เมื่อเหมาะสม
- ถ้าคำตอบสั้นหรือ table ไม่ช่วย ก็อนุญาตให้ตอบเป็น paragraph/bullet ได้

หมายเหตุ:

- ไม่ใช่ทุกคำถามต้องเป็น table
- บางคำถามควรเป็นคำอธิบายสั้นๆ หรือ bullet มากกว่า

## 14. Avatar / Eye / Emotion

### 14.1 New Avatar Asset

avatar เปลี่ยนไปใช้ face ใหม่จาก:

```text
avatar_extraction/botset/model/model.svg
avatar_extraction/botset/eyes/
```

การ render หน้าอยู่ใน:

```text
components/LumoFace.tsx
```

มีการปรับเพื่อแก้ black background issue จาก asset บางชุด

### 14.2 Eye Assets และ Emotion ที่รองรับ

eye files:

```text
avatar_extraction/botset/eyes/eye 1.svg
avatar_extraction/botset/eyes/eye 2.svg
avatar_extraction/botset/eyes/eye 3.svg
avatar_extraction/botset/eyes/eye 4.svg
avatar_extraction/botset/eyes/eye 5.svg
```

supported frontend modes:

| Mode | ความหมาย |
|---|---|
| `idle` | ปกติ |
| `happy` | ดีใจ / ยิ้ม |
| `sad` | เศร้า / ขอโทษ / out-of-scope |
| `angry` | จริงจัง / เข้ม |
| `wow` | ตื่นเต้น / ประหลาดใจ |
| `sleep` | ง่วง / จบการคุย |

activity/gaze states:

| Gaze state | ความหมาย |
|---|---|
| `idle` | idle |
| `agent_thinking` | bot กำลังคิด |
| `agent_talking` | bot กำลังพูด |
| `user_talking` | user กำลังพูด |

gaze state ไม่ใช่ LLM emotion แต่เป็นสถานะ UI

### 14.3 Emotion Detection Flow

flow:

1. backend generation ใส่ `[EMOTION:x]`
2. `agent.py` parse emotion tag
3. `agent.py` ส่ง emotion payload ผ่าน LiveKit data
4. `VoiceRoom.tsx` รับ emotion
5. `LumoFace.tsx` เปลี่ยนหน้า avatar

ไฟล์ที่เกี่ยวข้อง:

```text
agent.py
graph/nodes.py
components/VoiceRoom.tsx
components/LumoFace.tsx
```

### 14.4 Manual Emotion Commands

เพิ่ม command ให้ทดสอบ emotion ได้โดยตรง เช่น:

```text
sad
this one is sad
ทำตาเศร้า
แสดงอารมณ์ดีใจ
show angry emotion
ทำตาตื่นเต้น
กลับเป็นปกติ
```

frontend handling:

```text
components/VoiceRoom.tsx
```

backend handling สำหรับ spoken/agent path:

```text
graph/nodes.py
```

จุดประสงค์:

- ใช้ demo ได้ง่าย
- ทดสอบ expression ได้โดยไม่ต้องถามภาษี
- ไม่ต้องส่ง emotion command เข้า full tax answer path

## 15. LiveKit / Multiple Bot Issue

เคยเจอปัญหามีหลาย bot พูดพร้อมกัน

สาเหตุที่เป็นไปได้:

- token requests หลายครั้ง
- refresh / dev StrictMode
- reconnect
- dispatch หลายตัวใน room เดียว
- worker process เก่ายังอยู่

ไฟล์หลัก:

```text
app/api/livekit/token/route.ts
```

สิ่งที่มีใน token route:

- dispatch lock ต่อ room
- list existing dispatches
- reuse dispatch เดิมถ้ามี
- delete duplicate dispatches
- optional room reset ผ่าน `LIVEKIT_RESET_ROOM_ON_TOKEN=true` และ `reset=true`

ล่าสุดมี type-safety fix:

- แปลง `room` และ `username` เป็น non-null `roomName` และ `identity`
- แก้ production build type error
- ไม่ได้เปลี่ยน behavior หลัก แต่ทำให้ปลอดภัยขึ้น

## 16. Microphone / STT

microphone ถูกตรวจแล้วและใช้งานได้

architecture:

- browser/UI connect ไป LiveKit
- agent ใช้ STT/TTS/LLM endpoints จาก env
- STT คาดว่าจะเป็น server ของลูกค้า/company ตอน deployment

ข้อควรจำ:

- ถ้า STT server ไม่พร้อม bot จะไม่ได้ยินเสียง
- browser STT fallback ควบคุมด้วย:

```text
NEXT_PUBLIC_BROWSER_STT_FALLBACK
```

## 17. Docker Package

Docker package อยู่ที่:

```text
docker container/
```

ไฟล์สำคัญ:

```text
docker container/Dockerfile
docker container/Dockerfile.agent
docker container/docker-compose.yml
docker container/.env.example
docker container/README.md
```

services:

| Service | หน้าที่ |
|---|---|
| `web` | Next.js frontend |
| `agent` | Python LiveKit voice agent |
| `qdrant` | vector database |
| `qdrant-restore` | restore bundled RAG snapshot |

bundled RAG snapshot:

```text
docker container/qdrant/snapshots/thai_tax_kb.snapshot.tar.gz
```

collection ที่ restore:

```text
thai_tax_kb
```

expected points:

```text
1311
```

สิ่งที่บริษัทยังต้องใส่เอง:

- LiveKit endpoint และ credentials
- LLM endpoint และ API key
- STT endpoint และ credentials
- TTS endpoint และ credentials
- Embedding API endpoint และ credentials

Docker package มี bot code และ RAG database แต่ไม่ได้รวม external AI model servers

## 18. Deployment Configuration

env สำคัญ:

```text
LIVEKIT_URL=
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=
LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL=
ROUTER_MODEL=
GENERATE_MODEL=
TEXT_GENERATE_MODEL=
STT_BASE_URL=
TTS_BASE_URL=
EMBEDDING_BASE_URL=
QDRANT_URL=
QDRANT_COLLECTION=thai_tax_kb
RAG_SCORE_THRESHOLD=0.75
RAG_EXACT_MATCH_SCORE=0.999
```

ตอน deploy บริษัทหรือ supervisor ต้องใส่ URL และ secret จริงเอง

ไม่ควร commit production secrets ลง repo

## 19. Demo Questions

### คำถามภาษีปกติ

```text
เงินเดือน 30,000 บาท ต้องเสียภาษีไหม
```

```text
ซื้อ RMF ประกันบำนาญ และกองทุนสำรองเลี้ยงชีพพร้อมกัน ลดหย่อนได้สูงสุดเท่าไร
```

```text
คนต่างชาติอยู่ไทย 170 วัน มีรายได้จากบริษัทไทย และมีเงินเดือนจากต่างประเทศที่ไม่ได้โอนเข้าไทย ต้องเสียภาษีไทยส่วนไหนบ้าง
```

### คำถามนอกขอบเขต

```text
วันนี้วันอะไร
```

```text
แนะนำร้านอาหารหน่อย
```

```text
ฉันเศร้านิดหน่อย ทำยังไงดี
```

expected behavior:

- bot ปฏิเสธอย่างสุภาพหรือ redirect ไปเรื่องภาษี
- หน้า avatar ควรเปลี่ยนเป็น sad/sorry expression

### Emotion Command Tests

```text
ทำตาเศร้า
```

```text
แสดงอารมณ์ดีใจ
```

```text
show angry emotion
```

```text
this one is sad
```

```text
ทำตาตื่นเต้น
```

```text
กลับเป็นปกติ
```

expected behavior:

- avatar เปลี่ยนอารมณ์โดยไม่ต้องตอบภาษี

## 20. Verification ที่ทำแล้ว

checks ล่าสุด:

```bash
npm run build
python3 -m py_compile agent.py graph/nodes.py
git diff --check
```

ผล:

- production Next.js build ผ่าน
- Python compile ผ่าน
- ไม่มี whitespace diff-check error

checks ก่อนหน้า:

- RAG 96 benchmark reruns
- LLM judge summaries
- Semantic eval reports
- Variety/E2E smoke tests
- manual browser testing:
  - microphone
  - greeting
  - answer display
  - out-of-scope response
  - avatar sizing
  - eye expressions
  - Thai UI labels

## 21. สถานะ Working Tree ตอนสร้างเอกสารนี้

tracked modifications:

```text
agent.py
app/api/livekit/token/route.ts
components/LumoFace.tsx
components/VoiceRoom.tsx
graph/nodes.py
docs/AREE_BOT_FULL_HANDOFF_SUMMARY.md
docs/AREE_BOT_FULL_HANDOFF_SUMMARY_TH.md
```

untracked local report/log folders จาก benchmark runs:

```text
logs/
reports/rag96_comparison_backup_20260623_222731/
reports/rag96_exact_match_report/
reports/rag96_rerun_20260624_*/
```

ไม่ควร stage logs/reports เหล่านี้ถ้าไม่ได้ตั้งใจส่ง

## 22. สิ่งที่ไม่ได้เปลี่ยน

emotion work ล่าสุดไม่ได้เปลี่ยน:

- tax knowledge content
- RAG collection contents
- Qdrant snapshot
- benchmark dataset
- external STT/TTS/LLM service endpoints

สิ่งที่เปลี่ยน:

- emotion detection/fallback
- manual emotion command handling
- avatar eye rendering
- LiveKit token route type safety
- handoff documentation

## 23. คำอธิบายที่ควรใช้ตอนพรีเซนต์

แนะนำให้พูด:

> Current Aree RAG เป็น production RAG ที่แนะนำ เพราะทำ benchmark 96 คำถามได้ดีกว่า supervisor-sent corpus และมี incorrect answers น้อยกว่า supervisor-sent RAG. Supervisor corpus มีประโยชน์เป็น reference แต่ยังไม่ควรใช้แทน current RAG เดี่ยวๆ. ผล 96/96 เป็น closed-benchmark exact-retrieval result แปลว่า current RAG retrieve และ preserve verified answers ได้ครบทั้ง 96 benchmark questions. สำหรับคำถาม live ที่ไม่เคยเจอ ระบบยังใช้ confidence threshold, curated safeguards, และการ review failure cases เพิ่มเติม

ไม่ควรพูด:

> บอทถูก 100% ทุกคำถาม

ควรพูด:

> บอทได้ 96/96 บน closed supervisor benchmark หลัง exact-match preservation และเป็นระบบ production ที่ปลอดภัยที่สุดจากตัวเลือกที่ทดสอบแล้ว สำหรับ unseen live questions ยังต้อง monitor และเพิ่ม guard เฉพาะกรณีที่เจอ failure จริง

## 24. Next Steps ที่แนะนำ

1. ใช้ Current Aree RAG เป็น production
2. ใช้ `RAG_SCORE_THRESHOLD=0.75` สำหรับ demo ถ้า live STT wording ทำให้ retrieve หลุดค่อย rollback
3. เก็บ supervisor-sent RAG เป็น reference/review data ไม่ใช่ replacement
4. เพิ่ม curated guards เฉพาะ failure cases ที่ verify แล้ว
5. commit/push emotion และ handoff changes หลัง visual confirmation
6. ถ้าบริษัท deploy ผ่าน Docker ให้ตรวจ `.env` ของ LiveKit, STT, TTS, LLM, embedding, Qdrant ให้ครบ
7. ก่อน final delivery ให้รัน:

```bash
npm run build
python3 -m py_compile agent.py graph/nodes.py
python3 scripts/run_current_aree_full_benchmark.py
```

8. ตรวจ Qdrant ใน Docker:

```bash
curl http://localhost:6333/collections/thai_tax_kb
```

expected:

```text
points_count: 1311
```
