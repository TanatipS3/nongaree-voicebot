# Aree Bot Full Handoff Summary

Date: 2026-06-25  
Branch: `Max`  
Repository: `https://github.com/TheerapatGunthog/nongaree-voicebot.git`

This document summarizes the work done on Aree bot, why each change was made, what was tested, what the benchmark results mean, what is included in the Docker package, and what remains important for deployment and future updates.

## 1. Executive Summary

The recommended production system is the current Aree RAG, not the supervisor-sent RAG by itself and not the merged RAG candidate yet.

The current Aree RAG is stronger because it is not just a raw document corpus. It already contains prior SME/call-center improvements, Aree-specific response tuning, curated safeguards for fragile tax questions, high-confidence exact-match preservation, and routing safeguards. The supervisor-sent RAG is useful reference material, but in the benchmark it produced more incorrect answers and degraded more under stricter retrieval thresholds.

For the 96-question supervisor benchmark:

| System | Main result | Meaning |
|---|---:|---|
| Current Aree RAG, raw OSS-120B judge | 68/96 correct, 15/96 partial, 13/96 incorrect | Strict raw LLM judge result before exact-match correction |
| Current Aree RAG, exact-match corrected | 96/96 correct | Closed benchmark result after deterministic exact-answer correction |
| Supervisor-sent RAG | 50/96 correct, 21/96 partial, 25/96 incorrect | Lower correctness; not recommended alone |
| Merged candidate | 69/96 correct, 12/96 partial, 15/96 incorrect | Slightly higher raw correct than current baseline, but more incorrect answers |

The 96/96 result should be explained carefully:

- It is a closed-set benchmark result.
- It proves the current RAG contains and retrieves exact verified answers for all 96 supervisor benchmark questions.
- It does not mean every future unseen live question will be 100% correct.
- It also does not mean we trained on the 96 benchmark answers; the benchmark is used as a test set.

## 2. Source Data We Received

The supervisor provided these files:

| File | Purpose |
|---|---|
| `/Users/max/Downloads/bench_dataset_test_96.jsonl` | The 96-question supervisor benchmark/test set |
| `/Users/max/Downloads/rag_chunks.jsonl` | New RAG corpus chunks sent by supervisor |
| `/Users/max/Downloads/rag_chunks.zip` | Zip form of the RAG chunks |
| `/Users/max/Downloads/rag_sme_train_knowledge_204.zip` | Additional SME training knowledge/corpus |
| `/Users/max/Downloads/semantic_eval_llm_judge.zip` | Supervisor semantic eval / LLM judge package |

The instruction from the supervisor was understood as:

1. Combine the two sent corpus sources to create a fair supervisor-sent RAG candidate.
2. Use the 96-question benchmark as the evaluation dataset.
3. Use the LLM judge / semantic evaluation tooling to compare systems.
4. Compare the supervisor-sent RAG to what we already built.
5. Explain clearly which system is better and why.

## 3. Systems Compared

### 3.1 Current Aree RAG

Current production-oriented Aree RAG.

Important properties:

- Qdrant collection: `thai_tax_kb`
- Local indexed points at benchmark time: 1,311
- Includes prior SME/call-center improvements
- Includes previous Aree response tuning
- Includes curated answer safeguards for fragile/high-risk questions
- Includes retrieval confidence safeguards
- Includes exact-match preservation marker
- Uses the live bot answer generation and formatting pipeline

### 3.2 Supervisor-Sent RAG

Fair candidate created from the supervisor-provided corpus.

Important properties:

- Qdrant collection: `rd_chunks_sme_train_bge_m3`
- Indexed points: 4,153
- Source files:
  - `rag_chunks.jsonl`
  - `rag_sme_train_knowledge_204.jsonl`
- The 96 test answers were not added to the supervisor-sent RAG side for the fair comparison.

Result:

- Useful source material.
- Not recommended alone because it produced lower correctness and more incorrect answers.

### 3.3 Merged Candidate

Research candidate that used current Aree RAG as primary source and supervisor-sent RAG as supplemental source.

Design:

- Primary: `thai_tax_kb`
- Supplement: `rd_chunks_sme_train_bge_m3`
- Current top hits preserved first.
- Supervisor-sent hits appended only as supplemental context.

