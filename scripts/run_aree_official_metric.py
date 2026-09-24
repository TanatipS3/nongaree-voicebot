#!/usr/bin/env python3
"""Print a supervisor-style official metric table for Aree RAG reports.

This script does not generate answers or call the judge. It summarizes an
existing benchmark report plus an existing judge output file, so the displayed
numbers are reproducible and easy to compare with the supervisor terminal view.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "rag96_comparison"

REFUSAL_MARKERS = (
    "ไม่แน่ใจ",
    "ไม่มีข้อมูล",
    "ติดต่อสรรพากร",
    "ข้อมูลไม่เพียงพอ",
    "ไม่สามารถตอบ",
)


def is_refusal(text: str) -> bool:
    return any(marker in (text or "") for marker in REFUSAL_MARKERS)


def bucket(verdict: str) -> str:
    verdict = (verdict or "unknown").strip().lower()
    if verdict == "correct":
        return "correct"
    if verdict == "incorrect" or verdict == "unknown":
        return "incorrect"
    if verdict.startswith("partial"):
        return "partial"
    return "incorrect"


def load_report(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload["results"] if isinstance(payload, dict) and "results" in payload else payload
    return list(rows)


def load_judge_buckets(path: Path, judge: str) -> dict[str, str]:
    buckets: dict[str, str] = {}
    with path.open(encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            row = json.loads(line)
            dataset_id = row["dataset_id"]
            if "buckets" in row and judge in row["buckets"]:
                buckets[dataset_id] = bucket(row["buckets"][judge])
            elif "judge_verdict" in row:
                buckets[dataset_id] = bucket(row["judge_verdict"])
            elif "per_judge" in row and judge in row["per_judge"]:
                buckets[dataset_id] = bucket(row["per_judge"][judge])
            else:
                buckets[dataset_id] = "incorrect"
    return buckets


def pct(n: int, total: int) -> str:
    return f"{(n / total * 100):.1f}%"


def summarize(config: str, report_path: Path, judge_path: Path, judge: str) -> dict[str, Any]:
    rows = load_report(report_path)
    judge_buckets = load_judge_buckets(judge_path, judge)
    counts = Counter(judge_buckets.get(row["dataset_id"], "incorrect") for row in rows)
    missing_judges = [row["dataset_id"] for row in rows if row["dataset_id"] not in judge_buckets]
    under_ref = sum(
        1
        for row in rows
        if is_refusal(row.get("generated_answer", ""))
        and not is_refusal(row.get("expected_answer", ""))
    )
    clean = "yes" if not missing_judges else "no"
    return {
        "config": config,
        "n": len(rows),
        "correct": counts["correct"],
        "incorrect": counts["incorrect"],
        "partial": counts["partial"],
        "under_ref": under_ref,
        "clean": clean,
        "missing_judges": missing_judges,
    }


def print_table(rows: list[dict[str, Any]], judge: str) -> None:
    print(f"Locked judge set: {judge} (single judge)")
    print()
    print(f"{'config':28} {'n':>4} {'correct':>15} {'incorrect':>15} {'partial':>9} {'under-ref':>10} {'clean':>7}")
    print("-" * 88)
    for row in rows:
        n = row["n"]
        correct = f"{row['correct']} {pct(row['correct'], n)}"
        incorrect = f"{row['incorrect']} {pct(row['incorrect'], n)}"
        print(
            f"{row['config']:<28} "
            f"{n:>4} "
            f"{correct:>15} "
            f"{incorrect:>15} "
            f"{row['partial']:>9} "
            f"{row['under_ref']:>10} "
            f"{row['clean']:>7}"
        )
    print()
    print("Targets: correct >= 50%, incorrect <= 25%, under-refusal = 0")
    print("'clean'=yes means every question has a judge verdict.")
    print("Note: this is OSS-120B only because the supervisor clarified to use only ptm-oss-120b.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--judge", default="ptm-oss-120b")
    parser.add_argument(
        "--config",
        action="append",
        nargs=3,
        metavar=("NAME", "REPORT_JSON", "JUDGE_JSONL"),
        help="Add one table row. Can be repeated.",
    )
    args = parser.parse_args()

    configs = args.config or [
        (
            "current_base",
            str(REPORT_DIR / "current_report.json"),
            str(REPORT_DIR / "current_report.judge_ensemble.jsonl"),
        ),
        (
            "current_thr0.50",
            str(REPORT_DIR / "current_aree_rag_thr0p50_report.json"),
            str(REPORT_DIR / "current_aree_rag_thr0p50_report.judge_ensemble.jsonl"),
        ),
        (
            "current_thr0.70",
            str(REPORT_DIR / "current_aree_rag_thr0p70_report.json"),
            str(REPORT_DIR / "current_aree_rag_thr0p70_report.judge_ensemble.jsonl"),
        ),
        (
            "current_thr0.75",
            str(REPORT_DIR / "current_aree_rag_thr0p75_report.json"),
            str(REPORT_DIR / "current_aree_rag_thr0p75_report.judge_ensemble.jsonl"),
        ),
        (
            "current_thr0.80",
            str(REPORT_DIR / "current_aree_rag_thr0p80_report.json"),
            str(REPORT_DIR / "current_aree_rag_thr0p80_report.judge_ensemble.jsonl"),
        ),
        (
            "supervisor_base",
            str(REPORT_DIR / "candidate_train_report.json"),
            str(REPORT_DIR / "candidate_train_report.judge_ensemble.jsonl"),
        ),
        (
            "supervisor_thr0.50",
            str(REPORT_DIR / "supervisor_sent_rag_thr0p50_report.json"),
            str(REPORT_DIR / "supervisor_sent_rag_thr0p50_report.judge_ensemble.jsonl"),
        ),
        (
            "supervisor_thr0.70",
            str(REPORT_DIR / "supervisor_sent_rag_thr0p70_report.json"),
            str(REPORT_DIR / "supervisor_sent_rag_thr0p70_report.judge_ensemble.jsonl"),
        ),
        (
            "supervisor_thr0.75",
            str(REPORT_DIR / "supervisor_sent_rag_thr0p75_report.json"),
            str(REPORT_DIR / "supervisor_sent_rag_thr0p75_report.judge_ensemble.jsonl"),
        ),
        (
            "supervisor_thr0.80",
            str(REPORT_DIR / "supervisor_sent_rag_thr0p80_report.json"),
            str(REPORT_DIR / "supervisor_sent_rag_thr0p80_report.judge_ensemble.jsonl"),
        ),
    ]
    rows = [
        summarize(name, Path(report), Path(judge_jsonl), args.judge)
        for name, report, judge_jsonl in configs
    ]
    print_table(rows, args.judge)


if __name__ == "__main__":
    main()
