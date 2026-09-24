#!/usr/bin/env python3
"""Compare current and candidate RAG collections on the 96-question benchmark."""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import AsyncQdrantClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

JUDGE_PACKAGE = Path("/Users/max/Downloads/semantic_eval_llm_judge")
if JUDGE_PACKAGE.exists() and str(JUDGE_PACKAGE) not in sys.path:
    sys.path.insert(0, str(JUDGE_PACKAGE))

try:
    from rag_bench.evaluate import answer_similarity
    from rag_bench.llm import LlmConfig, generate_benchmark_answer, make_client
    from rag_bench.rag import format_context
except ImportError as exc:  # pragma: no cover - CLI dependency guard
    raise SystemExit(
        "Missing semantic_eval_llm_judge package. Expected it at "
        f"{JUDGE_PACKAGE}. Original error: {exc}"
    ) from exc


DEFAULT_BENCH = Path("/Users/max/Downloads/bench_dataset_test_96.jsonl")
DEFAULT_OUTPUT = ROOT / "reports" / "rag96_comparison"
DEFAULT_COLLECTIONS = (
    "current:thai_tax_kb",
    "candidate_train:rd_chunks_sme_train_bge_m3",
    "candidate_all_debug:rd_chunks_sme_all_bge_m3_extractive",
)
THRESHOLDS = (0.5, 0.7, 0.8)
EXTRACTIVE_EXACT_MATCH_SCORE = float(os.getenv("BENCH_EXTRACTIVE_EXACT_SCORE", "0.999") or "0.999")


@dataclass(frozen=True)
class CollectionSpec:
    label: str
    name: str


def _clean_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def load_benchmark(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            row = json.loads(line)
            row["question"] = _clean_text(row.get("question"))
            row["expected_answer"] = _clean_text(row.get("expected_answer"))
            row.setdefault("split_80_20", "test")
            row.setdefault("expected_answer_source", "")
            rows.append(row)
    return rows


def parse_collection_specs(values: list[str]) -> list[CollectionSpec]:
    specs = []
    for value in values:
        if ":" in value:
            label, name = value.split(":", 1)
        else:
            label = value
            name = value
        specs.append(CollectionSpec(label=label.strip(), name=name.strip()))
    return specs


def _embedding_client() -> OpenAI:
    return OpenAI(
        base_url=os.environ["EMBEDDING_BASE_URL"],
        api_key=os.environ["EMBEDDING_API_KEY"],
    )


def embed_questions(questions: list[str]) -> list[list[float]]:
    client = _embedding_client()
    response = client.embeddings.create(
        input=questions,
        model=os.environ["EMBEDDING_MODEL"],
    )
    return [item.embedding for item in sorted(response.data, key=lambda item: item.index)]


def _payload_to_hit(point: Any, rank: int) -> dict[str, Any]:
    payload = point.payload or {}
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}

    record_id = (
        payload.get("record_id")
        or metadata.get("record_id")
        or metadata.get("source_dataset_id")
        or str(point.id)
    )
    title = (
        payload.get("title")
        or metadata.get("title")
        or metadata.get("domain")
        or ""
    )
    answer = (
        payload.get("answer")
        or payload.get("text_original")
        or payload.get("text")
        or payload.get("content")
        or metadata.get("text_clean")
        or payload.get("page_content")
        or ""
    )
    domain = payload.get("domain") or metadata.get("domain") or ""
    ref_link = payload.get("ref_link") or metadata.get("ref_link") or metadata.get("ref_links") or ""
    cluster_id = payload.get("cluster_id") or metadata.get("cluster_id") or str(point.id)
    source_lineage = payload.get("source_lineage") or metadata.get("expected_answer_source") or ""
    problem = payload.get("problem") or metadata.get("traceability_ref") or ""

    if payload.get("page_content") and not answer:
        answer = payload["page_content"]
    if not title and problem:
        title = problem

    return {
        "rank": rank,
        "record_id": str(record_id),
        "cluster_id": str(cluster_id),
        "title": _clean_text(title),
        "answer": _clean_text(answer),
        "domain": _clean_text(domain),
        "ref_link": _clean_text(ref_link),
        "score": float(point.score or 0.0),
        "source_lineage": _clean_text(source_lineage),
    }


def hits_to_context(hits: list[dict[str, Any]]) -> str:
    rag_hits = []
    for hit in hits:
        rag_hits.append(
            type(
                "RagHitObj",
                (),
                {
                    "record_id": hit["record_id"],
                    "cluster_id": hit["cluster_id"],
                    "title": hit["title"],
                    "answer": hit["answer"],
                    "domain": hit["domain"],
                    "ref_link": hit["ref_link"],
                    "score": hit["score"],
                    "source_lineage": hit["source_lineage"],
                },
            )()
        )
    return format_context(rag_hits)


