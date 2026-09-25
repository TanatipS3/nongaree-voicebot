"""End-to-end test of the VOICE path: speak a question into the room and check what
Aree heard.

`e2e_livekit_turn.py` types its question over the data channel, so it never touches STT.
This one publishes a real audio track instead, which exercises the half a typed test can
never reach: microphone audio -> LiveKit -> VAD -> `ptm-asr-1` -> the graph.

The question is spoken by the project's OWN TTS, so no recording is needed and the test is
repeatable. The agent echoes whatever STT recognised as a `chat_user` event, so the script
can compare what it said against what Aree heard, word for word.

Run it INSIDE the agent container (it has the SDK, the credentials and the TTS endpoint):

    docker compose exec -T -e PYTHONIOENCODING=utf-8 agent python - < scripts/e2e_voice_turn.py
    docker compose exec -T -e PYTHONIOENCODING=utf-8 agent python - "ภาษีมูลค่าเพิ่มคิดกี่เปอร์เซ็นต์" < scripts/e2e_voice_turn.py

Side effects: a room `nongaree-voicetest` (deleted afterwards) and a memory file for user
`voicetest` on the usual 30-minute TTL.
"""

import array
import asyncio
import json
import os
import sys
import time

import httpx
from livekit import api, rtc

QUESTION = sys.argv[1] if len(sys.argv) > 1 else "ลดหย่อนบุตรได้เท่าไหร่"
ROOM = os.getenv("E2E_ROOM", "nongaree-voicetest")
AGENT_NAME = os.getenv("AGENT_NAME", "nongaree-agent")
WS_URL = os.environ["LIVEKIT_URL"]
HTTP_URL = "http" + WS_URL[2:] if WS_URL.startswith("ws") else WS_URL
KEY = os.environ["LIVEKIT_API_KEY"]
SECRET = os.environ["LIVEKIT_API_SECRET"]

TTS_BASE = os.environ["TTS_BASE_URL"].rstrip("/")
TTS_KEY = os.environ["TTS_API_KEY"]
TTS_MODEL = os.getenv("TTS_MODEL", "ptm-tts-1")
TTS_VOICE = os.getenv("TTS_VOICE", "ped")

SAMPLE_RATE = 24000          # what the TTS endpoint returns as raw PCM
FRAME_MS = 10
SAMPLES_PER_FRAME = SAMPLE_RATE * FRAME_MS // 1000
SPEECH_PEAK = 500            # int16 level that counts as speech, not silence
GREETING_QUIET_S = 1.5
GREETING_MAX_WAIT_S = 45
TRAILING_SILENCE_S = 2.0     # lets VAD decide the utterance ended
ANSWER_TIMEOUT_S = 150


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


