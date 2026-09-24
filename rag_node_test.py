"""Manual test runner for the Nongaree retrieve node.

This file is intentionally separate from the voicebot graph so RAG/retrieval
testing does not clutter the production agent flow.

Usage:
    python rag_node_test.py "เงินเดือนเท่าไหร่ถึงต้องเสียภาษี?"
"""

from __future__ import annotations

import argparse
import asyncio
import os
from textwrap import shorten

from dotenv import load_dotenv


REQUIRED_ENV = (
    "QDRANT_URL",
    "QDRANT_COLLECTION",
    "EMBEDDING_BASE_URL",
    "EMBEDDING_API_KEY",
    "EMBEDDING_MODEL",
)


def _validate_env() -> None:
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        joined = ", ".join(missing)
        raise SystemExit(
            "Missing required environment variables for retrieval test: "
            f"{joined}\n"
            "Create/update .env first, then rerun this script."
        )


async def _run(query: str) -> None:
    from graph.nodes import retrieve_node

    result = await retrieve_node(
        {
            "messages": [],
            "query": query,
            "context": "",
            "answer": "",
            "emotion": "idle",
            "route": "rag",
        }
    )
    context = result.get("context", "").strip()

    print("\nQuery")
    print(query)
    print("\nRetrieved context")
    if not context:
        print("(no context returned)")
        return

    print(context)
    print("\nPreview")
    print(shorten(context.replace("\n", " "), width=500, placeholder=" ..."))


def main() -> None:
    parser = argparse.ArgumentParser(description="Test the Nongaree retrieve node.")
    parser.add_argument(
        "query",
        nargs="?",
        default="เงินเดือนเท่าไหร่ถึงต้องเสียภาษี?",
        help="Thai tax question to retrieve evidence for.",
    )
    args = parser.parse_args()

    load_dotenv()
    _validate_env()
    asyncio.run(_run(args.query))


if __name__ == "__main__":
    main()
