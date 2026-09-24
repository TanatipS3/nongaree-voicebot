#!/usr/bin/env python3
"""Latency benchmark for LLM, TTS, STT, and Embedding endpoints."""

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from statistics import mean

import httpx
from dotenv import load_dotenv

load_dotenv()

ITERATIONS = 3
WAV_FILE = Path(__file__).parent / "test.wav"

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
MODELS = [m.strip() for m in os.getenv("LLM_MODELS", "").split(",") if m.strip()]
if not MODELS and os.getenv("LLM_MODEL"):
    MODELS = [os.getenv("LLM_MODEL", "")]

LLM_PROMPT = "สวัสดีครับ กรุณาแนะนำตัวสั้นๆ"
TTS_TEXT = "สวัสดีครับ ยินดีต้อนรับสู่กรมสรรพากร"
EMBED_TEXT = "ภาษีเงินได้บุคคลธรรมดา"

COL1 = 18
COL2 = 46


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _ms(v: float) -> str:
    return f"{v:.0f}ms"


def _stat(d: dict) -> str:
    return f"avg={_ms(d['avg'])}  min={_ms(d['min'])}  max={_ms(d['max'])}"


# ── LLM ──────────────────────────────────────────────────────────────────────


async def _bench_llm_once(model: str) -> dict:
    t_start = time.perf_counter()
    ttft: float | None = None
    token_count = 0

    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream(
            "POST",
            f"{LLM_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": LLM_PROMPT}],
                "stream": True,
                "max_tokens": 200,
            },
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except Exception:
                    continue
                content = (
                    chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                )
                if content:
                    if ttft is None:
                        ttft = time.perf_counter() - t_start
                    token_count += 1  # approx: 1 chunk ≈ 1 token

    total = time.perf_counter() - t_start
    return {
        "ttft_ms": (ttft or 0) * 1000,
        "total_ms": total * 1000,
        "tokens_per_sec": token_count / total if total > 0 else 0,
    }


async def _bench_llm_model(model: str) -> dict:
    results = []
    for i in range(ITERATIONS):
        print(f"    [{i + 1}/{ITERATIONS}]...", end=" ", flush=True)
        r = await _bench_llm_once(model)
        results.append(r)
        print(
            f"TTFT={r['ttft_ms']:.0f}ms  total={r['total_ms']:.0f}ms  ~{r['tokens_per_sec']:.1f} tok/s"
        )
    return {
        "ttft_ms": {
            "avg": mean(r["ttft_ms"] for r in results),
            "min": min(r["ttft_ms"] for r in results),
            "max": max(r["ttft_ms"] for r in results),
        },
        "total_ms": {
            "avg": mean(r["total_ms"] for r in results),
            "min": min(r["total_ms"] for r in results),
            "max": max(r["total_ms"] for r in results),
        },
        "tokens_per_sec": {
            "avg": mean(r["tokens_per_sec"] for r in results),
            "min": min(r["tokens_per_sec"] for r in results),
            "max": max(r["tokens_per_sec"] for r in results),
        },
    }


async def bench_llm() -> list[tuple[str, dict]]:
    model_results: list[tuple[str, dict]] = []
    for model in MODELS:
        print(f"  Model: {model}")
        try:
            result = await _bench_llm_model(model)
            model_results.append((model, result))
        except Exception as e:
            print(f"  ERROR ({model}): {e}")
    return model_results


# ── TTS ──────────────────────────────────────────────────────────────────────


async def _bench_tts_once() -> dict:
    base_url = _env("TTS_BASE_URL")
    api_key = _env("TTS_API_KEY")
    model = _env("TTS_MODEL", "ptm-tts-1")
    voice = _env("TTS_VOICE", "ped")

    t_start = time.perf_counter()
    first_byte: float | None = None
    total_bytes = 0

    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream(
            "POST",
            f"{base_url}/audio/speech",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "voice": voice,
                "input": TTS_TEXT,
                "response_format": "wav",
            },
        ) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes(chunk_size=4096):
                if chunk:
                    if first_byte is None:
                        first_byte = time.perf_counter() - t_start
                    total_bytes += len(chunk)

    total = time.perf_counter() - t_start
    # WAV: 44-byte header, 24 kHz 16-bit mono → duration = pcm_bytes / (24000 * 2)
    pcm_bytes = max(0, total_bytes - 44)
    audio_duration_ms = (pcm_bytes / (24000 * 2)) * 1000
    rtf = (audio_duration_ms / 1000) / total if total > 0 else 0

    return {
        "first_byte_ms": (first_byte or 0) * 1000,
        "total_ms": total * 1000,
        "audio_duration_ms": audio_duration_ms,
        "rtf": rtf,
    }


