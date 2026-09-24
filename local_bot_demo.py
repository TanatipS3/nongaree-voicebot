"""Standalone local Nongaree bot demo.

This serves a small browser UI with:
- Lumo-style face
- typed input
- optional browser speech recognition
- browser speech synthesis
- backend call into the existing LangGraph agent graph

It is intentionally separate from the LiveKit/Next frontend so the RAG/text
path can be tested even when the voice stack or Node runtime is not ready.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import threading
import webbrowser
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 8765


HTML = r"""<!doctype html>
<html lang="th">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Nongaree Local Bot Demo</title>
<style>
  * { box-sizing: border-box; }
  body {
    margin: 0;
    min-height: 100vh;
    background: #000;
    color: #fff;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    display: grid;
    place-items: center;
  }
  main {
    width: min(980px, calc(100vw - 32px));
    display: grid;
    grid-template-columns: minmax(260px, 390px) 1fr;
    gap: 28px;
    align-items: center;
  }
  .face-panel, .chat-panel {
    border: 1px solid rgba(255,255,255,.16);
    background: rgba(255,255,255,.035);
    border-radius: 18px;
    padding: 24px;
    min-height: 520px;
  }
  .face-panel {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 18px;
  }
  .face {
    width: 320px;
    height: 210px;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 54px;
    filter: drop-shadow(0 0 28px rgba(255,255,255,.23));
  }
  .eye {
    width: 82px;
    height: 70px;
    background: #fff;
    border-radius: 12px;
    box-shadow: 0 0 28px rgba(255,255,255,.7), 0 0 70px rgba(255,255,255,.25);
    transform-origin: center;
    transition: border-radius .18s, transform .18s, height .18s;
  }
  .mode-idle .eye { height: 70px; }
  .mode-thinking .eye { height: 56px; transform: translateY(-4px) rotate(-2deg); }
  .mode-talking .eye { animation: talk .32s infinite alternate; }
  .mode-happy .eye { height: 38px; border-radius: 50% 50% 14px 14px; transform: translateY(-8px); }
  .mode-sad .eye { height: 42px; transform: translateY(12px) rotate(2deg); opacity: .82; }
  .mode-error .eye { height: 44px; border-radius: 5px; transform: rotate(-7deg); }
  @keyframes talk {
    from { height: 58px; transform: translateY(0); }
    to { height: 82px; transform: translateY(-4px); }
  }
  .status {
    min-height: 20px;
    color: rgba(255,255,255,.58);
    letter-spacing: .12em;
    text-transform: uppercase;
    font-size: 13px;
  }
  h1 {
    margin: 0 0 6px;
    font-size: 25px;
    letter-spacing: .01em;
  }
  .sub {
    margin: 0 0 22px;
    color: rgba(255,255,255,.55);
    line-height: 1.55;
    font-family: system-ui, sans-serif;
  }
  textarea, .answer, .context {
    width: 100%;
    background: #080808;
    color: #fff;
    border: 1px solid rgba(255,255,255,.16);
    border-radius: 10px;
    padding: 14px;
    font: 15px/1.55 ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  }
  textarea {
    height: 96px;
    resize: vertical;
    outline: none;
  }
  .buttons {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    margin: 12px 0 18px;
  }
  button {
    background: #fff;
    color: #000;
    border: 1px solid #fff;
    border-radius: 999px;
    padding: 10px 18px;
    font: 700 13px ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    cursor: pointer;
  }
  button.secondary {
    background: transparent;
    color: #fff;
    border-color: rgba(255,255,255,.35);
  }
  button:disabled {
    opacity: .42;
    cursor: not-allowed;
  }
  .answer {
    min-height: 126px;
    white-space: pre-wrap;
    font-family: system-ui, sans-serif;
  }
  .meta {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    color: rgba(255,255,255,.48);
    font-size: 12px;
    margin: 10px 0;
  }
  details {
    margin-top: 12px;
    color: rgba(255,255,255,.66);
  }
  summary {
    cursor: pointer;
    margin-bottom: 8px;
  }
  .context {
    max-height: 160px;
    overflow: auto;
    font-size: 12px;
    color: rgba(255,255,255,.76);
    white-space: pre-wrap;
  }
  @media (max-width: 820px) {
    main { grid-template-columns: 1fr; padding: 16px 0; }
    .face-panel, .chat-panel { min-height: auto; }
    .face { width: 260px; height: 160px; gap: 38px; }
  }