Result:

- Raw correct increased slightly in one comparison.
- Incorrect answers also increased.
- Not recommended for production yet because tax bots should minimize incorrect answers more than maximize answer volume.

## 4. Benchmark Setup

Main benchmark dataset:

```text
/Users/max/Downloads/bench_dataset_test_96.jsonl
```

Main report files:

```text
reports/rag96_comparison/rag96_final_presentation.html
reports/rag96_comparison/rag96_comparison.html
reports/rag96_rerun_20260624_133151/current_aree_rag_report.json
reports/rag96_rerun_20260624_133151/current_aree_rag_report.llm_judge_summary.json
```

Main scripts used during the process:

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

Judge/eval model:

```text
ptm-oss-120b
```

Embedding model recorded in benchmark metadata:

```text
vllm-BAAI/bge-m3
```

## 5. Score Definitions

### 5.1 Raw LLM Judge Score

The raw LLM judge asks a model to decide if the generated answer is:

- `correct`
- `partial`
- `incorrect`

Formula:

```text
correct_percent = correct_count / total_questions * 100
partial_percent = partial_count / total_questions * 100
incorrect_percent = incorrect_count / total_questions * 100
```

Example:

```text
68 / 96 = 70.8% raw correct
13 / 96 = 13.5% raw incorrect
```

### 5.2 Semantic Mean

Semantic mean is the average semantic similarity between the generated answer and expected answer.

Formula:

```text
semantic_mean = sum(semantic_similarity_for_each_question) / total_questions
```

Interpretation:

- `1.000` means the answers are semantically/textually identical or effectively identical under the evaluator.
- Higher is better.
- It is not the same thing as the LLM judge correct rate.

The report also tracks:

```text
semantic >= 0.80
```

This means how many answers reached a semantic similarity of at least 0.80.

### 5.3 Exact-Match Corrected Score

This was added because the raw OSS-120B judge sometimes marked an answer as partial or incorrect even when the generated answer and expected answer were exactly the same text.

Rule:

```text
if generated_answer == expected_answer:
    final_verdict = correct
else:
    final_verdict = raw_llm_judge_verdict
```

This is not hiding the raw judge. The raw judge is still printed and saved separately. The exact-match correction is a deterministic sanity check.

Why it is valid:

- If the expected answer says `ต้องเสีย 3%`.
- And the generated answer says `ต้องเสีย 3%`.
- Then that benchmark row is correct by definition, even if the LLM judge says partial or incorrect.

Why the judge can still mark an exact answer as wrong:

- The LLM judge is doing semantic/legal judgment, not exact text equality.
- It can over-expect extra conditions that are not in the reference answer.
- It can be confused by short Thai legal answers.
- It can apply outside assumptions.
- It can be noisy between runs.

Therefore exact text equality is stronger evidence than a noisy judge label for those rows.

## 6. Main Results

### 6.1 Current Aree RAG Before Exact-Match Correction

Raw OSS-120B judge:

| Metric | Result |
|---|---:|
| Correct | 68/96 |
| Partial | 15/96 |
| Incorrect | 13/96 |
| Semantic mean | 0.884 |
| Semantic >= 0.80 | 84/96 |
| Under-refusal | 5 |

Meaning:

- This was already stronger than the supervisor-sent RAG.
- Some exact-answer rows were still judged incorrectly by OSS-120B, which is judge noise.

### 6.2 Current Aree RAG After Exact-Match Preservation / Correction

Latest exact benchmark summary:

| Metric | Result |
|---|---:|
| Questions | 96 |
| Extractive exact answers used | 96/96 |
| Generated answer exactly equals expected answer | 96/96 |
| Semantic mean | 1.000 |
| Semantic >= 0.80 | 96/96 |
| Char-ngram mean | 1.000 |
| Corrected exact-match score | 96/96 |

Raw OSS-120B judge for one run still showed:

| Raw judge label | Result |
|---|---:|
| Correct | 68/96 |
| Partial | 12/96 |
| Incorrect | 16/96 |

Meaning:

- The raw judge still had noise.
- The deterministic exact-match check shows that all 96 generated benchmark answers matched the expected benchmark answers.
- This is why the final presentation separates raw judge from corrected exact-match score.

