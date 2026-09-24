"""Conversation memory for the multi-turn path.

This lives in ``graph/`` rather than ``agent.py`` on purpose: ``agent.py`` cannot be
imported without ``livekit`` installed, so an offline harness that wanted to exercise
multi-turn behaviour would have to reimplement the memory loop and would then drift
from what production actually runs. Keeping it here lets the agent and
``scripts/multiturn_benchmark.py`` drive the *same* code.

Nothing in this module reads the environment at import time, and it does not import
``agent``, so it is safe to import from anywhere in ``graph/``.
"""

from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger("nongaree-agent")

# Turns of raw history kept before compaction kicks in, and how many turns survive
# verbatim on the other side of it. Both are counted in TURNS; `history` holds two
# entries per turn (user + assistant), which is why the call sites double them.
MAX_WINDOW = 10
KEEP_RECENT = 2

_THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL)

# --- pinned user facts ----------------------------------------------------------
#
# Compaction keeps only KEEP_RECENT turns verbatim, so anything older survives only if
# the summary carries it. It did not: the summariser runs on ROUTER_MODEL (thaillm-8b)
# with max_tokens=200 and "ไม่เกิน 3 ประโยค", and an 8B model writing three sentences of
# Thai prose drops "80,000" most of the time. That is defect 2 in HANDOFF.md §3c, and it
# is why `fact_retention` is nondeterministic between runs.
#
# Prompting cannot make this reliable, so the numbers the USER stated are extracted
# mechanically and pinned onto the summary AFTER the LLM has written it. The model can
# no longer drop them. Only user turns are read: what the user told us about themselves
# (salary, dependants, age) is what a follow-up depends on, whereas numbers Aree said
# are re-derivable from the knowledge base.
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_LEAD_WORD_RE = re.compile(r"[ก-๙]+$")
_TRAIL_WORD_RE = re.compile(r"^([ก-๙]{1,4}|%)")
_PINNED_PREFIX = "ข้อมูลที่ผู้ใช้ระบุ: "
_MAX_PINNED_FACTS = 8

# Not every number is worth pinning, and the cap makes that matter: a conversation is
# full of incidental digits (form codes, "ข้อ 2", section numbers) and keeping the most
# RECENT eight would evict the salary stated in turn 1 — the one fact follow-ups
# actually depend on. So facts are ranked, not truncated by recency.
_SALIENT_UNITS = ("บาท", "คน", "ปี", "เดือน", "วัน", "%", "ครั้ง", "กรมธรรม์", "ราย")
_SALIENT_NOUNS = (
    "เงินเดือน", "รายได้", "รายรับ", "เงินได้", "โบนัส", "ค่าจ้าง", "กำไร", "ยอดขาย",
    "ลูก", "บุตร", "อายุ", "คู่สมรส", "ภรรยา", "สามี",
    "ลดหย่อน", "ประกัน", "เบี้ย", "กองทุน", "ดอกเบี้ย", "บริจาค", "ภาษี",
)


def _trailing_unit(text: str) -> str:
    """The unit right after a number.

    Thai does not put spaces between words, so a plain "1-6 Thai characters" match on
    "100,000 บาทต้องจ่าย" yields "บาทต้อ". Known units are therefore tried first, and the
    short generic match is only a fallback.
    """
    stripped = text.lstrip()
    for unit in _SALIENT_UNITS:
        if stripped.startswith(unit):
            return unit
    # Particles and question tails are not units. "อายุเกิน 65 ล่ะ" was being pinned as
    # though "ล่ะ" measured something.
    for particle in ("ล่ะ", "หล่ะ", "ค่ะ", "คะ", "ครับ", "นะ", "ไหม", "หรือ", "ด้วย", "แล้ว"):
        if stripped.startswith(particle):
            return ""
    match = _TRAIL_WORD_RE.match(stripped)
    return match.group(1) if match else ""


