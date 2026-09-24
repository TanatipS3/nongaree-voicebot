#!/usr/bin/env python3
"""Run an improved hybrid retrieval benchmark for the sent RAG corpus."""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from types import SimpleNamespace
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


COLLECTION = "rd_chunks_sme_train_bge_m3"
LABEL = "improved_hybrid_train"
OUTPUT = DEFAULT_OUTPUT / f"{LABEL}_report.json"
TOKEN_RE = re.compile(r"[0-9a-zA-Z]+|[ก-๙]{2,}")
FORM_RE = re.compile(
    r"(ภ\.?\s*ง\.?\s*ด\.?\s*\d+|ภงด\s*\d+|ภ\.?\s*พ\.?\s*\d+|ภพ\s*\d+|ค\.?\s*\d+|[0-9]+[a-zA-Z]+)",
    re.IGNORECASE,
)


@dataclass
class SearchRecord:
    point_id: str
    hit: dict[str, Any]
    search_text: str
    tokens: Counter[str]
    length: int
    source_priority: float


def normalize(value: str) -> str:
    return re.sub(r"[^0-9a-zก-๙]+", "", value.lower())


def tokens(value: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(value or "") if token.strip()]


def direction_terms(value: str) -> set[str]:
    norm = normalize(value)
    found = set()
    if any(term in norm for term in ("ไม่ถึง", "น้อยกว่า", "ต่ำกว่า", "ไม่เกิน")):
        found.add("below")
    if any(term in norm for term in ("เกิน", "มากกว่า", "ตั้งแต่", "ถึง180", "ครบ180")):
        found.add("above")
    return found


def domain_terms(value: str) -> set[str]:
    norm = normalize(value)
    found = set()
    if any(term in norm for term in ("นิติบุคคล", "บริษัท", "กำไรสุทธิ", "รอบบัญชี")):
        found.add("CIT")
    if any(term in norm for term in ("บุคคลธรรมดา", "เงินเดือน", "ลดหย่อน", "รายได้", "ภงด90", "ภงด91", "ภงด94")):
        found.add("PIT")
    if any(term in norm for term in ("ภาษีมูลค่าเพิ่ม", "แวต", "vat", "ใบกำกับ", "ภพ")):
        found.add("VAT")
    if any(term in norm for term in ("หักณที่จ่าย", "หักณที่จ่าย", "หักณที่จ่าย", "หักณ", "ณที่จ่าย")):
        found.add("WHT")
    return found


def exact_forms(value: str) -> set[str]:
    return {normalize(match.group(1)) for match in FORM_RE.finditer(value or "")}


def source_priority(hit: dict[str, Any]) -> float:
    record_id = hit.get("record_id", "")
    lineage = hit.get("source_lineage", "")
    if str(record_id).startswith("SME-TRAIN:"):
        return 0.10
    if "nong_ari" in str(lineage):
        return 0.08
    return 0.0


def severe_mismatch(query: str, hit: dict[str, Any]) -> bool:
    text = "\n".join(str(hit.get(key, "")) for key in ("record_id", "title", "domain", "answer"))
    q_forms = exact_forms(query)
    if q_forms and not (q_forms & exact_forms(text)):
        return True

    q_direction = direction_terms(query)
    h_direction = direction_terms(text)
    if "below" in q_direction and h_direction == {"above"}:
        return True
    if "above" in q_direction and h_direction == {"below"}:
        return True
    return False