async def bench_tts() -> dict:
    results = []
    for i in range(ITERATIONS):
        print(f"  TTS [{i + 1}/{ITERATIONS}]...", end=" ", flush=True)
        r = await _bench_tts_once()
        results.append(r)
        print(
            f"first={r['first_byte_ms']:.0f}ms  total={r['total_ms']:.0f}ms  audio={r['audio_duration_ms']:.0f}ms  RTF={r['rtf']:.2f}x"
        )
    return {
        "first_byte_ms": {
            "avg": mean(r["first_byte_ms"] for r in results),
            "min": min(r["first_byte_ms"] for r in results),
            "max": max(r["first_byte_ms"] for r in results),
        },
        "total_ms": {
            "avg": mean(r["total_ms"] for r in results),
            "min": min(r["total_ms"] for r in results),
            "max": max(r["total_ms"] for r in results),
        },
        "audio_duration_ms": {"avg": mean(r["audio_duration_ms"] for r in results)},
        "rtf": {"avg": mean(r["rtf"] for r in results)},
    }


# ── TTS chunk-size benchmark ─────────────────────────────────────────────────

TTS_TEXTS = [
    ("5 chars", "ค่ะ"),
    ("10 chars", "สวัสดีค่ะ"),
    ("20 chars", "สวัสดีครับ ยินดีให้บริการค่ะ"),
    ("40 chars", "ดิฉันชื่ออารีค่ะ ผู้ช่วยของกรมสรรพากร"),
    ("60 chars", "ภาษีมูลค่าเพิ่มหรือแวตคือภาษีที่จัดเก็บจากสินค้าและบริการค่ะ"),
    ("80 chars", "น่าเสียดายที่พลาดกำหนดยื่นแบบค่ะ แต่ยังแก้ไขได้นะคะ ค่าปรับอยู่ที่ร้อยละสองค่ะ"),
]


async def _bench_tts_chunk_once(text: str) -> dict:
    base_url = _env("TTS_BASE_URL")
    api_key = _env("TTS_API_KEY")
    model = _env("TTS_MODEL", "ptm-tts-1")
    voice = _env("TTS_VOICE", "ped")

    t_start = time.perf_counter()
    first_byte: float | None = None

    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream(
            "POST",
            f"{base_url}/audio/speech",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "voice": voice,
                "input": text,
                "response_format": "pcm",  # PCM
            },
        ) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes(chunk_size=4096):
                if chunk and first_byte is None:
                    first_byte = time.perf_counter() - t_start

    total = time.perf_counter() - t_start
    return {
        "first_byte_ms": (first_byte or 0) * 1000,
        "total_ms": total * 1000,
    }


async def bench_tts_chunks() -> list[tuple[str, dict]]:
    chunk_results: list[tuple[str, dict]] = []
    for label, text in TTS_TEXTS:
        first_bytes, totals = [], []
        for i in range(ITERATIONS):
            print(f"  {label} [{i + 1}/{ITERATIONS}]...", end=" ", flush=True)
            try:
                r = await _bench_tts_chunk_once(text)
                first_bytes.append(r["first_byte_ms"])
                totals.append(r["total_ms"])
                print(f"first={r['first_byte_ms']:.0f}ms  total={r['total_ms']:.0f}ms")
            except Exception as e:
                print(f"ERROR: {e or type(e).__name__}")
        if not first_bytes:
            continue
        chunk_results.append(
            (
                label,
                {
                    "first_byte_ms": {
                        "avg": mean(first_bytes),
                        "min": min(first_bytes),
                        "max": max(first_bytes),
                    },
                    "total_ms": {
                        "avg": mean(totals),
                        "min": min(totals),
                        "max": max(totals),
                    },
                },
            )
        )
    return chunk_results