def _salient_token(phrase: str) -> str:
    """The unit or noun that makes this fact meaningful, or "" if there is none."""
    for unit in _SALIENT_UNITS:
        if unit in phrase:
            return unit
    for noun in _SALIENT_NOUNS:
        if noun in phrase:
            return noun
    return ""


def _fact_phrases(text: str) -> list[str]:
    """Every number in `text`, each with just enough context to stay meaningful.

    "ถ้าเงินเดือน 100,000 บาทต้อง..." -> "เงินเดือน 100,000 บาท". A bare "100,000" in a
    summary is nearly useless to the next turn; the leading noun is what makes it usable.
    """
    phrases = []
    for match in _NUMBER_RE.finditer(text):
        number = match.group(0)
        # Thai is unspaced, so any fixed-width window can slice mid-word. The window is
        # a hint for the reader; the number and its unit are the load-bearing parts and
        # those are always exact.
        lead_match = _LEAD_WORD_RE.search(text[max(0, match.start() - 16):match.start()].rstrip())
        unit = _trailing_unit(text[match.end():match.end() + 8])
        parts = []
        if lead_match:
            parts.append(lead_match.group(0))
        parts.append(number)
        if unit:
            parts.append(unit)
        phrases.append(" ".join(parts))
    return phrases


def _salience(phrase: str) -> int:
    """How worth pinning this fact is. 0 means drop it entirely.

    2 — carries a unit or noun this domain actually reasons about (salary, dependants,
        age, premiums). These are what a follow-up like "แล้วถ้ามีลูก 3 คนล่ะ" needs.
    1 — money-SHAPED: comma-grouped or four digits and up, even with an unrecognised
        noun. Catches phrasings the lists above miss without letting "ข้อ 2" through.
    0 — an incidental digit. Dropped rather than allowed to consume the cap.
    """
    number_match = _NUMBER_RE.search(phrase)
    number = number_match.group(0) if number_match else ""
    if _salient_token(phrase):
        return 2
    if "," in number or len(number.replace(",", "")) >= 4:
        return 1
    return 0


def extract_user_facts(history: list[dict], existing_summary: str = "") -> list[str]:
    """Numbers the user stated, oldest first, deduplicated by the number itself.

    `existing_summary`'s pinned line is read back so facts survive repeated compaction.
    Only that line is parsed, not the prose around it — otherwise figures Aree quoted
    would accumulate into the pin over successive rounds.
    """
    facts: dict[str, str] = {}
    first_seen: dict[str, int] = {}

    def remember(phrase: str) -> None:
        number_match = _NUMBER_RE.search(phrase)
        if not phrase or not number_match:
            return
        # Keyed on the number AND what it measures, not the digits alone: "ลูก 3 คน" and
        # "ข้อ 3" are different facts, and keying on "3" let the second silently
        # overwrite the first.
        key = f"{number_match.group(0)}|{_salient_token(phrase)}"
        # Later mentions win the PHRASING (a corrected salary replaces the first), but
        # the original position is kept so ranking still favours what was said early.
        facts[key] = phrase
        first_seen.setdefault(key, len(first_seen))

    for line in existing_summary.splitlines():
        if line.startswith(_PINNED_PREFIX):
            for phrase in line[len(_PINNED_PREFIX):].split(" · "):
                remember(phrase.strip())

    for msg in history:
        if msg.get("role") != "user":
            continue
        for phrase in _fact_phrases(str(msg.get("content", ""))):
            remember(phrase)

    ranked = sorted(
        ((key, phrase) for key, phrase in facts.items() if _salience(phrase)),
        key=lambda item: (-_salience(item[1]), first_seen[item[0]]),
    )
    return [phrase for _, phrase in ranked[:_MAX_PINNED_FACTS]]


def pin_facts(summary: str, facts: list[str]) -> str:
    """Put `facts` on their own line above the prose summary."""
    if not facts:
        return summary
    pinned = _PINNED_PREFIX + " · ".join(facts)
    return f"{pinned}\n{summary}" if summary else pinned

