#!/usr/bin/env python3
"""Create threshold-gated benchmark reports from existing generated reports."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "rag96_comparison"
FALLBACK_TEXT = "น้องอารีไม่แน่ใจในข้อมูลส่วนนี้ค่ะ แนะนำให้ติดต่อสรรพากรโดยตรงเพื่อความถูกต้องนะคะ"


def load_report(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def make_threshold_report(source: Path, label: str, threshold: float) -> Path:
    report = load_report(source)
    gated = deepcopy(report)
    gated["metadata"]["label"] = f"{label}_thr{threshold:.2f}".replace(".", "p")
    gated["metadata"]["source_report"] = str(source)
    gated["metadata"]["retrieval_threshold"] = threshold
    gated["metadata"]["threshold_method"] = (
        "Kept generated answer only when top_retrieval_score >= threshold; "
        "otherwise replaced with standard refusal."
    )

    refused = 0
    for row in gated["results"]:
        if float(row.get("top_retrieval_score") or 0.0) < threshold:
            row["generated_answer"] = FALLBACK_TEXT
            row["fallback"] = True
            row["threshold_refused"] = True
            refused += 1
        else:
            row["threshold_refused"] = False

    gated["summary"] = {
        **gated.get("summary", {}),
        "retrieval_threshold": threshold,
        "threshold_refused": refused,
        "threshold_refusal_rate": refused / len(gated["results"]) if gated["results"] else 0.0,
    }
    out = REPORT_DIR / f"{gated['metadata']['label']}_report.json"
    out.write_text(json.dumps(gated, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, action="append", default=[0.70, 0.75, 0.80])
    parser.add_argument(
        "--source",
        action="append",
        nargs=2,
        metavar=("LABEL", "REPORT_JSON"),
        default=[
            ("current_aree_rag", str(REPORT_DIR / "current_report.json")),
            ("supervisor_sent_rag", str(REPORT_DIR / "candidate_train_report.json")),
        ],
    )
    args = parser.parse_args()

    for label, source in args.source:
        for threshold in args.threshold:
            out = make_threshold_report(Path(source), label, threshold)
            print(out)


if __name__ == "__main__":
    main()
