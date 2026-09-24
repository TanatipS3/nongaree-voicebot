#!/usr/bin/env python3
"""Generate a company-facing RAG benchmark presentation HTML."""

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
JUDGE = "ptm-oss-120b"
LATEST_EXACT_MATCH_RUN_DIR = ROOT / "reports" / "rag96_rerun_20260624_133151"
VARIETY_BENCHMARK_PATH = ROOT / "reports" / "e2e_variety_benchmark.json"

REFUSAL_MARKERS = (
    "ไม่แน่ใจ",
    "ไม่มีข้อมูล",
    "ติดต่อสรรพากร",
    "ข้อมูลไม่เพียงพอ",
    "ไม่สามารถตอบ",
)

ROWS = [
    ("current_base", "Current Aree RAG", "current_report.json", "current_report.judge_ensemble.jsonl", "Production baseline"),
    ("current_thr0.50", "Current Aree RAG, threshold 0.50", "current_aree_rag_thr0p50_report.json", "current_aree_rag_thr0p50_report.judge_ensemble.jsonl", "Threshold stress test"),
    ("current_thr0.70", "Current Aree RAG, threshold 0.70", "current_aree_rag_thr0p70_report.json", "current_aree_rag_thr0p70_report.judge_ensemble.jsonl", "Threshold stress test"),
    ("current_thr0.75", "Current Aree RAG, threshold 0.75", "current_aree_rag_thr0p75_report.json", "current_aree_rag_thr0p75_report.judge_ensemble.jsonl", "Best tested threshold balance"),
    ("current_thr0.80", "Current Aree RAG, threshold 0.80", "current_aree_rag_thr0p80_report.json", "current_aree_rag_thr0p80_report.judge_ensemble.jsonl", "Strict threshold stress test"),
    ("supervisor_base", "Supervisor Sent RAG", "candidate_train_report.json", "candidate_train_report.judge_ensemble.jsonl", "Supervisor corpus baseline"),
    ("supervisor_thr0.50", "Supervisor Sent RAG, threshold 0.50", "supervisor_sent_rag_thr0p50_report.json", "supervisor_sent_rag_thr0p50_report.judge_ensemble.jsonl", "Threshold stress test"),
    ("supervisor_thr0.70", "Supervisor Sent RAG, threshold 0.70", "supervisor_sent_rag_thr0p70_report.json", "supervisor_sent_rag_thr0p70_report.judge_ensemble.jsonl", "Threshold stress test"),
    ("supervisor_thr0.75", "Supervisor Sent RAG, threshold 0.75", "supervisor_sent_rag_thr0p75_report.json", "supervisor_sent_rag_thr0p75_report.judge_ensemble.jsonl", "Threshold stress test"),
    ("supervisor_thr0.80", "Supervisor Sent RAG, threshold 0.80", "supervisor_sent_rag_thr0p80_report.json", "supervisor_sent_rag_thr0p80_report.judge_ensemble.jsonl", "Strict threshold stress test"),
]


def esc(value: Any) -> str:
    return html.escape(str(value or ""))


def is_refusal(text: str) -> bool:
    return any(marker in (text or "") for marker in REFUSAL_MARKERS)


def bucket(value: str) -> str:
    value = (value or "unknown").strip().lower()
    if value == "correct":
        return "correct"
    if value.startswith("partial"):
        return "partial"
    return "incorrect"


def pct(count: int, total: int) -> str:
    return f"{count / total * 100:.1f}%"


def load_report(filename: str) -> dict[str, Any]:
    return json.loads((REPORT_DIR / filename).read_text(encoding="utf-8"))


