"""Is RAG_SCORE_THRESHOLD (0.75) rejecting answerable questions? Measured: yes — but it
cannot be lowered.

HANDOFF.md listed "RAG_SCORE_THRESHOLD = 0.75 is untested" as an open item, with several
failures sitting at 0.55-0.67 and the suggestion that lowering it might rescue them. This
script answers that, and the answer is NO. Run it before anyone proposes the change again.

    QDRANT_URL=http://localhost:6333 PYTHONIOENCODING=utf-8 python scripts/threshold_sweep.py

Method: three populations that must move in different directions.
  RESCUE   turns the harness fails on, which SHOULD retrieve
  GUARD    off-topic and off-corpus questions, which MUST NOT retrieve
  CONTROL  core tax questions, which must keep working at any threshold

Measured 2026-09-10 against the live 1311-point index:

  RESCUE   ต้องยื่นแบบไหน 0.7223 · แล้วถ้าอายุเกิน 65 ล่ะ 0.7302 · แล้วถ้ามีลูก 2 คนล่ะ 0.7335
  GUARD    ควรซื้อกองทุนรวมตัวไหนดี 0.7221 · จดทะเบียนสมรสใช้เอกสารอะไร 0.7241 ·
           แล้วถ้าอยากซื้อคอนโดล่ะ 0.7248 · ค่าจ้างขั้นต่ำปีนี้เท่าไหร่ 0.7404 ·
           ธนาคารไหนให้ดอกเบี้ยเงินฝากสูงสุด 0.7439

The two populations INTERLEAVE, and two guards score higher than every rescue. No
threshold separates them, so lowering the gate buys three rescued turns and admits
banking/insurance/registry questions the three-way separation exists to keep out.
**Leave RAG_SCORE_THRESHOLD at 0.75.**

RESOLVED — the three turns are fixed WITHOUT touching the gate. This script's own
verdict line now reads, at the unchanged 0.75:

    0.75: rescued 3/3  control 5/5  new leaks 0  SAFE
    0.73: rescued 3/3  control 5/5  new leaks 2  LEAKS [ค่าจ้างขั้นต่ำ, ธนาคารไหน...]

which is the whole argument in two lines: the rescues are available at 0.75, and every
lower setting still leaks. What made that possible is a signal the gate never saw —
`retriever._should_rescue_low_score()` consults the LEXICAL score (computed after the
gate, so previously thrown away) plus explicit tax vocabulary above a 0.72 floor. See the
comment block there for the measured cut points, and `graph.nodes._fast_route` for the
provider-recommendation rejection that handles the adjacent-domain half.

Caveat when reading the output: this script calls `retrieve_with_sources` directly and
therefore SKIPS routing. `ประกันชีวิตบริษัทไหนดีที่สุด` still shows as a leak here, but in
the real path `_fast_route` rejects it as a provider-recommendation question before
retrieval runs. `ประกันสังคมจ่ายเดือนละเท่าไหร่` (0.7588) is a genuine remaining leak: it
clears the gate outright on the opener-widened candidate, and it is borderline anyway —
RD does answer about ประกันสังคมลดหย่อน, just not about contribution rates.

Previously noted here and now fixed: `VAT คิดกี่เปอร์เซ็นต์` scored 0.6811 and retrieved
nothing. It reaches 0.7655 via the English-term alias (HANDOFF.md §3e Fix 18), which is
why CONTROL is now 5/5 rather than 4/5.
"""
import asyncio
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(_REPO, ".env"))
# Root .env points at 8102, which is inside a Windows reserved range; host-side scripts
# must override it. Same trap as scripts/multiturn_benchmark.py.
os.environ["QDRANT_URL"] = os.environ.get("QDRANT_URL_OVERRIDE") or "http://localhost:6333"

from graph import retriever as R  # noqa: E402
from graph.nodes import build_retrieval_candidates  # noqa: E402


def _hist(*pairs):
    msgs = []
    for q, a in pairs:
        msgs += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
    return msgs


CHILD_A = "ลดหย่อนบุตรได้คนละ 30,000 บาท สูงสุดไม่เกิน 3 คน"
SALARY_A = "เงินเดือน 100,000 บาท ต้องเสียภาษีประมาณ 115,000 บาทต่อปี"
INCOME_A = "เงินได้สุทธิเกิน 150,000 บาทต่อปี เริ่มเสียภาษี"

RESCUE = [
    ("แล้วถ้าอายุเกิน 65 ล่ะ",
     _hist(("ถ้าเงินเดือน 100,000 บาทต้องจ่ายภาษีปีละเท่าไหร่", SALARY_A),
           ("แล้วถ้ามีลูก 3 คนล่ะ", CHILD_A))),
    ("ต้องยื่นแบบไหน",
     _hist(("ถ้าเงินเดือน 100,000 บาทต้องจ่ายภาษีปีละเท่าไหร่", SALARY_A),
           ("แล้วถ้ามีลูก 3 คนล่ะ", CHILD_A))),
    ("แล้วถ้ามีลูก 2 คนล่ะ",
     _hist(("เงินได้เท่าไหร่ต้องเริ่มเสียภาษี", INCOME_A),
           ("วันนี้อากาศเป็นยังไง", "หนูตอบได้เฉพาะเรื่องภาษีค่ะ"))),
]

