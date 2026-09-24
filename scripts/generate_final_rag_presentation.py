#!/usr/bin/env python3
"""Create a final presentation-style HTML for RAG comparison and improvement."""

from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "rag96_comparison"
OUTPUT = REPORT_DIR / "rag96_final_presentation.html"

SYSTEMS = [
    {
        "label": "old_current",
        "name": "Current RAG",
        "short": "Current tuned baseline",
        "report": REPORT_DIR / "current_report.json",
        "description": "The RAG currently used by Aree bot. It is tuned for Nong Aree tax responses and includes prior SME/call-center improvements.",
        "sources": ["Current Qdrant collection: thai_tax_kb", "1,311 local points at time of benchmark"],
        "role": "Baseline to protect.",
    },
    {
        "label": "new_sent",
        "name": "New RAG Sent By Supervisor",
        "short": "Fair sent-corpus candidate",
        "report": REPORT_DIR / "candidate_train_report.json",
        "description": "The two new RAG corpus files combined as a fair candidate: RD chunks plus 204 SME training rows. The 96 test answers are excluded.",
        "sources": ["rag_chunks.jsonl: 4,009 embedded RD chunks", "rag_sme_train_knowledge_204.jsonl: 204 SME train rows", "Qdrant collection: rd_chunks_sme_train_bge_m3, 4,153 points"],
        "role": "New candidate to evaluate.",
    },
    {
        "label": "merged_candidate",
        "name": "Merged Candidate",
        "short": "Candidate, not production default",
        "report": REPORT_DIR / "improved_merged_report.json",
        "description": "Production-oriented improvement that keeps the current tuned RAG as the anchor and adds the sent corpus as supplemental context with a no-regression guard.",
        "sources": ["Primary: thai_tax_kb", "Supplement: rd_chunks_sme_train_bge_m3", "No 96 test answers added to the sent-corpus side"],
        "role": "Candidate to continue improving; not safer than current yet.",
    },
]


def esc(value: Any) -> str:
    return html.escape(str(value or ""))


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_semantic(report_path: Path) -> dict[str, dict[str, Any]]:
    path = report_path.with_name(report_path.stem + ".semantic_eval.jsonl")
    rows = {}
    with path.open(encoding="utf-8") as file:
        for line in file:
            if line.strip():
                row = json.loads(line)
                rows[row["dataset_id"]] = row
    return rows


def bucket(verdict: str) -> str:
    if verdict == "correct":
        return "correct"
    if verdict.startswith("partial:"):
        return "partial"
    if verdict == "incorrect":
        return "incorrect"
    return "unknown"


def metrics(system: dict[str, Any]) -> dict[str, Any]:
    report = load_json(system["report"])
    sem = load_semantic(system["report"])
    rows = report["results"]
    counts = Counter(bucket(sem[row["dataset_id"]]["judge_verdict"]) for row in rows)
    semantic_scores = [sem[row["dataset_id"]]["semantic_score"] for row in rows]
    char_scores = [row["answer_similarity"] for row in rows]
    retrieval = [row["top_retrieval_score"] for row in rows]
    return {
        "report": report,
        "semantic": sem,
        "questions": len(rows),
        "correct": counts["correct"],
        "partial": counts["partial"],
        "incorrect": counts["incorrect"],
        "correct_rate": counts["correct"] / len(rows),
        "partial_rate": counts["partial"] / len(rows),
        "incorrect_rate": counts["incorrect"] / len(rows),
        "semantic_mean": mean(semantic_scores),
        "semantic_080": sum(score >= 0.80 for score in semantic_scores),
        "char_mean": mean(char_scores),
        "retrieval_080": sum(score >= 0.80 for score in retrieval),
        "fallbacks": sum(1 for row in rows if row.get("fallback")),
    }


def failure_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, int]:
    before_sem = before["semantic"]
    after_sem = after["semantic"]
    improved = worsened = same = 0
    for dataset_id, row in before_sem.items():
        before_bucket = bucket(row["judge_verdict"])
        after_bucket = bucket(after_sem[dataset_id]["judge_verdict"])
        order = {"incorrect": 0, "partial": 1, "correct": 2, "unknown": 0}
        if order[after_bucket] > order[before_bucket]:
            improved += 1
        elif order[after_bucket] < order[before_bucket]:
            worsened += 1
        else:
            same += 1
    return {"improved": improved, "worsened": worsened, "same": same}


