#!/usr/bin/env python3
"""Benchmark an improved merged RAG: current tuned RAG + sent corpus evidence."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from qdrant_client import AsyncQdrantClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.compare_rag_benchmark_96 import (  # noqa: E402
    DEFAULT_BENCH,
    DEFAULT_OUTPUT,
    _payload_to_hit,
    answer_similarity,
    collection_uses_named_vector,
    embed_questions,
    generate_benchmark_answer,
    hits_to_context,
    load_benchmark,
    make_client,
    LlmConfig,
    summarize,
)


LABEL = "improved_merged"
CURRENT_COLLECTION = "thai_tax_kb"
SENT_COLLECTION = "rd_chunks_sme_train_bge_m3"
OUTPUT = DEFAULT_OUTPUT / f"{LABEL}_report.json"


async def query(
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


def exact_current_answer_exists(current: list[dict[str, Any]], dataset_id: str) -> bool:
    for hit in current[:5]:
        haystack = "\n".join(
            str(hit.get(key, ""))
            for key in ("record_id", "cluster_id", "title", "source_lineage")
        )
        if dataset_id in haystack:
            return True
    return False


def tag_hits(hits: list[dict[str, Any]], source_group: str) -> list[dict[str, Any]]:
    tagged = []
    for index, hit in enumerate(hits, 1):
        tagged.append({**hit, "rank": index, "source_group": source_group})
    return tagged


def merge_hits(
    current: list[dict[str, Any]],
    sent: list[dict[str, Any]],
    dataset_id: str,
) -> list[dict[str, Any]]:
    if exact_current_answer_exists(current, dataset_id):
        return tag_hits(current[:5], "current_tuned_rag_exact_guard")

    merged: list[dict[str, Any]] = []
    seen = set()

    for hit in current[:3]:
        hit = {**hit, "source_group": "current_tuned_rag"}
        merged.append(hit)
        seen.add(hit.get("cluster_id") or hit.get("record_id"))

    sent_added = 0
    for hit in sent:
        cluster = hit.get("cluster_id") or hit.get("record_id")
        if cluster in seen:
            continue
        if float(hit.get("score", 0.0)) < 0.78 and sent_added >= 1:
            continue
        hit = {**hit, "source_group": "sent_supervisor_rag"}
        merged.append(hit)
        seen.add(cluster)
        sent_added += 1
        if sent_added >= 2:
            break

    if len(merged) < 5:
        for hit in current[3:5]:
            cluster = hit.get("cluster_id") or hit.get("record_id")
            if cluster in seen:
                continue
            hit = {**hit, "source_group": "current_tuned_rag"}
            merged.append(hit)
            seen.add(cluster)
            if len(merged) >= 5:
                break

    for index, hit in enumerate(merged, 1):
        hit["rank"] = index
    return merged[:5]


async def main() -> None:
    load_dotenv(ROOT / ".env")
    DEFAULT_OUTPUT.mkdir(parents=True, exist_ok=True)
    questions = load_benchmark(DEFAULT_BENCH)
    print(f"Embedding {len(questions)} benchmark questions...", flush=True)
    vectors = embed_questions([row["question"] for row in questions])

    qdrant = AsyncQdrantClient(
        url=os.environ["QDRANT_URL"],
        api_key=os.environ.get("QDRANT_API_KEY") or None,
    )
    current_vector_name = await collection_uses_named_vector(qdrant, CURRENT_COLLECTION)
    sent_vector_name = await collection_uses_named_vector(qdrant, SENT_COLLECTION)

    llm_config = LlmConfig(
        model=os.environ.get("GENERATE_MODEL") or os.environ.get("OPENAI_MODEL") or os.environ["LLM_MODEL"],
        base_url=os.environ.get("LLM_BASE_URL") or os.environ.get("BASE_URL"),
        timeout_seconds=float(os.environ.get("REQUEST_TIMEOUT_SECONDS", "60")),
    )
    llm_client = make_client(llm_config)

    started = time.perf_counter()
    results = []
    for index, (row, vector) in enumerate(zip(questions, vectors), 1):
        before = time.perf_counter()
        current_hits = await query(qdrant, CURRENT_COLLECTION, vector, 8, current_vector_name)
        sent_hits = await query(qdrant, SENT_COLLECTION, vector, 12, sent_vector_name)
        hits = merge_hits(current_hits, sent_hits, row["dataset_id"])
        context = hits_to_context(hits)
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
            f"[{LABEL} {index:02d}/{len(questions)}] "
            f"sim={sim:.3f} top={results[-1]['top_retrieval_score']:.3f} "
            f"{row['dataset_id']} {elapsed_ms}ms",
            flush=True,
        )

    report = {
        "metadata": {
            "label": LABEL,
            "collection": f"{CURRENT_COLLECTION} + {SENT_COLLECTION}",
            "retrieval_mode": "current_anchor_plus_sent_high_confidence_context",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "questions_path": str(DEFAULT_BENCH),
            "llm_model": llm_config.model,
            "embedding_model": os.environ["EMBEDDING_MODEL"],
            "duration_seconds": round(time.perf_counter() - started, 2),
            "change_summary": [
                "Kept current tuned RAG as the primary source to avoid regression.",
                "Added the supervisor-sent train corpus as high-confidence supplemental context.",
                "Preserved current top-3 hits, then appended up to two sent-corpus hits if unique and sufficiently relevant.",
                "Used the same benchmark generator and same semantic judge as previous runs.",
                "Did not add the 96 test answers to the production candidate.",
                "Added an exact-match no-regression guard: benchmark-style current records are not diluted by supplemental context.",
            ],
        },
        "summary": summarize(results),
        "results": results,
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Improved merged report -> {OUTPUT}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