def print_tts_chunks(chunk_results: list[tuple[str, dict]]) -> None:
    if not chunk_results:
        return

    C0, C1, C2 = 13, 14, 14
    total_w = C0 + C1 + C2 + 10

    def hline(l, m, r, f="─"):
        print(f"{l}{f * (C0 + 2)}{m}{f * (C1 + 2)}{m}{f * (C2 + 2)}{r}")

    def row(a, b, c):
        print(f"│ {a:<{C0}} │ {b:<{C1}} │ {c:<{C2}} │")

    print(f"\n┌{'─' * (total_w - 2)}┐")
    title = f"  TTS CHUNK SIZE BENCHMARK  —  {ITERATIONS} iterations per length"
    print(f"│{title:<{total_w - 2}}│")
    hline("├", "┬", "┤")
    row("Text Length", "First Byte", "Total")
    hline("├", "┼", "┤")
    for label, data in chunk_results:
        row(label, _ms(data["first_byte_ms"]["avg"]), _ms(data["total_ms"]["avg"]))
    hline("└", "┴", "┘")


# ── STT ──────────────────────────────────────────────────────────────────────


async def _bench_stt_once(wav_bytes: bytes) -> dict:
    base_url = _env("STT_BASE_URL")
    api_key = _env("STT_API_KEY")
    model = _env("STT_MODEL", "ptm-asr-1")

    t_start = time.perf_counter()
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{base_url}/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": ("test.wav", wav_bytes, "audio/wav")},
            data={"model": model},
        )
        resp.raise_for_status()
    total = time.perf_counter() - t_start
    transcript = resp.json().get("text", "")
    return {"total_ms": total * 1000, "transcript": transcript}


async def bench_stt() -> dict:
    wav_bytes = WAV_FILE.read_bytes()
    results = []
    for i in range(ITERATIONS):
        print(f"  STT [{i + 1}/{ITERATIONS}]...", end=" ", flush=True)
        r = await _bench_stt_once(wav_bytes)
        results.append(r)
        print(f"total={r['total_ms']:.0f}ms  transcript={r['transcript'][:40]!r}")
    return {
        "total_ms": {
            "avg": mean(r["total_ms"] for r in results),
            "min": min(r["total_ms"] for r in results),
            "max": max(r["total_ms"] for r in results),
        },
        "transcript": results[-1]["transcript"],
    }


# ── Embedding ────────────────────────────────────────────────────────────────


async def _bench_embed_once() -> dict:
    base_url = _env("EMBEDDING_BASE_URL")
    api_key = _env("EMBEDDING_API_KEY")
    model = _env("EMBEDDING_MODEL")

    t_start = time.perf_counter()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{base_url}/embeddings",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "input": EMBED_TEXT},
        )
        resp.raise_for_status()
    total = time.perf_counter() - t_start
    vector = resp.json()["data"][0]["embedding"]
    return {"total_ms": total * 1000, "dimensions": len(vector)}


async def bench_embed() -> dict:
    results = []
    for i in range(ITERATIONS):
        print(f"  Embed [{i + 1}/{ITERATIONS}]...", end=" ", flush=True)
        r = await _bench_embed_once()
        results.append(r)
        print(f"total={r['total_ms']:.0f}ms  dims={r['dimensions']}")
    return {
        "total_ms": {
            "avg": mean(r["total_ms"] for r in results),
            "min": min(r["total_ms"] for r in results),
            "max": max(r["total_ms"] for r in results),
        },
        "dimensions": results[0]["dimensions"],
    }


# ── Table output ─────────────────────────────────────────────────────────────


def _row(label: str, value: str) -> None:
    print(f"│ {label:<{COL1}} │ {value:<{COL2}} │")


def _divider() -> None:
    print(f"├{'─' * (COL1 + 2)}┼{'─' * (COL2 + 2)}┤")


def print_llm_comparison(model_results: list[tuple[str, dict]]) -> None:
    if not model_results:
        return

    MC = max(len("Model"), max(len(m) for m, _ in model_results)) + 2
    TC, LC, SC = 12, 12, 16

    def hline(l, m, r, f="─"):
        print(
            f"{l}{f * (MC + 2)}{m}{f * (TC + 2)}{m}{f * (LC + 2)}{m}{f * (SC + 2)}{r}"
        )

    def row(a, b, c, d):
        print(f"│ {a:<{MC}} │ {b:<{TC}} │ {c:<{LC}} │ {d:<{SC}} │")

    total_w = MC + TC + LC + SC + 11
    print(f"\n┌{'─' * (total_w - 2)}┐")
    title = f"  LLM BENCHMARK COMPARISON  —  {ITERATIONS} iterations per model"
    print(f"│{title:<{total_w - 2}}│")
    hline("├", "┬", "┤")
    row("Model", "TTFT (avg)", "Total (avg)", "Tokens/sec")
    hline("├", "┼", "┤")
    for model, data in model_results:
        row(
            model,
            _ms(data["ttft_ms"]["avg"]),
            _ms(data["total_ms"]["avg"]),
            f"{data['tokens_per_sec']['avg']:.1f} tok/s",
        )
    hline("└", "┴", "┘")