def system_card(system: dict[str, Any], m: dict[str, Any]) -> str:
    sources = "".join(f"<li>{esc(item)}</li>" for item in system["sources"])
    return f"""
    <article class="card">
      <div class="eyebrow">{esc(system['short'])}</div>
      <h3>{esc(system['name'])}</h3>
      <p>{esc(system['description'])}</p>
      <ul>{sources}</ul>
      <dl>
        <div><dt>Correct</dt><dd>{m['correct']}/96 ({pct(m['correct_rate'])})</dd></div>
        <div><dt>Partial</dt><dd>{m['partial']}/96 ({pct(m['partial_rate'])})</dd></div>
        <div><dt>Incorrect</dt><dd>{m['incorrect']}/96 ({pct(m['incorrect_rate'])})</dd></div>
        <div><dt>Semantic mean</dt><dd>{m['semantic_mean']:.3f}</dd></div>
      </dl>
    </article>
    """


def metric_table(rows: list[tuple[dict[str, Any], dict[str, Any]]]) -> str:
    body = []
    for system, m in rows:
        body.append(
            "<tr>"
            f"<td><strong>{esc(system['name'])}</strong><br><span>{esc(system['role'])}</span></td>"
            f"<td>{m['correct']}/96<br><span>{pct(m['correct_rate'])}</span></td>"
            f"<td>{m['partial']}/96<br><span>{pct(m['partial_rate'])}</span></td>"
            f"<td>{m['incorrect']}/96<br><span>{pct(m['incorrect_rate'])}</span></td>"
            f"<td>{m['semantic_mean']:.3f}</td>"
            f"<td>{m['semantic_080']}/96<br><span>{pct(m['semantic_080'] / 96)}</span></td>"
            f"<td>{m['char_mean']:.3f}</td>"
            f"<td>{m['retrieval_080']}/96</td>"
            "</tr>"
        )
    return "".join(body)


def top_changes(before: dict[str, Any], after: dict[str, Any], limit: int = 10) -> str:
    before_rows = {row["dataset_id"]: row for row in before["report"]["results"]}
    after_rows = {row["dataset_id"]: row for row in after["report"]["results"]}
    before_sem = before["semantic"]
    after_sem = after["semantic"]
    changes = []
    for dataset_id, after_row in after_rows.items():
        delta = after_sem[dataset_id]["semantic_score"] - before_sem[dataset_id]["semantic_score"]
        changes.append((delta, dataset_id, before_rows[dataset_id], after_row))
    changes.sort(reverse=True, key=lambda item: item[0])
    rows = []
    for delta, dataset_id, before_row, after_row in changes[:limit]:
        rows.append(
            "<tr>"
            f"<td>{esc(dataset_id)}</td>"
            f"<td>{esc(after_row['question'])}</td>"
            f"<td>{before_sem[dataset_id]['semantic_score']:.3f}</td>"
            f"<td>{after_sem[dataset_id]['semantic_score']:.3f}</td>"
            f"<td>{delta:+.3f}</td>"
            f"<td>{esc(before_sem[dataset_id]['judge_verdict'])} -> {esc(after_sem[dataset_id]['judge_verdict'])}</td>"
            "</tr>"
        )
    return "".join(rows)


