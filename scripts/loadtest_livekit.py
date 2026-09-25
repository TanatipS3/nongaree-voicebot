"""Ramped load test for Aree: N concurrent full turns, measured, on the real stack.

Deliberately gentle — it steps through small concurrency levels (default 1, 5, 10) with a
pause between them, so it can run alongside light production traffic. Each virtual user is
a real LiveKit session: its own room, its own agent dispatch, one typed question, and the
same answer path a person gets. Nothing is mocked, so the numbers mean something.

Run it INSIDE the agent container, which already holds the SDK and the credentials:

    docker compose exec -T -e PYTHONIOENCODING=utf-8 agent python - < scripts/loadtest_livekit.py
    docker compose exec -T -e PYTHONIOENCODING=utf-8 agent python - --steps 1,5,10 < scripts/loadtest_livekit.py
    docker compose exec -T -e PYTHONIOENCODING=utf-8 agent python - --steps 1,3 --question "ภาษีคืออะไร" < scripts/loadtest_livekit.py

What it reports per step: how many sessions completed, and p50/p95 for
  join     - dispatch to the agent entering the room
  sources  - question to routing+retrieval finishing (chat_sources)
  panel    - question to the on-screen answer (chat_answer)
  audio    - question to the FIRST audio frame; this is the wait a user actually feels
  spoken   - question to the spoken answer completing

Cost per virtual user is one agent subprocess, two LLM streams and the TTS chunks for one
answer — i.e. exactly one real user. Ten concurrent is ten real users' worth of load, so
watch the p95 audio column: when it climbs steeply between steps, that is the ceiling.

Cleanup: rooms are deleted at the end of every step. Each fake user leaves a conversation
memory file (`loadtest-*`) which expires on the normal 30-minute TTL.
"""

import argparse
import array
import asyncio
import json
import os
import statistics
import sys
import time

import httpx
from livekit import api, rtc

WS_URL = os.environ["LIVEKIT_URL"]
HTTP_URL = "http" + WS_URL[2:] if WS_URL.startswith("ws") else WS_URL
KEY = os.environ["LIVEKIT_API_KEY"]
SECRET = os.environ["LIVEKIT_API_SECRET"]
AGENT_NAME = os.getenv("AGENT_NAME", "nongaree-agent")

# --voice: the question is SPOKEN instead of typed, which is the only way to put real
# load on VAD + ptm-asr-1. The audio is synthesised ONCE with the project's own TTS and
# shared by every virtual user, so the test does not measure TTS while measuring STT.
SAMPLE_RATE = 24000
FRAME_MS = 10
SAMPLES_PER_FRAME = SAMPLE_RATE * FRAME_MS // 1000
TRAILING_SILENCE_S = 2.0
SPOKEN_PCM: bytes | None = None

JOIN_TIMEOUT_S = 90
# int16 level that counts as speech rather than silence; measured speech peaks ~18000.
SPEECH_PEAK = 500
GREETING_QUIET_S = 1.5      # silence this long means the greeting has finished
GREETING_MAX_WAIT_S = 40    # ...but never wait longer than this
ANSWER_TIMEOUT_S = 150


def pct(values, p):
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    idx = min(int(round((p / 100) * (len(ordered) - 1))), len(ordered) - 1)
    return ordered[idx]


async def synthesize(text: str) -> bytes:
    """Raw PCM16 @ 24kHz of the question, spoken by the project's own TTS."""
    base = os.environ["TTS_BASE_URL"].rstrip("/")
    async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=10.0)) as client:
        resp = await client.post(
            f"{base}/audio/speech",
            headers={"Authorization": f"Bearer {os.environ['TTS_API_KEY']}"},
            json={"model": os.getenv("TTS_MODEL", "ptm-tts-1"),
                  "voice": os.getenv("TTS_VOICE", "ped"),
                  "input": text, "response_format": "pcm"},
        )
        resp.raise_for_status()
        return resp.content


def fmt(value):
    return f"{value:6.1f}" if isinstance(value, (int, float)) else "     -"


