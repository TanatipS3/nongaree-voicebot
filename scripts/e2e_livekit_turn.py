"""End-to-end smoke test of ONE Aree turn through the real LiveKit server — no browser,
no SSO, no access to the public domain needed.

It acts as a fake user: creates a throwaway room, dispatches the agent into it exactly
like /api/livekit/token does, joins, waits out the greeting, sends a typed question over
the data channel, and prints what the page would have shown (panel answer, spoken
answer, route, citations) plus whether real audio arrived on the agent's track.

Run it INSIDE the agent container, which already has the LiveKit SDK and the server
credentials in its environment (nothing is printed from them):

    docker compose exec -T agent python - < scripts/e2e_livekit_turn.py
    docker compose exec -T agent python - "ภาษีคาร์บอนเครดิตฟาร์มกุ้งคำนวณยังไง" < scripts/e2e_livekit_turn.py

Side effects: a room `nongaree-e2etest` (deleted at the end) and a conversation-memory
file for user `e2etest` (expires with the normal 30-minute TTL). The turn is served by
whichever worker is registered under AGENT_NAME — on the server that is production.
"""

import asyncio
import array
import json
import os
import sys
import time

from livekit import api, rtc

QUESTION = sys.argv[1] if len(sys.argv) > 1 else "ลดหย่อนบุตรได้เท่าไหร่"
ROOM = os.getenv("E2E_ROOM", "nongaree-e2etest")
AGENT_NAME = os.getenv("AGENT_NAME", "nongaree-agent")
WS_URL = os.environ["LIVEKIT_URL"]
HTTP_URL = "http" + WS_URL[2:] if WS_URL.startswith("ws") else WS_URL
KEY = os.environ["LIVEKIT_API_KEY"]
SECRET = os.environ["LIVEKIT_API_SECRET"]

JOIN_TIMEOUT_S = 120      # dispatch over a slow link has taken minutes before
GREETING_WAIT_S = 15      # a question sent mid-greeting is still delivered, but keep it clean
ANSWER_TIMEOUT_S = 150


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


async def main() -> int:
    lk = api.LiveKitAPI(HTTP_URL, KEY, SECRET)
    room = rtc.Room()
    state = {"panel": None, "voice": None, "route": None, "sources": None,
             "audio_frames": 0, "audio_peak": 0}
    agent_here = asyncio.Event()
    answered = asyncio.Event()
    audio_tasks: list[asyncio.Task] = []

    def is_agent(p) -> bool:
        return p.identity != "e2etest"

    @room.on("participant_connected")
    def _joined(p):
        log(f"participant joined: {p.identity}")
        if is_agent(p):
            agent_here.set()

    async def count_audio(track):
        async for ev in rtc.AudioStream(track):
            samples = array.array("h", bytes(ev.frame.data))
            state["audio_frames"] += 1
            if samples:
                state["audio_peak"] = max(state["audio_peak"], max(abs(s) for s in samples))

    @room.on("track_subscribed")
    def _track(track, publication, participant):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            log(f"subscribed to audio from {participant.identity}")
            audio_tasks.append(asyncio.ensure_future(count_audio(track)))

    @room.on("data_received")
    def _data(packet):
        try:
            msg = json.loads(bytes(packet.data).decode("utf-8"))
        except Exception:
            return
        kind = msg.get("type")
        if kind == "chat_sources":
            diag = msg.get("diagnostics") or {}
            state["route"] = diag.get("route")
            state["sources"] = len(msg.get("sources") or [])
            log(f"sources: route={state['route']} citations={state['sources']} "
                f"job={diag.get('job_id')} agent={diag.get('agent_name')}")
        elif kind == "chat_answer" and msg.get("text"):
            state["panel"] = msg["text"]
            log(f"panel answer received ({len(msg['text'])} chars)")
        elif kind == "voice_answer":
            state["voice"] = msg.get("text") or ""
            log(f"voice answer received ({len(state['voice'])} chars)")
        if state["panel"] is not None and state["voice"] is not None:
            answered.set()

    try:
        await lk.room.create_room(api.CreateRoomRequest(name=ROOM))
        await lk.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(agent_name=AGENT_NAME, room=ROOM))
        log(f"room {ROOM} created, agent '{AGENT_NAME}' dispatched via {HTTP_URL}")

        token = (api.AccessToken(KEY, SECRET)
                 .with_identity("e2etest").with_name("e2etest")
                 .with_grants(api.VideoGrants(room_join=True, room=ROOM))
                 .to_jwt())
        await room.connect(WS_URL, token)
        log("connected to LiveKit as e2etest")
        if any(is_agent(p) for p in room.remote_participants.values()):
            agent_here.set()

        try:
            await asyncio.wait_for(agent_here.wait(), JOIN_TIMEOUT_S)
        except asyncio.TimeoutError:
            log(f"FAIL: no agent joined within {JOIN_TIMEOUT_S}s "
                "(is the worker registered under AGENT_NAME?)")
            return 2

        log(f"agent is in the room; waiting {GREETING_WAIT_S}s for the greeting")
        await asyncio.sleep(GREETING_WAIT_S)

        payload = json.dumps({"type": "text_input", "text": QUESTION}, ensure_ascii=False)
        await room.local_participant.publish_data(payload.encode("utf-8"), reliable=True)
        log(f"asked: {QUESTION}")

        try:
            await asyncio.wait_for(answered.wait(), ANSWER_TIMEOUT_S)
        except asyncio.TimeoutError:
            log(f"FAIL: no complete answer within {ANSWER_TIMEOUT_S}s")
        await asyncio.sleep(3)  # let the last audio frames arrive
    finally:
        for t in audio_tasks:
            t.cancel()
        await room.disconnect()
        try:
            await lk.room.delete_room(api.DeleteRoomRequest(room=ROOM))
        except Exception:
            pass
        await lk.aclose()

    print()
    print("=" * 60)
    print("route       :", state["route"])
    print("citations   :", state["sources"])
    print("audio       :", f"{state['audio_frames']} frames, peak amplitude {state['audio_peak']}",
          "(silent!)" if state["audio_peak"] < 200 else "(real sound)")
    print("-" * 60)
    print("SPOKEN :", state["voice"])
    print("-" * 60)
    print("PANEL  :", (state["panel"] or "")[:1200])
    print("=" * 60)
    ok = bool(state["panel"]) and state["voice"] is not None and state["audio_peak"] >= 200
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