# Guards against two summarisation passes overlapping. Module-level, i.e. per worker
# process — livekit-agents runs each job in its own process, so this is effectively
# per-job today.
_summarizing: bool = False

_summary_llm = None


def _get_summary_llm():
    """Lazy singleton, matching the convention in graph/nodes.py.

    Lazy rather than module-level so importing this module costs nothing — the
    offline harness imports it for `build_messages_for_graph`/`append_turn` and
    should not build an LLM client it may never call.
    """
    global _summary_llm
    if _summary_llm is None:
        from langchain_openai import ChatOpenAI

        _summary_llm = ChatOpenAI(
            base_url=os.getenv("LLM_BASE_URL"),
            api_key=os.getenv("LLM_API_KEY"),
            model=os.getenv("ROUTER_MODEL"),
            # 200 could truncate three sentences of Thai mid-word, which then reads as a
            # corrupted summary to the next turn. This runs in the background, off the
            # user's critical path, so the headroom is close to free. The numbers are
            # pinned separately either way — see extract_user_facts().
            max_tokens=320,
            temperature=0.3,
        )
    return _summary_llm


def new_memory() -> dict:
    """A fresh, empty conversation memory."""
    return {"history": [], "summary": ""}


def build_messages_for_graph(memory: dict) -> list[dict]:
    """Flatten memory into the ``messages`` list the graph consumes."""
    messages = []
    if memory["summary"]:
        messages.append({
            "role": "system",
            "content": f"สรุปบทสนทนาก่อนหน้า: {memory['summary']}",
        })
    messages.extend(memory["history"])
    return messages


def append_turn(memory: dict, question: str, *, spoken: str = "", detail: str = "") -> bool:
    """Record one exchange. Returns True if anything was recorded.

    Recorded when EITHER answer produced content. Keying this on spoken output alone
    dropped the exchange whenever the voice path was barged into or failed, leaving a
    hole in the history that broke the next follow-up question.
    """
    if not (detail or spoken):
        return False
    memory["history"].append({"role": "user", "content": question})
    memory["history"].append({
        "role": "assistant",
        "content": detail or spoken,
    })
    return True


def make_turn_recorder(memory: dict, question: str, *, on_recorded=None):
    """Record one exchange at most once, as soon as an answer actually exists.

    Both answer paths in ``agent.py`` used to append only after the LAST audio frame
    had played, so the turn was absent from ``memory`` for the whole spoken answer. A
    follow-up asked inside that window was routed with no conversation context:
    ``_is_tax_followup()`` needs a tax keyword in the RECENT CONTEXT, and with an empty
    history the fast router falls through to "out_of_scope". Measured on the same
    two-turn conversation, varying only the gap: answered with 3 citations at ~39s
    (voice finished), "outside our scope" at ~11s (voice still playing).

    It was not merely a delay. A typed follow-up runs ``_cancel_current_speech``, which
    calls ``active_text_response_task.cancel()`` — so the previous turn's coroutine is
    CANCELLED, ``except asyncio.CancelledError: raise`` runs, and the append at its tail
    is never reached. The turn was lost for the rest of the conversation.

    So recording hangs off the DETAIL task instead. That is what ``append_turn`` stores
    (``detail or spoken`` — detail wins whenever it exists), it is published over the
    data channel independently of TTS, and it finishes seconds before the audio does.
    Stored content is therefore identical to what the tail would have stored; it just
    lands in memory while the user is still reading it, which is exactly when they type
    the follow-up. The tail call stays as the fallback for a turn that produced speech
    but no panel answer.

    ``on_recorded(memory)`` is invoked once, after a successful append — that is where
    ``agent.py`` persists and schedules summarisation. It lives here rather than in
    ``agent.py`` so it can be exercised without ``livekit`` installed, the same reason
    the rest of this module was extracted.

    Returns ``(record, on_detail_ready)``: a guarded recorder, and a done-callback to
    attach to the detail task.
    """
    recorded = False

    def record(*, spoken: str = "", detail: str = "") -> bool:
        nonlocal recorded
        if recorded:
            return False
        if not append_turn(memory, question, spoken=spoken, detail=detail):
            return False
        recorded = True
        if on_recorded is not None:
            on_recorded(memory)
        return True

    def on_detail_ready(task) -> None:
        """Done-callback for the detail task; safe on a cancelled or failed one."""
        try:
            if task.cancelled() or task.exception() is not None:
                return
        except Exception:
            return
        record(detail=task.result() or "")

    return record, on_detail_ready