async def one_session(lk, index, question, prefix, voice=False):
    """One virtual user: room, dispatch, join, ask, wait for both answers."""
    room_name = f"nongaree-{prefix}-{index:02d}"
    room = rtc.Room()
    marks = {}
    got_answer = asyncio.Event()
    agent_in = asyncio.Event()
    audio_task = None
    result = {"room": room_name, "ok": False, "error": None}

    @room.on("participant_connected")
    def _joined(p):
        if p.identity != room_name:
            marks.setdefault("join", time.perf_counter())
            agent_in.set()

    async def count_audio(track):
        # Measure the first frame carrying actual SOUND, not the first frame at all: a live
        # track streams continuously, silence included, so "first frame after the question"
        # arrived in milliseconds and reported 0.0s. Two earlier attempts got this wrong —
        # the first timed the GREETING (-11.3s), the second timed silence (0.0s).
        # Sampling every 5th frame (50ms) keeps the CPU cost down: at 10+ concurrent
        # sessions, analysing every frame of every stream in one Python process starved
        # the event loop and produced ping timeouts that looked like server latency.
        seen = 0
        async for ev in rtc.AudioStream(track):
            seen += 1
            if seen % 5:
                continue
            samples = array.array("h", bytes(ev.frame.data))
            if not samples:
                continue
            peak = max(abs(s) for s in samples)
            if peak < SPEECH_PEAK:
                continue
            now = time.perf_counter()
            marks["last_loud"] = now          # also used to detect the greeting ending
            asked_at = marks.get("ask_at")
            if asked_at is not None and now >= asked_at:
                marks.setdefault("audio", now)

    @room.on("track_subscribed")
    def _track(track, publication, participant):
        nonlocal audio_task
        if track.kind == rtc.TrackKind.KIND_AUDIO and audio_task is None:
            audio_task = asyncio.ensure_future(count_audio(track))

    @room.on("data_received")
    def _data(packet):
        try:
            msg = json.loads(bytes(packet.data).decode("utf-8"))
        except Exception:
            return
        kind = msg.get("type")
        if kind == "chat_user" and msg.get("text") and "ask_end" in marks:
            marks.setdefault("stt", time.perf_counter())   # recognition latency
            result["heard"] = msg["text"]
        if kind == "chat_sources":
            marks.setdefault("sources", time.perf_counter())
        elif kind == "chat_answer" and msg.get("text"):
            marks.setdefault("panel", time.perf_counter())
        elif kind == "voice_answer":
            marks.setdefault("spoken", time.perf_counter())
        if "panel" in marks and "spoken" in marks:
            got_answer.set()

    try:
        t0 = time.perf_counter()
        await lk.room.create_room(api.CreateRoomRequest(name=room_name))
        await lk.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(agent_name=AGENT_NAME, room=room_name))
        token = (api.AccessToken(KEY, SECRET)
                 .with_identity(room_name).with_name(room_name)
                 .with_grants(api.VideoGrants(room_join=True, room=room_name))
                 .to_jwt())
        await room.connect(WS_URL, token)
        source = None
        if voice:
            source = rtc.AudioSource(SAMPLE_RATE, 1)
            mic = rtc.LocalAudioTrack.create_audio_track("mic", source)
            await room.local_participant.publish_track(
                mic, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
        if any(p.identity != room_name for p in room.remote_participants.values()):
            marks.setdefault("join", time.perf_counter())
            agent_in.set()
        await asyncio.wait_for(agent_in.wait(), JOIN_TIMEOUT_S)
        result["join"] = marks["join"] - t0

        # Wait for the greeting to actually STOP, rather than sleeping a fixed time and
        # hoping. Asking mid-greeting also triggers an interrupt, whose tail would be
        # measured as the answer's first audio.
        quiet_deadline = time.perf_counter() + GREETING_MAX_WAIT_S
        while time.perf_counter() < quiet_deadline:
            last_loud = marks.get("last_loud")
            if last_loud and (time.perf_counter() - last_loud) > GREETING_QUIET_S:
                break
            await asyncio.sleep(0.25)
        await asyncio.sleep(0.5)

        asked = time.perf_counter()
        marks["ask_at"] = asked          # opens the window for the audio measurement
        if voice and source is not None:
            silence = b"\x00" * (SAMPLES_PER_FRAME * 2)
            step = SAMPLES_PER_FRAME * 2
            pcm = SPOKEN_PCM or b""
            for offset in range(0, len(pcm), step):
                chunk = pcm[offset:offset + step]
                if len(chunk) < step:
                    chunk = chunk + b"\x00" * (step - len(chunk))
                await source.capture_frame(
                    rtc.AudioFrame(chunk, SAMPLE_RATE, 1, SAMPLES_PER_FRAME))
                await asyncio.sleep(FRAME_MS / 1000)   # real time, or VAD sees a burst
            for _ in range(int(TRAILING_SILENCE_S * 1000 / FRAME_MS)):
                await source.capture_frame(
                    rtc.AudioFrame(silence, SAMPLE_RATE, 1, SAMPLES_PER_FRAME))
                await asyncio.sleep(FRAME_MS / 1000)
            marks["ask_end"] = time.perf_counter()     # STT latency is measured from here
        else:
            marks["ask_end"] = asked
            await room.local_participant.publish_data(
                json.dumps({"type": "text_input", "text": question},
                           ensure_ascii=False).encode("utf-8"), reliable=True)
        await asyncio.wait_for(got_answer.wait(), ANSWER_TIMEOUT_S)
        for key in ("sources", "panel", "audio", "spoken"):
            if key in marks:
                result[key] = marks[key] - asked
        if "stt" in marks and "ask_end" in marks:
            result["stt"] = marks["stt"] - marks["ask_end"]
        result["ok"] = "panel" in marks
    except asyncio.TimeoutError:
        result["error"] = "timeout"
    except Exception as exc:  # noqa: BLE001 - a failed virtual user is data, not a crash
        result["error"] = f"{type(exc).__name__}: {exc}"[:120]
    finally:
        if audio_task:
            audio_task.cancel()
        try:
            await room.disconnect()
        except Exception:
            pass
        try:
            await lk.room.delete_room(api.DeleteRoomRequest(room=room_name))
        except Exception:
            pass
    return result


async def run_step(lk, n, question, prefix, stagger, voice=False):
    print(f"\n=== {n} concurrent ===", flush=True)
    tasks = []
    for i in range(n):
        tasks.append(asyncio.ensure_future(
            one_session(lk, i, question, f"{prefix}{n}", voice)))
        if stagger:
            await asyncio.sleep(stagger)      # avoid a thundering herd on dispatch
    results = await asyncio.gather(*tasks)

    ok = [r for r in results if r["ok"]]
    print(f"completed {len(ok)}/{n}", flush=True)
    for r in results:
        if r["error"]:
            print(f"   FAILED {r['room']}: {r['error']}", flush=True)

    print(f"{'metric':8} {'p50':>7} {'p95':>7}   (seconds)")
    for key in ("join", "stt", "sources", "panel", "audio", "spoken"):
        vals = [r[key] for r in ok if key in r]
        print(f"{key:8} {fmt(pct(vals, 50))} {fmt(pct(vals, 95))}")
    if voice:
        misheard = [r for r in ok if r.get("heard") and r["heard"].strip() != question.strip()]
        none_heard = [r for r in ok if not r.get("heard")]
        print(f"STT: {len(ok) - len(misheard) - len(none_heard)}/{len(ok)} exact, "
              f"{len(misheard)} different, {len(none_heard)} not recognised")
        for r in misheard[:3]:
            print(f"   heard instead: {r['heard'][:80]}")
    return {"n": n, "ok": len(ok), "of": n,
            "audio_p95": pct([r["audio"] for r in ok if "audio" in r], 95),
            "panel_p95": pct([r["panel"] for r in ok if "panel" in r], 95)}


async def main() -> int:
    ap = argparse.ArgumentParser(description="Ramped concurrency test for Aree.")
    ap.add_argument("--steps", default="1,5,10", help="concurrency levels, comma separated")
    ap.add_argument("--question", default="ลดหย่อนบุตรได้เท่าไหร่")
    ap.add_argument("--prefix", default="loadtest")
    ap.add_argument("--stagger", type=float, default=1.0,
                    help="seconds between starting each virtual user")
    ap.add_argument("--rest", type=float, default=20.0,
                    help="seconds to let the system settle between steps")
    ap.add_argument("--voice", action="store_true",
                    help="SPEAK each question instead of typing it (loads VAD + STT)")
    args = ap.parse_args()

    steps = [int(x) for x in args.steps.split(",") if x.strip()]
    print(f"target   : {WS_URL}")
    print(f"agent    : {AGENT_NAME}")
    print(f"question : {args.question}")
    print(f"steps    : {steps}")

    if args.voice:
        global SPOKEN_PCM
        print("mode     : VOICE (synthesising the question once, shared by all users)")
        SPOKEN_PCM = await synthesize(args.question)
        print(f"audio    : {len(SPOKEN_PCM)} bytes "
              f"(~{len(SPOKEN_PCM) / 2 / SAMPLE_RATE:.1f}s of speech)")
    else:
        print("mode     : TYPED (data channel; STT is not exercised)")

    lk = api.LiveKitAPI(HTTP_URL, KEY, SECRET)
    summary = []
    try:
        for i, n in enumerate(steps):
            summary.append(await run_step(lk, n, args.question, args.prefix,
                                          args.stagger, args.voice))
            if i < len(steps) - 1:
                print(f"\n...resting {args.rest:.0f}s", flush=True)
                await asyncio.sleep(args.rest)
    finally:
        await lk.aclose()

    print("\n" + "=" * 46)
    print(f"{'conc':>4} {'ok':>7} {'audio p95':>11} {'panel p95':>11}")
    for row in summary:
        print(f"{row['n']:>4} {str(row['ok']) + '/' + str(row['of']):>7} "
              f"{fmt(row['audio_p95'])}      {fmt(row['panel_p95'])}")
    print("=" * 46)
    print("Read it as: the step where p95 audio starts climbing steeply is the ceiling.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