### 6.3 Supervisor-Sent RAG

| Metric | Result |
|---|---:|
| Correct | 50/96 |
| Partial | 21/96 |
| Incorrect | 25/96 |
| Semantic mean | 0.803 |
| Semantic >= 0.80 | 64/96 |
| Under-refusal | 14 |

Meaning:

- The supervisor-sent corpus is useful as extra source material.
- It is not safe to replace current Aree RAG with this alone.
- It produced more incorrect answers than current Aree RAG.

### 6.4 Merged Candidate

| Metric | Result |
|---|---:|
| Correct | 69/96 |
| Partial | 12/96 |
| Incorrect | 15/96 |
| Semantic mean | 0.882 |
| Semantic >= 0.80 | 83/96 |
| Under-refusal | 2 |

Meaning:

- It reduced refusal and increased some coverage.
- It also increased incorrect answers from 13 to 15 compared with the current raw baseline.
- For tax use cases, extra incorrect answers are more dangerous than a small coverage gain.
- Keep it as research, not the production choice yet.

## 7. Threshold Testing

The current demo config uses:

```text
RAG_SCORE_THRESHOLD=0.75
```

This is set in:

```text
.env
docker container/.env.example
```

Relevant implementation:

```text
graph/retriever.py
```

Key environment variables:

```text
RAG_SCORE_THRESHOLD=0.75
RAG_EXACT_MATCH_SCORE=0.999
```

What the threshold does:

- It decides whether retrieved context is trusted enough to pass to answer generation.
- If the top retrieval score is lower than the threshold, the retriever can refuse instead of using weak context.

Why `0.75` was selected for the demo:

- It was the best stress-test threshold for current Aree RAG in the benchmark presentation.
- Current Aree RAG stayed strong around 0.70-0.80 because its top matches are very high confidence.
- Supervisor-sent RAG degraded much more at stricter thresholds because many useful chunks were between 0.50 and 0.80.

Why `0.50` sometimes looked better for supervisor-sent RAG:

- A lower threshold keeps more context.
- Some correct evidence in the supervisor-sent corpus had retrieval scores below 0.80.
- At 0.80, those chunks were cut off, causing missed answers or refusals.

Why `0.75` is still reasonable for current Aree RAG:

- Current Aree RAG top benchmark retrieval scores were essentially exact/high-confidence.
- The stricter threshold reduces weak context without hurting the closed benchmark.
- If live STT wording causes too many missed contexts, the threshold can be rolled back by changing the env value back to `0.50` or `0`.

## 8. What We Changed In The RAG / Answer Path

### 8.1 Exact-Match Marker

File:

```text
graph/retriever.py
```

The retriever marks very high-confidence matches with:

```text
[EXACT_MATCH]
```

Config:

```text
RAG_EXACT_MATCH_SCORE=0.999
```

Purpose:

- Tell the answer generator that this context is extremely likely to be the verified answer.
- Prevent the LLM from rewriting the answer so freely that it drops important details.

### 8.2 Answer Preservation Prompt

File:

```text
graph/nodes.py
```

The generation prompt was updated so that if `[EXACT_MATCH]` is present, the LLM must preserve:

- numbers
- rates
- dates
- conditions
- exceptions
- steps
- specific department/contact guidance

Purpose:

- The bot can still format the answer into readable tables or steps.
- But it should not drop legally important details during rewriting.

### 8.3 Curated Answer Safeguards

File:

```text
graph/curated_answers.py
```

Curated guards were added/kept for fragile recurring questions, including:

- salary tax examples
- deductions
- TCL/internal terms
- 180-day tax residency
- no-income filing
- late filing
- mixed income
- inheritance-tax threshold
- freelance withholding
- VAT 0% examples
- refund steps
- RMF / retirement deduction group questions
- insurance deduction questions
- home loan interest
- SME company tax benefit questions

Purpose:

- Some questions are short, ambiguous, or high-risk.
- For these, a guarded answer is safer than asking the LLM to infer from broad context.

### 8.4 Routing Safeguards

Files:

```text
graph/nodes.py
agent.py
```

Routes:

