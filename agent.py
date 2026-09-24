import asyncio
import contextlib
import json
import logging
import os
import re
import time
import uuid
from typing import AsyncIterable

import certifi
import httpx
from dotenv import load_dotenv

os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

from livekit import rtc
from livekit.agents import (
    Agent,
    AgentSession,
    AutoSubscribe,
    JobContext,
    JobProcess,
    RoomInputOptions,
    WorkerOptions,
    cli,
    get_job_context,
    llm,
    NOT_GIVEN,
    NotGivenOr,
)
from livekit.agents.tts import TTS, ChunkedStream, TTSCapabilities
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions
from livekit.plugins import openai, silero

load_dotenv()

from graph.nodes import (  # noqa: E402 — must follow load_dotenv()
    curated_node,
    out_of_scope_node,
    parallel_node,
    stream_text_answer,
    stream_voice_answer,
)
from graph.text_normalization import clean_display_text, normalize_for_tts  # noqa: E402
from graph.conversation import (  # noqa: E402
    build_messages_for_graph,
    make_turn_recorder,
    maybe_summarize,
    new_memory,
)
from graph.conversation_store import (  # noqa: E402
    load_conversation,
    room_to_key,
    save_conversation,
)
from latency import tracker  # noqa: E402

_text_input_queue: asyncio.Queue[str] = asyncio.Queue()


