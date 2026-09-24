# Detailed Preview Handoff

## Summary

This work separates what the bot speaks from what the UI renders as the detailed preview.

- The bot still speaks a short summary for the current turn.
- The old `CURRENT TURN` visual panel was removed.
- The right-side `DETAILED PREVIEW` panel is now the main visible answer area.
- The user question is shown in the preview header as `QUESTION`.
- Detailed text is formatted into structured UI blocks for common tax question types.

Pushed commit:

```text
a6aa60b Improve detailed preview formatting
```

Branch:

```text
Max
```

## Main Files

```text
components/VoiceRoom.tsx
graph/nodes.py
```

## Behavior

### Voice Output

Voice output remains separate from the detailed preview. The bot can speak a compact answer while the UI displays a richer breakdown.

Relevant flow:

```text
agent.py
  voice_sentence_stream()
    -> stream_voice_answer()
    -> TTS
```

### Detailed Preview

The frontend receives `chat_delta` / `chat_answer` events and renders them in the detailed preview.

Relevant flow:

```text
agent.py
  stream_text_to_chat()
    -> stream_text_answer()
    -> chat_delta / chat_answer

components/VoiceRoom.tsx
  DataReceived handler
    -> setSmartDetailPreview()
    -> renderMarkdownPreview()
```

## Preview Types

### General Markdown

If the detail model returns markdown tables, bullets, numbered lists, or headings, the frontend renders them directly.

Marker examples:

```text
TABLE
CALC
FILING
DEDUCTION
CONDITION
INFO
ANSWER
```

### Low-Info Definition Questions

Questions like these use an `INFO` layout if the model returns plain text:

```text
9e คืออะไร?
VAT คืออะไร?
ภ.ง.ด.91 คืออะไร?
e-Filing คืออะไร?
```

The UI renders:

```text
ความหมาย
รายละเอียด
```

### Salary / Tax Calculation Questions

Salary questions use a calculation layout if the model returns plain text.

Example query:

```text
ผมอายุ 22 ปี เพิ่งเริ่มทำงาน เงินเดือน 18,000 บาท ต้องยื่นภาษีไหม?
```

Expected preview sections:

```text
ผลเบื้องต้น
รายการ / วิธีคิด / ผลลัพธ์
เกณฑ์ที่เกี่ยวข้อง
ควรถามต่อ
```

Age is now considered:

```text
อายุ 22 ปี: ใช้เกณฑ์บุคคลธรรมดาทั่วไป ยังไม่เข้าเงื่อนไขสิทธิผู้สูงอายุ
```

If age is already provided, `ควรถามต่อ` does not ask for age again. It asks for other missing inputs such as:

```text
เดือนที่เริ่มทำงานจริง
โบนัส
รายได้อื่น
กองทุน
ประกัน
คู่สมรสหรือบุตร
```

### Deduction Questions

Deduction questions use a structured layout if the model returns plain text.

Example query:

```text
ประกันชีวิตลดหย่อนภาษีได้เท่าไร?
```

Expected preview sections:

```text
สรุปลดหย่อน
รายการ / วงเงิน / รายละเอียด
เงื่อนไขสำคัญ
ควรถามต่อ
```

Deduction follow-up suggestions:

```text
จ่ายเบี้ยจริงปีนี้เท่าไร
เป็นประกันของตนเอง พ่อแม่ คู่สมรส หรือบุตร
เป็นประกันชีวิตทั่วไป ประกันสุขภาพ หรือแบบบำนาญ
มีหลักฐานการชำระเงินและหนังสือรับรองจากบริษัทประกันหรือไม่
```

## Detail Model Prompt Changes

`graph/nodes.py` now instructs `TEXT_SYSTEM_PROMPT` to:

- Use information-style text, not spoken Thai.
- Avoid polite endings like `ค่ะ`, `ครับ`, `นะคะ`, `นะครับ`.
- Avoid long plain paragraphs.
- Use markdown tables for definitions, calculations, salary/tax questions, and deduction questions.
- Include salary age handling when age is provided.
- Include deduction follow-up questions.

## Sample QA Queries

Use these to verify the behavior.

### Definition

```text
9e คืออะไร?
```

Expected:

```text
INFO or TABLE marker
compact definition format
no ค่ะ / ครับ in detailed preview
```

### Salary Tax

```text
ฉันได้เงินเดือน 25,000 บาท ต้องเสียภาษีหรือไม่?
```

Expected:

```text
CALC / FILING / DEDUCTION markers
calculation table
filing threshold section
follow-up suggestions
```

### Salary With Age

```text
ผมอายุ 22 ปี เพิ่งเริ่มทำงาน เงินเดือน 18,000 บาท ต้องยื่นภาษีไหม?
```

Expected:

```text
age row in calculation table
age note in related criteria
follow-up asks for month started, not age
```

### Deduction

```text
ประกันชีวิตลดหย่อนภาษีได้เท่าไร?
```

Expected:

```text
DEDUCTION / CONDITION markers
deduction limit table
condition card
deduction-specific follow-up card
```

### List / Long Detail

```text
ต้องใช้เอกสารอะไรบ้างในการยื่นภาษี?
```

Expected:

```text
detailed preview shows full list
voice should stay short or hand off to the preview
```

## Run / Verify

Frontend:

```bash
npm run dev
```

Build check:

```bash
npm run build
```

Lint check:

```bash
npm run lint
```

Python syntax check:

```bash
python3 -m py_compile graph/nodes.py
```

Restart the Python agent after prompt changes:

```bash
./open_voicebot_agent.command
```

Start frontend:

```bash
./open_voicebot_frontend.command
```

## Notes

- The screenshot file was not committed.
- Generated `__pycache__` files were not committed.
- There are unrelated local changes in the worktree that were intentionally not included in the pushed commit.