def should_use_extractive_answer(hits: list[dict[str, Any]]) -> bool:
    if os.getenv("BENCH_EXTRACTIVE_EXACT", "true").lower() == "false":
        return False
    return bool(hits and hits[0]["score"] >= EXTRACTIVE_EXACT_MATCH_SCORE and hits[0]["answer"].strip())


async def query_collection(
    qdrant: AsyncQdrantClient,
    collection: str,
    vector: list[float],
    limit: int,
    vector_name: str | None,
) -> list[dict[str, Any]]:
    kwargs: dict[str, Any] = {
        "collection_name": collection,
        "query": vector,
        "limit": limit,
        "with_payload": True,
        "with_vectors": False,
    }
    if vector_name:
        kwargs["using"] = vector_name
    result = await qdrant.query_points(**kwargs)
    return [_payload_to_hit(point, rank) for rank, point in enumerate(result.points, 1)]


async def collection_uses_named_vector(qdrant: AsyncQdrantClient, collection: str) -> str | None:
    info = await qdrant.get_collection(collection)
    vectors = info.config.params.vectors
    if isinstance(vectors, dict):
        return os.environ.get("QDRANT_VECTOR_NAME", "dense")
    return None


def load_judge_ensemble(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    rows = {}
    with path.open(encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            row = json.loads(line)
            rows[row["dataset_id"]] = row
    return rows


def load_semantic_eval(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    rows = {}
    with path.open(encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            row = json.loads(line)
            rows[row["dataset_id"]] = row
    return rows


def summarize(
    results: list[dict[str, Any]],
    judge_rows: dict[str, dict[str, Any]] | None = None,
    semantic_rows: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    judge_rows = judge_rows or {}
    semantic_rows = semantic_rows or {}
    similarities = [row["answer_similarity"] for row in results]
    semantic_scores = [
        semantic_rows[row["dataset_id"]]["semantic_score"]
        for row in results
        if row["dataset_id"] in semantic_rows
    ]
    top_scores = [row["top_retrieval_score"] for row in results]
    fallback_count = sum(row["fallback"] for row in results)
    summary: dict[str, Any] = {
        "questions": len(results),
        "mean_similarity": mean(similarities) if similarities else 0.0,
        "mean_semantic_score": mean(semantic_scores) if semantic_scores else None,
        "mean_top_retrieval_score": mean(top_scores) if top_scores else 0.0,
        "fallback_rate": fallback_count / len(results) if results else 0.0,
        "thresholds": {},
        "judge": {},
    }
    for threshold in THRESHOLDS:
        summary["thresholds"][str(threshold)] = {
            "retrieval_accept_rate": mean(
                row["top_retrieval_score"] >= threshold for row in results
            )
            if results
            else 0.0,
            "similarity_pass_rate": mean(row["answer_similarity"] >= threshold for row in results)
            if results
            else 0.0,
            "semantic_pass_rate": mean(score >= threshold for score in semantic_scores)
            if semantic_scores
            else None,
        }
    verdict_rows = judge_rows or semantic_rows
    if verdict_rows:
        counts: dict[str, int] = {}
        for row in verdict_rows.values():
            label = row.get("ensemble") or row.get("judge_verdict", "unknown")
            if label.startswith("partial:"):
                label = "partial"
            counts[label] = counts.get(label, 0) + 1
        total = sum(counts.values()) or 1
        summary["judge"] = {
            "counts": counts,
            "correct_rate": counts.get("correct", 0) / total,
            "partial_rate": counts.get("partial", 0) / total,
            "incorrect_rate": counts.get("incorrect", 0) / total,
        }
    return summary


async def run_collection(
    spec: CollectionSpec,
    questions: list[dict[str, Any]],
    vectors: list[list[float]],
    output_dir: Path,
    limit: int,
) -> Path:
    qdrant = AsyncQdrantClient(
        url=os.environ["QDRANT_URL"],
        api_key=os.environ.get("QDRANT_API_KEY") or None,
    )
    vector_name = await collection_uses_named_vector(qdrant, spec.name)
    llm_config = LlmConfig(
        model=os.environ.get("GENERATE_MODEL") or os.environ.get("OPENAI_MODEL") or os.environ["LLM_MODEL"],
        base_url=os.environ.get("LLM_BASE_URL") or os.environ.get("BASE_URL"),
        timeout_seconds=float(os.environ.get("REQUEST_TIMEOUT_SECONDS", "60")),
    )
    llm_client = make_client(llm_config)

    results = []
    start = time.perf_counter()
    for index, (row, vector) in enumerate(zip(questions, vectors), 1):
        before = time.perf_counter()
        hits = await query_collection(qdrant, spec.name, vector, limit, vector_name)
        context = hits_to_context(hits)
        used_extractive_exact = should_use_extractive_answer(hits)
        if used_extractive_exact:
            generated = hits[0]["answer"].strip()
        else:
            generated = generate_benchmark_answer(
                context,
                row["question"],
                client=llm_client,
                config=llm_config,
            )
        sim = answer_similarity(generated, row["expected_answer"])
        elapsed_ms = round((time.perf_counter() - before) * 1000)
        results.append(
            {
                "dataset_id": row["dataset_id"],
                "question_number": row.get("question_number", ""),
                "question_type": row.get("question_type", ""),
                "domain_name": row.get("domain_name", ""),
                "split_80_20": row.get("split_80_20", "test"),
                "expected_answer_source": row.get("expected_answer_source", ""),
                "question": row["question"],
                "expected_answer": row["expected_answer"],
                "generated_answer": generated,
                "answer_similarity": sim,
                "top_retrieval_score": hits[0]["score"] if hits else 0.0,
                "used_extractive_exact": used_extractive_exact,
                "retrieved_records": [
                    {key: value for key, value in hit.items() if key != "answer"}
                    for hit in hits
                ],
                "retrieved_context_preview": [
                    {**{key: value for key, value in hit.items() if key != "answer"}, "answer_preview": hit["answer"][:500]}
                    for hit in hits[:3]
                ],
                "fallback": "ไม่แน่ใจ" in generated or not generated.strip(),
                "elapsed_ms": elapsed_ms,
            }
        )
        print(
            f"[{spec.label} {index:02d}/{len(questions)}] "
            f"sim={sim:.3f} top={results[-1]['top_retrieval_score']:.3f} "
            f"extractive={int(used_extractive_exact)} "
            f"{row['dataset_id']} {elapsed_ms}ms",
            flush=True,
        )

    report = {
        "metadata": {
            "label": spec.label,
            "collection": spec.name,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "questions_path": str(DEFAULT_BENCH),
            "llm_model": llm_config.model,
            "embedding_model": os.environ["EMBEDDING_MODEL"],
            "duration_seconds": round(time.perf_counter() - start, 2),
            "extractive_exact_match_score": EXTRACTIVE_EXACT_MATCH_SCORE,
            "extractive_exact_enabled": os.getenv("BENCH_EXTRACTIVE_EXACT", "true").lower() != "false",
        },
        "summary": summarize(results),
        "results": results,
    }
    output = output_dir / f"{spec.label}_report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def pct_or_na(value: float | None) -> str:
    return "not run" if value is None else pct(value)


def num_or_na(value: float | None) -> str:
    return "not run" if value is None else f"{value:.3f}"


def esc(value: Any) -> str:
    return html.escape(str(value or ""))


def row_class(delta: float) -> str:
    if delta >= 0.08:
        return "better"
    if delta <= -0.08:
        return "worse"
    return ""


def render_html(report_paths: list[Path], output: Path) -> None:
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in report_paths]
    for report in reports:
        report_path = Path(report_paths[reports.index(report)])
        judge_path = report_path.with_suffix(".judge_ensemble.jsonl")
        semantic_path = report_path.with_name(report_path.stem + ".semantic_eval.jsonl")
        judge_rows = load_judge_ensemble(judge_path)
        semantic_rows = load_semantic_eval(semantic_path)
        report["judge_rows"] = judge_rows
        report["semantic_rows"] = semantic_rows
        report["summary"] = summarize(report["results"], judge_rows, semantic_rows)

    baseline = reports[0]
    by_id = {
        report["metadata"]["label"]: {row["dataset_id"]: row for row in report["results"]}
        for report in reports
    }
    judge_by_label = {
        report["metadata"]["label"]: report.get("judge_rows", {})
        for report in reports
    }
    semantic_by_label = {
        report["metadata"]["label"]: report.get("semantic_rows", {})
        for report in reports
    }

    cards = []
    for report in reports:
        label = report["metadata"]["label"]
        summary = report["summary"]
        judge = summary.get("judge") or {}
        cards.append(
            f"""
            <section class="card">
              <div class="eyebrow">{esc(label)}</div>
              <h2>{esc(report['metadata']['collection'])}</h2>
              <dl>
                <div><dt>Questions</dt><dd>{summary['questions']}</dd></div>
                <div><dt>Mean semantic score</dt><dd>{num_or_na(summary['mean_semantic_score'])}</dd></div>
                <div><dt>Mean char-ngram score</dt><dd>{summary['mean_similarity']:.3f}</dd></div>
                <div><dt>Semantic pass >= 0.80</dt><dd>{pct_or_na(summary['thresholds']['0.8']['semantic_pass_rate'])}</dd></div>
                <div><dt>Retrieval top score >= 0.80</dt><dd>{pct(summary['thresholds']['0.8']['retrieval_accept_rate'])}</dd></div>
                <div><dt>Fallback rate</dt><dd>{pct(summary['fallback_rate'])}</dd></div>
                <div><dt>LLM judge correct</dt><dd>{pct(judge.get('correct_rate', 0.0)) if judge else 'not run'}</dd></div>
                <div><dt>LLM judge incorrect</dt><dd>{pct(judge.get('incorrect_rate', 0.0)) if judge else 'not run'}</dd></div>
              </dl>
            </section>
            """
        )

    summary_rows = []
    for report in reports:
        summary = report["summary"]
        judge = summary.get("judge") or {}
        summary_rows.append(
            "<tr>"
            f"<td>{esc(report['metadata']['label'])}</td>"
            f"<td>{esc(report['metadata']['collection'])}</td>"
            f"<td>{num_or_na(summary['mean_semantic_score'])}</td>"
            f"<td>{summary['mean_similarity']:.3f}</td>"
            f"<td>{pct_or_na(summary['thresholds']['0.7']['semantic_pass_rate'])}</td>"
            f"<td>{pct_or_na(summary['thresholds']['0.8']['semantic_pass_rate'])}</td>"
            f"<td>{pct(summary['thresholds']['0.8']['similarity_pass_rate'])}</td>"
            f"<td>{pct(summary['thresholds']['0.7']['retrieval_accept_rate'])}</td>"
            f"<td>{pct(summary['thresholds']['0.8']['retrieval_accept_rate'])}</td>"
            f"<td>{pct(judge.get('correct_rate', 0.0)) if judge else 'not run'}</td>"
            f"<td>{pct(judge.get('partial_rate', 0.0)) if judge else 'not run'}</td>"
            f"<td>{pct(judge.get('incorrect_rate', 0.0)) if judge else 'not run'}</td>"
            "</tr>"
        )

    labels = [report["metadata"]["label"] for report in reports]
    detail_rows = []
    for base_row in baseline["results"]:
        dataset_id = base_row["dataset_id"]
        base_sim = base_row["answer_similarity"]
        cells = [
            f"<td><strong>{esc(dataset_id)}</strong><br><span>{esc(base_row['domain_name'])}</span></td>",
            f"<td>{esc(base_row['question'])}</td>",
        ]
        for label in labels:
            row = by_id[label][dataset_id]
            judge_row = judge_by_label[label].get(dataset_id, {})
            semantic_row = semantic_by_label[label].get(dataset_id, {})
            verdict = (
                judge_row.get("ensemble")
                or semantic_row.get("judge_verdict")
                or "not run"
            )
            semantic_score = semantic_row.get("semantic_score")
            delta = row["answer_similarity"] - base_sim
            cells.append(
                f"<td class='{row_class(delta)}'>"
                f"semantic <strong>{semantic_score:.3f}</strong><br>" if semantic_score is not None else ""
                f"char {row['answer_similarity']:.3f}<br>"
                f"top {row['top_retrieval_score']:.3f}<br>"
                f"judge: {esc(verdict)}<br>"
                f"<details><summary>answer</summary><p>{esc(row['generated_answer'])}</p></details>"
                f"<details><summary>top context</summary><p>{esc(row['retrieved_context_preview'][0]['title'] if row['retrieved_context_preview'] else '')}</p></details>"
                "</td>"
            )
        detail_rows.append("<tr>" + "".join(cells) + "</tr>")

    winner = max(reports, key=lambda item: item["summary"]["mean_similarity"])
    judge_ready = any(report.get("judge_rows") for report in reports)
    output.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RAG 96 Benchmark Comparison</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #112936;
      --muted: #607987;
      --line: #b8ddea;
      --soft: #edf9fd;
      --panel: #f7fcfe;
      --good: #d9f2e3;
      --bad: #fde3df;
      --blue: #23799b;
    }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: #ffffff;
    }}
    main {{
      max-width: 1440px;
      margin: 0 auto;
      padding: 32px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 32px;
      letter-spacing: 0;
    }}
    h2 {{
      margin: 6px 0 16px;
      font-size: 20px;
      letter-spacing: 0;
    }}
    p {{
      line-height: 1.55;
    }}
    .muted {{
      color: var(--muted);
    }}
    .notice {{
      margin: 24px 0;
      padding: 16px 18px;
      border: 1px solid var(--line);
      background: var(--soft);
      border-radius: 8px;
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 16px;
      margin: 24px 0;
    }}
    .card {{
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      padding: 18px;
    }}
    .eyebrow {{
      font-size: 12px;
      text-transform: uppercase;
      color: var(--blue);
      font-weight: 700;
      letter-spacing: .08em;
    }}
    dl {{
      display: grid;
      gap: 10px;
      margin: 0;
    }}
    dl div {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      border-top: 1px solid #d5edf5;
      padding-top: 10px;
    }}
    dt {{
      color: var(--muted);
    }}
    dd {{
      margin: 0;
      font-weight: 700;
      text-align: right;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 18px 0 32px;
      font-size: 14px;
    }}
    th, td {{
      border: 1px solid var(--line);
      padding: 10px;
      vertical-align: top;
    }}
    th {{
      background: var(--soft);
      text-align: left;
      position: sticky;
      top: 0;
      z-index: 1;
    }}
    td span {{
      color: var(--muted);
      font-size: 12px;
    }}
    .better {{
      background: var(--good);
    }}
    .worse {{
      background: var(--bad);
    }}
    details {{
      margin-top: 6px;
    }}
    summary {{
      cursor: pointer;
      color: var(--blue);
      font-weight: 650;
    }}
    details p {{
      white-space: pre-wrap;
      max-height: 220px;
      overflow: auto;
      background: #fff;
      border: 1px solid #d5edf5;
      padding: 8px;
      border-radius: 6px;
    }}
    .wide {{
      overflow-x: auto;
    }}
  </style>
