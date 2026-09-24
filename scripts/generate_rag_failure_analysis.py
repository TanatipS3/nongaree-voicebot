#!/usr/bin/env python3
"""Render failure analysis for RAG 96 semantic judge results."""

from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "rag96_comparison"
OUTPUT = REPORT_DIR / "rag96_failure_analysis.html"
REPORTS = [
    ("current", "Current RAG", REPORT_DIR / "current_report.json"),
    ("candidate_train", "New Fair RAG", REPORT_DIR / "candidate_train_report.json"),
    ("improved_merged", "Improved Merged RAG", REPORT_DIR / "improved_merged_report.json"),
    ("candidate_all_debug", "New Debug/All RAG", REPORT_DIR / "candidate_all_debug_report.json"),
]


def esc(value: Any) -> str:
    return html.escape(str(value or ""))


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_semantic(path: Path) -> dict[str, dict[str, Any]]:
    rows = {}
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as file:
        for line in file:
            if line.strip():
                row = json.loads(line)
                rows[row["dataset_id"]] = row
    return rows


def verdict_bucket(verdict: str) -> str:
    if verdict == "correct":
        return "correct"
    if verdict.startswith("partial:"):
        return "partial"
    return verdict or "unknown"


def classify_failure(row: dict[str, Any], sem: dict[str, Any]) -> tuple[str, str]:
    verdict = sem.get("judge_verdict", "")
    semantic = float(sem.get("semantic_score", 0.0) or 0.0)
    top_score = float(row.get("top_retrieval_score", 0.0) or 0.0)
    generated = str(row.get("generated_answer", ""))
    retrieved = row.get("retrieved_context_preview") or []

    if "ไม่แน่ใจ" in generated or not generated.strip():
        return (
            "retrieval / missing exact knowledge",
            "The answer refused. Check whether the correct source exists and whether top-k retrieval is too strict.",
        )
    if top_score < 0.70:
        return (
            "retrieval ranking",
            "Top retrieval score is below 0.70. Add query expansions, metadata, or reranking for this topic.",
        )
    if top_score >= 0.80 and semantic < 0.70:
        return (
            "wrong or broad top context",
            "The retriever is confident but the answer is semantically far from expected. Inspect the top source and metadata.",
        )
    if verdict.startswith("partial:") and semantic >= 0.80:
        return (
            "generation completeness",
            "The answer is close but missing conditions, numbers, or scope. Tighten generation instructions for exact details.",
        )
    if verdict == "incorrect" and semantic >= 0.80:
        return (
            "judge-sensitive / scope mismatch",
            "Semantic score is high but judge rejected it. Review for overbroad caveats, missing exact scope, or judge noise.",
        )
    if retrieved and top_score >= 0.70:
        return (
            "generation or source extraction",
            "Relevant-looking context was retrieved, but the answer did not match enough. Review prompt and source chunk quality.",
        )
    return (
        "unknown",
        "Manual review needed.",
    )


def row_html(row: dict[str, Any], sem: dict[str, Any]) -> str:
    category, fix = classify_failure(row, sem)
    retrieved = row.get("retrieved_context_preview") or []
    top = retrieved[0] if retrieved else {}
    verdict = sem.get("judge_verdict", "not run")
    semantic = sem.get("semantic_score")
    semantic_text = "not run" if semantic is None else f"{semantic:.3f}"
    return f"""
    <tr>
      <td>
        <strong>{esc(row.get('dataset_id'))}</strong><br>
        <span>{esc(row.get('domain_name'))}</span>
      </td>
      <td>{esc(row.get('question'))}</td>
      <td>
        <strong>{esc(verdict)}</strong><br>
        semantic {semantic_text}<br>
        char {float(row.get('answer_similarity', 0.0)):.3f}<br>
        retrieval {float(row.get('top_retrieval_score', 0.0)):.3f}
      </td>
      <td>
        <strong>{esc(category)}</strong>
        <p>{esc(fix)}</p>
      </td>
      <td>
        <details open><summary>Generated</summary><p>{esc(row.get('generated_answer'))}</p></details>
        <details><summary>Expected</summary><p>{esc(row.get('expected_answer'))}</p></details>
        <details><summary>Top retrieved source</summary>
          <p><strong>{esc(top.get('record_id'))}</strong><br>{esc(top.get('title'))}<br><br>{esc(top.get('answer_preview'))}</p>
        </details>
      </td>
    </tr>
    """