def _env_enabled(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _build_stt_plugin():
    if not _env_enabled("STT_ENABLED", True):
        logger.info("LiveKit STT disabled by STT_ENABLED=false")
        return None

    base_url = os.getenv("STT_BASE_URL", "").rstrip("/")
    api_key = os.getenv("STT_API_KEY", "")
    model = os.getenv("STT_MODEL", "")
    if not base_url or not api_key or not model:
        logger.warning("LiveKit STT not configured; voice session will use text/browser input only")
        return None

    stt_required = _env_enabled("STT_REQUIRED", False)
    try:
        with httpx.Client(timeout=httpx.Timeout(2.0, connect=1.0)) as client:
            response = client.get(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            response.raise_for_status()
    except Exception:
        message = (
            "LiveKit STT endpoint is unreachable at %s; starting without server-side STT. "
            "Browser speech fallback and typed text still work. Set STT_REQUIRED=true to fail instead."
        )
        if stt_required:
            logger.exception("Required LiveKit STT endpoint is unreachable at %s", base_url)
            raise
        logger.warning(message, base_url, exc_info=True)
        return None

    logger.info("LiveKit STT enabled: %s (%s)", model, base_url)
    return openai.STT(base_url=base_url, api_key=api_key, model=model)


class _WavTTSStream(ChunkedStream):
    def __init__(
        self, *, tts: "WavTTS", input_text: str, conn_options: APIConnectOptions
    ) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._wav_tts = tts

    async def _stream_pcm(self, output_emitter, input_text: str) -> None:
        chunk_start = time.perf_counter()
        async with self._wav_tts._client.stream(
                "POST",
                f"{self._wav_tts._base_url}/audio/speech",
                headers={"Authorization": f"Bearer {self._wav_tts._api_key}"},
                json={
                    "model": self._wav_tts._model,
                    "voice": self._wav_tts._voice,
                    "input": input_text,
                    "response_format": "pcm",
                },
            ) as response:
            response.raise_for_status()
            first_chunk = True
            async for chunk in response.aiter_bytes(chunk_size=4096):
                if chunk:
                    if first_chunk:
                        chunk_ms = (time.perf_counter() - chunk_start) * 1000
                        logger.debug(
                            "TTS first byte [%d chars]: %.0fms",
                            len(input_text),
                            chunk_ms,
                        )
                        first_chunk = False
                    output_emitter.push(chunk)

    async def _run(self, output_emitter) -> None:
        output_emitter.initialize(
            request_id=str(uuid.uuid4()),
            sample_rate=24000,
            num_channels=1,
            mime_type="audio/pcm",
        )

        try:
            await self._stream_pcm(output_emitter, self._input_text)
        except httpx.ReadTimeout:
            logger.warning("TTS timeout for text: %.40s", self._input_text)
            await self._stream_pcm(output_emitter, self._input_text[:50])

        output_emitter.flush()


class WavTTS(TTS):
    def __init__(self) -> None:
        super().__init__(
            capabilities=TTSCapabilities(streaming=False),
            sample_rate=24000,
            num_channels=1,
        )
        self._base_url = os.environ["TTS_BASE_URL"]
        self._api_key = os.environ["TTS_API_KEY"]
        self._model = os.getenv("TTS_MODEL", "ptm-tts-1")
        self._voice = os.getenv("TTS_VOICE", "ped")
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> ChunkedStream:
        text = normalize_for_tts(text)
        return _WavTTSStream(tts=self, input_text=text, conn_options=conn_options)


logger = logging.getLogger("nongaree-agent")

# MAX_WINDOW / KEEP_RECENT and the memory helpers now live in graph/conversation.py
# so the offline multi-turn harness can drive the same code without livekit.
# Grace period the error path waits on the detail-panel task before deciding the
# on-screen answer failed too. Keep it short: it only runs after a failure.
DETAIL_GRACE_TIMEOUT_S = 5.0
_VALID_EMOTIONS_SET = {"happy", "sad", "angry", "wow", "sleep", "idle"}
_current_producer_task: asyncio.Task | None = None


_EMOJI_RE = re.compile(r"[^\u0000-\u007F\u0E00-\u0E7F\s\n.,!?:;()\-\[\]]")
_ANGRY_CONTEXT_TERMS = (
    "โทษหนัก",
    "เจตนา",
    "หลีกเลี่ยง",
    "หนีภาษี",
    "ปลอม",
    "ทุจริต",
    "คดี",
    "อาญา",
    "หมายเรียก",
    "โกรธ",
    "จริงจัง",
    "ดุ",
    "เบี้ยปรับ",
)
_SAD_CONTEXT_TERMS = (
    "ขอโทษ",
    "เสียใจ",
    "ไม่สบายใจ",
    "กังวล",
    "ลืม",
    "พลาด",
    "เลยกำหนด",
    "นอกขอบเขต",
    "ตอบไม่ได้",
    "ไม่สามารถ",
    "ไม่มีข้อมูล",
    "ไม่พบข้อมูล",
    "ต้องถามเพิ่ม",
    "ยังไม่พอ",
    "ขาดข้อมูล",
)
_HAPPY_CONTEXT_TERMS = (
    "ได้เลย",
    "ข่าวดี",
    "ไม่ยาก",
    "ช่วย",
    "ถูกต้อง",
    "เรียบร้อย",
    "ไม่ต้องเสีย",
    "ไม่ต้องจ่าย",
    "สามารถ",
    "ยังแก้ไข",
)
_WOW_CONTEXT_TERMS = ("ยอดเยี่ยม", "น่าสนใจ", "เยอะ", "พิเศษ")


def normalize_stream_emotion(query: str, text: str, emotion: str) -> str:
    emotion = emotion if emotion in _VALID_EMOTIONS_SET else "idle"
    context = f"{query}\n{text}".lower()
    if any(term in context for term in _SAD_CONTEXT_TERMS):
        return "sad"
    if emotion == "angry":
        if any(term in context for term in _ANGRY_CONTEXT_TERMS):
            return "angry"
        return "idle"
    if emotion == "idle":
        if any(term in context for term in _HAPPY_CONTEXT_TERMS):
            return "happy"
        if any(term in context for term in _WOW_CONTEXT_TERMS):
            return "wow"
    return emotion


def split_to_tts_chunks(text: str) -> list[str]:
    text = strip_think_tags(text)
    text = _EMOJI_RE.sub("", text)
    text = re.sub(r"\[EMOTION:\w+\]", "", text)
    return [clean_display_text(c.strip()) for c in text.split("\n") if c.strip()]


def pop_speakable_chunks(buf: str) -> tuple[list[str], str]:
    """Return complete chunks from the streaming buffer, keeping the tail."""

    chunks: list[str] = []
    while True:
        newline_positions = [idx for idx in (buf.find("\n"),) if idx >= 0]
        punctuation = re.search(r"[.!?。！？]\s*", buf)
        thai_ending = re.search(r"(ค่ะ|ครับ|นะคะ|นะครับ)(\s+|$)", buf)
        candidates = newline_positions[:]
        if punctuation:
            candidates.append(punctuation.end())
        if thai_ending:
            candidates.append(thai_ending.end())
        if not candidates:
            break

        split_at = min(candidates)
        if split_at <= 0:
            split_at = 1
        chunk = clean_display_text(buf[:split_at].strip())
        buf = buf[split_at:]
        if chunk:
            chunks.append(chunk)
    return chunks, buf


def strip_think_tags(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


async def send_emotion(room: rtc.Room, emotion: str) -> None:
    payload = json.dumps({"type": "emotion", "emotion": emotion}, ensure_ascii=False).encode()
    await room.local_participant.publish_data(payload, reliable=True)


async def send_sources(room: rtc.Room, state: dict) -> None:
    """Publish the chunks an answer was built from, for the [1][2][3] citations.

    Sent once per turn, right after routing/retrieval and before the answer
    streams, so the panel can render the markers as soon as the text lands.
    Non-rag routes send an empty list, which clears the previous turn's markers.
    """
    sources = state.get("sources") or []
    # Diagnostics ride along on this message rather than a new one — it is already
    # sent once per turn. None of it is personal data, and it is what makes a problem
    # report triageable: `retrieval_empty` alone separates "the score gate rejected
    # everything" from "we had context and still got it wrong".
    diagnostics = {
        "route": state.get("route") or "",
        "retrieval_empty": not (state.get("context") or "").strip(),
        "job_id": "",
        "agent_name": os.getenv("AGENT_NAME", "nongaree-agent"),
    }
    try:
        diagnostics["job_id"] = get_job_context().job.id
    except Exception:
        pass
    payload = json.dumps(
        {"type": "chat_sources", "sources": sources, "diagnostics": diagnostics},
        ensure_ascii=False,
    ).encode()
    await room.local_participant.publish_data(payload, reliable=True)


async def send_chat_event(room: rtc.Room, event_type: str, text: str) -> None:
    payload = json.dumps({"type": event_type, "text": text}, ensure_ascii=False).encode()
    await room.local_participant.publish_data(payload, reliable=True)


async def _close_voice_turn(room: rtc.Room, spoken: str) -> None:
    """Always tell the frontend the spoken half of a turn is over — even if nothing was said.

    `voice_answer` used to be sent only when something was spoken. A turn whose spoken
    reply yielded no speakable sentence (observed live on `ลดหย่อนบุตรได้เท่าไหร่`: both LLM
    streams returned 200 and closed, the panel answer was delivered, and TTS was never
    called) sent no voice event at all. The frontend's 'กำลังเตรียมคำตอบสั้น...' placeholder
    is cleared only by a voice event, so the UI stayed on กำลังคิด and queued every later
    question forever. An empty `voice_answer` is how the frontend clears it.
    """
    if not spoken:
        logger.warning("Spoken answer produced no speakable sentences; closing the voice turn empty")
    try:
        await send_chat_event(room, "voice_answer", spoken)
    except Exception:
        logger.exception("Failed to publish voice_answer")


def _persist_memory(memory: dict) -> None:
    """Save the conversation so a page reload does not start from nothing.

    Never raises: a storage failure must not take down a turn that otherwise worked.
    The room name is resolved from the job context rather than plumbed through, so both
    the voice and typed paths get it without extra arguments.
    """
    try:
        save_conversation(room_to_key(get_job_context().room.name), memory)
    except Exception:
        logger.exception("Failed to persist conversation memory")


_background_tasks: set[asyncio.Task] = set()


async def _summarize_and_persist(memory: dict) -> None:
    """Compaction happens in the background, so persist again once it has run."""
    await maybe_summarize(memory)
    _persist_memory(memory)


def _persist_and_summarize(memory: dict) -> None:
    """`on_recorded` hook for make_turn_recorder: save now, compact in the background.

    Synchronous because it also runs from the detail task's done-callback, which is
    plain event-loop code rather than a coroutine.
    """
    _persist_memory(memory)
    # Hold a reference until it finishes: the event loop keeps only weak references to
    # tasks, so an unreferenced fire-and-forget task can be garbage-collected mid-run
    # (Python asyncio.create_task docs) — a summary that silently never completes.
    task = asyncio.create_task(_summarize_and_persist(memory))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _base_graph_state(query: str, memory: dict) -> dict:
    return {
        "query": query,
        "messages": build_messages_for_graph(memory),
        "context": "",
        "answer": "",
        "emotion": "idle",
        "route": "direct",
    }


async def prepare_response_state(query: str, memory: dict) -> dict:
    state = _base_graph_state(query, memory)
    state.update(await parallel_node(state))

    if state["route"] == "curated":
        state.update(await curated_node(state))
    elif state["route"] == "out_of_scope":
        state.update(await out_of_scope_node(state))

    return state


def clean_text_output(text: str) -> str:
    text = strip_think_tags(text)
    text = re.sub(r"\[EMOTION:\w+\]", "", text)
    return text.strip()


LIST_DETAIL_HANDOFF = (
    "รายการนี้ค่อนข้างยาวค่ะ หนูแสดงรายละเอียดทั้งหมดไว้ที่แผงด้านขวาแล้วนะคะ"
)

# Spoken ONLY when the turn produced nothing at all - no panel answer either. That is a
# genuine total failure, so "the system took too long, please ask again" is accurate.
# Normal turns never reach this path: the spoken answer streams from
# voice_sentence_stream, TTS errors are swallowed inside producer(), and a stopped
# session is handled by _say_if_running(), so this is an unexpected-exception path only.
NO_ANSWER_FALLBACK = (
    "ขอโทษค่ะ ระบบใช้เวลานานหรือมีปัญหาระหว่างเตรียมคำตอบ กรุณาลองถามอีกครั้งนะคะ"
)

# Spoken when the DETAIL answer WAS delivered and only the spoken half failed. The
# supervisor report behind this is exactly that case: the old code claimed the system
# was slow while a complete answer sat on screen, and stored that apology as the spoken
# half of the turn, so it also appeared in the history next to the real answer.
VOICE_FAILED_PANEL_OK = (
    "ขออภัยค่ะ เสียงขัดข้องระหว่างตอบ คำตอบเต็มแสดงอยู่บนหน้าจอแล้วนะคะ"
)


def is_list_detail_query(query: str) -> bool:
    normalized = clean_display_text(query).lower()
    return any(
        term in normalized
        for term in (
            "เอกสาร",
            "หลักฐาน",
            "รายการ",
            "อะไรบ้าง",
            "ใดบ้าง",
            "มีอะไร",
            "paper",
            "papers",
            "document",
            "documents",
            "list",
        )
    )


def looks_like_list_chunk(text: str) -> bool:
    normalized = clean_display_text(text)
    if re.search(r"(^|\s)\d+[\.)]\s+", normalized):
        return True
    return any(marker in normalized for marker in ("|", "ลำดับ", "ดังนี้", "ได้แก่"))


def compact_spoken_answer(query: str, answer: str) -> str:
    answer = clean_text_output(answer)
    lines = [line.strip() for line in answer.splitlines() if line.strip()]
    if not lines:
        return ""

    normalized_query = query.lower()
    is_tcl_query = (
        "tcl" in normalized_query
        or "ทีซีแอล" in query
        or "ทะเบียนคุมรายการ" in query
        or "บัญชีผู้เสียภาษีอากร" in query
    )
    if is_tcl_query and looks_like_list_chunk(answer):
        if any(term in query for term in ("หยุด", "ล่ม", "ผลกระทบ", "กระทบ", "ให้บริการไม่ได้")):
            return (
                "ถ้าระบบทีซีแอลหยุดให้บริการ งานทะเบียน บัญชีผู้เสียภาษี "
                "ลูกหนี้ภาษี และงานข้อมูลภายในอาจล่าช้าค่ะ "
                "หนูสรุปรายละเอียดเป็นตารางไว้ที่แผงด้านขวาแล้วนะคะ"
            )
        return (
            "ระบบทีซีแอลคือระบบทะเบียนคุมรายการและบัญชีผู้เสียภาษีอากรค่ะ "
            "ใช้ช่วยจัดการข้อมูลทะเบียน ลูกหนี้ภาษี และข้อมูลปฏิบัติงานภายใน "
            "หนูสรุปหน้าที่หลักเป็นตารางไว้ที่แผงด้านขวาแล้วนะคะ"
        )

    if "ดอกเบี้ย" in query and "บ้าน" in query and "ลดหย่อน" in query:
        return (
            "ดอกเบี้ยเงินกู้ซื้อบ้านลดหย่อนภาษีได้สูงสุดเก้าหมื่นบาทต่อปีค่ะ "
            "ต้องเป็นดอกเบี้ยที่จ่ายจริงเพื่อซื้อหรือสร้างที่อยู่อาศัย "
            "และควรมีหลักฐานจากสถาบันการเงินนะคะ"
        )

    if is_list_detail_query(query) and (
        len(lines) > 2 or looks_like_list_chunk(answer)
    ):
        return LIST_DETAIL_HANDOFF

    if "เงินเดือน" in query and "เงินได้สุทธิ" in answer:
        tax_line = next(
            (
                line
                for line in lines
                if "ไม่มีภาษีต้องชำระ" in line or "ภาษีประมาณ" in line
            ),
            "",
        )
        age_line = next(
            (
                line
                for line in lines
                if "อายุ" in line and "จากอายุ" in line and "ยังไม่ได้ระบุอายุ" not in line
            ),
            "",
        )
        return " ".join(line for line in (lines[0], tax_line, age_line) if line).strip()

    if len(lines) == 1:
        return lines[0]
    return " ".join(lines[:2])


async def stream_text_to_chat(room: rtc.Room, state: dict) -> str:
    if state["route"] in {"curated", "out_of_scope"}:
        answer = clean_text_output(state.get("answer", ""))
        if answer:
            await send_chat_event(room, "chat_delta", f"{answer}\n")
            await send_chat_event(room, "chat_answer", answer)
        return answer

    parts: list[str] = []
    try:
        async for token in stream_text_answer(state):
            if not token:
                continue
            parts.append(token)
            await send_chat_event(room, "chat_delta", token)
    except Exception:
        logger.exception("Text generation stream failed")

    answer = clean_text_output("".join(parts))
    if answer:
        await send_chat_event(room, "chat_answer", answer)
    return answer


async def _detail_answer_if_delivered(text_task: asyncio.Task | None) -> str:
    """Return the detail-panel answer if that task already delivered one.

    Called only from the error path, to decide whether the spoken-path fallback is
    also allowed to overwrite the panel. Empty string means the panel has nothing
    usable on it and the fallback should be shown there too.
    """
    if text_task is None:
        return ""
    if not text_task.done():
        # It may be moments from finishing; give it a bounded chance rather than
        # discarding a nearly-complete answer.
        try:
            await asyncio.wait_for(asyncio.shield(text_task), DETAIL_GRACE_TIMEOUT_S)
        except Exception:
            return ""
    if text_task.cancelled() or text_task.exception() is not None:
        return ""
    return (text_task.result() or "").strip()



async def voice_sentence_stream(
    query: str,
    state: dict,
) -> AsyncIterable[tuple[str, str]]:
    if state["route"] in {"curated", "out_of_scope"}:
        answer = compact_spoken_answer(query, state.get("answer", ""))
        emotion = normalize_stream_emotion(query, answer, state.get("emotion", "idle"))
        if not tracker.emotions or tracker.emotions[-1] != emotion:
            tracker.emotions.append(emotion)
        for line in split_to_tts_chunks(answer):
            yield line, emotion
        return

    current_emotion = "idle"
    buf = ""
    in_think = False
    list_handoff_sent = False
    suppress_list_voice = False

    tracker.generate_start = time.perf_counter()
    async for token in stream_voice_answer(state):
        if not tracker.generate_first_token:
            tracker.generate_first_token = time.perf_counter()
        if not token:
            continue

        if not in_think:
            if "<think>" in token:
                in_think = True
                pre = token[:token.index("<think>")]
                if pre:
                    buf += pre
                continue
            buf += token
        else:
            if "</think>" in token:
                in_think = False
                post = token[token.index("</think>") + len("</think>"):]
                if post:
                    buf += post
            continue

        for m in re.finditer(r"\[EMOTION:(\w+)\]", buf):
            tag_emotion = m.group(1)
            if tag_emotion in _VALID_EMOTIONS_SET:
                current_emotion = normalize_stream_emotion(query, buf, tag_emotion)
        if not tracker.emotions or tracker.emotions[-1] != current_emotion:
            tracker.emotions.append(current_emotion)
        buf = re.sub(r"\[EMOTION:\w+\]", "", buf)
        buf = _EMOJI_RE.sub("", buf)

        chunks, buf = pop_speakable_chunks(buf)
        for line in chunks:
            if is_list_detail_query(query):
                suppress_list_voice = True
                if list_handoff_sent:
                    continue
                line = LIST_DETAIL_HANDOFF
                list_handoff_sent = True

            current_emotion = normalize_stream_emotion(query, line, current_emotion)
            if not tracker.emotions or tracker.emotions[-1] != current_emotion:
                tracker.emotions.append(current_emotion)
            logger.debug("TTS sentence [%d]: %s", len(line), line[:40])
            yield line, current_emotion

    tracker.generate_done = time.perf_counter()
    remaining = re.sub(r"\[EMOTION:\w+\]", "", buf).strip()
    remaining = _EMOJI_RE.sub("", remaining).strip()
    if remaining:
        remaining = clean_display_text(remaining)
        if is_list_detail_query(query):
            if list_handoff_sent:
                return
            remaining = LIST_DETAIL_HANDOFF
            list_handoff_sent = True

        current_emotion = normalize_stream_emotion(query, remaining, current_emotion)
        if not tracker.emotions or tracker.emotions[-1] != current_emotion:
            tracker.emotions.append(current_emotion)
        yield remaining, current_emotion


class GraphLLMStream(llm.LLMStream):
    def __init__(
        self,
        llm_inst: llm.LLM,
        *,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool],
        conn_options: APIConnectOptions,
    ) -> None:
        super().__init__(
            llm_inst, chat_ctx=chat_ctx, tools=tools, conn_options=conn_options
        )

    async def _run(self) -> None:
        # Emit one placeholder token so LiveKit starts the TTS pipeline for
        # voice turns. VoiceAgent.tts_node discards this stream and generates
        # the real response from the STT transcript via the graph.
        self._event_ch.send_nowait(
            llm.ChatChunk(
                id=str(uuid.uuid4()),
                delta=llm.ChoiceDelta(content=" "),
            )
        )


class GraphLLM(llm.LLM):
    def __init__(self) -> None:
        super().__init__()

    def chat(
        self,
        *,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool] | None = None,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
        parallel_tool_calls: NotGivenOr[bool] = NOT_GIVEN,
        tool_choice: NotGivenOr[llm.ToolChoice] = NOT_GIVEN,
        extra_kwargs: NotGivenOr[dict[str, any]] = NOT_GIVEN,
    ) -> llm.LLMStream:
        return GraphLLMStream(
            self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options
        )


class VoiceAgent(Agent):
    def __init__(self, memory: dict) -> None:
        self.memory = memory
        super().__init__(
            instructions=(
                "You are Aree (อารี), a helpful voice assistant for the Thai Revenue Department (กรมสรรพากร).\n"
                "Always respond in Thai language only.\n"
                "Be polite, professional, and use formal Thai (ภาษาราชการ).\n"
                "Your role is to answer questions about taxes, tax filing, tax returns,\n"
                "and Revenue Department services.\n\n"
                "Text normalization rules (apply to every response before output):\n"
                "- Convert numbers to Thai words: 10 → สิบ, 100 → หนึ่งร้อย, 2567 → สองพันห้าร้อยหกสิบเจ็ด\n"
                "- Transliterate English words to Thai pronunciation: VAT → แวต, e-Filing → อี-ไฟลิ่ง\n"
                "- Use \\n to create natural phrase breaks every 1-2 sentences\n\n"
                "Emotion tags:\n"
                "- [EMOTION:happy]  → good news, successful filing, refund approved\n"
                "- [EMOTION:sad]    → apologizing, bad news, system errors\n"
                "- [EMOTION:angry]  → only severe cases like tax evasion, fraud, fake documents, criminal cases, or heavy penalties; do not use for normal tax explanations or simple missed deadlines\n"
                "- [EMOTION:wow]    → surprising tax facts, large refund amounts\n"
                "- [EMOTION:sleep]  → ending conversation, farewell\n"
                "- [EMOTION:idle]   → default neutral state\n\n"
                "You can include [EMOTION:x] tags anywhere in your response, "
                "before any sentence that has a different emotional tone.\n\n"
                "Rules:\n"
                "- Always start response with one [EMOTION:x] tag\n"
                "- Add a new [EMOTION:x] tag before any sentence with different emotion\n"
                "- Do not repeat the same emotion tag consecutively\n\n"
                "Example response:\n"
                "[EMOTION:sad] น่าเสียดายที่พลาดกำหนดยื่นแบบค่ะ \n"
                "[EMOTION:happy] แต่ยังแก้ไขได้นะคะ ยังสามารถยื่นแบบล่าช้าได้ค่ะ \n"
                "[EMOTION:idle] ค่าปรับอยู่ที่ร้อยละสองของภาษีที่ต้องชำระค่ะ\n\n"
                "Always introduce yourself as อารี on first message."
            ),
            stt=_build_stt_plugin(),
            llm=GraphLLM(),
            tts=WavTTS(),
        )

    async def on_enter(self) -> None:
        try:
            await send_emotion(get_job_context().room, "happy")
        except Exception:
            logger.exception("Failed to publish greeting emotion")
        logger.info("Agent entered room; greeting is handled after user participant is ready")

    async def on_user_turn_completed(
        self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage
    ) -> None:
        user_text = (new_message.text_content or "").strip()
        if not user_text:
            logger.warning("Voice turn completed without text content")
            return
        logger.info("Voice input received: %s", user_text)
        _text_input_queue.put_nowait(user_text)

    async def tts_node(  # type: ignore[override]
        self,
        text: AsyncIterable[str],
        model_settings,
    ) -> AsyncIterable[rtc.AudioFrame]:  # type: ignore[return]
        user_text = ""

        try:
            user_text = _text_input_queue.get_nowait()
            logger.info("Using text input: %s", user_text)
        except asyncio.QueueEmpty:
            try:
                for msg in reversed(self.session._chat_ctx.messages):
                    if str(getattr(msg, "role", "")).lower() == "user":
                        content = msg.content
                        if isinstance(content, list):
                            content = " ".join(
                                str(c) for c in content if isinstance(c, str)
                            )
                        user_text = str(content).strip()
                        break
            except Exception:
                pass

        if user_text:
            tracker.reset()
            tracker.stt_done = time.perf_counter()
            try:
                room = get_job_context().room
                await send_chat_event(room, "chat_user", user_text)
                await send_chat_event(room, "chat_status", "กำลังคิดคำตอบ...")
            except Exception:
                pass

            async def discard_stream():
                try:
                    async for _ in text:
                        pass
                except Exception:
                    pass

            asyncio.create_task(discard_stream())

            response_state = await prepare_response_state(user_text, self.memory)
            room = get_job_context().room
            try:
                await send_sources(room, response_state)
            except Exception:
                logger.exception("Failed to publish answer sources")
            text_task = asyncio.create_task(stream_text_to_chat(room, response_state))
            # Record the turn as soon as the PANEL answer is ready, not after the last
            # audio frame. See make_turn_recorder(): a follow-up asked while Aree is
            # still speaking was routed with an empty history and fell through to
            # "out_of_scope".
            record_turn, on_detail_ready = make_turn_recorder(
                self.memory, user_text, on_recorded=_persist_and_summarize
            )
            text_task.add_done_callback(on_detail_ready)

            async def tts_pipeline(
                sentences: AsyncIterable[tuple[str, str]],
            ) -> AsyncIterable[tuple[list[rtc.AudioFrame], str]]:
                global _current_producer_task

                if _current_producer_task and not _current_producer_task.done():
                    _current_producer_task.cancel()
                    try:
                        await _current_producer_task
                    except asyncio.CancelledError:
                        pass

                queue: asyncio.Queue = asyncio.Queue(maxsize=3)

                async def producer():
                    try:
                        async for sentence, emotion in sentences:
                            if not sentence.strip():
                                continue
                            frames = []
                            stream = self.tts.synthesize(sentence)
                            async for audio_event in stream:
                                frames.append(audio_event.frame)
                            await queue.put((frames, emotion))
                    except asyncio.CancelledError:
                        pass
                    finally:
                        await queue.put(None)  # always signal end

                _current_producer_task = asyncio.create_task(producer())

                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    yield item

                await _current_producer_task

            yielded_sentences: list[str] = []

            async def sentence_stream_with_tracking():
                async for sentence, emotion in voice_sentence_stream(user_text, response_state):
                    yielded_sentences.append(sentence)
                    try:
                        await send_chat_event(room, "voice_delta", f"{sentence}\n")
                    except Exception:
                        pass
                    yield sentence, emotion

            first_audio_logged = False

            async for frames, emotion in tts_pipeline(sentence_stream_with_tracking()):
                logger.debug("→ sending emotion: %s", emotion)
                try:
                    await send_emotion(get_job_context().room, emotion)
                except Exception:
                    pass
                logger.debug("→ yielding %d frames for emotion: %s", len(frames), emotion)
                for frame in frames:
                    if not first_audio_logged:
                        first_audio_logged = True
                        tracker.first_audio = time.perf_counter()
                        tracker.log_summary()
                    yield frame

            voice_answer = " ".join(yielded_sentences) if yielded_sentences else ""
            await _close_voice_turn(room, voice_answer)
            text_answer = await text_task
            # Fallback only: the detail-ready callback above has almost always recorded
            # this turn already. Still needed for a turn that produced speech but no
            # panel answer — append_turn records when EITHER answer has content, because
            # keying on spoken output alone dropped the exchange whenever the voice path
            # was barged into or failed.
            record_turn(spoken=voice_answer, detail=text_answer)
        else:
            async for frame in super().tts_node(text, model_settings):
                yield frame


def prewarm(proc: JobProcess) -> None:
    started = time.perf_counter()
    proc.userdata["vad"] = silero.VAD.load()
    logger.info("Prewarm complete: VAD loaded in %.0fms", (time.perf_counter() - started) * 1000)


async def entrypoint(ctx: JobContext) -> None:
    entry_started = time.perf_counter()
    logger.info("Connecting to room: %s", ctx.room.name)
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    logger.info("LiveKit connected in %.0fms", (time.perf_counter() - entry_started) * 1000)
    logger.info(
        "Room participants: %s",
        [p.identity for p in ctx.room.remote_participants.values()],
    )
    logger.info("Room name: %s, SID: %s", ctx.room.name, await ctx.room.sid)

    participant = await ctx.wait_for_participant()
    logger.info("Participant connected: %s", participant.identity)

    # Was `new_memory()`: memory lived and died with the JOB, and Fix 8 ends the job
    # on session close, so every page reload wiped the conversation. Falls back to an
    # empty memory if MEMORY_DIR is unwritable.
    memory: dict = load_conversation(room_to_key(ctx.room.name))

    # Start session immediately
    session = AgentSession(
        vad=ctx.proc.userdata["vad"],
        min_endpointing_delay=float(os.getenv("MIN_ENDPOINTING_DELAY", "0.1")),
        max_endpointing_delay=float(os.getenv("MAX_ENDPOINTING_DELAY", "1.0")),
        allow_interruptions=True,
        min_interruption_duration=float(os.getenv("MIN_INTERRUPTION_DURATION", "0.35")),
        min_interruption_words=int(os.getenv("MIN_INTERRUPTION_WORDS", "0")),
        false_interruption_timeout=float(os.getenv("FALSE_INTERRUPTION_TIMEOUT", "1.2")),
        resume_false_interruption=False,
    )

    session_started = time.perf_counter()
    await session.start(
        room=ctx.room,
        agent=VoiceAgent(memory=memory),
        room_input_options=RoomInputOptions(),
    )
    logger.info("Agent session started in %.0fms", (time.perf_counter() - session_started) * 1000)
    # The room outlives the AgentSession: room event handlers stay registered after
    # the session stops, and session.say() then raises "AgentSession isn't running".
    session_closed = False

    @session.on("close")
    def _on_session_close(_event) -> None:
        nonlocal session_closed
        session_closed = True
        # The job outlives the session: LiveKit closes the AgentSession when the
        # participant disconnects, but keeps this job alive and reuses it if the
        # same participant rejoins — with a session that can never speak again.
        # End the job so a rejoin is dispatched a fresh one.
        logger.info("Agent session closed; ending job so a rejoin gets a fresh session")
        ctx.shutdown(reason="agent_session_closed")

    async def _say_if_running(text: str, **kwargs) -> bool:
        """Speak, unless the session has stopped. Returns False if nothing was said."""
        if session_closed:
            return False
        try:
            await session.say(text, **kwargs)
            return True
        except RuntimeError as exc:
            message = str(exc)
            # livekit-agents raises TWO different messages for "not usable right now":
            #   "AgentSession isn't running"                — already stopped
            #   "AgentSession is closing, cannot use say()" — mid-teardown
            # Only the first was matched, so a participant reconnecting DURING teardown
            # sent _greet_rejoined_user into an unretrieved task exception. `session_closed`
            # cannot cover it either: it is set from the `close` event, which fires after
            # closing finishes, so the whole `closing` window slips past the guard above.
            if "isn't running" not in message and "is closing" not in message:
                raise
            logger.warning("Dropped speech: agent session is not usable (%s)", message)
            return False

    last_rejoin_greeting_at = 0.0
    active_text_response_task: asyncio.Task | None = None
    interrupt_generation = 0

    async def _cancel_current_speech(reason: str) -> None:
        nonlocal active_text_response_task, interrupt_generation
        global _current_producer_task

        interrupt_generation += 1

        try:
            await session.interrupt(force=True)
        except Exception:
            logger.exception("Failed to interrupt current speech")

        if _current_producer_task and not _current_producer_task.done():
            _current_producer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await _current_producer_task

        if active_text_response_task and not active_text_response_task.done():
            active_text_response_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await active_text_response_task

        active_text_response_task = None
        logger.info("Interrupted current speech: %s", reason)

    async def _greet_rejoined_user(identity: str) -> None:
        nonlocal last_rejoin_greeting_at
        if session_closed:
            return
        now = time.perf_counter()
        if now - last_rejoin_greeting_at < 10:
            return
        last_rejoin_greeting_at = now
        try:
            await send_emotion(ctx.room, "happy")
        except Exception:
            logger.exception("Failed to publish rejoin greeting emotion")
        logger.info("Greeting joined participant: %s", identity)
        await _say_if_running(
            "สวัสดีค่ะ ดิฉันชื่ออารีค่ะ ผู้ช่วยของกรมสรรพากร\nมีอะไรให้ดิฉันช่วยไหมคะ",
            allow_interruptions=True,
        )

    await _greet_rejoined_user(participant.identity)

    async def _process_text_and_speak(text: str) -> None:
        generation = interrupt_generation
        text_task: asyncio.Task | None = None
        producer_task: asyncio.Task | None = None
        try:
            tracker.reset()
            tracker.stt_done = time.perf_counter()
            response_state = await prepare_response_state(text, memory)
            try:
                await send_sources(ctx.room, response_state)
            except Exception:
                logger.exception("Failed to publish answer sources")
            text_task = asyncio.create_task(stream_text_to_chat(ctx.room, response_state))
            # Record as soon as the PANEL answer is ready. Critical on this path: a new
            # typed question runs _cancel_current_speech(), which CANCELS this coroutine,
            # so the append at the tail below is never reached and the turn used to be
            # lost outright. See make_turn_recorder().
            record_turn, on_detail_ready = make_turn_recorder(
                memory, text, on_recorded=_persist_and_summarize
            )
            text_task.add_done_callback(on_detail_ready)

            queue: asyncio.Queue = asyncio.Queue(maxsize=3)
            yielded_sentences: list[str] = []

            async def producer():
                try:
                    async for sentence, emotion in voice_sentence_stream(text, response_state):
                        if generation != interrupt_generation:
                            break
                        if not sentence.strip():
                            continue
                        yielded_sentences.append(sentence)
                        try:
                            await send_chat_event(ctx.room, "voice_delta", f"{sentence}\n")
                        except Exception:
                            pass
                        frames = []
                        stream = session._agent.tts.synthesize(sentence)
                        async for audio_event in stream:
                            if generation != interrupt_generation:
                                break
                            frames.append(audio_event.frame)
                        if generation != interrupt_generation:
                            break
                        await queue.put((frames, emotion, sentence))
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("TTS producer error")
                finally:
                    with contextlib.suppress(asyncio.CancelledError):
                        await queue.put(None)

            producer_task = asyncio.create_task(producer())

            first = True
            while True:
                if generation != interrupt_generation:
                    break
                item = await queue.get()
                if item is None:
                    break
                frames, emotion, sentence = item

                try:
                    await send_emotion(ctx.room, emotion)
                except Exception:
                    pass

                def make_audio_gen(sentence_frames):
                    async def gen():
                        nonlocal first
                        for frame in sentence_frames:
                            if first:
                                first = False
                                tracker.first_audio = time.perf_counter()
                                tracker.log_summary()
                            yield frame
                    return gen()

                spoke = await _say_if_running(
                    sentence, audio=make_audio_gen(frames), allow_interruptions=True
                )
                if not spoke:
                    # Session is gone; nobody can hear the rest. The detail panel is
                    # published over the data channel and is unaffected.
                    break

            await producer_task

            if generation != interrupt_generation:
                return

            voice_answer = " ".join(yielded_sentences) if yielded_sentences else ""
            await _close_voice_turn(ctx.room, voice_answer)
            text_answer = await text_task
            # Fallback only: the detail-ready callback above has almost always recorded
            # this turn already. Still needed for a turn that produced speech but no
            # panel answer — append_turn records when EITHER answer has content, because
            # keying on spoken output alone dropped the exchange whenever the voice path
            # was barged into or failed.
            record_turn(spoken=voice_answer, detail=text_answer)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to process text input and speak")
            # The detail panel is fed by an independent task. A failure on the
            # spoken path (TTS, or session.say on a session that already stopped)
            # must not overwrite an on-screen answer that streamed through fine.
            detail_answer = await _detail_answer_if_delivered(text_task)
            # Two failures, two different things to say. Only a turn that produced
            # NOTHING gets the "system took too long" apology; when the panel answer is
            # fine the spoken line reports a voice glitch instead of contradicting it.
            # That line is also what `voice_answer` carries, so the history no longer
            # shows an apology as the spoken half beside a complete answer.
            fallback = VOICE_FAILED_PANEL_OK if detail_answer else NO_ANSWER_FALLBACK
            try:
                if not detail_answer:
                    await send_chat_event(ctx.room, "chat_delta", f"{fallback}\n")
                    await send_chat_event(ctx.room, "chat_answer", fallback)
                # Sad is for a turn the user got nothing from. A delivered panel answer
                # with a broken voice is a glitch, not a failed answer.
                await send_emotion(ctx.room, "sad" if not detail_answer else "idle")
                # The fallback is spoken through session.say(), which emits no voice_delta,
                # so without this the frontend never learns the voice turn ended.
                await _close_voice_turn(ctx.room, fallback)
                await _say_if_running(fallback, allow_interruptions=True)
            except Exception:
                logger.exception("Failed to send text input fallback response")
        finally:
            for task in (producer_task, text_task):
                if task and not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task

    async def _handle_text_input(data: rtc.DataPacket):
        nonlocal active_text_response_task
        try:
            msg = json.loads(data.data.decode())
            if msg.get("type") == "interrupt":
                await _cancel_current_speech("client_interrupt")
                return
            if msg.get("type") == "text_input":
                text = msg.get("text", "").strip()
                if not text:
                    return
                logger.info("Text input received: %s", text)
                await _cancel_current_speech("new_text_input")
                await send_chat_event(ctx.room, "chat_user", text)
                await send_chat_event(ctx.room, "chat_status", "กำลังคิดคำตอบ...")
                active_text_response_task = asyncio.create_task(_process_text_and_speak(text))
        except Exception:
            logger.exception("Failed to process text input")

    def on_data_received(data: rtc.DataPacket):
        # Deliberately NOT gated on session_closed: the detail-panel answer is
        # published over ctx.room and still works without a live AgentSession, so
        # dropping the packet here would lose an answer we can actually deliver.
        # _say_if_running() handles the speech half safely.
        asyncio.create_task(_handle_text_input(data))

    ctx.room.on("data_received", on_data_received)

    # Log participant when they join (non-blocking)
    @ctx.room.on("participant_connected")
    def on_participant(participant):
        logger.info("Participant connected: %s", participant.identity)
        if str(participant.identity).startswith("agent-"):
            return
        asyncio.create_task(_greet_rejoined_user(participant.identity))


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            # Must match AGENT_NAME in app/api/livekit/token/route.ts, which is
            # what dispatches to it. Defaults to "nongaree-agent" so an
            # environment that sets nothing behaves exactly as before.
            agent_name=os.getenv("AGENT_NAME", "nongaree-agent"),
        )
    )
