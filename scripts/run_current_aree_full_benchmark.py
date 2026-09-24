#!/usr/bin/env python3
"""Run the current Aree RAG 96-question benchmark end to end.

This wraps the same flow used for the latest check:
1. Generate answers from the current Qdrant collection.
2. Run semantic similarity.
3. Run OSS-120B LLM judge.
4. Export raw/corrected LLM judge summary files.

Example:
    python3 scripts/run_current_aree_full_benchmark.py
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCH = Path("/Users/max/Downloads/bench_dataset_test_96.jsonl")
DEFAULT_JUDGE_PACKAGE = Path("/Users/max/Downloads/semantic_eval_llm_judge")
DEFAULT_COLLECTION = "thai_tax_kb"
DEFAULT_LABEL = "current_aree_rag"
DEFAULT_JUDGE_MODEL = "ptm-oss-120b"
DEFAULT_EMBED_MODEL = "vllm-BAAI/bge-m3"


def load_env(path: Path) -> dict[str, str]:
    env = os.environ.copy()
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return env


def run(cmd: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    print("\n$ " + " ".join(shlex.quote(part) for part in cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bench", type=Path, default=DEFAULT_BENCH)
    parser.add_argument("--judge-package", type=Path, default=DEFAULT_JUDGE_PACKAGE)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--label", default=DEFAULT_LABEL)
    parser.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    parser.add_argument("--embed-model", default=DEFAULT_EMBED_MODEL)
    parser.add_argument("--judge-workers", type=int, default=8)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "reports" / f"rag96_rerun_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
    )
    args = parser.parse_args()

    if not args.bench.exists():
        raise SystemExit(f"Benchmark file not found: {args.bench}")
    if not args.judge_package.exists():
        raise SystemExit(f"Semantic eval package not found: {args.judge_package}")

    env = load_env(ROOT / ".env")
    env["EMBED_MODEL"] = args.embed_model
    env["EMBED_BASE_URL"] = env.get("EMBEDDING_BASE_URL", env.get("EMBED_BASE_URL", ""))
    env["JUDGE_MODEL"] = args.judge_model

    threshold = env.get("RAG_SCORE_THRESHOLD", "0")
    print(f"Active env RAG_SCORE_THRESHOLD={threshold}", flush=True)
    print(f"Output directory: {args.output_dir}", flush=True)

    run(
        [
            sys.executable,
            "scripts/compare_rag_benchmark_96.py",
            "--bench",
            str(args.bench),
            "--collection",
            f"{args.label}:{args.collection}",
            "--output-dir",
            str(args.output_dir),
        ],
        cwd=ROOT,
        env=env,
    )

    report_path = args.output_dir / f"{args.label}_report.json"
    run(
        [
            sys.executable,
            "scripts/run_semantic_eval.py",
            "--report",
            str(report_path),
            "--questions",
            str(args.bench),
            "--judge",
            "--judge-workers",
            str(args.judge_workers),
        ],
        cwd=args.judge_package,
        env=env,
    )

    run(
        [
            sys.executable,
            "scripts/summarize_benchmark_result.py",
            "--report",
            str(report_path),
        ],
        cwd=ROOT,
        env=env,
    )

    print("\nDone.", flush=True)
    print(f"Report JSON: {report_path}", flush=True)
    print(f"Semantic CSV: {report_path.with_name(report_path.stem + '.semantic_eval.csv')}", flush=True)
    print(f"Semantic JSONL: {report_path.with_name(report_path.stem + '.semantic_eval.jsonl')}", flush=True)
    print(
        f"LLM judge summary JSON: {report_path.with_name(report_path.stem + '.llm_judge_summary.json')}",
        flush=True,
    )
    print(
        f"LLM judge per-question CSV: {report_path.with_name(report_path.stem + '.llm_judge_results.csv')}",
        flush=True,
    )
    print(f"HTML: {args.output_dir / 'rag96_comparison.html'}", flush=True)


if __name__ == "__main__":
    main()