def main() -> None:
    loaded = [(system, metrics(system)) for system in SYSTEMS]
    by_label = {system["label"]: m for system, m in loaded}
    sent_to_merged = failure_delta(by_label["new_sent"], by_label["merged_candidate"])
    current_to_merged = failure_delta(by_label["old_current"], by_label["merged_candidate"])

    card_html = "".join(system_card(system, m) for system, m in loaded[:3])
    table_html = metric_table(loaded)
    change_rows = top_changes(by_label["new_sent"], by_label["merged_candidate"])

    OUTPUT.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Aree Bot RAG Benchmark Final Report</title>
  <style>
    :root {{
      --ink: #102a38;
      --muted: #607684;
      --line: #b8ddea;
      --soft: #edf9fd;
      --panel: #f8fdff;
      --blue: #21789a;
      --green: #16784a;
      --amber: #9a6500;
      --red: #a13b2b;
    }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: #fff;
    }}
    main {{
      max-width: 1480px;
      margin: 0 auto;
      padding: 36px;
    }}
    section {{
      margin-top: 42px;
    }}
    h1 {{
      margin: 0;
      font-size: 38px;
      letter-spacing: 0;
    }}
    h2 {{
      font-size: 26px;
      margin: 0 0 14px;
    }}
    h3 {{
      margin: 8px 0 12px;
    }}
    p, li {{
      line-height: 1.55;
    }}
    .muted, span {{
      color: var(--muted);
    }}
    .hero {{
      border-bottom: 2px solid var(--line);
      padding-bottom: 28px;
    }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 14px;
      margin: 24px 0;
    }}
    .summary div, .callout {{
      border: 1px solid var(--line);
      background: var(--soft);
      border-radius: 8px;
      padding: 16px;
    }}
    .summary strong {{
      display: block;
      font-size: 28px;
      margin-top: 6px;
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 16px;
    }}
    .card {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
      background: var(--panel);
    }}
    .eyebrow {{
      text-transform: uppercase;
      color: var(--blue);
      font-size: 12px;
      font-weight: 800;
      letter-spacing: .08em;
    }}
    dl {{
      display: grid;
      gap: 8px;
      margin: 14px 0 0;
    }}
    dl div {{
      display: flex;
      justify-content: space-between;
      border-top: 1px solid #d5edf5;
      padding-top: 8px;
      gap: 12px;
    }}
    dt {{
      color: var(--muted);
    }}
    dd {{
      margin: 0;
      font-weight: 800;
      text-align: right;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 18px 0;
      font-size: 14px;
    }}
    th, td {{
      border: 1px solid var(--line);
      padding: 10px;
      vertical-align: top;
    }}
    th {{
      text-align: left;
      background: var(--soft);
    }}
    .flow {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
      counter-reset: step;
    }}
    .flow div {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      background: var(--panel);
    }}
    .flow div::before {{
      counter-increment: step;
      content: counter(step);
      display: inline-grid;
      place-items: center;
      width: 26px;
      height: 26px;
      background: var(--blue);
      color: white;
      border-radius: 50%;
      font-weight: 800;
      margin-bottom: 8px;
    }}
    .good {{ color: var(--green); font-weight: 800; }}
    .warn {{ color: var(--amber); font-weight: 800; }}
    .bad {{ color: var(--red); font-weight: 800; }}
    a {{ color: var(--blue); font-weight: 750; }}
  </style>