async def load_records(qdrant: AsyncQdrantClient, collection: str) -> list[SearchRecord]:
    rows: list[SearchRecord] = []
    offset = None
    rank = 1
    while True:
        points, offset = await qdrant.scroll(
            collection_name=collection,
            limit=512,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in points:
            fake = SimpleNamespace(id=point.id, payload=point.payload or {}, score=0.0)
            hit = _payload_to_hit(fake, rank)
            search_text = "\n".join(
                str(part)
                for part in (
                    hit.get("record_id"),
                    hit.get("title"),
                    hit.get("domain"),
                    hit.get("source_lineage"),
                    hit.get("answer"),
                )
                if part
            )
            tok = Counter(tokens(search_text))
            rows.append(
                SearchRecord(
                    point_id=str(point.id),
                    hit=hit,
                    search_text=search_text,
                    tokens=tok,
                    length=sum(tok.values()) or 1,
                    source_priority=source_priority(hit),
                )
            )
            rank += 1
        if offset is None:
            break
    return rows


def build_idf(records: list[SearchRecord]) -> dict[str, float]:
    df: Counter[str] = Counter()
    for record in records:
        df.update(record.tokens.keys())
    total = len(records)
    return {
        token: math.log((total - count + 0.5) / (count + 0.5) + 1)
        for token, count in df.items()
    }


def lexical_score(query: str, record: SearchRecord, idf: dict[str, float], avg_len: float) -> float:
    query_tokens = tokens(query)
    if not query_tokens:
        return 0.0
    k1 = 1.4
    b = 0.72
    score = 0.0
    for token in query_tokens:
        tf = record.tokens.get(token, 0)
        if not tf:
            continue
        denom = tf + k1 * (1 - b + b * record.length / avg_len)
        score += idf.get(token, 0.0) * ((tf * (k1 + 1)) / denom)

    q_norm = normalize(query)
    r_norm = normalize(record.search_text)
    if q_norm and q_norm in r_norm:
        score += 10.0

    q_forms = exact_forms(query)
    if q_forms:
        r_forms = exact_forms(record.search_text)
        matches = q_forms & r_forms
        score += 9.0 * len(matches)
        if not matches:
            score -= 3.0

    q_domain = domain_terms(query)
    if q_domain:
        record_domain = str(record.hit.get("domain") or "").upper()
        if any(domain in record_domain for domain in q_domain):
            score += 2.0

    q_direction = direction_terms(query)
    r_direction = direction_terms(record.search_text)
    if q_direction and r_direction:
        if q_direction & r_direction:
            score += 2.0
        elif "below" in q_direction and "above" in r_direction:
            score -= 4.0
        elif "above" in q_direction and "below" in r_direction:
            score -= 4.0

    return max(score, 0.0)


async def dense_hits(
    qdrant: AsyncQdrantClient,
    vector: list[float],
    collection: str,
    vector_name: str | None,
    limit: int,
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


def hybrid_rank(
    query: str,
    dense: list[dict[str, Any]],
    records: list[SearchRecord],
    idf: dict[str, float],
    avg_len: float,
    limit: int,
) -> list[dict[str, Any]]:
    dense_by_id = {hit["record_id"]: hit for hit in dense}
    dense_scores = {hit["record_id"]: float(hit["score"]) for hit in dense}
    lexical_scored = [
        (lexical_score(query, record, idf, avg_len), record)
        for record in records
    ]
    lexical_scored.sort(key=lambda item: item[0], reverse=True)
    top_lexical = lexical_scored[:80]
    max_lexical = max((score for score, _ in top_lexical), default=1.0) or 1.0

    candidates: dict[str, dict[str, Any]] = {}
    for hit in dense:
        candidates[hit["record_id"]] = {**hit}
    for lex_score, record in top_lexical:
        candidates.setdefault(record.hit["record_id"], {**record.hit})
        candidates[record.hit["record_id"]]["_lexical_score"] = lex_score / max_lexical
        candidates[record.hit["record_id"]]["_source_priority"] = record.source_priority

    ranked = []
    for record_id, hit in candidates.items():
        dense_score = dense_scores.get(record_id, 0.0)
        lexical_norm = float(hit.get("_lexical_score", 0.0))
        priority = float(hit.get("_source_priority", source_priority(hit)))
        combined = (0.78 * dense_score) + (0.16 * lexical_norm) + priority
        if record_id.startswith("SME-TRAIN:"):
            combined += 0.02
        hit = {key: value for key, value in hit.items() if not key.startswith("_")}
        hit["score"] = min(combined, 1.0)
        hit["hybrid_dense_score"] = dense_score
        hit["hybrid_lexical_score"] = lexical_norm
        ranked.append(hit)

    ranked.sort(key=lambda item: item["score"], reverse=True)
    deduped = []
    seen_clusters = set()

    # Dense retrieval is usually the most stable signal. Keep clean dense anchors,
    # then use hybrid reranking to add rescue context. Only skip an anchor when it
    # visibly contradicts exact query constraints such as form number or direction.
    anchors = [hit for hit in dense[:2] if not severe_mismatch(query, hit)]
    ordered = anchors + [
        hit
        for hit in ranked
        if hit.get("record_id") not in {anchor.get("record_id") for anchor in anchors}
    ]

    for hit in ordered:
        cluster = hit.get("cluster_id") or hit.get("record_id")
        if cluster in seen_clusters:
            continue
        seen_clusters.add(cluster)
        hit["rank"] = len(deduped) + 1
        deduped.append(hit)
        if len(deduped) >= limit:
            break
    return deduped


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
    vector_name = await collection_uses_named_vector(qdrant, COLLECTION)
    print(f"Loading payloads from {COLLECTION}...", flush=True)
    records = await load_records(qdrant, COLLECTION)
    idf = build_idf(records)
    avg_len = mean(record.length for record in records)
    print(f"Loaded {len(records)} records for hybrid lexical rerank.", flush=True)

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
        dense = await dense_hits(qdrant, vector, COLLECTION, vector_name, limit=80)
        hits = hybrid_rank(row["question"], dense, records, idf, avg_len, limit=5)
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
            "collection": COLLECTION,
            "retrieval_mode": "hybrid_dense_bm25_metadata_rerank",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "questions_path": str(DEFAULT_BENCH),
            "llm_model": llm_config.model,
            "embedding_model": os.environ["EMBEDDING_MODEL"],
            "duration_seconds": round(time.perf_counter() - started, 2),
            "change_summary": [
                "Kept the sent fair train collection as the knowledge base.",
                "Added dense top-80 retrieval instead of dense top-5.",
                "Added BM25-style lexical scoring over record id, title, domain, source lineage, and answer text.",
                "Boosted exact tax form/code matches, domain hints, and SME train records.",
                "Penalized obvious direction mismatches such as below-180-day questions retrieving above-180-day records.",
                "Fused dense, lexical, and metadata scores before passing top-5 context to the same answer generator.",
            ],
        },
        "summary": summarize(results),
        "results": results,
    }
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Improved report -> {OUTPUT}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