def build_section(label: str, title: str, report_path: Path) -> str:
    report = load_json(report_path)
    semantic = load_semantic(report_path.with_name(report_path.stem + ".semantic_eval.jsonl"))
    rows = report["results"]
    failures = [
        row
        for row in rows
        if verdict_bucket(semantic.get(row["dataset_id"], {}).get("judge_verdict", "")) != "correct"
    ]
    failures.sort(
        key=lambda row: (
            semantic.get(row["dataset_id"], {}).get("judge_verdict", ""),
            semantic.get(row["dataset_id"], {}).get("semantic_score", 0.0),
        )
    )

    counts = Counter(
        verdict_bucket(semantic.get(row["dataset_id"], {}).get("judge_verdict", "unknown"))
        for row in rows
    )
    categories = Counter(
        classify_failure(row, semantic.get(row["dataset_id"], {}))[0]
        for row in failures
    )
    sem_scores = [
        semantic[row["dataset_id"]]["semantic_score"]
        for row in rows
        if row["dataset_id"] in semantic
    ]
    summary_cards = f"""
    <div class="metrics">
      <div><span>Total</span><strong>{len(rows)}</strong></div>
      <div><span>Correct</span><strong>{counts.get('correct', 0)} ({pct(counts.get('correct', 0) / len(rows))})</strong></div>
      <div><span>Partial</span><strong>{counts.get('partial', 0)} ({pct(counts.get('partial', 0) / len(rows))})</strong></div>
      <div><span>Incorrect</span><strong>{counts.get('incorrect', 0)} ({pct(counts.get('incorrect', 0) / len(rows))})</strong></div>
      <div><span>Mean semantic</span><strong>{mean(sem_scores):.3f}</strong></div>
    </div>
    """
    category_rows = "".join(
        f"<tr><td>{esc(name)}</td><td>{count}</td></tr>"
        for name, count in categories.most_common()
    )
    failure_rows = "".join(row_html(row, semantic.get(row["dataset_id"], {})) for row in failures)
    return f"""
    <section id="{esc(label)}">
      <h2>{esc(title)}</h2>
      {summary_cards}
      <h3>Failure Types</h3>
      <table class="compact"><thead><tr><th>Type</th><th>Count</th></tr></thead><tbody>{category_rows}</tbody></table>
      <h3>Partial / Incorrect Cases</h3>
      <table>
        <thead>
          <tr>
            <th>ID</th><th>Question</th><th>Scores</th><th>Likely Cause</th><th>Evidence</th>
          </tr>
        </thead>
        <tbody>{failure_rows}</tbody>
      </table>
    </section>
    """


def main() -> None:
    sections = [build_section(label, title, path) for label, title, path in REPORTS]
    OUTPUT.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RAG 96 Failure Analysis</title>
  <style>
    :root {{
      --ink: #112936;
      --muted: #637b88;
      --line: #b7ddea;
      --soft: #edf9fd;
      --panel: #f8fdff;
      --accent: #23799b;
    }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: #fff;
    }}
    main {{
      max-width: 1500px;
      margin: 0 auto;
      padding: 32px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 32px;
    }}
    h2 {{
      margin-top: 42px;
      border-top: 2px solid var(--line);
      padding-top: 24px;
    }}
    h3 {{
      margin-top: 24px;
    }}
    .muted, span {{
      color: var(--muted);
    }}
    nav {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin: 24px 0;
    }}
    nav a {{
      color: var(--accent);
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 8px 12px;
      text-decoration: none;
      font-weight: 700;
    }}
    .notice {{
      border: 1px solid var(--line);
      background: var(--soft);
      border-radius: 8px;
      padding: 16px;
      line-height: 1.5;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 12px;
      margin: 16px 0;
    }}
    .metrics div {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
    }}
    .metrics span {{
      display: block;
      font-size: 13px;
      margin-bottom: 6px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 12px 0 28px;
      font-size: 14px;
    }}
    .compact {{
      max-width: 680px;
    }}
    th, td {{
      border: 1px solid var(--line);
      padding: 10px;
      vertical-align: top;
    }}
    th {{
      background: var(--soft);
      text-align: left;
    }}
    td p {{
      line-height: 1.45;
    }}
    details p {{
      white-space: pre-wrap;
      max-height: 260px;
      overflow: auto;
      background: #fff;
      border: 1px solid #d5edf5;
      padding: 8px;
      border-radius: 6px;
    }}
    summary {{
      cursor: pointer;
      color: var(--accent);
      font-weight: 700;
    }}
  </style>
</head>
<body>
  <main>
    <h1>RAG 96 Failure Analysis</h1>
    <p class="muted">Generated from semantic eval outputs in {esc(REPORT_DIR)}.</p>
    <div class="notice">
      This report is for improvement planning. It lists only non-correct judge cases and assigns a likely failure type using retrieval score, semantic score, fallback text, and verdict.
      The labels are triage hints, not final human review.
    </div>
    <nav>
      <a href="#current">Current RAG</a>
      <a href="#candidate_train">New Fair RAG</a>
      <a href="#improved_merged">Improved Merged RAG</a>
      <a href="#candidate_all_debug">New Debug/All RAG</a>
    </nav>
    {''.join(sections)}
  </main>
</body>
</html>
""",
        encoding="utf-8",
    )
    print(f"Failure analysis -> {OUTPUT}")


if __name__ == "__main__":
    main()