</style>
</head>
<body>
<main>
  <section class="face-panel">
    <div id="face" class="face mode-idle">
      <div class="eye"></div>
      <div class="eye"></div>
    </div>
    <div id="status" class="status">idle</div>
  </section>
  <section class="chat-panel">
    <h1>Nongaree Local Bot Demo</h1>
    <p class="sub">Typed input goes to the existing Python graph, retrieve node, Qdrant, and LLM. Speech output uses the browser so we can test without the full LiveKit voice path first.</p>
    <textarea id="question">เงินเดือนเท่าไหร่ถึงต้องเสียภาษี?</textarea>
    <div class="buttons">
      <button id="ask">ASK</button>
      <button id="mic" class="secondary">VOICE INPUT</button>
      <button id="speak" class="secondary">SPEAK AGAIN</button>
      <button id="clear" class="secondary">CLEAR</button>
    </div>
    <div class="meta">
      <span id="route">route: n/a</span>
      <span id="latency">latency: n/a</span>
    </div>
    <div id="answer" class="answer">Answer will appear here.</div>
    <details>
      <summary>Retrieved context</summary>
      <div id="context" class="context">(empty)</div>
    </details>
  </section>
</main>
<script>
const face = document.getElementById('face');
const statusEl = document.getElementById('status');
const questionEl = document.getElementById('question');
const answerEl = document.getElementById('answer');
const contextEl = document.getElementById('context');
const routeEl = document.getElementById('route');
const latencyEl = document.getElementById('latency');
const askBtn = document.getElementById('ask');
const micBtn = document.getElementById('mic');
const speakBtn = document.getElementById('speak');
const clearBtn = document.getElementById('clear');
let lastAnswer = '';

function setMode(mode, label = mode) {
  face.className = 'face mode-' + mode;
  statusEl.textContent = label;
}

function cleanForSpeech(text) {
  return text.replace(/\[EMOTION:\w+\]/g, '').replace(/\[[^\]]+\]/g, '').trim();
}

function browserSpeak(text) {
  const clean = cleanForSpeech(text);
  if (!clean || !('speechSynthesis' in window)) return;
  window.speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(clean);
  utter.lang = 'th-TH';
  utter.rate = 1.0;
  utter.pitch = 1.08;
  utter.onstart = () => setMode('talking', 'talking');
  utter.onend = () => setMode('idle', 'idle');
  utter.onerror = () => setMode('idle', 'idle');
  window.speechSynthesis.speak(utter);
}

async function speak(text) {
  const clean = cleanForSpeech(text);
  if (!clean) return;
  try {
    setMode('talking', 'talking');
    const res = await fetch('/tts', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text: clean })
    });
    if (!res.ok) throw new Error('tts service failed');
    const blob = await res.blob();
    const audio = new Audio(URL.createObjectURL(blob));
    audio.onended = () => setMode('idle', 'idle');
    audio.onerror = () => {
      setMode('idle', 'idle');
      browserSpeak(clean);
    };
    await audio.play();
  } catch {
    browserSpeak(clean);
  }
}

async function ask() {
  const text = questionEl.value.trim();
  if (!text) return;
  askBtn.disabled = true;
  setMode('thinking', 'thinking');
  answerEl.textContent = 'กำลังคิด...';
  contextEl.textContent = '';
  routeEl.textContent = 'route: running';
  latencyEl.textContent = 'latency: running';
  try {
    const res = await fetch('/ask', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'request failed');
    lastAnswer = data.answer || '';
    answerEl.textContent = lastAnswer || '(no answer returned)';
    contextEl.textContent = data.context || '(no context returned)';
    routeEl.textContent = 'route: ' + (data.route || 'n/a');
    latencyEl.textContent = 'latency: ' + (data.latency_ms || 'n/a') + ' ms';
    setMode('happy', 'answer');
    speak(lastAnswer);
  } catch (err) {
    answerEl.textContent = String(err.message || err);
    setMode('error', 'error');
  } finally {
    askBtn.disabled = false;
  }
}

