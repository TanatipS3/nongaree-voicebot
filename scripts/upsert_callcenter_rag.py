#!/usr/bin/env python3
"""Upsert call center corrected Q&A rows into the bot Qdrant collection."""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import re
import uuid
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import PointStruct

DEFAULT_DATASET = (
    Path(__file__).resolve().parents[2]
    / "agent-rack"
    / "01_dataset"
    / "nong_ari_callcenter_corrected_items.csv"
)
POINT_NAMESPACE = uuid.UUID("5d89d0bf-3819-4c9c-b881-b65f6a4fdbfb")


def _normalize(value: str) -> str:
    return re.sub(r"[^0-9a-zก-๙]+", "", value.lower())


def _load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def _domain(domain_code: str) -> str:
    return domain_code.replace(")", "").strip() or "GENERAL"


def _page_content(row: dict[str, str]) -> str:
    return (
        f"[{_domain(row['domain_code'])}] [callcenter_corrected]\n"
        f"หัวข้อ: {row['question']}\n"
        f"คำถามตัวอย่างจากชุด Call Center: {row['question']}\n"
        f"คำตอบที่ตรวจแก้แล้ว: {row['expected_answer']}"
    )


def _embedding_text(row: dict[str, str]) -> str:
    return row["question"]


def _embedding(text: str) -> list[float]:
    client = OpenAI(
        base_url=os.environ["EMBEDDING_BASE_URL"],
        api_key=os.environ["EMBEDDING_API_KEY"],
    )
    response = client.embeddings.create(input=text, model=os.environ["EMBEDDING_MODEL"])
    return response.data[0].embedding


def _point(row: dict[str, str], vector: list[float]) -> PointStruct:
    point_id = str(uuid.uuid5(POINT_NAMESPACE, row["dataset_id"]))
    payload = {
        "page_content": _page_content(row),
        "metadata": {
            "record_id": row["dataset_id"],
            "source_dataset_id": row["dataset_id"],
            "cluster_id": f"CALLCENTER-{row['question_number']}",
            "title": row["question"],
            "text_clean": row["expected_answer"],
            "domain": _domain(row["domain_code"]),
            "subdomain": "callcenter_corrected",
            "knowledge_role": "callcenter_corrected_answer",
            "expected_answer_source": row["expected_answer_source"],
            "source_priority": 5,
            "canonical_score": 1000.0,
            "traceability_ref": f"callcenter_corrected:{row['dataset_id']}",
            "norm_key": _normalize(row["question"]),
            "question": row["question"],
            "question_number": row["question_number"],
            "split_80_20": row["split_80_20"],
            "evaluation_pool": row["evaluation_pool"],
            "knowledge_training_priority": row["knowledge_training_priority"],
            "callcenter_verdict": row["callcenter_verdict"],
            "drifted_both_runs": row["drifted_both_runs"],
            "ref_links": "[]",
            "image_urls": "[]",
            "has_image_asset": False,
        },
    }
    return PointStruct(id=point_id, vector={"dense": vector}, payload=payload)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--batch-size", type=int, default=8)
    args = parser.parse_args()

    load_dotenv(Path.cwd() / ".env")
    rows = _load_rows(args.dataset)
    client = AsyncQdrantClient(
        url=os.environ["QDRANT_URL"],
        api_key=os.environ.get("QDRANT_API_KEY") or None,
    )

    points: list[PointStruct] = []
    loop = asyncio.get_running_loop()
    for index, row in enumerate(rows, 1):
        vector = await loop.run_in_executor(None, _embedding, _embedding_text(row))
        points.append(_point(row, vector))
        print(f"[{index:02d}/{len(rows)}] prepared {row['dataset_id']}")
        if len(points) >= args.batch_size:
            await client.upsert(os.environ["QDRANT_COLLECTION"], points=points, wait=True)
            points.clear()
    if points:
        await client.upsert(os.environ["QDRANT_COLLECTION"], points=points, wait=True)

    info = await client.get_collection(os.environ["QDRANT_COLLECTION"])
    print(f"upserted={len(rows)} collection_points={info.points_count}")


if __name__ == "__main__":
    asyncio.run(main())
