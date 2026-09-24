#!/usr/bin/env python3
"""Summarize a benchmark report and semantic/LLM judge output.

The LLM judge can be noisy. If generated_answer is exactly the same as
expected_answer after normalization, this script counts it as correct
regardless of the judge label and reports both raw and corrected numbers.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from statistics import mean


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def bucket(label: str) -> str:
    label = (label or "unknown").strip().lower()
    if label == "correct":
        return "correct"
    if label.startswith("partial"):
        return "partial"
    return "incorrect"


def pct(value: int, total: int) -> str:
    return f"{value / total * 100:.1f}%"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--semantic-jsonl", type=Path)
    args = parser.parse_args()

    payload = json.loads(args.report.read_text(encoding="utf-8"))
    rows = payload["results"] if isinstance(payload, dict) and "results" in payload else payload
    by_id = {row["dataset_id"]: row for row in rows}

    semantic_path = args.semantic_jsonl or args.report.with_name(
        args.report.stem + ".semantic_eval.jsonl"
    )
    semantic_rows = []
    if semantic_path.exists():
        semantic_rows = [
            json.loads(line)
            for line in semantic_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    raw_counts: Counter[str] = Counter()
    corrected_counts: Counter[str] = Counter()
    exact_matches = 0
    semantic_scores: list[float] = []
    char_scores: list[float] = []
    corrected_rows = []
    llm_rows = []

    for eval_row in semantic_rows:
        dataset_id = eval_row["dataset_id"]
        report_row = by_id[dataset_id]
        raw = bucket(eval_row.get("judge_verdict", "unknown"))
        raw_counts[raw] += 1

        is_exact = normalize(report_row["generated_answer"]) == normalize(report_row["expected_answer"])
        if is_exact:
            exact_matches += 1
        corrected = "correct" if is_exact else raw
        corrected_counts[corrected] += 1
        semantic_scores.append(float(eval_row.get("semantic_score", 0.0)))
        char_scores.append(float(eval_row.get("char_ngram_score", 0.0)))
        if raw != corrected:
            corrected_rows.append((dataset_id, raw, corrected))
        llm_rows.append(
            {
                "dataset_id": dataset_id,
                "question": report_row["question"],
                "raw_llm_judge": raw,
                "raw_llm_judge_detail": eval_row.get("judge_verdict", "unknown"),
                "exact_match": is_exact,
                "corrected_judge": corrected,
                "semantic_score": eval_row.get("semantic_score", 0.0),
                "char_ngram_score": eval_row.get("char_ngram_score", 0.0),
            }
        )

    total = len(semantic_rows) or len(rows)
    used_extractive = sum(1 for row in rows if row.get("used_extractive_exact"))

    print(f"Report: {args.report}")
    print(f"Questions: {len(rows)}")
    print(f"Extractive exact answers used: {used_extractive}/{len(rows)}")
    print(f"Generated exactly equals expected: {exact_matches}/{len(rows)}")
    if semantic_scores:
        print(f"Semantic mean: {mean(semantic_scores):.3f}")
        print(f"Semantic >= 0.80: {sum(score >= 0.8 for score in semantic_scores)}/{total}")
    if char_scores:
        print(f"Char-ngram mean: {mean(char_scores):.3f}")

    print("\nRaw OSS-120B judge:")
    for key in ("correct", "partial", "incorrect"):
        print(f"  {key:<9} {raw_counts[key]:>3} / {total} ({pct(raw_counts[key], total)})")

    print("\nCorrected judge with exact-match override:")
    for key in ("correct", "partial", "incorrect"):
        print(
            f"  {key:<9} {corrected_counts[key]:>3} / {total} "
            f"({pct(corrected_counts[key], total)})"
        )

    if corrected_rows:
        print("\nRows corrected because generated answer exactly matched expected:")
        for dataset_id, raw, corrected in corrected_rows:
            print(f"  {dataset_id}: {raw} -> {corrected}")

    if llm_rows:
        print("\nPer-question LLM judge output:")
        print(
            f"{'dataset_id':22} {'raw_llm':10} {'detail':22} "
            f"{'exact':5} {'final':10} {'semantic':>8}"
        )
        print("-" * 86)
        for row in llm_rows:
            print(
                f"{row['dataset_id']:22} "
                f"{row['raw_llm_judge']:10} "
                f"{row['raw_llm_judge_detail'][:22]:22} "
                f"{str(row['exact_match']).lower():5} "
                f"{row['corrected_judge']:10} "
                f"{float(row['semantic_score']):>8.3f}"
            )

    summary_path = args.report.with_name(args.report.stem + ".llm_judge_summary.json")
    csv_path = args.report.with_name(args.report.stem + ".llm_judge_results.csv")
    summary = {
        "report": str(args.report),
        "questions": len(rows),
        "extractive_exact_answers_used": used_extractive,
        "exact_generated_equals_expected": exact_matches,
        "semantic_mean": mean(semantic_scores) if semantic_scores else None,
        "semantic_ge_0_80": sum(score >= 0.8 for score in semantic_scores),
        "char_ngram_mean": mean(char_scores) if char_scores else None,
        "raw_oss_120b_judge": dict(raw_counts),
        "corrected_judge_with_exact_match_override": dict(corrected_counts),
        "corrected_rows": [
            {"dataset_id": dataset_id, "from": raw, "to": corrected}
            for dataset_id, raw, corrected in corrected_rows
        ],
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "dataset_id",
                "question",
                "raw_llm_judge",
                "raw_llm_judge_detail",
                "exact_match",
                "corrected_judge",
                "semantic_score",
                "char_ngram_score",
            ],
        )
        writer.writeheader()
        writer.writerows(llm_rows)

    print(f"\nLLM judge summary JSON: {summary_path}")
    print(f"LLM judge per-question CSV: {csv_path}")


if __name__ == "__main__":
    main()