def print_results(*, tts=None, stt=None, embed=None) -> None:
    sections = []
    if tts:
        sections.append(("tts", tts))
    if stt:
        sections.append(("stt", stt))
    if embed:
        sections.append(("embed", embed))

    if not sections:
        return

    total_w = COL1 + COL2 + 7
    print(f"\n┌{'─' * (total_w - 2)}┐")
    print(
        f"│{'  LATENCY BENCHMARK RESULTS  —  ' + str(ITERATIONS) + ' iterations per service':<{total_w - 2}}│"
    )
    print(f"├{'─' * (COL1 + 2)}┬{'─' * (COL2 + 2)}┤")

    for idx, (kind, data) in enumerate(sections):
        if kind == "tts":
            _row("TTS First Byte", _stat(data["first_byte_ms"]))
            _row("TTS Total", _stat(data["total_ms"]))
            _row("TTS Audio Dur", f"avg={_ms(data['audio_duration_ms']['avg'])}")
            _row(
                "TTS RTF", f"avg={data['rtf']['avg']:.2f}x  (<1 = slower than realtime)"
            )
        elif kind == "stt":
            _row("STT Total", _stat(data["total_ms"]))
            _row("STT Transcript", data["transcript"][: COL2 - 2])
        elif kind == "embed":
            _row("Embed Total", _stat(data["total_ms"]))
            _row("Embed Dims", str(data["dimensions"]))

        if idx < len(sections) - 1:
            _divider()

    print(f"└{'─' * (COL1 + 2)}┴{'─' * (COL2 + 2)}┘")


# ── Main ──────────────────────────────────────────────────────────────────────


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Latency benchmark for LLM/TTS/STT/Embedding endpoints"
    )
    parser.add_argument("--llm", action="store_true", help="Benchmark LLM only")
    parser.add_argument("--tts", action="store_true", help="Benchmark TTS only")
    parser.add_argument(
        "--tts-chunks",
        action="store_true",
        help="Benchmark TTS latency across chunk sizes",
    )
    parser.add_argument("--stt", action="store_true", help="Benchmark STT only")
    parser.add_argument("--embed", action="store_true", help="Benchmark Embedding only")
    args = parser.parse_args()

    run_all = not any([args.llm, args.tts, args.tts_chunks, args.stt, args.embed])

    llm_results: list[tuple[str, dict]] = []
    tts_chunks_result: list[tuple[str, dict]] = []
    tts_result = stt_result = embed_result = None

    if args.llm or run_all:
        if not MODELS:
            print("\nSKIP LLM: LLM_MODELS (or LLM_MODEL) not set in .env")
        else:
            print(
                f"\nRunning LLM benchmark — {len(MODELS)} model(s), {ITERATIONS} iterations each..."
            )
            llm_results = await bench_llm()

    if args.tts or run_all:
        print(f"\nRunning TTS benchmark ({ITERATIONS} iterations)...")
        try:
            tts_result = await bench_tts()
        except Exception as e:
            print(f"  ERROR: {e}")

    if args.tts_chunks:
        print(
            f"\nRunning TTS chunk-size benchmark ({ITERATIONS} iterations per length)..."
        )
        try:
            tts_chunks_result = await bench_tts_chunks()
        except Exception as e:
            print(f"  ERROR: {e}")

    if args.stt or run_all:
        print(f"\nRunning STT benchmark ({ITERATIONS} iterations)...")
        if not WAV_FILE.exists():
            print(f"  SKIP: {WAV_FILE} not found")
        else:
            try:
                stt_result = await bench_stt()
            except Exception as e:
                print(f"  ERROR: {e}")

    if args.embed or run_all:
        print(f"\nRunning Embedding benchmark ({ITERATIONS} iterations)...")
        if not _env("EMBEDDING_BASE_URL"):
            print("  SKIP: EMBEDDING_BASE_URL not set in .env")
        else:
            try:
                embed_result = await bench_embed()
            except Exception as e:
                print(f"  ERROR: {e}")

    print_llm_comparison(llm_results)
    print_results(tts=tts_result, stt=stt_result, embed=embed_result)
    print_tts_chunks(tts_chunks_result)


if __name__ == "__main__":
    asyncio.run(main())