askBtn.addEventListener('click', ask);
questionEl.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') ask();
});
speakBtn.addEventListener('click', () => speak(lastAnswer || answerEl.textContent));
clearBtn.addEventListener('click', () => {
  questionEl.value = '';
  answerEl.textContent = 'Answer will appear here.';
  contextEl.textContent = '(empty)';
  setMode('idle', 'idle');
});

const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
if (!Recognition) {
  micBtn.disabled = true;
  micBtn.textContent = 'VOICE NOT SUPPORTED';
} else {
  const rec = new Recognition();
  rec.lang = 'th-TH';
  rec.interimResults = false;
  rec.continuous = false;
  rec.onstart = () => setMode('thinking', 'listening');
  rec.onresult = (event) => {
    questionEl.value = event.results[0][0].transcript;
    setMode('thinking', 'heard input');
  };
  rec.onerror = () => setMode('error', 'voice error');
  rec.onend = () => {
    if (questionEl.value.trim()) ask();
    else setMode('idle', 'idle');
  };
  micBtn.addEventListener('click', () => rec.start());
}
</script>
</body>
</html>"""


def _clean_answer(text: str) -> str:
    text = re.sub(r"\[EMOTION:\w+\]", "", text or "")
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"<think>.*$", "", text, flags=re.DOTALL)
    return text.strip()


def _wav_from_pcm(pcm: bytes, sample_rate: int = 24000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return out.getvalue()


async def _tts_wav(text: str) -> bytes:
    base_url = os.environ["TTS_BASE_URL"].rstrip("/")
    api_key = os.environ["TTS_API_KEY"]
    model = os.getenv("TTS_MODEL", "ptm-tts-1")
    voice = os.getenv("TTS_VOICE", "ped")
    async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=10.0)) as client:
        response = await client.post(
            f"{base_url}/audio/speech",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "voice": voice,
                "input": text,
                "response_format": "pcm",
            },
        )
        response.raise_for_status()
    return _wav_from_pcm(response.content)


async def _ask_graph(text: str) -> dict:
    from graph.graph import compiled_graph

    result = await compiled_graph.ainvoke(
        {
            "messages": [],
            "query": text,
            "context": "",
            "answer": "",
            "emotion": "idle",
            "route": "direct",
        }
    )
    return {
        "answer": _clean_answer(result.get("answer", "")),
        "context": result.get("context", ""),
        "route": result.get("route", ""),
        "emotion": result.get("emotion", ""),
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/tts":
            try:
                length = int(self.headers.get("content-length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                text = _clean_answer(str(payload.get("text", "")).strip())
                if not text:
                    raise ValueError("empty tts text")
                wav = asyncio.run(_tts_wav(text))
                self._send(200, wav, "audio/wav")
            except Exception as exc:
                self._send(
                    500,
                    json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8",
                )
            return

        if parsed.path != "/ask":
            self._send(404, b"not found", "text/plain")
            return
        try:
            length = int(self.headers.get("content-length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            text = str(payload.get("text", "")).strip()
            if not text:
                raise ValueError("empty question")

            import time

            t0 = time.perf_counter()
            result = asyncio.run(_ask_graph(text))
            result["latency_ms"] = f"{(time.perf_counter() - t0) * 1000:.1f}"
            self._send(
                200,
                json.dumps(result, ensure_ascii=False).encode("utf-8"),
                "application/json; charset=utf-8",
            )
        except Exception as exc:
            self._send(
                500,
                json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False).encode("utf-8"),
                "application/json; charset=utf-8",
            )

    def log_message(self, fmt: str, *args) -> None:
        print("%s - %s" % (self.address_string(), fmt % args))


def main() -> None:
    load_dotenv(ROOT / ".env")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}"
    print(f"Nongaree local bot demo: {url}")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
