"""Multi-turn conversation benchmark for the Aree voicebot.

Why this exists: multi-turn behaviour is a stack of calibrations — a 10-turn window,
a 3-sentence summary, a 40-character follow-up ceiling, a 17-entry anaphora list —
that were each tuned against a handful of hand-picked pairs with nothing to catch a
regression. This is the measuring instrument. Build it first, take a baseline, then
land one change at a time and read the delta.

It drives the SAME memory code the agent runs (`graph.conversation`, extracted for
exactly this reason) and the SAME classifier the agent runs (`compiled_graph`, entered
at `parallel_node`). It deliberately does NOT pre-set `route` — `CLAUDE.md` warns that
doing so bypasses the classifier, which is how the Fix 9 misrouting bug stayed hidden.

Assertions are on ROUTING and RETRIEVAL, never on answer text. Answer text is recorded
in the JSON for human review but is far too noisy to gate on.

Usage:
    python scripts/multiturn_benchmark.py --stage s0-baseline
    python scripts/multiturn_benchmark.py --stage s1 --baseline reports/multiturn/s0-baseline.json
    python scripts/multiturn_benchmark.py --mode replay --transcript reports/multiturn/s0-baseline.json

Requires Qdrant and the embedding/LLM endpoints. Qdrant defaults to localhost:6333
because the root .env points at 8102, which sits inside a Windows reserved port range.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REQUIRED_ENV = (
    "QDRANT_URL",
    "QDRANT_COLLECTION",
    "EMBEDDING_BASE_URL",
    "EMBEDDING_API_KEY",
    "EMBEDDING_MODEL",
    "LLM_BASE_URL",
    "LLM_API_KEY",
)


# --- fixture --------------------------------------------------------------------
#
# Ten conversations, ~40 turns. Each exists to hold down a specific defect or a
# specific regression risk; a conversation that cannot fail tells you nothing.
#
# Per-turn keys:
#   q                  the question
#   expect_route       "rag" | "direct" | "curated" | "out_of_scope"
#   expect_retrieval   True if this turn should retrieve non-empty context
#   expect_clusters_any  any-of match against the returned sources' cluster_id
#   expect_widened     whether build_retrieval_query SHOULD widen this query
#   carry_facts        strings that must still be visible in what memory hands the graph
#   drop_memory        simulate a page reload before this turn (defect 1)
#
# `expect_widened` and `carry_facts` express DESIRED behaviour, so several turns are
# expected to fail at baseline. That is the point.

# Verified against the live 1311-point index: this exact question returns these three
# chunks. Any-of, not all-of — retrieval is a top-3 over a fused ranking, so demanding
# an exact set would make the harness brittle without adding signal.
# First line of NO_SOURCE_ANSWER; used to tell an abstain apart from a curated answer.
_NO_SOURCE_KEY = "ขออภัยค่ะ ตอนนี้ยังไม่มีข้อมูลเพียงพอ"

ANCHOR_CHILD_DEDUCTION = ["CALLCENTER-116", "CALLCENTER-34", "CALLCENTER-112"]

CONVERSATIONS = [
    {
        "id": "salary_chain",
        "tags": ["anaphora", "numeric_carry"],
        "why": "The documented salary -> children -> age chain. Turn 0 is CURATED "
               "(find_curated_answer handles the calculator), so the follow-ups widen "
               "with a question that has no chunk behind it — measured 0 chars. "
               "t3 'ต้องยื่นแบบไหน' scores 0.7223 dense, just under RAG_SCORE_THRESHOLD, "
               "and used to abstain. NOW PASSES via the on-topic rescue in "
               "retriever._should_rescue_low_score (tax vocabulary + a 0.72 floor), not "
               "by lowering the gate — see scripts/threshold_sweep.py for why the gate "
               "itself must stay at 0.75.",
        "turns": [
            {"q": "ถ้าเงินเดือน 100,000 บาทต้องจ่ายภาษีปีละเท่าไหร่",
             "expect_route": "curated", "expect_retrieval": False},
            {"q": "แล้วถ้ามีลูก 3 คนล่ะ",
             "expect_route": "rag", "expect_retrieval": True,
             "expect_widened": True, "carry_facts": ["100,000"]},
            {"q": "แล้วถ้าอายุเกิน 65 ล่ะ",
             "expect_route": "rag", "expect_retrieval": True,
             "expect_widened": True, "carry_facts": ["100,000"]},
            {"q": "ต้องยื่นแบบไหน",
             "expect_route": "rag", "expect_retrieval": True},
        ],
    },
    {
        "id": "answer_carry",
        "tags": ["anaphora", "answer_antecedent"],
        "why": "Antecedent lives in the ANSWER, not the previous question — "
               "_last_user_question never consults assistant turns.",
        "turns": [
            {"q": "เงินเดือน 50,000 บาท คำนวณภาษีให้หน่อย",
             "expect_route": "curated", "expect_retrieval": False},
            {"q": "ลดหย่อนอะไรได้บ้าง",
             "expect_route": "rag", "expect_retrieval": True},
            {"q": "แล้วถ้าซื้อประกันชีวิตด้วยล่ะ",
             "expect_route": "rag", "expect_retrieval": True,
             "expect_widened": True, "carry_facts": ["50,000"]},
        ],
    },
    {
        "id": "deduction_chain",
        "tags": ["anaphora"],
        "why": "Deduction-limit chain. Turn 0 is CURATED, so this is a second "
               "instance of the follow-up-after-curated failure.",
        "turns": [
            {"q": "ประกันชีวิตลดหย่อนได้เท่าไหร่",
             "expect_route": "curated", "expect_retrieval": False},
            {"q": "แล้วถ้าซื้อ 2 กรมธรรม์ล่ะ",
             "expect_route": "rag", "expect_retrieval": True, "expect_widened": True},
            {"q": "ประกันสุขภาพล่ะ",
             "expect_route": "rag", "expect_retrieval": True, "expect_widened": True},
            {"q": "รวมกันแล้วลดหย่อนได้สูงสุดเท่าไหร่",
             "expect_route": "rag", "expect_retrieval": True},
        ],
    },
    {
        "id": "form_code_chain",
        "tags": ["exact_match", "must_not_widen"],
        "why": "Form codes take the lexical-first [EXACT_MATCH] path. Widening them "
               "pollutes that path — build_retrieval_query must leave them alone.",
        "turns": [
            {"q": "ภ.ง.ด.90 คืออะไร",
             "expect_route": "rag", "expect_retrieval": True, "expect_widened": False},
            {"q": "ภ.ง.ด.91 ล่ะ",
             "expect_route": "rag", "expect_retrieval": True, "expect_widened": False},
            {"q": "สองแบบนี้ต่างกันยังไง",
             "expect_route": "rag", "expect_retrieval": True},
        ],
    },
    {
        "id": "topic_switch",
        "tags": ["must_not_widen"],
        "why": "Turn 3 is a NEW self-contained topic. Guards against over-widening "
               "when Stage 6 loosens the trigger.",
        "turns": [
            {"q": "ลดหย่อนบุตรได้เท่าไหร่",
             "expect_route": "rag", "expect_retrieval": True,
             "expect_clusters_any": ANCHOR_CHILD_DEDUCTION},
            {"q": "แล้วถ้ามีลูก 3 คนล่ะ",
             "expect_route": "rag", "expect_retrieval": True, "expect_widened": True},
            {"q": "ภาษีมูลค่าเพิ่มคิดกี่เปอร์เซ็นต์",
             "expect_route": "rag", "expect_retrieval": True, "expect_widened": False},
            {"q": "ใครต้องจดทะเบียนภาษีมูลค่าเพิ่มบ้าง",
             "expect_route": "rag", "expect_retrieval": True, "expect_widened": False},
        ],
    },
    {
        "id": "scope_bounce",
        "tags": ["routing", "three_way"],
        "why": "tax -> out_of_scope -> back to tax. Guards the Fix 9 / Fix 10 "
               "three-way separation, which memory-layer changes can silently break. "
               "t2 scores 0.7335 dense — below the 0.75 gate but above every threshold "
               "that keeps off-topic questions out, so it used to abstain. NOW PASSES "
               "via the lexical rescue (its own words are in the corpus), which is a "
               "signal the dense gate never sees; see scripts/threshold_sweep.py.",
        "turns": [
            {"q": "เงินได้เท่าไหร่ต้องเริ่มเสียภาษี",
             "expect_route": "rag", "expect_retrieval": True},
            {"q": "วันนี้อากาศเป็นยังไง",
             "expect_route": "out_of_scope", "expect_retrieval": False},
            {"q": "แล้วถ้ามีลูก 2 คนล่ะ",
             "expect_route": "rag", "expect_retrieval": True, "expect_widened": True},
            {"q": "ขอบคุณครับ",
             "expect_route": "direct", "expect_retrieval": False},
        ],
    },
    {
        "id": "long_followup",
        "tags": ["anaphora", "char_cliff"],
        "why": "Turn 3 is anaphoric but longer than _FOLLOWUP_MAX_CHARS (40), so it is "
               "not widened today. EXPECTED TO FAIL AT BASELINE — Stage 6a target.",
        "turns": [
            {"q": "ลดหย่อนบุตรได้เท่าไหร่",
             "expect_route": "rag", "expect_retrieval": True,
             "expect_clusters_any": ANCHOR_CHILD_DEDUCTION},
            {"q": "แล้วถ้ามีลูก 3 คนล่ะ",
             "expect_route": "rag", "expect_retrieval": True, "expect_widened": True},
            # Measured: retrieves 3729 chars BARE. The 40-char cliff is not hurting
            # this question, so asserting expect_widened here would encode a wish the
            # data contradicts. Retrieval success is what matters.
            {"q": "แล้วถ้ากรณีแบบนั้นแต่ยื่นรวมกับคู่สมรสจะต่างกันไหมครับ",
             "expect_route": "rag", "expect_retrieval": True},
        ],
    },
    {
        "id": "markerless_coref",
        "tags": ["anaphora", "markerless"],
        "why": "Coreference with NO _ANAPHORA_MARKERS hit. EXPECTED TO FAIL AT "
               "BASELINE — the marker list cannot see these. Stage 6b target.",
        "turns": [
            {"q": "ลดหย่อนบุตรได้เท่าไหร่",
             "expect_route": "rag", "expect_retrieval": True,
             "expect_clusters_any": ANCHOR_CHILD_DEDUCTION},
            # t1 fails on ROUTING (_fast_route sends it to out_of_scope, so retrieve_node
            # never runs and the candidate cascade cannot help) — Stage 6b target.
            # t2 was 0 chars at baseline and is rescued by the cascade.
            {"q": "ต้องใช้เอกสารอะไรบ้าง",
             "expect_route": "rag", "expect_retrieval": True},
            {"q": "ยื่นได้ถึงเมื่อไหร่",
             "expect_route": "rag", "expect_retrieval": True},
            {"q": "ยื่นออนไลน์ได้ไหม",
             "expect_route": "rag", "expect_retrieval": True},
        ],
    },
    {
        "id": "long_session",
        "tags": ["summarization", "window"],
        "why": "Long enough to trip summarization (MAX_WINDOW=10 turns). The last "
               "turns assert the opening salary figure survived compaction.",
        "turns": [
            {"q": "เงินเดือน 80,000 บาท ต้องเสียภาษีเท่าไหร่",
             "expect_route": "curated", "expect_retrieval": False},
            {"q": "ลดหย่อนส่วนตัวได้เท่าไหร่", "expect_route": "rag", "expect_retrieval": True},
            # Was "curated" — but the canned answer that took it was the LIFE/HEALTH insurance
            # one (it matched "ประกัน" inside ประกันสังคม), i.e. a wrong answer. Since the
            # canned-answer coverage guard (2026-09-14) it retrieves the real
            # "เงินสมทบประกันสังคมลดหย่อนภาษีได้ไหม" chunk instead.
            {"q": "ประกันสังคมลดหย่อนได้ไหม", "expect_route": "rag", "expect_retrieval": True},
            {"q": "กองทุนสำรองเลี้ยงชีพลดหย่อนได้เท่าไหร่", "expect_route": "curated", "expect_retrieval": False},
            {"q": "ดอกเบี้ยบ้านลดหย่อนได้เท่าไหร่", "expect_route": "curated", "expect_retrieval": False},
            {"q": "บริจาคลดหย่อนได้เท่าไหร่", "expect_route": "rag", "expect_retrieval": True},
            {"q": "ค่าฝากครรภ์ลดหย่อนได้ไหม", "expect_route": "rag", "expect_retrieval": True},
            {"q": "เบี้ยประกันสุขภาพพ่อแม่ลดหย่อนได้ไหม", "expect_route": "curated", "expect_retrieval": False},
            {"q": "ซื้อกองทุน RMF ลดหย่อนได้เท่าไหร่", "expect_route": "curated", "expect_retrieval": False},
            {"q": "กองทุน SSF ลดหย่อนได้เท่าไหร่", "expect_route": "rag", "expect_retrieval": True},
            {"q": "ยื่นภาษีออนไลน์ทำยังไง", "expect_route": "rag", "expect_retrieval": True},
            {"q": "แล้วเงินเดือนที่บอกไปตอนแรกต้องเสียเท่าไหร่",
             "expect_route": "rag", "expect_retrieval": True, "carry_facts": ["80,000"]},
        ],
    },
    {
        "id": "unanswerable_guard",
        "tags": ["abstain", "must_not_retrieve"],
        "why": "The candidate cascade must NOT manufacture context for a question the "
               "corpus cannot answer. Abstaining is correct here — _no_source_response() "
               "exists to stop the generator answering from model knowledge.",
        "turns": [
            {"q": "ลดหย่อนบุตรได้เท่าไหร่",
             "expect_route": "rag", "expect_retrieval": True,
             "expect_clusters_any": ANCHOR_CHILD_DEDUCTION},
            {"q": "ภาษีคาร์บอนเครดิตฟาร์มกุ้งคำนวณยังไง",
             "expect_route": "curated", "expect_retrieval": False},
            {"q": "แล้วถ้าฟาร์มกุ้งคาร์บอนเครดิตล่ะ",
             "expect_route": "curated", "expect_retrieval": False},
        ],
    },
    {
        "id": "formcode_opener_guard",
        "tags": ["abstain", "must_not_retrieve", "borrowed_code"],
        "why": "unanswerable_guard with a FORM-CODE opener. The retriever's exact-code "
               "shortcut runs before the score gate, and cascade candidate 4 appends the "
               "opener — so a borrowed 'ภ.ง.ด.90' used to answer the shrimp-farm question "
               "with 471 chars of ภ.ง.ด.90. Found by the 2026-09-11 browser regression pass; "
               "unanswerable_guard could not see it because its opener has no form code.",
        "turns": [
            {"q": "ภ.ง.ด.90 คืออะไร", "expect_route": "rag", "expect_retrieval": True},
            {"q": "ภาษีคาร์บอนเครดิตฟาร์มกุ้งคำนวณยังไง",
             "expect_route": "curated", "expect_retrieval": False},
        ],
    },
    {
        "id": "unlisted_followups",
        "tags": ["followup_classifier", "markerless", "guard"],
        "why": "Follow-ups phrased outside every keyword list (defect #6). Without the LLM "
               "follow-up classifier t1 and t5 route out_of_scope ('outside our scope' "
               "mid-conversation). t2/t3 are the guards the classifier must not rescue: an "
               "off-topic question and a provider recommendation with a 'ล่ะ' on it (the "
               "latter was rescued to rag by the keyword path until 2026-09-14).",
        "turns": [
            {"q": "ลดหย่อนบุตรได้เท่าไหร่", "expect_route": "rag", "expect_retrieval": True,
             "expect_clusters_any": ANCHOR_CHILD_DEDUCTION},
            {"q": "สูงสุดกี่คน", "expect_route": "rag", "expect_retrieval": True},
            {"q": "วันนี้อากาศเป็นยังไง", "expect_route": "out_of_scope", "expect_retrieval": False},
            {"q": "แล้วธนาคารไหนดอกเบี้ยสูงสุดล่ะ",
             "expect_route": "out_of_scope", "expect_retrieval": False},
            {"q": "ภ.ง.ด.90 คืออะไร", "expect_route": "rag", "expect_retrieval": True},
            {"q": "ใครต้องใช้บ้าง", "expect_route": "rag", "expect_retrieval": True},
        ],
    },
    {
        "id": "reconnect",
        "tags": ["persistence"],
        "why": "Simulates a page reload mid-conversation. EXPECTED TO FAIL AT "
               "BASELINE — memory is per-job today, so the reload wipes it. Stage 4 target.",
        "turns": [
            {"q": "เงินเดือน 60,000 บาท ต้องเสียภาษีเท่าไหร่",
             "expect_route": "curated", "expect_retrieval": False},
            {"q": "ลดหย่อนบุตรได้เท่าไหร่", "expect_route": "rag", "expect_retrieval": True},
            {"q": "แล้วถ้ามีลูก 2 คนล่ะ",
             "expect_route": "rag", "expect_retrieval": True, "expect_widened": True},
            {"q": "แล้วถ้าอายุเกิน 65 ล่ะ", "drop_memory": True,
             "expect_route": "rag", "expect_retrieval": True,
             "expect_widened": True, "carry_facts": ["60,000"]},
            {"q": "ต้องยื่นแบบไหน", "expect_route": "rag", "expect_retrieval": True},
        ],
    },
]


# --- environment ----------------------------------------------------------------

def _validate_env() -> None:
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        raise SystemExit(
            "Missing required environment variables: " + ", ".join(missing) +
            "\nCreate/update .env first, then rerun."
        )


def _apply_qdrant_default(explicit: str | None) -> None:
    """Point at the locally published Qdrant unless told otherwise.

    Root .env says 8102, which is inside a Windows reserved range (2970-3069 etc.
    shift over time). docker-compose.local.yml publishes 6333 for exactly this
    reason. Bake the default in rather than making every future run remember it.
    """
    if explicit:
        os.environ["QDRANT_URL"] = explicit
        return
    if os.environ.get("QDRANT_URL", "").endswith(":8102"):
        os.environ["QDRANT_URL"] = "http://localhost:6333"


# --- driving one turn -----------------------------------------------------------

async def run_turn(turn: dict, memory: dict, *, mode: str, pinned_answer: str | None):
    """Run one turn through the real classifier and record what happened."""
    from graph.conversation import append_turn, build_messages_for_graph
    from graph.nodes import NO_SOURCE_ANSWER, build_retrieval_query

    question = turn["q"]
    messages = build_messages_for_graph(memory)
    history_chars = sum(len(m.get("content", "")) for m in messages)

    # Pure function, no network: tells us whether widening WOULD fire for this turn.
    retrieval_query = build_retrieval_query(question, messages)
    widened = retrieval_query.strip() != question.strip()

    # carry_facts is asserted against what memory hands the graph, which is the only
    # place the summary's fidelity is observable.
    flattened = "".join(m.get("content", "") for m in messages)

    state = {
        "messages": messages,
        "query": question,
        "context": "",
        "answer": "",
        "emotion": "idle",
        # Default field value, NOT a pre-set route: parallel_node overwrites it
        # unconditionally, so the whole classifier chain still runs.
        "route": "direct",
    }

    started = time.perf_counter()
    if mode == "replay":
        from graph.nodes import parallel_node
        result = dict(state)
        result.update(await parallel_node(state))
        answer = pinned_answer if pinned_answer is not None else result.get("answer", "")
    else:
        from graph.graph import compiled_graph
        result = await compiled_graph.ainvoke(state)
        answer = result.get("answer", "")
    elapsed_ms = (time.perf_counter() - started) * 1000

    # `route == "curated"` is ambiguous on its own: it is either a real
    # find_curated_answer() hit (a good answer) or _no_source_response() giving up.
    # Those are opposite outcomes, so every delta is unreadable without this split.
    no_source = _NO_SOURCE_KEY in (answer or "")

    context = (result.get("context") or "").strip()
    sources = result.get("sources") or []
    cluster_ids = [s.get("cluster_id", "") for s in sources if isinstance(s, dict)]

    checks = {}
    if "expect_route" in turn:
        checks["route"] = (result.get("route") == turn["expect_route"])
    if "expect_retrieval" in turn:
        checks["retrieval"] = (bool(context) == turn["expect_retrieval"])
    if "expect_clusters_any" in turn:
        checks["clusters"] = bool(set(cluster_ids) & set(turn["expect_clusters_any"]))
    if "expect_widened" in turn:
        checks["widened"] = (widened == turn["expect_widened"])
    if "carry_facts" in turn:
        checks["carry"] = all(fact in flattened for fact in turn["carry_facts"])

    append_turn(memory, question, spoken=answer, detail=answer)

    return {
        "q": question,
        "route": result.get("route"),
        "no_source": no_source,
        "context_chars": len(context),
        "cluster_ids": cluster_ids,
        "widened": widened,
        "retrieval_query": retrieval_query if widened else "",
        "history_chars": history_chars,
        "elapsed_ms": round(elapsed_ms),
        "answer": answer,
        "checks": checks,
        "passed": all(checks.values()) if checks else True,
    }


async def run_conversation(conv: dict, *, mode: str, transcript: dict | None):
    from graph.conversation import maybe_summarize, new_memory
    from graph.conversation_store import (
        delete_conversation,
        load_conversation,
        save_conversation,
    )

    # Mirror the agent exactly: it persists after every recorded turn and loads on join.
    # The conversation id stands in for the per-user room key.
    key = conv["id"]
    delete_conversation(key)          # each run starts clean
    memory = new_memory()
    turns_out = []
    for index, turn in enumerate(conv["turns"]):
        if turn.get("drop_memory"):
            # A page reload. Before Stage 1 this meant a brand-new job and an empty
            # memory; now the agent reloads from the store, so the harness does too.
            memory = load_conversation(key)

        pinned = None
        if transcript:
            pinned = transcript.get(conv["id"], {}).get(str(index))

        record = await run_turn(turn, memory, mode=mode, pinned_answer=pinned)
        record["index"] = index
        record["dropped_memory"] = bool(turn.get("drop_memory"))
        turns_out.append(record)

        status = "PASS" if record["passed"] else "FAIL"
        failed = [k for k, v in record["checks"].items() if not v]
        detail = f"  [{','.join(failed)}]" if failed else ""
        print(
            f"  {status}  t{index} {('no_source' if record['no_source'] else record['route']) or '-':<13}"
            f" ctx={record['context_chars']:>5}"
            f" hist={record['history_chars']:>5}"
            f" widen={'Y' if record['widened'] else 'n'}"
            f"  {turn['q'][:42]}{detail}"
        )

        # Mirror production: persist, then attempt summarization, then persist again
        # so the stored copy reflects any compaction (agent.py does the same).
        save_conversation(key, memory)
        await maybe_summarize(memory)
        save_conversation(key, memory)

    return turns_out


# --- metrics --------------------------------------------------------------------

def summarize(results: list[dict]) -> dict:
    def rate(key: str) -> dict:
        considered = [t for c in results for t in c["turns"] if key in t["checks"]]
        passed = [t for t in considered if t["checks"][key]]
        return {
            "passed": len(passed),
            "total": len(considered),
            "rate": round(len(passed) / len(considered), 3) if considered else None,
        }

    all_turns = [t for c in results for t in c["turns"]]
    hist = [t["history_chars"] for t in all_turns]
    return {
        "route_match": rate("route"),
        "retrieval_match": rate("retrieval"),
        "cluster_hit": rate("clusters"),
        "widen_match": rate("widened"),
        "fact_retention": rate("carry"),
        "no_source_turns": sum(1 for t in all_turns if t.get("no_source")),
        "turns_total": len(all_turns),
        "turns_passed": sum(1 for t in all_turns if t["passed"]),
        "history_chars_median": int(statistics.median(hist)) if hist else 0,
        "history_chars_max": max(hist) if hist else 0,
        "elapsed_ms_median": int(statistics.median(t["elapsed_ms"] for t in all_turns)) if all_turns else 0,
    }


def print_metrics(metrics: dict, baseline: dict | None) -> None:
    print("\n" + "=" * 72)
    print(f"{'metric':<22}{'value':>16}{'baseline':>16}{'delta':>16}")
    print("-" * 72)

    def line(label, value, base, fmt=lambda v: f"{v}"):
        if base is None:
            print(f"{label:<22}{fmt(value):>16}{'-':>16}{'-':>16}")
            return
        try:
            delta = value - base
            arrow = "+" if delta > 0 else ""
            print(f"{label:<22}{fmt(value):>16}{fmt(base):>16}{arrow + fmt(delta):>16}")
        except TypeError:
            print(f"{label:<22}{fmt(value):>16}{fmt(base):>16}{'-':>16}")

    for key in ("route_match", "retrieval_match", "cluster_hit", "widen_match", "fact_retention"):
        entry = metrics[key]
        base_entry = (baseline or {}).get(key)
        shown = f"{entry['rate']} ({entry['passed']}/{entry['total']})" if entry["total"] else "n/a"
        base_shown = ""
        if base_entry and base_entry["total"]:
            base_shown = f"{base_entry['rate']}"
        print(f"{key:<22}{shown:>16}{base_shown or '-':>16}"
              f"{_delta(entry, base_entry):>16}")

    line("no_source_turns", metrics["no_source_turns"], (baseline or {}).get("no_source_turns"))
    line("turns_passed", metrics["turns_passed"], (baseline or {}).get("turns_passed"))
    line("history_chars_median", metrics["history_chars_median"], (baseline or {}).get("history_chars_median"))
    line("history_chars_max", metrics["history_chars_max"], (baseline or {}).get("history_chars_max"))
    line("elapsed_ms_median", metrics["elapsed_ms_median"], (baseline or {}).get("elapsed_ms_median"))
    print("=" * 72)


def _delta(entry: dict, base_entry: dict | None) -> str:
    if not base_entry or entry["rate"] is None or base_entry.get("rate") is None:
        return "-"
    diff = round(entry["rate"] - base_entry["rate"], 3)
    return f"+{diff}" if diff > 0 else f"{diff}"


# --- main -----------------------------------------------------------------------

async def main_async(args) -> int:
    transcript = None
    if args.transcript:
        raw = json.loads(Path(args.transcript).read_text(encoding="utf-8"))
        transcript = {
            c["id"]: {str(t["index"]): t["answer"] for t in c["turns"]}
            for c in raw.get("conversations", [])
        }
        print(f"replaying pinned answers from {args.transcript}")

    selected = CONVERSATIONS
    if args.only:
        wanted = {name.strip() for name in args.only.split(",")}
        selected = [c for c in CONVERSATIONS if c["id"] in wanted]
        if not selected:
            raise SystemExit(f"no conversations matched --only {args.only}")

    results = []
    for conv in selected:
        print(f"\n[{conv['id']}] {conv['why']}")
        turns = await run_conversation(conv, mode=args.mode, transcript=transcript)
        results.append({
            "id": conv["id"],
            "tags": conv.get("tags", []),
            "why": conv.get("why", ""),
            "turns": turns,
            "passed": all(t["passed"] for t in turns),
        })

    metrics = summarize(results)

    baseline = None
    if args.baseline:
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8")).get("metrics")
    print_metrics(metrics, baseline)

    out_dir = ROOT / "reports" / "multiturn"
    out_dir.mkdir(parents=True, exist_ok=True)
    # A --only run covers a subset, so it must never overwrite a full report of the
    # same name — doing exactly that silently destroyed a reference baseline once and
    # produced a nonsense delta table on the next stage.
    suffix = "" if not args.only else "-only"
    out_path = out_dir / f"{args.stage}{suffix}.json"
    out_path.write_text(json.dumps({
        "run": {
            "stage": args.stage,
            "mode": args.mode,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "qdrant_url": os.environ.get("QDRANT_URL"),
            "collection": os.environ.get("QDRANT_COLLECTION"),
        },
        "metrics": metrics,
        "conversations": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {out_path.relative_to(ROOT)}")

    failed = [c["id"] for c in results if not c["passed"]]
    if failed:
        print(f"conversations with failures: {', '.join(failed)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Multi-turn conversation benchmark.")
    parser.add_argument("--stage", default="adhoc", help="label for the output report")
    parser.add_argument("--mode", choices=("full", "replay"), default="full",
                        help="full runs the whole graph; replay runs routing/retrieval "
                             "only and reuses pinned answers (deterministic, faster)")
    parser.add_argument("--transcript", help="report JSON to take pinned answers from (replay)")
    parser.add_argument("--baseline", help="report JSON to diff metrics against")
    parser.add_argument("--only", help="comma-separated conversation ids")
    parser.add_argument("--qdrant-url", help="override QDRANT_URL")
    args = parser.parse_args()

    if args.mode == "replay" and not args.transcript:
        raise SystemExit("--mode replay requires --transcript")

    # Thai output on a Windows console dies without this.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    load_dotenv(ROOT / ".env")
    # Isolated from the real store; reports/ is gitignored.
    os.environ.setdefault("MEMORY_DIR", str(ROOT / "reports" / "multiturn" / ".memory"))
    _apply_qdrant_default(args.qdrant_url)
    _validate_env()
    print(f"qdrant={os.environ['QDRANT_URL']} collection={os.environ['QDRANT_COLLECTION']}")

    # Sequential by design: latency.py's `tracker` is a process-wide singleton and
    # concurrent conversations would interleave its timings.
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