GUARD = [
    # from v2 — the two that define the ceiling
    ("ราคาทองวันนี้เท่าไหร่", _hist(("ลดหย่อนบุตรได้เท่าไหร่", CHILD_A))),
    ("ภาษีคาร์บอนเครดิตฟาร์มกุ้งคำนวณยังไง", _hist(("ลดหย่อนบุตรได้เท่าไหร่", CHILD_A))),
    ("วันนี้อากาศเป็นยังไง", _hist(("เงินได้เท่าไหร่ต้องเริ่มเสียภาษี", INCOME_A))),
    # tax-ADJACENT: high-scoring but outside what Aree should answer
    ("ธนาคารไหนให้ดอกเบี้ยเงินฝากสูงสุด", _hist(("ลดหย่อนบุตรได้เท่าไหร่", CHILD_A))),
    ("ควรซื้อกองทุนรวมตัวไหนดี", _hist(("ลดหย่อนบุตรได้เท่าไหร่", CHILD_A))),
    ("ประกันชีวิตบริษัทไหนดีที่สุด", _hist(("ลดหย่อนบุตรได้เท่าไหร่", CHILD_A))),
    ("ค่าจ้างขั้นต่ำปีนี้เท่าไหร่", _hist(("เงินได้เท่าไหร่ต้องเริ่มเสียภาษี", INCOME_A))),
    ("ประกันสังคมจ่ายเดือนละเท่าไหร่", _hist(("เงินได้เท่าไหร่ต้องเริ่มเสียภาษี", INCOME_A))),
    ("จดทะเบียนสมรสใช้เอกสารอะไร", _hist(("ลดหย่อนบุตรได้เท่าไหร่", CHILD_A))),
    ("อยากลาออกจากงานต้องบอกล่วงหน้ากี่วัน", _hist(("ลดหย่อนบุตรได้เท่าไหร่", CHILD_A))),
    ("ทำพาสปอร์ตใช้เวลากี่วัน", _hist(("ลดหย่อนบุตรได้เท่าไหร่", CHILD_A))),
    ("แล้วถ้าอยากซื้อคอนโดล่ะ ราคาประมาณเท่าไหร่", _hist(("ลดหย่อนบุตรได้เท่าไหร่", CHILD_A))),
]

CONTROL = [
    ("ลดหย่อนบุตรได้เท่าไหร่", []),
    ("เงินได้เท่าไหร่ต้องเริ่มเสียภาษี", []),
    ("ภ.ง.ด.90 คืออะไร", []),
    ("ขอคืนภาษีต้องทำยังไง", []),
    ("VAT คิดกี่เปอร์เซ็นต์", []),
]

THRESHOLDS = ["0.75", "0.73", "0.72", "0.715", "0.71", "0.705", "0.70"]


async def best_score(q, msgs):
    best = 0.0
    for cand, _allow in build_retrieval_candidates(q, msgs):
        vector = R._get_embedding_cached(cand)
        resp = await R._get_qdrant().query_points(
            collection_name=os.environ["QDRANT_COLLECTION"], query=vector,
            using=os.environ.get("QDRANT_VECTOR_NAME", "dense"),
            limit=int(os.getenv("RAG_TOP_K", "3")), with_payload=False)
        if resp.points:
            best = max(best, float(resp.points[0].score))
    return best


async def chars_at(q, msgs):
    for cand, allow in build_retrieval_candidates(q, msgs):
        text, _ = await R.retrieve_with_sources(cand, allow_low_score_rescue=allow)
        if (text or "").strip():
            return len(text)
    return 0


async def main():
    print("=== best dense score per query ===")
    for group, items in (("RESCUE", RESCUE), ("GUARD", GUARD), ("CONTROL", CONTROL)):
        print(f"\n-- {group} --")
        for q, m in items:
            print(f"  {await best_score(q, m):.4f}  {q[:48]}")

    rows = {}
    for th in THRESHOLDS:
        os.environ["RAG_SCORE_THRESHOLD"] = th
        for group, items in (("RESCUE", RESCUE), ("GUARD", GUARD), ("CONTROL", CONTROL)):
            for q, m in items:
                rows.setdefault((group, q), {})[th] = await chars_at(q, m)

    print("\n=== verdict (leaks counted as NEW vs the 0.75 baseline) ===")
    base_leaks = {q for (g, q), v in rows.items() if g == "GUARD" and v["0.75"] > 0}
    print(f"pre-existing leaks at 0.75: {sorted(base_leaks) or 'none'}\n")
    for th in THRESHOLDS:
        r = sum(1 for (g, _), v in rows.items() if g == "RESCUE" and v[th] > 0)
        new = sorted(q for (g, q), v in rows.items()
                     if g == "GUARD" and v[th] > 0 and q not in base_leaks)
        c = sum(1 for (g, _), v in rows.items() if g == "CONTROL" and v[th] > 0)
        tag = "SAFE " if not new and r else ("LEAKS" if new else "     ")
        print(f"  {th:>6}: rescued {r}/{len(RESCUE)}  control {c}/{len(CONTROL)}  "
              f"new leaks {len(new)}  {tag} {new if new else ''}")


asyncio.run(main())