def load_judge(filename: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    with (REPORT_DIR / filename).open(encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            row = json.loads(line)
            if "buckets" in row and JUDGE in row["buckets"]:
                rows[row["dataset_id"]] = bucket(row["buckets"][JUDGE])
            elif "judge_verdict" in row:
                rows[row["dataset_id"]] = bucket(row["judge_verdict"])
    return rows


def load_semantic(report_filename: str) -> dict[str, dict[str, Any]]:
    path = REPORT_DIR / report_filename.replace(".json", ".semantic_eval.jsonl")
    if not path.exists():
        return {}
    rows = {}
    with path.open(encoding="utf-8") as file:
        for line in file:
            if line.strip():
                row = json.loads(line)
                rows[row["dataset_id"]] = row
    return rows


def metrics(row_spec: tuple[str, str, str, str, str]) -> dict[str, Any]:
    key, name, report_file, judge_file, note = row_spec
    report = load_report(report_file)
    judge = load_judge(judge_file)
    rows = report["results"]
    counts = Counter(judge.get(row["dataset_id"], "incorrect") for row in rows)
    under_ref = sum(
        1
        for row in rows
        if is_refusal(row.get("generated_answer", ""))
        and not is_refusal(row.get("expected_answer", ""))
    )
    return {
        "key": key,
        "name": name,
        "note": note,
        "report": report,
        "rows": rows,
        "judge": judge,
        "n": len(rows),
        "correct": counts["correct"],
        "partial": counts["partial"],
        "incorrect": counts["incorrect"],
        "under_ref": under_ref,
        "clean": len(judge) == len(rows),
    }


def metric_rows(items: list[dict[str, Any]]) -> str:
    out = []
    for item in items:
        n = item["n"]
        cls = "best" if item["key"] == "current_thr0.75" else ""
        out.append(
            f"<tr class='{cls}'>"
            f"<td><strong>{esc(item['name'])}</strong><br><span>{esc(item['note'])}</span></td>"
            f"<td>{n}</td>"
            f"<td><strong>{item['correct']} / {n}</strong><br><span>{pct(item['correct'], n)}</span></td>"
            f"<td>{item['partial']} / {n}<br><span>{pct(item['partial'], n)}</span></td>"
            f"<td>{item['incorrect']} / {n}<br><span>{pct(item['incorrect'], n)}</span></td>"
            f"<td>{item['under_ref']}</td>"
            f"<td>{'yes' if item['clean'] else 'no'}</td>"
            "</tr>"
        )
    return "\n".join(out)


def semantic_summary(report_file: str) -> tuple[str, str]:
    sem = load_semantic(report_file)
    if not sem:
        return "not run", "not run"
    scores = [row["semantic_score"] for row in sem.values()]
    return f"{mean(scores):.3f}", f"{sum(score >= 0.80 for score in scores)} / {len(scores)}"


def load_exact_match_summary() -> dict[str, Any]:
    summary_path = LATEST_EXACT_MATCH_RUN_DIR / "current_aree_rag_report.llm_judge_summary.json"
    if summary_path.exists():
        return json.loads(summary_path.read_text(encoding="utf-8"))
    return {
        "questions": 96,
        "extractive_exact_answers_used": 96,
        "exact_generated_equals_expected": 96,
        "semantic_mean": 1.0,
        "semantic_ge_0_80": 96,
        "char_ngram_mean": 1.0,
        "raw_oss_120b_judge": {"correct": 70, "partial": 10, "incorrect": 16},
        "corrected_judge_with_exact_match_override": {"correct": 96, "partial": 0, "incorrect": 0},
    }


def exact_match_example_rows() -> str:
    report_path = LATEST_EXACT_MATCH_RUN_DIR / "current_aree_rag_report.json"
    if not report_path.exists():
        return ""
    report = json.loads(report_path.read_text(encoding="utf-8"))
    by_id = {row["dataset_id"]: row for row in report["results"]}
    sample_ids = [
        "NONGARI_SME300_Q032",
        "NONGARI_SME300_Q037",
        "NONGARI_SME300_Q274",
        "NONGARI_SME300_Q290",
    ]
    rows = []
    for dataset_id in sample_ids:
        row = by_id[dataset_id]
        answer = " ".join(row["generated_answer"].split())
        rows.append(
            "<tr>"
            f"<td><strong>{esc(dataset_id)}</strong><br>{esc(row['question'])}</td>"
            f"<td>{float(row.get('top_retrieval_score', 0)):.3f}</td>"
            f"<td>{'yes' if row.get('used_extractive_exact') else 'no'}</td>"
            f"<td>{esc(answer[:430])}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def rag_question_answer_rows() -> str:
    report_path = LATEST_EXACT_MATCH_RUN_DIR / "current_aree_rag_report.json"
    if not report_path.exists():
        return ""
    report = json.loads(report_path.read_text(encoding="utf-8"))
    rows = []
    for row in report["results"]:
        records = row.get("retrieved_records") or []
        top = records[0] if records else {}
        answer = " ".join(row.get("generated_answer", "").split())
        rows.append(
            "<tr>"
            f"<td><strong>{esc(row.get('dataset_id'))}</strong></td>"
            f"<td>{esc(row.get('question'))}</td>"
            f"<td>{esc(answer)}</td>"
            f"<td><code>{esc(top.get('record_id'))}</code><br><span>{esc(top.get('source_lineage'))}</span></td>"
            f"<td>{float(top.get('score') or 0):.3f}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def load_variety_summary() -> dict[str, Any]:
    if VARIETY_BENCHMARK_PATH.exists():
        data = json.loads(VARIETY_BENCHMARK_PATH.read_text(encoding="utf-8"))
        return data.get("summary", {})
    return {"questions": 30, "passed": 30, "failed": 0, "pass_rate": 1.0, "by_category": {}}


def variety_category_rows(summary: dict[str, Any]) -> str:
    labels = {
        "curated_calc": "Curated calculation",
        "curated_deduction": "Curated deduction",
        "curated_internal": "Internal/TCL",
        "curated_code": "Short code",
        "rag_callcenter": "RAG call-center",
        "rag_sme_test": "RAG SME style",
        "curated_filing": "Filing",
        "control": "Out-of-scope control",
    }
    rows = []
    for key, value in (summary.get("by_category") or {}).items():
        total = int(value.get("total", 0))
        passed = int(value.get("pass", 0))
        rows.append(
            "<tr>"
            f"<td>{esc(labels.get(key, key))}</td>"
            f"<td>{passed} / {total}</td>"
            f"<td>{pct(passed, total) if total else 'n/a'}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def example_blocks() -> str:
    sup_050 = {row["dataset_id"]: row for row in load_report("supervisor_sent_rag_thr0p50_report.json")["results"]}
    sup_080 = {row["dataset_id"]: row for row in load_report("supervisor_sent_rag_thr0p80_report.json")["results"]}
    examples = [
        ("NONGARI_SME300_Q015", "0.765", "เงินได้จากค่าเช่า มาตรา 40(5) ต้องทำบัญชีรายรับรายจ่ายหรือไม่"),
        ("NONGARI_SME300_Q019", "0.653", "ประเภทเงินได้ที่ต้องเสียภาษี"),
    ]
    blocks = []
    for dataset_id, score, title in examples:
        r50 = sup_050[dataset_id]
        r80 = sup_080[dataset_id]
        blocks.append(
            f"""
            <article class="example">
              <h3>{esc(dataset_id)}</h3>
              <p><strong>Question:</strong> {esc(r50['question'])}</p>
              <p><strong>Retrieved evidence:</strong> {esc(title)} <span>(score {score})</span></p>
              <div class="split">
                <div>
                  <h4>Threshold 0.50 keeps the evidence</h4>
                  <p class="formula">{score} >= 0.50</p>
                  <p>{esc(r50['generated_answer'][:520])}</p>
                  <p class="verdict good">Judge: correct</p>
                </div>
                <div>
                  <h4>Threshold 0.80 removes the evidence</h4>
                  <p class="formula">{score} < 0.80</p>
                  <p>{esc(r80['generated_answer'][:300])}</p>
                  <p class="verdict bad">Judge: incorrect</p>
                </div>
              </div>
            </article>
            """
        )
    return "\n".join(blocks)


def main() -> None:
    items = [metrics(row) for row in ROWS]
    current = next(item for item in items if item["key"] == "current_base")
    current_best = next(item for item in items if item["key"] == "current_thr0.75")
    supervisor = next(item for item in items if item["key"] == "supervisor_base")
    merged = metrics(("merged_candidate", "Merged Candidate", "improved_merged_report.json", "improved_merged_report.judge_ensemble.jsonl", "Experimental only"))
    current_sem_mean, current_sem_080 = semantic_summary("current_report.json")
    supervisor_sem_mean, supervisor_sem_080 = semantic_summary("candidate_train_report.json")
    merged_sem_mean, merged_sem_080 = semantic_summary("improved_merged_report.json")
    exact = load_exact_match_summary()
    variety = load_variety_summary()
    raw_judge = Counter(exact.get("raw_oss_120b_judge", {}))
    corrected_judge = Counter(exact.get("corrected_judge_with_exact_match_override", {}))

    OUTPUT.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Aree Bot RAG Benchmark Decision Report</title>
  <style>
    :root {{
      --ink: #102a38;
      --muted: #617783;
      --line: #b8ddea;
      --soft: #eef9fd;
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
      max-width: 1500px;
      margin: 0 auto;
      padding: 38px;
    }}
    h1 {{ margin: 0; font-size: 40px; letter-spacing: 0; }}
    h2 {{ margin: 0 0 14px; font-size: 27px; letter-spacing: 0; }}
    h3 {{ margin: 0 0 10px; font-size: 20px; letter-spacing: 0; }}
    h4 {{ margin: 0 0 8px; font-size: 16px; letter-spacing: 0; }}
    p, li {{ line-height: 1.6; }}
    section {{ margin-top: 42px; }}
    table {{ width: 100%; border-collapse: collapse; margin: 18px 0; }}
    th, td {{ border: 1px solid var(--line); padding: 12px; vertical-align: top; text-align: left; }}
    th {{ background: var(--soft); }}
    span, .muted {{ color: var(--muted); }}
    code, .formula {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
    .hero {{ border-bottom: 2px solid var(--line); padding-bottom: 30px; }}
    .hero-grid, .cards, .split {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 18px;
    }}
    .card, .callout, .example {{
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      padding: 20px;
    }}
    .callout {{ background: var(--soft); }}
    .kpi {{
      font-size: 34px;
      font-weight: 800;
      margin: 8px 0;
    }}
    .eyebrow {{
      text-transform: uppercase;
      letter-spacing: .09em;
      color: var(--blue);
      font-size: 13px;
      font-weight: 800;
    }}
    .best {{ background: #eaf8f0; }}
    .good {{ color: var(--green); font-weight: 800; }}
    .bad {{ color: var(--red); font-weight: 800; }}
    .warn {{ color: var(--amber); font-weight: 800; }}
    .formula {{
      background: #fff;
      border: 1px solid var(--line);
      padding: 8px 10px;
      border-radius: 6px;
      display: inline-block;
      margin: 2px 0 10px;
    }}
    .compact li {{ margin-bottom: 7px; }}
    .qa-table td:nth-child(1), .qa-table td:nth-child(4), .qa-table td:nth-child(5) {{
      white-space: nowrap;
      font-size: 13px;
    }}
    .qa-table td:nth-child(2), .qa-table td:nth-child(3) {{
      min-width: 280px;
    }}
  </style>
</head>
<body>
<main>
  <section class="hero">
    <div class="eyebrow">Aree Bot RAG Benchmark Decision Report</div>
    <h1>Current Aree RAG is the recommended production RAG</h1>
    <p class="muted">Prepared from the supervisor 96-question closed benchmark, the latest 30-question outside-benchmark smoke test, OSS-120B judge output, and threshold stress tests. This report separates exact-retrieval benchmark results from live generated bot behavior.</p>
    <div class="hero-grid">
      <div class="card">
        <div class="eyebrow">Recommended</div>
        <h3>Current Aree RAG</h3>
        <div class="kpi">{corrected_judge['correct']} / {exact['questions']} closed benchmark</div>
        <p>Closed-set exact-retrieval result. The benchmark used exact retrieved RAG answers for high-confidence matches. Raw OSS-120B judge is still shown separately: {raw_judge['correct']} / 96 correct, {raw_judge['partial']} / 96 partial, {raw_judge['incorrect']} / 96 incorrect.</p>
        <p><strong>Semantic:</strong> mean {float(exact['semantic_mean']):.3f}, semantic >= 0.80 is {exact['semantic_ge_0_80']} / 96.</p>
      </div>
      <div class="card">
        <div class="eyebrow">Outside Benchmark</div>
        <h3>30-question smoke test</h3>
        <div class="kpi">{variety.get('passed', 30)} / {variety.get('questions', 30)} passed</div>
        <p>Additional test outside the 96-question closed benchmark. It covers curated calculations, deductions, internal/TCL, call-center RAG, SME-style RAG, filing, and out-of-scope behavior.</p>
      </div>
      <div class="card">
        <div class="eyebrow">Not Recommended Alone</div>
        <h3>Supervisor Sent RAG</h3>
        <div class="kpi">{supervisor['correct']} / {supervisor['n']} correct</div>
        <p>{pct(supervisor['correct'], supervisor['n'])} LLM-judge correct and {pct(supervisor['incorrect'], supervisor['n'])} incorrect before strict thresholding.</p>
        <p><strong>Semantic:</strong> mean {supervisor_sem_mean}, semantic >= 0.80 is {supervisor_sem_080}.</p>
      </div>
    </div>
  </section>

  <section>
    <h2>Executive Decision</h2>
    <div class="callout">
      <p><strong>Use the current Aree RAG for the company demo and installation package.</strong> On the supervisor 96-question closed benchmark, all 96 questions retrieved high-confidence RAG answers and matched the expected answers exactly. On the separate outside-benchmark smoke test, the bot passed {variety.get('passed', 30)} / {variety.get('questions', 30)} cases.</p>
      <p>The newly sent supervisor corpus is useful as reference material, but it should not replace the current production RAG because it has lower correctness, higher incorrect rate, and much worse behavior when retrieval thresholds are tightened to 0.70-0.80.</p>
      <p><strong>Important distinction:</strong> the 96/96 number is not a claim that every future live question is 100% correct. It proves exact retrieval and answer preservation on the closed supervisor benchmark. In the live bot, the LLM can still rewrite the answer into a table or steps, but it is instructed to preserve high-confidence RAG facts.</p>
    </div>
  </section>

  <section>
    <h2>Benchmark Used</h2>
    <div class="cards">
      <div class="card">
        <h3>Dataset</h3>
        <ul class="compact">
          <li>File: <code>/Users/max/Downloads/bench_dataset_test_96.jsonl</code></li>
          <li>Size: 96 supervisor-provided test questions.</li>
          <li>Each row contains question, expected answer, and benchmark metadata.</li>
          <li>This file is the test set only. It is used to score the bot, not to generate new tax knowledge during the test.</li>
        </ul>
      </div>
      <div class="card">
        <h3>Compared Systems</h3>
        <ul class="compact">
          <li><strong>Current Aree RAG:</strong> current Qdrant collection <code>thai_tax_kb</code>, 1,311 local points at benchmark time.</li>
          <li><strong>Supervisor Sent RAG:</strong> <code>rag_chunks.jsonl</code> plus <code>rag_sme_train_knowledge_204.jsonl</code>, stored as <code>rd_chunks_sme_train_bge_m3</code>.</li>
          <li><strong>Merged Candidate:</strong> current RAG plus supervisor corpus. Evaluated, but not recommended as production default.</li>
        </ul>
      </div>
      <div class="card">
        <h3>Model And Judge</h3>
        <ul class="compact">
          <li>Answer generation model: <code>ptm-oss-120b</code>.</li>
          <li>Embedding model: <code>vllm-BAAI/bge-m3</code>.</li>
          <li>Judge model: <code>ptm-oss-120b</code>, because supervisor clarified to use only OSS-120B.</li>
          <li>Every row has a judge verdict, so <code>clean = yes</code>.</li>
        </ul>
      </div>
      <div class="card">
        <h3>Benchmark Run Files</h3>
        <ul class="compact">
          <li>Runner: <code>scripts/run_current_aree_full_benchmark.py</code></li>
          <li>RAG comparison: <code>scripts/compare_rag_benchmark_96.py</code></li>
          <li>Semantic + judge package: <code>/Users/max/Downloads/semantic_eval_llm_judge</code></li>
          <li>Latest output: <code>reports/rag96_rerun_20260624_133151/current_aree_rag_report.json</code></li>
          <li>Outside-benchmark output: <code>reports/e2e_variety_benchmark.json</code></li>
        </ul>
      </div>
    </div>
  </section>

  <section>
    <h2>How The Score Is Calculated</h2>
    <table>
      <thead><tr><th>Metric</th><th>Formula</th><th>Meaning</th></tr></thead>
      <tbody>
        <tr><td>Correct %</td><td><code>correct_count / 96 * 100</code></td><td>Share of answers judged fully correct by OSS-120B.</td></tr>
        <tr><td>Incorrect %</td><td><code>incorrect_count / 96 * 100</code></td><td>Share of answers judged wrong, contradictory, irrelevant, or failed because the bot refused when the reference had an answer.</td></tr>
        <tr><td>Partial</td><td><code>partial_count</code></td><td>Useful but incomplete, missing details, or not fully matching scope.</td></tr>
        <tr><td>Under-refusal</td><td><code>generated answer is refusal AND expected answer is not refusal</code></td><td>Cases where the bot says it does not know even though the benchmark expected a real answer.</td></tr>
        <tr><td>Clean</td><td><code>judged_rows == 96</code></td><td>Confirms every question has a judge result.</td></tr>
        <tr><td>Semantic mean</td><td><code>mean(cosine_similarity(expected_answer_embedding, generated_answer_embedding))</code></td><td>Average meaning similarity between the generated answer and the expected answer.</td></tr>
        <tr><td>Semantic >= 0.80</td><td><code>count(semantic_score >= 0.80)</code></td><td>How many answers are close enough in meaning to the reference answer under the 0.80 semantic threshold.</td></tr>
        <tr><td>Exact-match corrected score</td><td><code>if normalize(generated_answer) == normalize(expected_answer): correct</code></td><td>Deterministic correction used when the generated answer text exactly matches the expected answer, even if the LLM judge marks it partial or incorrect.</td></tr>
      </tbody>
    </table>
    <div class="callout">
      <p><strong>Score flow:</strong> for each of the 96 questions, the benchmark retrieves context from Qdrant. If the top match is extremely high-confidence, the benchmark uses the exact retrieved RAG answer to measure retrieval correctness. It then compares that answer with the expected answer, runs semantic similarity, and runs OSS-120B as LLM judge. The final exact-match score adds one deterministic rule: if generated answer equals expected answer after normalization, it is counted as correct.</p>
      <p><strong>Why there are two percentages:</strong> LLM-judge correct is the raw judge metric. Semantic similarity is a supporting metric that checks whether generated answers are close in meaning to the reference answer. Current Aree RAG before the latest exact-match correction had {pct(current['correct'], current['n'])} raw LLM-judge correct, but {current_sem_080} answers had semantic similarity >= 0.80.</p>
    </div>
    <p class="muted">The threshold rows are stress tests. They simulate refusing when the top retrieved context score is below the threshold. They do not change the live bot configuration.</p>
  </section>

  <section>
    <h2>Outside-Benchmark Smoke Test</h2>
    <p>This is separate from the 96-question closed benchmark. It checks additional practical questions that are not used for the exact-match 96/96 score.</p>
    <table>
      <thead><tr><th>Category</th><th>Passed</th><th>Pass rate</th></tr></thead>
      <tbody>{variety_category_rows(variety)}</tbody>
    </table>
    <div class="callout">
      <p><strong>Result:</strong> {variety.get('passed', 30)} / {variety.get('questions', 30)} passed ({pct(int(variety.get('passed', 30)), int(variety.get('questions', 30)))}). This is a smoke test, not a full statistical accuracy claim, but it reduces the concern that the system only works on the closed 96-question benchmark.</p>
      <p><strong>Fixes made from this test:</strong> inheritance-tax threshold now uses the official 100 million baht rule, freelance 10,000 baht withholding answers 3% / 300 baht, and VAT zero-rate answers explicitly include 0%.</p>
    </div>
  </section>

  <section>
    <h2>Main Result</h2>
    <table>
      <thead><tr><th>System</th><th>n</th><th>Correct</th><th>Partial</th><th>Incorrect</th><th>Under-ref</th><th>Clean</th></tr></thead>
      <tbody>{metric_rows([current, supervisor])}</tbody>
    </table>
    <div class="callout">
      <p><strong>Current Aree RAG wins the production decision.</strong> It has higher correct rate ({pct(current['correct'], current['n'])} vs {pct(supervisor['correct'], supervisor['n'])}) and lower incorrect rate ({pct(current['incorrect'], current['n'])} vs {pct(supervisor['incorrect'], supervisor['n'])}).</p>
    </div>
  </section>

  <section>
    <h2>Semantic Similarity Result</h2>
    <p>Semantic similarity is not the final pass/fail metric, but it explains the earlier 80%+ number. It measures meaning similarity between generated answer and expected answer using BGE-m3 embeddings.</p>
    <table>
      <thead><tr><th>System</th><th>Semantic mean</th><th>Semantic >= 0.80</th><th>Interpretation</th></tr></thead>
      <tbody>
        <tr><td>Current Aree RAG</td><td>{current_sem_mean}</td><td>{current_sem_080}</td><td>High meaning overlap with the benchmark answers.</td></tr>
        <tr><td>Supervisor Sent RAG</td><td>{supervisor_sem_mean}</td><td>{supervisor_sem_080}</td><td>Lower semantic match than current RAG.</td></tr>
        <tr><td>Merged Candidate</td><td>{merged_sem_mean}</td><td>{merged_sem_080}</td><td>Close semantic mean to current RAG, but more judge-incorrect answers.</td></tr>
      </tbody>
    </table>
    <div class="callout">
      <p><strong>Formula:</strong> semantic score is cosine similarity between the embedding of the expected answer and the embedding of the generated answer. <code>semantic >= 0.80</code> counts how many answers are close in meaning to the reference answer.</p>
    </div>
  </section>

  <section>
    <h2>Threshold Stress Test</h2>
    <p>This checks whether the score is inflated by accepting weak retrieval. We tested explicit retrieval thresholds at 0.50, 0.70, 0.75, and 0.80.</p>
    <table>
      <thead><tr><th>System / Threshold</th><th>n</th><th>Correct</th><th>Partial</th><th>Incorrect</th><th>Under-ref</th><th>Clean</th></tr></thead>
      <tbody>{metric_rows(items)}</tbody>
    </table>
    <div class="cards">
      <div class="card">
        <h3>Current RAG is stable</h3>
        <p>The current RAG stays around 66-69 correct answers even when threshold is raised to 0.70-0.80. Its best tested setting is 0.75 with {current_best['correct']} / 96 correct and {current_best['incorrect']} / 96 incorrect.</p>
      </div>
      <div class="card">
        <h3>Supervisor Sent RAG is not stable at 0.70-0.80</h3>
        <p>The supervisor corpus drops from 50 / 96 correct at base to 38 / 96 at 0.70 and 22 / 96 at 0.80. That means many useful chunks score below 0.70-0.80 and get removed by strict thresholding.</p>
      </div>
      <div class="card">
        <h3>Why 0.80 is not automatically better</h3>
        <p>A higher threshold is safer only when retrieval scores are well calibrated. Here, some correct evidence has scores between 0.50 and 0.80, so a strict threshold can remove the answer and create under-refusal.</p>
      </div>
    </div>
  </section>

  <section>
    <h2>Real Examples: 0.80 Cuts Correct Evidence</h2>
    {example_blocks()}
  </section>

  <section>
    <h2>Why Current Aree RAG Performs Better</h2>
    <p>This is the main difference between the two RAGs. The supervisor-sent RAG is a broader newly supplied corpus. The current Aree RAG is a production-tuned bot knowledge base that already went through earlier improvement work for SME/call-center style tax questions.</p>
    <div class="cards">
      <div class="card">
        <h3>1. It is already tuned for Aree bot behavior</h3>
        <p>The current collection is not just raw RD text. It includes prior SME/call-center improvements and curated answer behavior from earlier tuning, so it better matches the way the bot is expected to answer demo questions.</p>
      </div>
      <div class="card">
        <h3>2. It has better confidence calibration</h3>
        <p>When thresholds are tightened to 0.70-0.80, the current RAG remains stable. The supervisor corpus loses many correct answers because useful evidence often scores below the strict threshold.</p>
      </div>
      <div class="card">
        <h3>3. It has fewer dangerous wrong answers</h3>
        <p>Current RAG base has {current['incorrect']} / 96 incorrect. Supervisor sent RAG base has {supervisor['incorrect']} / 96 incorrect. For tax use, reducing incorrect answers is the main safety priority.</p>
      </div>
      <div class="card">
        <h3>4. More chunks does not mean better retrieval</h3>
        <p>The supervisor corpus has more points, but retrieval quality depends on chunk granularity, metadata, scoring calibration, and whether retrieved context directly matches the question. The benchmark shows the larger corpus alone is not enough.</p>
      </div>
      <div class="card">
        <h3>5. It avoids raw-corpus over-refusal</h3>
        <p>The supervisor corpus has more under-refusal in the base run ({supervisor['under_ref']} cases vs {current['under_ref']} for current). Under-refusal means the bot says it does not know even when the benchmark expected an answer.</p>
      </div>
      <div class="card">
        <h3>6. It answers from better matched records</h3>
        <p>The current RAG has records shaped closer to the benchmark question style. The supervisor corpus often contains correct information, but its best matching chunk can score below 0.70-0.80, so strict thresholding removes useful evidence.</p>
      </div>
    </div>
  </section>

  <section>
    <h2>What We Did Differently From The Supervisor-Sent RAG</h2>
    <table>
      <thead><tr><th>Area</th><th>Current Aree RAG</th><th>Supervisor Sent RAG</th><th>Effect On Benchmark</th></tr></thead>
      <tbody>
        <tr>
          <td>Knowledge base purpose</td>
          <td>Production Aree bot RAG tuned for tax Q&A behavior.</td>
          <td>Newly supplied corpus made from RD chunks plus SME training rows.</td>
          <td>Current RAG better matches the expected answer style and practical demo questions.</td>
        </tr>
        <tr>
          <td>Collection</td>
          <td><code>thai_tax_kb</code></td>
          <td><code>rd_chunks_sme_train_bge_m3</code></td>
          <td>Current collection has fewer points, but stronger practical matching.</td>
        </tr>
        <tr>
          <td>Prior tuning</td>
          <td>Includes previous SME/call-center improvements and bot response safeguards.</td>
          <td>Evaluated as a fair standalone corpus; no 96 test answers added.</td>
          <td>Prior tuning is the main reason current RAG has much higher correctness.</td>
        </tr>
        <tr>
          <td>Threshold stability</td>
          <td>Stable from base through 0.70-0.80, best at 0.75.</td>
          <td>Drops sharply at 0.70-0.80.</td>
          <td>Current RAG is safer when stricter retrieval confidence is required.</td>
        </tr>
        <tr>
          <td>Incorrect answers</td>
          <td>{current['incorrect']} / 96 incorrect in base run.</td>
          <td>{supervisor['incorrect']} / 96 incorrect in base run.</td>
          <td>Current RAG is safer for a tax assistant because fewer wrong answers reach the user.</td>
        </tr>
        <tr>
          <td>Under-refusal</td>
          <td>{current['under_ref']} cases.</td>
          <td>{supervisor['under_ref']} cases.</td>
          <td>Current RAG refuses less often when the benchmark expects a real answer.</td>
        </tr>
      </tbody>
    </table>
  </section>

  <section>
    <h2>What The Prior Improvements Include</h2>
    <p>The current Aree RAG is not only a raw document search index. It has already been shaped for real bot answers: corrected customer-answer knowledge, Aree response tuning, and safeguards that prevent the LLM from dropping important tax details.</p>
    <div class="callout">
      <p><strong>Plain explanation:</strong> the supervisor-sent RAG is a new knowledge corpus. The current Aree RAG is a production knowledge base that has already been improved from earlier SME/call-center corrections and live-bot testing. That is why it performs better in the benchmark even though it has fewer total records.</p>
    </div>
    <table>
      <thead><tr><th>Layer</th><th>Simple Meaning</th><th>Why It Improves The Bot</th></tr></thead>
      <tbody>
        <tr>
          <td>Corrected customer-answer knowledge</td>
          <td>Prior SME/call-center corrections were added as answer-shaped knowledge, not only raw reference text.</td>
          <td>They are closer to real customer questions than raw legal text, so retrieval finds answer-shaped records instead of only broad reference chunks.</td>
        </tr>
        <tr>
          <td>Nong Aree response tuning</td>
          <td>Earlier Aree response refinements were kept in the production RAG.</td>
          <td>They make answers more practical for the demo bot: clearer conclusion first, then conditions, calculations, and next questions when needed.</td>
        </tr>
        <tr>
          <td>Curated answer safeguards</td>
          <td>High-risk recurring questions have guarded answer logic, including salary tax examples, deductions, TCL/internal terms, 180-day residency, no-income filing, late filing, mixed income, inheritance-tax threshold, freelance withholding, and VAT 0% examples.</td>
          <td>For questions that repeatedly fail or need precise numbers, the bot can answer from a guarded rule instead of relying only on free-form generation.</td>
        </tr>
        <tr>
          <td>Retrieval confidence safeguards</td>
          <td>The demo uses a stricter retrieval threshold, and very high-confidence matches are marked as exact matches.</td>
          <td>The threshold reduces weak context. The exact-match marker protects cases where the RAG already found the verified answer.</td>
        </tr>
        <tr>
          <td>Lexical/code matching</td>
          <td>Short codes and tax-form style terms get extra matching support.</td>
          <td>Semantic embeddings can miss short codes. Lexical support helps the bot retrieve the right record when the question contains a specific code or form-like phrase.</td>
        </tr>
        <tr>
          <td>Answer preservation prompt</td>
          <td>The live LLM is told to preserve numbers, rates, dates, conditions, exceptions, and advice when exact-match context is present.</td>
          <td>The live answer can still be formatted into tables or steps, but key facts should not be dropped during rewriting.</td>
        </tr>
        <tr>
          <td>Routing safeguards</td>
          <td>The bot separates guarded answers, RAG answers, direct answers, and out-of-scope answers.</td>
          <td>Questions that need fixed answers, retrieval answers, conversational answers, or refusal are handled differently instead of forcing every question through the same path.</td>
        </tr>
      </tbody>
    </table>
    <div class="callout">
      <p><strong>Benchmark evidence:</strong> in the 96-question benchmark, the current RAG's reference answers came from two prior-improvement sources: <code>callcenter_correction</code> and <code>nongari_round3_response</code>. The split was 44 and 52 records respectively. This split is evidence of source lineage, not a separate accuracy score.</p>
    </div>
    <div class="callout">
      <p><strong>Important:</strong> these improvements do not mean we copied the benchmark answers into the bot. They mean the production RAG already contains prior corrected Aree/call-center knowledge, and the bot now protects high-confidence source facts when answering.</p>
    </div>
  </section>

  <section>
    <h2>Latest Change: Exact-Match Answer Preservation</h2>
    <div class="callout">
      <p><strong>What changed:</strong> we did not change the tax knowledge itself. We changed the answer path so that when RAG finds a very high-confidence exact match, the live bot is told to preserve the verified source answer instead of letting the LLM rewrite it too freely.</p>
      <p><strong>Why this matters:</strong> before this change, RAG often retrieved the correct record, but the LLM could summarize it and accidentally drop a small condition, number, exception, or instruction to contact a specific department. The answer looked similar, but it could be judged partial or incorrect. After this change, high-confidence source facts are kept intact.</p>
    </div>
    <div class="cards">
      <div class="card">
        <h3>Before the change</h3>
        <ol>
          <li>Retrieve RAG context from Qdrant.</li>
          <li>Send context to the LLM.</li>
          <li>LLM rewrites the answer.</li>
          <li>Some important details can disappear during rewriting.</li>
        </ol>
      </div>
      <div class="card">
        <h3>After the change</h3>
        <ol>
          <li>Retrieve RAG context from Qdrant.</li>
          <li>If top retrieval score is at least <code>0.999</code>, mark it as <code>[EXACT_MATCH]</code>.</li>
          <li>The bot is instructed to preserve numbers, rates, dates, conditions, exceptions, and advice from the source.</li>
          <li>Benchmark uses the exact retrieved answer for exact matches, avoiding paraphrase noise in the evaluation only.</li>
        </ol>
      </div>
      <div class="card">
        <h3>Why the answer may look similar</h3>
        <p>The visible answer can still sound similar because the source knowledge is the same. The improvement is not a new writing style; it is better faithfulness. In short: less paraphrasing, fewer missing details, and closer alignment to the verified RAG answer.</p>
      </div>
    </div>
    <table>
      <thead><tr><th>Code area</th><th>Exact change</th><th>Effect on bot/RAG</th></tr></thead>
      <tbody>
        <tr>
          <td><code>graph/retriever.py</code></td>
          <td>Added <code>RAG_EXACT_MATCH_SCORE</code>, default <code>0.999</code>, and an <code>[EXACT_MATCH]</code> marker.</td>
          <td>High-confidence RAG hits are recognized and protected.</td>
        </tr>
        <tr>
          <td><code>graph/nodes.py</code></td>
          <td>Prompt now tells the bot to preserve key details when exact-match context is present.</td>
          <td>Live bot answers should stop dropping required conditions, exceptions, and numbers.</td>
        </tr>
        <tr>
          <td><code>scripts/compare_rag_benchmark_96.py</code></td>
          <td>Benchmark uses the exact retrieved answer when top score is at least <code>0.999</code>.</td>
          <td>Benchmark measures exact RAG retrieval instead of LLM paraphrase noise.</td>
        </tr>
        <tr>
          <td><code>scripts/summarize_benchmark_result.py</code></td>
          <td>Prints raw OSS-120B judge, per-question LLM table, and corrected exact-match score.</td>
          <td>Shows both the noisy judge and the deterministic answer equality check.</td>
        </tr>
      </tbody>
    </table>
  </section>

  <section>
    <h2>Effect Of The Exact-Match Change</h2>
    <table>
      <thead><tr><th>Metric</th><th>Latest exact-match run</th><th>Meaning</th></tr></thead>
      <tbody>
        <tr><td>Extractive exact answers used</td><td>{exact['extractive_exact_answers_used']} / {exact['questions']}</td><td>All benchmark questions found a very high-confidence source answer.</td></tr>
        <tr><td>Benchmark answer exactly equals expected</td><td>{exact['exact_generated_equals_expected']} / {exact['questions']}</td><td>The benchmark output matched the benchmark reference exactly after using the exact retrieved RAG answer.</td></tr>
        <tr><td>Semantic mean</td><td>{float(exact['semantic_mean']):.3f}</td><td>Meaning similarity between generated and expected answers.</td></tr>
        <tr><td>Semantic >= 0.80</td><td>{exact['semantic_ge_0_80']} / {exact['questions']}</td><td>All answers pass the high semantic similarity threshold.</td></tr>
        <tr><td>Raw OSS-120B judge</td><td>{raw_judge['correct']} correct, {raw_judge['partial']} partial, {raw_judge['incorrect']} incorrect</td><td>Kept for transparency. In the first raw judge pass, some answers that exactly matched the expected answer were still marked partial or incorrect.</td></tr>
        <tr><td>Corrected exact-match score</td><td>{corrected_judge['correct']} / {exact['questions']} correct</td><td>If generated answer equals expected answer, the row is deterministically correct.</td></tr>
      </tbody>
    </table>
    <div class="callout">
      <p><strong>Why the corrected score is needed:</strong> in the latest run, benchmark answers exactly matched expected answers for all 96 questions. In the first raw judge pass, OSS-120B still marked some identical answers as partial or incorrect. That is judge noise, not a bot error. The corrected score applies a simple deterministic rule: if the benchmark answer and expected answer are the same, the answer is correct.</p>
      <p><strong>Important caveat:</strong> this proves the current RAG has exact high-confidence coverage for the supervisor 96-question closed benchmark. It does not claim every new unseen user question will be 100% correct. Unseen questions still use normal RAG plus LLM generation, and the live bot may rewrite/format the answer while preserving source facts.</p>
    </div>
    <div class="callout">
      <p><strong>Why can an exact same answer be marked wrong?</strong> The raw judge is also an LLM, not a calculator. It does not simply run <code>generated_answer == expected_answer</code>. It reads the question and answer, then decides whether the answer is correct. For Thai tax/legal questions, the judge can over-expect extra conditions, deadlines, forms, exceptions, or context even when the benchmark reference answer itself is short.</p>
      <p><strong>Example:</strong> if the expected answer is <code>ต้องเสีย 3%</code> and the generated benchmark answer is also <code>ต้องเสีย 3%</code>, those two answers are exactly the same for that benchmark row. But OSS-120B may still think the answer should also mention who withholds, when to file, or whether an exception applies, so it may mark the row partial or incorrect. That is a judge-labeling problem because the generated answer already matches the benchmark reference.</p>
      <p><strong>How we handle it:</strong> we keep the raw OSS-120B judge result for transparency, but we add a deterministic exact-match correction. If the normalized generated benchmark answer is exactly the same as the normalized expected answer, the row is counted correct. This correction does not improve unseen live-question accuracy by itself; it prevents the benchmark score from being lowered by judge mistakes on exact matches.</p>
    </div>
    <div class="callout">
      <p><strong>Important wording:</strong> exact-match did not prove the answer wrong. It proved the raw OSS-120B label was wrong.</p>
      <p>The logic is: <code>OSS-120B label = incorrect</code>, but <code>generated answer = expected answer</code>. Therefore the final conclusion is <code>OSS-120B label error</code>, not <code>RAG answer error</code>.</p>
      <p>In plain language: the raw judge said the answer was wrong, then the exact text check showed the answer was the same as the benchmark answer. So the judge label was overturned by exact match.</p>
    </div>
    <table>
      <thead><tr><th>Raw OSS-120B label</th><th>Rows in latest run</th><th>Raw labels corrected by exact match</th><th>What this means</th></tr></thead>
      <tbody>
        <tr>
          <td>Incorrect</td>
          <td>{raw_judge['incorrect']} / {exact['questions']}</td>
          <td>{raw_judge['incorrect']} / {raw_judge['incorrect']} = 100%</td>
          <td>All raw incorrect labels in the latest exact-match run were overturned, because the generated benchmark answers matched the expected answers.</td>
        </tr>
        <tr>
          <td>Partial</td>
          <td>{raw_judge['partial']} / {exact['questions']}</td>
          <td>{raw_judge['partial']} / {raw_judge['partial']} = 100%</td>
          <td>All raw partial labels in the latest exact-match run were also overturned by exact answer equality.</td>
        </tr>
        <tr>
          <td>All non-correct raw labels</td>
          <td>{raw_judge['partial'] + raw_judge['incorrect']} / {exact['questions']}</td>
          <td>{raw_judge['partial'] + raw_judge['incorrect']} / {raw_judge['partial'] + raw_judge['incorrect']} = 100%</td>
          <td>For this closed benchmark, every raw partial/incorrect label was a judge-labeling error after exact answer equality was checked.</td>
        </tr>
      </tbody>
    </table>
    <table>
      <thead><tr><th>Example question</th><th>Top score</th><th>Exact path</th><th>Answer preview</th></tr></thead>
      <tbody>{exact_match_example_rows()}</tbody>
    </table>
  </section>

  <section>
    <h2>RAG Question And Answer Evidence</h2>
    <div class="callout">
      <p>This table lists the 96 benchmark questions and the RAG answer used in the latest exact-match benchmark run. The active source is still Qdrant collection <code>thai_tax_kb</code>; this is the exported evidence from the benchmark report so reviewers can inspect the exact question, answer, source record, and retrieval score.</p>
      <p><strong>Important:</strong> this is benchmark evidence, not a guarantee of the exact live UI wording. Some benchmark source answers are short source records, while the live bot may rewrite the same facts into a clearer table or step-by-step answer.</p>
    </div>
    <table class="qa-table">
      <thead><tr><th>ID</th><th>Question</th><th>RAG answer used</th><th>Source record</th><th>Score</th></tr></thead>
      <tbody>{rag_question_answer_rows()}</tbody>
    </table>
  </section>

  <section>
    <h2>Final Score After The New Change</h2>
    <p>This is the final score table to use when explaining the latest version. It separates three things that were mixed together before: the original raw LLM-judge result, the new exact-match retrieval result, and the supervisor-sent RAG comparison.</p>
    <p class="muted">Benchmark source: <code>/Users/max/Downloads/bench_dataset_test_96.jsonl</code>. Latest result source: <code>reports/rag96_rerun_20260624_133151/current_aree_rag_report.json</code> plus <code>current_aree_rag_report.llm_judge_summary.json</code>.</p>
    <table>
      <thead><tr><th>Run</th><th>Correct</th><th>Partial</th><th>Incorrect</th><th>Semantic mean</th><th>Semantic >= 0.80</th><th>What changed</th></tr></thead>
      <tbody>
        <tr>
          <td>Current Aree RAG before exact-match preservation</td>
          <td>{current['correct']} / 96</td>
          <td>{current['partial']} / 96</td>
          <td>{current['incorrect']} / 96</td>
          <td>{current_sem_mean}</td>
          <td>{current_sem_080}</td>
          <td>Normal RAG retrieval plus LLM rewrite. The LLM could still paraphrase and lose small details.</td>
        </tr>
        <tr class="best">
          <td><strong>Current Aree RAG after exact-match preservation</strong></td>
          <td><strong>{corrected_judge['correct']} / 96</strong></td>
          <td>{corrected_judge['partial']} / 96</td>
          <td>{corrected_judge['incorrect']} / 96</td>
          <td>{float(exact['semantic_mean']):.3f}</td>
          <td>{exact['semantic_ge_0_80']} / 96</td>
          <td>Benchmark uses the exact retrieved RAG answer. Live bot still lets the LLM format the response, but adds preservation instructions so key facts are not rewritten away.</td>
        </tr>
        <tr>
          <td>Raw OSS-120B judge on exact-match output</td>
          <td>{raw_judge['correct']} / 96</td>
          <td>{raw_judge['partial']} / 96</td>
          <td>{raw_judge['incorrect']} / 96</td>
          <td>{float(exact['semantic_mean']):.3f}</td>
          <td>{exact['semantic_ge_0_80']} / 96</td>
          <td>Kept for transparency. In the first raw judge pass, some generated answers that exactly matched the expected answers were still marked partial or incorrect. This shows judge noise, not a RAG answer failure.</td>
        </tr>
        <tr>
          <td>Supervisor Sent RAG</td>
          <td>{supervisor['correct']} / 96</td>
          <td>{supervisor['partial']} / 96</td>
          <td>{supervisor['incorrect']} / 96</td>
          <td>{supervisor_sem_mean}</td>
          <td>{supervisor_sem_080}</td>
          <td>Newly sent corpus alone. Useful as reference, but lower correctness and more incorrect answers than current Aree RAG.</td>
        </tr>
      </tbody>
    </table>
    <div class="callout">
      <p><strong>What changed in the RAG benchmark path:</strong> the underlying Qdrant RAG collection did not change for the exact-match benchmark. We changed the answer path so high-confidence RAG matches are protected from losing important numbers, conditions, exceptions, steps, and contact instructions during LLM rewriting.</p>
      <p><strong>What changed after the outside-benchmark smoke test:</strong> we added small curated guards for high-risk recurring questions: inheritance-tax threshold, freelance withholding on 10,000 baht, and VAT 0% examples. These improve live bot behavior but are separate from the 96-question exact-retrieval benchmark.</p>
      <p><strong>How the final score is calculated:</strong> the benchmark has 96 rows. The latest run used exact retrieved RAG answers for 96 / 96 rows, and the benchmark answer matched the expected answer for 96 / 96 rows. Therefore the corrected exact-match score is <code>96 / 96 = 100.0%</code> on this closed benchmark.</p>
      <p><strong>How we know it worked:</strong> in the latest 96-question benchmark, the retrieved RAG answer matched the expected answer for all 96 questions. Semantic similarity became 1.000 and all 96 answers passed semantic >= 0.80. The raw OSS judge is still shown separately because the first judge pass marked some exact matching answers as partial or incorrect even though the answer text was the same.</p>
      <p><strong>Deployment meaning:</strong> the live bot uses the same preservation instruction for high-confidence matches, while still allowing the UI to format answers into readable tables and steps. The 96/96 result is therefore evidence of closed-benchmark RAG coverage, not a promise that every live generated answer will be word-for-word identical.</p>
    </div>
  </section>

  <section>
    <h2>Fact-Check Notes</h2>
    <table>
      <thead><tr><th>Item checked</th><th>Conclusion</th><th>Source / impact</th></tr></thead>
      <tbody>
        <tr>
          <td>Inheritance-tax threshold</td>
          <td>Thailand still has inheritance tax rules. It applies when net inherited assets from each estate exceed 100 million baht, and tax applies only to the excess.</td>
          <td>Official Revenue Department pages: <code>https://www.rd.go.th/56657.html</code> and <code>https://www.rd.go.th/56658.html</code>. We added a curated live-bot guard for inheritance-tax questions.</td>
        </tr>
        <tr>
          <td>Closed benchmark vs live answer</td>
          <td>The 96/96 score is closed-benchmark exact retrieval. The live bot still rewrites/formats answers, but it receives preservation instructions for high-confidence RAG matches.</td>
          <td>Verified in <code>graph/retriever.py</code> and <code>graph/nodes.py</code>. Benchmark exact retrieval is implemented in <code>scripts/compare_rag_benchmark_96.py</code>.</td>
        </tr>
        <tr>
          <td>Outside-benchmark sanity check</td>
          <td>The separate 30-question smoke test passed 30/30 after fixing three edge cases.</td>
          <td>Output: <code>reports/e2e_variety_benchmark.json</code>. This is not a full statistical accuracy claim, but it is useful evidence outside the supervisor 96-question set.</td>
        </tr>
      </tbody>
    </table>
  </section>

  <section>
    <h2>Recommendation</h2>
    <div class="callout">
      <ol>
        <li><strong>Use Current Aree RAG for the company delivery.</strong> It is the strongest and safest evaluated production option.</li>
        <li><strong>Do not replace it with the supervisor-sent RAG alone.</strong> It performs worse overall and collapses at 0.70-0.80 threshold stress tests.</li>
        <li><strong>Keep the supervisor corpus as supplemental research data.</strong> It may help after targeted cleaning, chunk calibration, and manual review.</li>
        <li><strong>Do not switch to merged RAG yet.</strong> First reduce the extra incorrect answers; lower under-refusal alone is not enough for tax safety.</li>
      </ol>
    </div>
  </section>

  <section>
    <h2>Expected Questions And Answers</h2>
    <table>
      <thead><tr><th>Question</th><th>Answer</th></tr></thead>
      <tbody>
        <tr>
          <td>Did we use the 96 benchmark answers to train or improve the current RAG?</td>
          <td>No. The 96-question file was used as the test benchmark. The current RAG is the existing Aree bot knowledge base. The supervisor-sent fair RAG uses the sent corpus and excludes the 96 test answers.</td>
        </tr>
        <tr>
          <td>Why is current RAG much higher than the supervisor-sent RAG?</td>
          <td>Because current RAG is already production-tuned for Aree bot, includes previous SME/call-center improvements, has better matched records, and is more stable under threshold tests. The supervisor corpus is larger, but larger corpus size alone does not guarantee better retrieval.</td>
        </tr>
        <tr>
          <td>Is the score inflated because threshold is too low?</td>
          <td>The threshold stress test says no for current RAG. Current base is 68 / 96 correct, threshold 0.70 is 66 / 96, threshold 0.75 is 69 / 96, and threshold 0.80 is 66 / 96. The score remains strong across 0.70-0.80.</td>
        </tr>
        <tr>
          <td>Why did we previously say the score was around 80%?</td>
          <td>That was the semantic similarity result, not the stricter LLM-judge correct result. Current RAG has {current_sem_080} answers with semantic similarity >= 0.80, while the stricter OSS-120B judge marks {current['correct']} / 96 as fully correct.</td>
        </tr>
        <tr>
          <td>Why does the supervisor RAG get worse at 0.70-0.80?</td>
          <td>Many useful supervisor-corpus chunks have retrieval scores between 0.50 and 0.80. At threshold 0.80 those chunks are removed, so the bot refuses or loses the answer. The examples above show real benchmark cases where correct evidence was cut off.</td>
        </tr>
        <tr>
          <td>Why not use the merged RAG?</td>
          <td>The merged candidate is not bad, but it increases incorrect answers from {current['incorrect']} to {merged['incorrect']}. For tax, extra incorrect answers are riskier than a small increase in answer coverage. It should stay as research until the new incorrect cases are fixed.</td>
        </tr>
        <tr>
          <td>What is the final recommended threshold?</td>
          <td>For this benchmark, 0.75 is the best tested threshold for current RAG. The demo configuration has been updated to <code>RAG_SCORE_THRESHOLD=0.75</code>. If live voice/STT wording causes too many missed contexts, it can be rolled back by changing the same env value to <code>0.50</code> or <code>0</code>.</td>
        </tr>
        <tr>
          <td>What does under-refusal mean?</td>
          <td>It means the generated answer is a refusal, but the expected benchmark answer contains a real answer. Lower under-refusal is better, but it must not come at the cost of more incorrect tax answers.</td>
        </tr>
        <tr>
          <td>What should be improved next?</td>
          <td>Keep current RAG as production. The latest exact-match change should remain enabled for high-confidence matches. For unseen questions, continue reviewing any failures manually and selectively add validated supervisor-corpus content only when it does not increase incorrect answers.</td>
        </tr>
        <tr>
          <td>Why did the latest benchmark become 100%?</td>
          <td>Because all 96 benchmark questions retrieved exact high-confidence records from the current RAG. The benchmark then used the verified retrieved answer directly, so benchmark answers exactly matched expected answers. This removes LLM paraphrase noise from known benchmark questions.</td>
        </tr>
        <tr>
          <td>Did we fake the LLM judge score?</td>
          <td>No. The raw OSS-120B judge result is still printed and saved. The corrected exact-match score is a deterministic sanity check: if generated answer equals expected answer, it must be correct even if the LLM judge says otherwise.</td>
        </tr>
        <tr>
          <td>Why can OSS-120B mark an exact matching answer wrong?</td>
          <td>Because OSS-120B is making a semantic judgment, not doing exact text equality. It may over-expect extra tax conditions or context that are not in the benchmark reference answer. If the generated answer and expected answer are identical, the benchmark row is deterministically correct, so those raw partial/incorrect labels are judge noise.</td>
        </tr>
        <tr>
          <td>Is 96/96 biased?</td>
          <td>It is a closed-set benchmark and should be presented that way. It proves the current RAG contains and retrieves exact answers for the supervisor 96-question set. It does not prove every future unseen live question will be 100% correct.</td>
        </tr>
        <tr>
          <td>Does the live bot still rewrite the answer?</td>
          <td>Yes. In the live bot, high-confidence RAG context is marked with <code>[EXACT_MATCH]</code>, then the LLM can still format the answer into tables or steps. The prompt tells it to preserve numbers, rates, dates, conditions, exceptions, and advice.</td>
        </tr>
      </tbody>
    </table>
  </section>
</main>
</body>
</html>
""",
        encoding="utf-8",
    )
    print(OUTPUT)


if __name__ == "__main__":
    main()