async def summarize_history(history: list[dict], existing_summary: str, llm=None) -> str:
    """Compress `history` into a short Thai summary.

    `llm` may be injected (the harness passes a stub to keep runs deterministic);
    it defaults to the lazy singleton.
    """
    llm = llm or _get_summary_llm()
    turns_text = ""
    for msg in history:
        role = "ผู้ใช้" if msg["role"] == "user" else "อารี"
        turns_text += f"{role}: {msg['content']}\n"

    prompt = f"""
[CRITICAL] ห้ามใช้ <think> tag ตอบตรงๆ ทันที

สรุปบทสนทนาต่อไปนี้เป็นภาษาไทยสั้นๆ ไม่เกิน 3 ประโยค
เน้นข้อมูลสำคัญที่ผู้ใช้ถามและอารีตอบไป
คงตัวเลขที่ผู้ใช้ระบุไว้ทุกตัว เช่น เงินเดือน จำนวนบุตร อายุ

{"สรุปก่อนหน้า: " + existing_summary if existing_summary else ""}

บทสนทนา:
{turns_text}

สรุป:"""

    response = await llm.ainvoke([
        {"role": "user", "content": prompt}
    ])
    result = response.content.strip()
    result = _THINK_TAG_RE.sub("", result).strip()
    return result


async def maybe_summarize(memory: dict, llm=None) -> None:
    """Compact `memory` in place once it grows past MAX_WINDOW turns."""
    global _summarizing
    if _summarizing:
        return
    if len(memory["history"]) <= MAX_WINDOW * 2:
        return

    _summarizing = True
    try:
        history = memory["history"]
        # Remember HOW MANY entries are being summarised, not which ones to keep.
        #
        # This runs as a fire-and-forget task, and the summary call below takes seconds.
        # The old code sliced `recent` before that await and assigned it afterwards, so any
        # turn appended during the wait was silently dropped — numbers included, and from
        # disk too on the next save (the "stale snapshot" hazard of async compaction).
        # Turns are only ever appended at the end, so removing the first `cut` entries
        # afterwards is correct however many arrived in the meantime.
        cut = len(history) - KEEP_RECENT * 2
        to_summarize = list(history[:cut])        # a copy: later appends can't change it
        previous_summary = memory["summary"]

        # Facts are collected BEFORE the LLM runs and pinned on afterwards, so a
        # summariser that drops "80,000" (or fails outright) cannot lose them.
        facts = extract_user_facts(to_summarize, previous_summary)
        new_summary = await summarize_history(to_summarize, previous_summary, llm)

        if memory["history"] is not history or len(history) < cut:
            # History was replaced while we waited (e.g. a restore). The cut no longer
            # describes this list; applying it would delete the wrong turns. A history
            # that stays too long is harmless — losing turns is not.
            logger.warning("History changed during summarisation; discarding the summary")
            return
        memory["summary"] = pin_facts(new_summary, facts)
        memory["history"] = history[cut:]
        logger.info(
            "Memory summarized (%d turns compressed): %.80s",
            len(to_summarize) // 2,
            new_summary,
        )
    except Exception:
        logger.exception("Failed to summarize history")
    finally:
        _summarizing = False