</head>
<body>
<main>
  <section class="hero">
    <h1>Aree Bot RAG Benchmark Final Report</h1>
    <p class="muted">Comparison of current RAG, supervisor-sent RAG, and merged candidate using the 96-question benchmark and provided semantic evaluator.</p>
    <div class="summary">
      <div><span>Benchmark set</span><strong>96 questions</strong></div>
      <div><span>Evaluator</span><strong>Semantic eval + LLM judge</strong></div>
      <div><span>Safest production choice</span><strong>Current RAG</strong></div>
      <div><span>Recommended path</span><strong>Keep current, fix targeted gaps</strong></div>
    </div>
    <div class="callout">
      <strong>Executive conclusion:</strong>
      The supervisor-sent RAG corpus is valuable, but as a direct replacement it underperforms the current tuned RAG on the 96-question benchmark.
      The merged candidate improves over the sent-only RAG, but it produces more incorrect answers than the current RAG. For tax use, fewer incorrect answers is the safer criterion, so the current RAG should remain the production default.
    </div>
  </section>

  <section>
    <h2>Systems Compared</h2>
    <div class="cards">{card_html}</div>
  </section>

  <section>
    <h2>Benchmark Methodology</h2>
    <div class="flow">
      <div><h3>Input Data</h3><p>Used <code>bench_dataset_test_96.jsonl</code> as the holdout benchmark. Used <code>rag_chunks.jsonl</code> and <code>rag_sme_train_knowledge_204.jsonl</code> as the sent corpus.</p></div>
      <div><h3>Answer Generation</h3><p>Generated answers with the same answer-generation path and model setting for every RAG setup, so only retrieved knowledge changed.</p></div>
      <div><h3>Semantic Eval</h3><p>Used the provided <code>semantic_eval_llm_judge</code> package to calculate semantic similarity between generated and expected answers.</p></div>
      <div><h3>LLM Judge</h3><p>Used <code>ptm-oss-120b</code> as the working judge. The intended 3-judge ensemble could not fully run because <code>thaillm-8b</code> was not accessible with this key and Minimax returned malformed judge responses.</p></div>
    </div>
  </section>

  <section>
    <h2>Main Results</h2>
    <table>
      <thead>
        <tr>
          <th>RAG setup</th>
          <th>Judge correct</th>
          <th>Judge partial</th>
          <th>Judge incorrect</th>
          <th>Semantic mean</th>
          <th>Semantic >= 0.80</th>
          <th>Char-ngram mean</th>
          <th>Retrieval >= 0.80</th>
        </tr>
      </thead>
      <tbody>{table_html}</tbody>
    </table>
    <p>
      The merged candidate has slightly more correct answers than current, but also more incorrect answers.
      Since tax answers are risk-sensitive, the current RAG is the better production choice because it has the lowest incorrect count among fair production candidates:
      <strong>{by_label['old_current']['incorrect']}/96 incorrect</strong> vs <strong>{by_label['merged_candidate']['incorrect']}/96 incorrect</strong> for the merged candidate and <strong>{by_label['new_sent']['incorrect']}/96 incorrect</strong> for the sent-only RAG.
    </p>
  </section>

  <section>
    <h2>Current RAG To Merged Candidate: What Changed</h2>
    <table>
      <thead>
        <tr>
          <th>Area</th>
          <th>Current RAG</th>
          <th>Merged Candidate</th>
          <th>Why We Tried It</th>
          <th>Benchmark Impact</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td>Knowledge source</td>
          <td><code>thai_tax_kb</code> only, containing the previously tuned RD/tax and SME/call-center records.</td>
          <td><code>thai_tax_kb</code> remains primary, with <code>rd_chunks_sme_train_bge_m3</code> added as supplemental evidence.</td>
          <td>Use the supervisor-sent corpus without throwing away the tuned current behavior.</td>
          <td>Recovered most of the sent-only loss, but did not reduce incorrect answers versus current.</td>
        </tr>
        <tr>
          <td>Retrieval strategy</td>
          <td>Retrieve from the current tuned collection.</td>
          <td>Retrieve current top hits first, then append up to two high-confidence sent-corpus hits for additional context.</td>
          <td>Raw sent chunks are broad, so they should support answers rather than replace the current top evidence.</td>
          <td>Retrieval >= 0.80 stayed high at <strong>{by_label['merged_candidate']['retrieval_080']}/96</strong>, same broad retrieval confidence as current.</td>
        </tr>
        <tr>
          <td>No-regression guard</td>
          <td>Not needed because only one tuned source is used.</td>
          <td>If current RAG retrieves an exact benchmark-style record, sent-corpus context is not allowed to dilute it.</td>
          <td>Early tests showed supplemental chunks could distract answers that current RAG already handled well.</td>
          <td>Kept semantic mean close to current: <strong>{by_label['merged_candidate']['semantic_mean']:.3f}</strong> vs current <strong>{by_label['old_current']['semantic_mean']:.3f}</strong>.</td>
        </tr>
        <tr>
          <td>Production decision</td>
          <td>Safest current default because it has the lowest incorrect count.</td>
          <td>Useful candidate for future improvement, but not safer yet.</td>
          <td>Tax answers should prioritize reducing incorrect answers over increasing correct count alone.</td>
          <td>Current has <strong>{by_label['old_current']['incorrect']}/96 incorrect</strong>; merged candidate has <strong>{by_label['merged_candidate']['incorrect']}/96 incorrect</strong>.</td>
        </tr>
      </tbody>
    </table>
  </section>

  <section>
    <h2>What We Tried To Improve The Sent RAG</h2>
    <div class="flow">
      <div><h3>Started With Sent Corpus</h3><p>The sent-only RAG combined RD chunks with the 204 SME train rows, excluding the 96 test answers.</p></div>
      <div><h3>Observed Retrieval Gap</h3><p>Raw RD chunks often retrieved broad related pages rather than the exact answer shape expected by the benchmark.</p></div>
      <div><h3>Tried Guarded Merge</h3><p>We kept current RAG as the anchor and added sent-corpus context only as supplement, with a guard against diluting exact current answers.</p></div>
      <div><h3>Decision</h3><p>The merged candidate improved over sent-only, but did not beat current on safety because incorrect answers increased.</p></div>
    </div>
    <div class="callout">
      <strong>Why not use the sent corpus directly?</strong>
      The fair sent-only RAG scored <strong>{by_label['new_sent']['correct']}/96 correct</strong>, mainly because raw RD chunks often retrieve broad related pages instead of the exact answer shape required by the benchmark.
      The merged candidate recovers much of that loss, but the current RAG remains safer because it has fewer incorrect answers.
    </div>
  </section>

  <section>
    <h2>Impact Of Improvement</h2>
    <table>
      <thead><tr><th>Comparison</th><th>Improved verdicts</th><th>Worsened verdicts</th><th>Unchanged verdicts</th></tr></thead>
      <tbody>
        <tr>
          <td>Sent fair RAG -> Merged candidate</td>
          <td class="good">{sent_to_merged['improved']}</td>
          <td class="bad">{sent_to_merged['worsened']}</td>
          <td>{sent_to_merged['same']}</td>
        </tr>
        <tr>
          <td>Current RAG -> Merged candidate</td>
          <td class="good">{current_to_merged['improved']}</td>
          <td class="bad">{current_to_merged['worsened']}</td>
          <td>{current_to_merged['same']}</td>
        </tr>
      </tbody>
    </table>
    <p>
      Against the sent-only fair RAG, the merged candidate is a clear upgrade.
      Against current RAG, it is not safer because the incorrect count increases. The recommended action is to keep current as production default and use the sent corpus to create targeted curated fixes.
    </p>
  </section>

  <section>
    <h2>Top Improvements From Sent RAG To Merged Candidate</h2>
    <table>
      <thead><tr><th>ID</th><th>Question</th><th>Sent semantic</th><th>Improved semantic</th><th>Delta</th><th>Judge verdict</th></tr></thead>
      <tbody>{change_rows}</tbody>
    </table>
  </section>

  <section>
    <h2>Why The Current RAG Still Needs Improvement</h2>
    <div class="callout">
      <strong>The current RAG is the safest of the fair options, but it is not perfect.</strong>
      It still has <strong>{by_label['old_current']['incorrect']}/96 incorrect</strong> and <strong>{by_label['old_current']['partial']}/96 partial</strong> by the single working LLM judge.
      The reason we did not blindly replace it with the sent corpus is that the sent corpus increased the error risk instead of reducing it.
    </div>
    <div class="flow">
      <div><h3>Best next improvement</h3><p>Review the current RAG's 10 incorrect cases and add targeted answer-style records or curated safeguards for those exact gaps.</p></div>
      <div><h3>Why not broad merge</h3><p>Raw RD chunks improve coverage but can distract retrieval/generation because they are broad pages, not concise answer records.</p></div>
      <div><h3>How to improve safely</h3><p>Patch only proven misses, rerun the 96-question benchmark, and accept changes only if incorrect answers decrease.</p></div>
      <div><h3>Success criterion</h3><p>For tax use, the main KPI should be fewer incorrect answers first, then higher correct count and semantic mean.</p></div>
    </div>
  </section>

  <section>
    <h2>Known Limitations</h2>
    <ul>
      <li>The LLM judge result is single-judge <code>ptm-oss-120b</code>, not the full 3-judge ensemble. The 3-judge runner could not complete with current credentials/model responses.</li>
      <li>The current RAG is strongly aligned to this benchmark. That is useful for preserving behavior, but it means the benchmark rewards answer-style records more than broad public RD chunks.</li>
      <li>The merged candidate has <strong>{by_label['merged_candidate']['incorrect']}/96 incorrect</strong> by the single judge, which is worse than current RAG's <strong>{by_label['old_current']['incorrect']}/96 incorrect</strong>. It should not replace current yet.</li>
    </ul>
  </section>

  <section>
    <h2>Deliverables</h2>
    <ul>
      <li><a href="rag96_comparison.html">Detailed comparison table</a></li>
      <li><a href="rag96_failure_analysis.html">Detailed failure analysis</a></li>
      <li><a href="current_report.semantic_eval.csv">Current RAG semantic eval CSV</a></li>
      <li><a href="candidate_train_report.semantic_eval.csv">Sent fair RAG semantic eval CSV</a></li>
      <li><a href="improved_merged_report.semantic_eval.csv">Merged candidate semantic eval CSV</a></li>
      <li><a href="judge_model_failure_report.json">Judge model access/failure report</a></li>
    </ul>
  </section>
</main>
</body>
</html>
""",
        encoding="utf-8",
    )
    print(f"Final presentation -> {OUTPUT}")


if __name__ == "__main__":
    main()