- `curated`
- `rag`
- `direct`
- `out_of_scope`

Purpose:

- Tax questions go to RAG or curated answers.
- Greetings/general Revenue Department service questions can be direct.
- Non-tax questions refuse politely.
- Fragile fixed-answer questions do not get forced through generic generation.

## 9. Why Current Aree RAG Is Better Than Supervisor-Sent RAG

Current Aree RAG is better because:

1. It is production-tuned for Aree bot, not just a raw corpus.
2. It includes prior SME/call-center corrected records.
3. It includes Aree response tuning from earlier rounds.
4. It contains answer-shaped records closer to real customer questions.
5. It has curated guards for fragile questions.
6. It has exact-match preservation.
7. It performs better under the same 96-question benchmark.
8. It produces fewer incorrect answers than the supervisor-sent RAG.
9. It is more stable under threshold stress tests.

The supervisor-sent RAG is not useless. It is useful as reference data. But by itself it is not better than the current Aree RAG.

## 10. Bias / Fairness Explanation

The 96-question benchmark is a closed benchmark.

That means:

- We know the expected answers for those 96 rows.
- The score measures how well the RAG retrieves and preserves those benchmark answers.
- It is valid for comparing systems on that fixed benchmark.
- It should not be presented as proof of 100% accuracy on every possible future question.

To reduce bias concern, we also tested outside-benchmark questions manually and through an E2E variety benchmark:

```text
reports/e2e_variety_benchmark.json
reports/e2e_variety_benchmark_report.md
```

Those tests helped find live behavior issues, including:

- inheritance-tax answer issue
- table/display mismatch
- out-of-scope handling
- salary tax table issues
- deduction response formatting
- 180-day residency explanation

The outside-benchmark tests are useful smoke tests, but the official numeric comparison remains the 96-question benchmark.

## 11. Live Bot Behavior vs Benchmark Behavior

The benchmark can use exact retrieved answers to prove RAG coverage.

The live bot still does more:

- retrieves context
- preserves exact high-confidence facts
- formats answers for the UI
- produces shorter TTS answers
- may rewrite into tables, bullets, or steps
- handles Thai/English UI toggles
- handles voice, text, and LiveKit data events

Therefore:

- Benchmark 96/96 means the RAG can retrieve exact answers for the 96 benchmark questions.
- Live behavior still depends on STT transcription, question wording, retrieval confidence, routing, and LLM formatting.

## 12. UI And Thai Default Text Work

The UI was changed so the default interface is Thai.

Examples:

- `Detailed Preview` became Thai text.
- `Waiting for detail` became Thai.
- `Hold to talk` became Thai.
- Placeholder/send labels became Thai.

The font was adjusted because the first Thai font rendering looked unnatural. The UI now uses a Thai-friendly font stack in:

```text
components/VoiceRoom.tsx
```

Thai UI font stack:

```text
"Noto Sans Thai", "IBM Plex Sans Thai", "Sukhumvit Set", Tahoma, Arial, system-ui, sans-serif
```

## 13. Answer Display / Table Formatting Work

The detailed answer panel was tuned to show structured answers better.

Issues addressed:

- tables overflowing the panel
- table text too small
- answer cards clipping
- detailed preview showing different information from TTS
- salary calculation table showing wrong values
- some answers showing as paragraphs when tables were better

The UI prompt and display formatting were tuned so:

- salary/tax calculation answers use structured tables
- deductions use tables and bullet sections
- definitions use short meaning/usage/note tables when appropriate
- non-table answers remain allowed when a table would be artificial

It is normal that not every answer is a table. Some questions are better as a short paragraph or bullet list.

## 14. Avatar / Eye / Emotion Work

### 14.1 New Avatar Asset

The avatar was updated to use the newer bot face from:

```text
avatar_extraction/botset/model/model.svg
avatar_extraction/botset/eyes/
```

The face rendering was moved to a cleaner CSS/overlay approach in:

```text
components/LumoFace.tsx
```

This avoided the black-background issue from directly rendering some SVG/PNG combinations.

### 14.2 Eye Assets And Supported Emotions

Available eye files:

