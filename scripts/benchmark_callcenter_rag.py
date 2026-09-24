#!/usr/bin/env python3
"""Benchmark Qdrant retrieval against Nong Ari SME benchmark data."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
from pathlib import Path
from statistics import mean

from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import AsyncQdrantClient

DEFAULT_DATASET = (
    Path(__file__).resolve().parents[2]
    / "agent-rack"
    / "01_dataset"
    / "nong_ari_callcenter_corrected_items.csv"
)
DEFAULT_THRESHOLDS = (0.5, 0.7, 0.8)
RELEVANT_OVERLAP_THRESHOLD = 0.20


def _normalize(value: str) -> str:
    return re.sub(r"[^0-9a-zก-๙]+", "", value.lower())


def _token_set(value: str) -> set[str]:
    return set(re.findall(r"[0-9a-zA-Z]+|[ก-๙]{2,}", value.lower()))


def _load_rows(path: Path, max_rows: int | None = None) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as file:
        rows = list(csv.DictReader(file))
    if max_rows is not None:
        rows = rows[:max_rows]
    return rows


def _embedding(text: str) -> list[float]:
    client = OpenAI(
        base_url=os.environ["EMBEDDING_BASE_URL"],
        api_key=os.environ["EMBEDDING_API_KEY"],
    )
    response = client.embeddings.create(input=text, model=os.environ["EMBEDDING_MODEL"])
    return response.data[0].embedding


def _payload_text(payload: dict) -> str:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    return "\n".join(
        str(part)
        for part in (
            payload.get("page_content"),
            metadata.get("text_clean"),
            metadata.get("record_id"),
            metadata.get("traceability_ref"),
            metadata.get("expected_answer_source"),
        )
        if part
    )


def _hit_is_expected(row: dict[str, str], payload: dict) -> bool:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    expected_id = row["dataset_id"]
    if metadata.get("record_id") == expected_id:
        return True
    if metadata.get("source_dataset_id") == expected_id:
        return True
    text = _payload_text(payload)
    return expected_id in text or row["question"] in text


def _overlap_score(expected: str, actual: str) -> float:
    expected_tokens = _token_set(expected)
    if not expected_tokens:
        return 0.0
    actual_tokens = _token_set(actual)
    return len(expected_tokens & actual_tokens) / len(expected_tokens)


async def _query_row(client: AsyncQdrantClient, row: dict[str, str], limit: int) -> dict:
    loop = asyncio.get_running_loop()
    vector = await loop.run_in_executor(None, _embedding, row["question"])
    result = await client.query_points(
        collection_name=os.environ["QDRANT_COLLECTION"],
        query=vector,
        using=os.environ.get("QDRANT_VECTOR_NAME", "dense"),
        limit=limit,
        with_payload=True,
        with_vectors=False,
    )
    hits = []
    for rank, point in enumerate(result.points, 1):
        payload = point.payload or {}
        text = _payload_text(payload)
        hits.append(
            {
                "rank": rank,
                "id": str(point.id),
                "score": float(point.score or 0.0),
                "expected": _hit_is_expected(row, payload),
                "answer_overlap": _overlap_score(row["expected_answer"], text),
                "relevant_by_overlap": _overlap_score(row["expected_answer"], text)
                >= RELEVANT_OVERLAP_THRESHOLD,
                "source": (payload.get("metadata") or {}).get("expected_answer_source", ""),
            }
        )
    return {"row": row, "hits": hits}


def _summarize(results: list[dict], thresholds: tuple[float, ...]) -> dict:
    top_scores = [item["hits"][0]["score"] for item in results if item["hits"]]
    summary = {
        "questions": len(results),
        "avg_top_score": mean(top_scores) if top_scores else 0.0,
        "expected_in_top1": sum(bool(item["hits"] and item["hits"][0]["expected"]) for item in results),
        "expected_in_top5": sum(any(hit["expected"] for hit in item["hits"][:5]) for item in results),
        "relevant_overlap_threshold": RELEVANT_OVERLAP_THRESHOLD,
        "relevant_in_top1": sum(
            bool(item["hits"] and item["hits"][0]["relevant_by_overlap"]) for item in results
        ),
        "relevant_in_top5": sum(
            any(hit["relevant_by_overlap"] for hit in item["hits"][:5]) for item in results
        ),
        "avg_best_top5_answer_overlap": mean(
            max((hit["answer_overlap"] for hit in item["hits"][:5]), default=0.0)
            for item in results
        )
        if results
        else 0.0,
        "thresholds": {},
    }
    for threshold in thresholds:
        accepted = [
            item
            for item in results
            if item["hits"] and item["hits"][0]["score"] >= threshold
        ]
        expected_accepted = [
            item
            for item in accepted
            if any(hit["expected"] for hit in item["hits"][:5] if hit["score"] >= threshold)
        ]
        relevant_accepted = [
            item
            for item in accepted
            if any(
                hit["relevant_by_overlap"]
                for hit in item["hits"][:5]
                if hit["score"] >= threshold
            )
        ]
        summary["thresholds"][str(threshold)] = {
            "accepted_top1": len(accepted),
            "accepted_top1_pct": len(accepted) / len(results) if results else 0.0,
            "expected_accepted_top5": len(expected_accepted),
            "expected_accepted_top5_pct": len(expected_accepted) / len(results) if results else 0.0,
            "relevant_accepted_top5": len(relevant_accepted),
            "relevant_accepted_top5_pct": len(relevant_accepted) / len(results) if results else 0.0,
        }
    return summary


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--max-rows", type=int)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--thresholds",
        default=",".join(str(value) for value in DEFAULT_THRESHOLDS),
        help="Comma-separated score thresholds to report.",
    )
    args = parser.parse_args()

    load_dotenv(Path.cwd() / ".env")
    thresholds = tuple(float(value) for value in args.thresholds.split(",") if value)
    rows = _load_rows(args.dataset, args.max_rows)
    client = AsyncQdrantClient(
        url=os.environ["QDRANT_URL"],
        api_key=os.environ.get("QDRANT_API_KEY") or None,
    )
    results = []
    for index, row in enumerate(rows, 1):
        item = await _query_row(client, row, args.limit)
        results.append(item)
        top = item["hits"][0] if item["hits"] else {"score": 0, "expected": False}
        best_overlap = max((hit["answer_overlap"] for hit in item["hits"][:5]), default=0.0)
        print(
            f"[{index:02d}/{len(rows)}] {row['dataset_id']} "
            f"top={top['score']:.4f} expected_top1={top['expected']} "
            f"best_overlap_top5={best_overlap:.2f}"
        )

    summary = _summarize(results, thresholds)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    asyncio.run(main())