</head>
<body>
<main>
  <h1>RAG 96 Benchmark Comparison</h1>
  <p class="muted">Generated {esc(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}. Benchmark: {esc(DEFAULT_BENCH)}.</p>
  <div class="notice">
    <strong>Current result:</strong> best mean similarity is <strong>{esc(winner['metadata']['label'])}</strong>
    ({winner['summary']['mean_similarity']:.3f}). LLM judge columns show {'3-judge ensemble results' if judge_ready else 'not run yet'}.
    <br>Fair comparison note: all collections use the same embedding endpoint and same answer-generation model; only retrieved knowledge differs.
  </div>
  <div class="cards">{''.join(cards)}</div>

  <h2>Metric Summary</h2>
  <div class="wide">
    <table>
      <thead>
        <tr>
          <th>Label</th><th>Collection</th><th>Mean similarity</th>
          <th>Similarity >= 0.5</th><th>Similarity >= 0.7</th><th>Similarity >= 0.8</th>
          <th>Retrieval >= 0.7</th><th>Retrieval >= 0.8</th>
          <th>Judge correct</th><th>Judge partial</th><th>Judge incorrect</th>
        </tr>
      </thead>
      <tbody>{''.join(summary_rows)}</tbody>
    </table>
  </div>

  <h2>Question-Level Comparison</h2>
  <p class="muted">Green means that collection improved similarity by at least 0.08 against the current baseline. Red means it dropped by at least 0.08.</p>
  <div class="wide">
    <table>
      <thead>
        <tr>
          <th>Question ID</th><th>Question</th>
          {''.join(f'<th>{esc(label)}</th>' for label in labels)}
        </tr>
      </thead>
      <tbody>{''.join(detail_rows)}</tbody>
    </table>
  </div>
</main>
</body>
</html>
""",
        encoding="utf-8",
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bench", type=Path, default=DEFAULT_BENCH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--collection", action="append", dest="collections")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--html-only", action="store_true")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    specs = parse_collection_specs(args.collections or list(DEFAULT_COLLECTIONS))
    report_paths = [args.output_dir / f"{spec.label}_report.json" for spec in specs]

    if not args.html_only:
        questions = load_benchmark(args.bench)
        print(f"Embedding {len(questions)} benchmark questions...", flush=True)
        vectors = embed_questions([row["question"] for row in questions])
        report_paths = []
        for spec in specs:
            report_paths.append(
                await run_collection(spec, questions, vectors, args.output_dir, args.limit)
            )

    html_path = args.output_dir / "rag96_comparison.html"
    render_html(report_paths, html_path)
    print(f"HTML report -> {html_path}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