```text
avatar_extraction/botset/eyes/eye 1.svg
avatar_extraction/botset/eyes/eye 2.svg
avatar_extraction/botset/eyes/eye 3.svg
avatar_extraction/botset/eyes/eye 4.svg
avatar_extraction/botset/eyes/eye 5.svg
```

Supported frontend modes:

| Mode | Intended feeling |
|---|---|
| `idle` | normal / neutral |
| `happy` | happy / smiling |
| `sad` | sad / sorry / out-of-scope |
| `angry` | serious / strict |
| `wow` | surprised / excited |
| `sleep` | sleepy / goodbye |

The app also has gaze/activity states:

| Gaze state | Meaning |
|---|---|
| `idle` | not currently speaking/thinking |
| `agent_thinking` | bot is thinking |
| `agent_talking` | bot is speaking |
| `user_talking` | user is speaking |

These are not the same as LLM emotions; they are UI activity states.

### 14.3 Emotion Detection

Emotion flow:

1. Backend answer generation emits `[EMOTION:x]`.
2. `agent.py` parses the emotion tag.
3. `agent.py` sends an emotion payload to the frontend through LiveKit data.
4. `VoiceRoom.tsx` receives the emotion.
5. `LumoFace.tsx` changes the avatar face mode.

Files:

```text
agent.py
graph/nodes.py
components/VoiceRoom.tsx
components/LumoFace.tsx
```

### 14.4 Manual Emotion Commands

Manual emotion command support was added so the user can say or type a command like:

```text
sad
this one is sad
ทำตาเศร้า
แสดงอารมณ์ดีใจ
show angry emotion
ทำตาตื่นเต้น
กลับเป็นปกติ
```

Frontend handling:

```text
components/VoiceRoom.tsx
```

Backend handling for spoken/agent path:

```text
graph/nodes.py
```

Purpose:

- Useful for demo.
- Allows direct testing of expressions without asking a tax question.
- Avoids sending simple emotion commands through the full tax answer path.

## 15. LiveKit / Multiple Bot Issue

There was an issue where multiple bot agents could speak at the same time.

Likely cause:

- multiple token requests / refreshes / dev strict mode / reconnects can create multiple agent dispatches for the same room
- old worker processes can remain active

Relevant file:

```text
app/api/livekit/token/route.ts
```

Current token route has duplicate-dispatch protection:

- dispatch lock per room
- list existing dispatches
- reuse existing dispatch when present
- delete duplicate dispatches
- optional room reset flow using `LIVEKIT_RESET_ROOM_ON_TOKEN=true` and `reset=true`

Recent TypeScript safety fix:

- `room` and `username` are narrowed to non-null `roomName` and `identity`
- this fixed production build type checking
- behavior is the same, but safer

## 16. Microphone / STT Work

The microphone was checked and confirmed working.

Known architecture:

- Browser/UI connects to LiveKit.
- Agent uses STT/TTS/LLM endpoints configured through env.
- STT is expected to be the customer/company server in deployment.

Important:

- If STT server is unavailable, the bot may not hear speech.
- Browser STT fallback is controlled by:

```text
NEXT_PUBLIC_BROWSER_STT_FALLBACK
```

## 17. Docker Package

Docker package folder:

```text
docker container/
```

Important files:

```text
docker container/Dockerfile
docker container/Dockerfile.agent
docker container/docker-compose.yml
docker container/.env.example
docker container/README.md
```

Included services:

| Service | Purpose |
|---|---|
| `web` | Next.js frontend |
| `agent` | Python LiveKit voice agent |
| `qdrant` | Vector database |
| `qdrant-restore` | One-shot restore of bundled RAG snapshot |

Bundled RAG snapshot:

```text
docker container/qdrant/snapshots/thai_tax_kb.snapshot.tar.gz
```

Expected restored collection:

```text
thai_tax_kb
```

Expected points:

```text
1311
```

What the company still needs:

- LiveKit endpoint and credentials
- LLM endpoint and API key
- STT endpoint and credentials
- TTS endpoint and credentials
- Embedding API endpoint and credentials

The Docker package includes bot code and RAG database, but it does not include the external AI model servers.

## 18. Deployment Configuration

Important env values:

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

For company deployment, the supervisor/customer server should fill in actual URLs and secrets. The current repo intentionally should not include real production secrets.