async def synth(text: str) -> bytes:
    """Speak the question with the project's own TTS; returns raw PCM16 @ 24kHz mono."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=10.0)) as client:
        resp = await client.post(
            f"{TTS_BASE}/audio/speech",
            headers={"Authorization": f"Bearer {TTS_KEY}"},
            json={"model": TTS_MODEL, "voice": TTS_VOICE, "input": text,
                  "response_format": "pcm"},
        )
        resp.raise_for_status()
        return resp.content


async def main() -> int:
    log(f"synthesising the question with {TTS_MODEL}/{TTS_VOICE}")
    pcm = await synth(QUESTION)
    seconds = len(pcm) / 2 / SAMPLE_RATE
    log(f"question audio: {len(pcm)} bytes (~{seconds:.1f}s)")

    lk = api.LiveKitAPI(HTTP_URL, KEY, SECRET)
    room = rtc.Room()
    marks = {}
    heard = {"user": None, "panel": None, "voice": None, "route": None}
    agent_in = asyncio.Event()
    answered = asyncio.Event()
    audio_task = None

    @room.on("participant_connected")
    def _joined(p):
        if p.identity != "voicetest":
            agent_in.set()

    async def watch_agent_audio(track):
        async for ev in rtc.AudioStream(track):
            samples = array.array("h", bytes(ev.frame.data))
            if samples and max(abs(s) for s in samples) >= SPEECH_PEAK:
                marks["last_loud"] = time.perf_counter()
                if "ask_at" in marks:
                    marks.setdefault("audio", time.perf_counter())

    @room.on("track_subscribed")
    def _track(track, publication, participant):
        nonlocal audio_task
        if track.kind == rtc.TrackKind.KIND_AUDIO and audio_task is None:
            audio_task = asyncio.ensure_future(watch_agent_audio(track))

    @room.on("data_received")
    def _data(packet):
        try:
            msg = json.loads(bytes(packet.data).decode("utf-8"))
        except Exception:
            return
        kind = msg.get("type")
        if kind == "chat_user" and msg.get("text"):
            heard["user"] = msg["text"]            # <- what STT recognised
            log(f"STT heard: {msg['text']}")
        elif kind == "chat_sources":
            heard["route"] = (msg.get("diagnostics") or {}).get("route")
        elif kind == "chat_answer" and msg.get("text"):
            heard["panel"] = msg["text"]
            marks.setdefault("panel", time.perf_counter())
        elif kind == "voice_answer":
            heard["voice"] = msg.get("text") or ""
            marks.setdefault("spoken", time.perf_counter())
        if heard["panel"] is not None and heard["voice"] is not None:
            answered.set()

    try:
        await lk.room.create_room(api.CreateRoomRequest(name=ROOM))
        await lk.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(agent_name=AGENT_NAME, room=ROOM))
        token = (api.AccessToken(KEY, SECRET)
                 .with_identity("voicetest").with_name("voicetest")
                 .with_grants(api.VideoGrants(room_join=True, room=ROOM))
                 .to_jwt())
        await room.connect(WS_URL, token)
        log("connected; publishing a microphone track")

        source = rtc.AudioSource(SAMPLE_RATE, 1)
        track = rtc.LocalAudioTrack.create_audio_track("mic", source)
        await room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))

        if any(p.identity != "voicetest" for p in room.remote_participants.values()):
            agent_in.set()
        await asyncio.wait_for(agent_in.wait(), 120)
        log("agent joined; waiting for the greeting to finish")

        deadline = time.perf_counter() + GREETING_MAX_WAIT_S
        while time.perf_counter() < deadline:
            last = marks.get("last_loud")
            if last and (time.perf_counter() - last) > GREETING_QUIET_S:
                break
            await asyncio.sleep(0.25)
        await asyncio.sleep(0.5)

        marks["ask_at"] = time.perf_counter()
        log(f"speaking: {QUESTION}")
        # Real-time pacing matters: VAD decides where the utterance ends, and a burst
        # dumped at once looks nothing like speech.
        silence = b"\x00" * (SAMPLES_PER_FRAME * 2)
        step = SAMPLES_PER_FRAME * 2
        for offset in range(0, len(pcm), step):
            chunk = pcm[offset:offset + step]
            if len(chunk) < step:
                chunk = chunk + b"\x00" * (step - len(chunk))
            await source.capture_frame(
                rtc.AudioFrame(chunk, SAMPLE_RATE, 1, SAMPLES_PER_FRAME))
            await asyncio.sleep(FRAME_MS / 1000)
        for _ in range(int(TRAILING_SILENCE_S * 1000 / FRAME_MS)):
            await source.capture_frame(
                rtc.AudioFrame(silence, SAMPLE_RATE, 1, SAMPLES_PER_FRAME))
            await asyncio.sleep(FRAME_MS / 1000)
        log("finished speaking; waiting for the answer")

        try:
            await asyncio.wait_for(answered.wait(), ANSWER_TIMEOUT_S)
        except asyncio.TimeoutError:
            log("FAIL: no complete answer in time")
        await asyncio.sleep(2)
    finally:
        if audio_task:
            audio_task.cancel()
        await room.disconnect()
        try:
            await lk.room.delete_room(api.DeleteRoomRequest(room=ROOM))
        except Exception:
            pass
        await lk.aclose()

    asked_at = marks.get("ask_at")
    def since(key):
        return f"{marks[key] - asked_at:5.1f}s" if key in marks and asked_at else "    -"

    print()
    print("=" * 64)
    print("SAID   :", QUESTION)
    print("HEARD  :", heard["user"] if heard["user"] is not None else "(nothing — STT produced no transcript)")
    exact = (heard["user"] or "").strip() == QUESTION.strip()
    print("MATCH  :", "exact" if exact else "DIFFERENT — compare the two lines above")
    print("-" * 64)
    print("route  :", heard["route"], "| first audio:", since("audio"),
          "| panel:", since("panel"), "| spoken:", since("spoken"))
    print("-" * 64)
    print("SPOKEN :", (heard["voice"] or "")[:300])
    print("PANEL  :", (heard["panel"] or "")[:500])
    print("=" * 64)
    ok = bool(heard["user"]) and bool(heard["panel"])
    print("RESULT:", "PASS — speech was recognised and answered" if ok
          else "FAIL — see above")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