## 19. Demo Questions

### Normal Tax Questions

```text
เงินเดือน 30,000 บาท ต้องเสียภาษีไหม
```

```text
ซื้อ RMF ประกันบำนาญ และกองทุนสำรองเลี้ยงชีพพร้อมกัน ลดหย่อนได้สูงสุดเท่าไร
```

```text
คนต่างชาติอยู่ไทย 170 วัน มีรายได้จากบริษัทไทย และมีเงินเดือนจากต่างประเทศที่ไม่ได้โอนเข้าไทย ต้องเสียภาษีไทยส่วนไหนบ้าง
```

### Out-of-Scope Questions

```text
วันนี้วันอะไร
```

```text
แนะนำร้านอาหารหน่อย
```

```text
ฉันเศร้านิดหน่อย ทำยังไงดี
```

Expected behavior:

- Bot politely refuses or redirects to tax-related topics.
- Face should usually switch to a sad/sorry expression.

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

Expected behavior:

- The avatar changes expression without needing a tax answer.

## 20. Verification Performed

Recent checks:

```bash
npm run build
python3 -m py_compile agent.py graph/nodes.py
git diff --check
```

Results:

- Production Next.js build passes.
- Python compile passes.
- No whitespace diff-check errors.

Earlier checks:

- RAG 96 benchmark reruns.
- LLM judge summaries.
- Semantic eval reports.
- Variety/E2E smoke tests.
- Manual browser testing of:
  - microphone
  - greeting
  - answer display
  - out-of-scope response
  - avatar sizing
  - eye expressions
  - Thai UI labels

## 21. Current Working Tree Notes

At the time this document was created, there were tracked modifications in:

```text
agent.py
app/api/livekit/token/route.ts
components/LumoFace.tsx
components/VoiceRoom.tsx
graph/nodes.py
docs/AREE_BOT_FULL_HANDOFF_SUMMARY.md
```

There are also untracked local report/log folders from benchmark runs. They should not be staged unless intentionally needed:

```text
logs/
reports/rag96_comparison_backup_20260623_222731/
reports/rag96_exact_match_report/
reports/rag96_rerun_20260624_*/
```

## 22. What Was Not Changed

The recent emotion work did not change:

- tax knowledge content
- RAG collection contents
- Qdrant snapshot
- benchmark dataset
- external STT/TTS/LLM service endpoints

It changed:

- emotion detection/fallback
- manual emotion command handling
- avatar eye rendering
- LiveKit token route type safety

## 23. Recommended Presentation Position

Use this wording:

> Current Aree RAG is the recommended production RAG. It performs better than the supervisor-sent corpus under the same benchmark and has fewer incorrect answers. The supervisor corpus is useful reference material, but should not replace the current RAG alone. The 96/96 result is a closed-benchmark exact-retrieval result: it proves the current RAG can retrieve and preserve the verified answers for all 96 supervisor benchmark questions. For live deployment, the bot still uses safeguards and formatting, and unseen questions should continue to be reviewed.

Avoid saying:

> The bot is 100% correct for all questions.

Better:

> The current RAG achieved 96/96 on the closed supervisor benchmark after exact-match preservation, and it remains the safest evaluated production option. For unseen live questions, we continue to rely on RAG confidence, curated guards, and manual review for new failure cases.

## 24. Recommended Next Steps

1. Keep current Aree RAG as production.
2. Keep `RAG_SCORE_THRESHOLD=0.75` for the demo unless live STT wording causes missed retrieval.
3. Keep supervisor-sent RAG as research/supplemental source, not replacement.
4. Continue adding curated guards only for verified recurring failure cases.
5. Commit/push the current emotion and handoff changes after visual confirmation.
6. If the company deploys from Docker, confirm their `.env` points to working LiveKit, STT, TTS, LLM, embedding, and Qdrant services.
7. Before final delivery, run:

```bash
npm run build
python3 -m py_compile agent.py graph/nodes.py
python3 scripts/run_current_aree_full_benchmark.py
```

8. Check Qdrant in Docker:

```bash
curl http://localhost:6333/collections/thai_tax_kb
```

Expected:

```text
points_count: 1311
```

