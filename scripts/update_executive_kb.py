"""Bring the RD executive roster in the knowledge base up to date (source: rd.go.th
"ผู้บริหารระดับสูง", ปรับปรุงล่าสุด 21-07-2026 — copy kept at scripts/kb/).

Two operations, and the split is the whole point:

1. **Seven existing chunks are corrected IN PLACE, payload only.** Their vectors are NOT
   touched. `CALLCENTER-98` is the chunk that actually answers "อธิบดีกรมสรรพากรชื่ออะไร"
   today (cosine 0.935 against that query), and that usefulness lives entirely in its
   vector. Re-embedding it on the answer text would throw that away; rewriting the payload
   keeps the retrieval behaviour and changes only the name that comes back.

2. **One new record is ADDED for the full roster**, as five points that share the same
   answer text and differ only in the question each one is embedded from.

**Embed the QUESTION, never the answer.** Measured against this collection: dense search
returns CALLCENTER-* points and essentially nothing else, because those were embedded from
their question text with the current model (`vllm-BAAI/bge-m3`) while the ~1000 original
KC-* vectors sit in a different space — cos(stored KC vector, fresh embedding of its own
text) is ~0.25, i.e. noise. A roster chunk embedded from the roster TEXT would be equally
invisible. The KC-* chunks are reachable only through the lexical half of the hybrid
search, which is why this script leaves their vectors alone rather than pretending to fix
them.

Phone numbers are written **dashed** (`02-272-8261`, not `0 2272 8261`) because
`normalize_phone_numbers_for_tts()` keys on that shape; spaced digits would be spoken as
amounts ("สองพันสองร้อยเจ็ดสิบสอง").

Run it inside the agent container — it has httpx, the credentials and the Qdrant host:

    # look first, change nothing (default)
    docker compose exec -T -e PYTHONIOENCODING=utf-8 agent python - < scripts/update_executive_kb.py
    # apply
    docker compose exec -T -e PYTHONIOENCODING=utf-8 agent python - --yes < scripts/update_executive_kb.py

Stdlib + httpx only, so it runs anywhere the env vars are set. **Restart the agent after
applying** — `graph/retriever.py` caches every payload once per process.
"""

import json
import os
import re
import sys
import uuid

import httpx

try:  # the container gets its env from compose; a host run needs the .env
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except Exception:
    pass

DRY_RUN = "--yes" not in sys.argv
QDRANT_URL = os.environ.get("QDRANT_URL", "http://qdrant:6333").rstrip("/")
COLLECTION = os.environ.get("QDRANT_COLLECTION", "thai_tax_kb")
QDRANT_KEY = os.environ.get("QDRANT_API_KEY") or ""
VECTOR_NAME = os.environ.get("QDRANT_VECTOR_NAME", "dense")

SOURCE_NOTE = "ข้อมูล ณ วันที่ 21 กรกฎาคม 2569"
NAMESPACE = uuid.UUID("7b3a1c92-4f5e-4a1d-9c77-2e6d0b8a5f31")

# --- the roster, exactly as the source page lists it -------------------------------

ROSTER = [
    ("อธิบดีกรมสรรพากร", "นายสมศักดิ์ อนันทวัฒน์", "02-272-8261"),
    ("ที่ปรึกษาด้านประสิทธิภาพ", "นายเกรียงศักดิ์ ประสงค์สุกาญจน์", "02-272-9537"),
    ("ที่ปรึกษาด้านเทคโนโลยีสารสนเทศและการสื่อสาร", "นางสาวภิญญู กำเนิดหล่ม", "02-272-8973"),
    ("ที่ปรึกษาด้านยุทธศาสตร์การจัดเก็บภาษี (กลุ่มธุรกรรมทางการเงินการธนาคาร)",
     "นางสาวสลักจิต พงษ์ศิริจันทร์", "02-272-8833"),
    ("ที่ปรึกษาด้านพัฒนาฐานภาษี", "นางสาวจิตรา ณีศะนันท์", "02-272-9909"),
    ("รองอธิบดีกรมสรรพากร (รักษาการในตำแหน่งที่ปรึกษาด้านยุทธศาสตร์การจัดเก็บภาษี "
     "กลุ่มธุรกิจพลังงาน)", "นายกฤดา กฤติยาโชติปกรณ์", "02-272-9539, 02-272-8971"),
    ("รองอธิบดีกรมสรรพากร", "นายภาณุวัฒน์ เหลืองวิไล", "02-272-8274, 02-272-9905"),
    ("รองอธิบดีกรมสรรพากร", "นายสุรยุทธ กอบกิจพานิชผล", "02-272-8633"),
    ("รองอธิบดีกรมสรรพากร", "นางสาวขวัญรัก สุวรรณรัมภา", "02-272-8975"),
]

ROSTER_TEXT = "\n".join(
    [f"ผู้บริหารระดับสูงของกรมสรรพากร ({SOURCE_NOTE}) มีดังนี้"]
    + [f"{position} {name} โทร {phone}" for position, name, phone in ROSTER]
    + ["สอบถามข้อมูลผู้บริหารเพิ่มเติมได้ที่กองบริหารทรัพยากรบุคคล โทร 02-272-8534"]
)

ROSTER_QUESTIONS = [
    "ผู้บริหารระดับสูงกรมสรรพากรมีใครบ้าง",
    "รายชื่อผู้บริหารกรมสรรพากรและเบอร์โทรศัพท์",
    "เบอร์โทรศัพท์ติดต่อผู้บริหารกรมสรรพากร",
    "ที่ปรึกษากรมสรรพากรมีใครบ้าง",
    "รองอธิบดีกรมสรรพากรมีใครบ้าง",
]

# --- the seven chunks that contradict it -------------------------------------------
# Each entry: point id -> (new text_clean, new page_content). The page_content keeps the
# shape its own family uses, because _payload_text() and the lexical scan both read it.

_DEPUTIES = (
    "ท่านรองอธิบดีกรมสรรพากร มี 4 ท่าน คือ นายภาณุวัฒน์ เหลืองวิไล "
    "นายสุรยุทธ กอบกิจพานิชผล นางสาวขวัญรัก สุวรรณรัมภา และ นายกฤดา กฤติยาโชติปกรณ์ "
    "ซึ่งรักษาการในตำแหน่งที่ปรึกษาด้านยุทธศาสตร์การจัดเก็บภาษี (กลุ่มธุรกิจพลังงาน) ค่ะ"
)


def _kc_content(domain: str, title: str, text: str) -> str:
    return f"[{domain}] หัวข้อ: {title.replace('_', ' ')}\n{text}"


def _callcenter_content(domain: str, question: str, answer: str) -> str:
    return (
        f"[{domain}] [callcenter_corrected]\n"
        f"หัวข้อ: {question}\n"
        f"คำถามตัวอย่างจากชุด Call Center: {question}\n"
        f"คำตอบที่ตรวจแก้แล้ว: {answer}"
    )


CORRECTIONS = {
    # the chunk that wins dense search for "who is the director-general"
    "011e9477-7060-53e8-aef8-3bc5741455e0": (
        "ท่านอธิบดีกรมสรรพากร ชื่อ นายสมศักดิ์ อนันทวัฒน์ ค่ะ",
        _callcenter_content("F", "ผู้อำนวยการหรืออธิบดีกรมสรรพากรชื่ออะไร",
                            "ท่านอธิบดีกรมสรรพากร ชื่อ นายสมศักดิ์ อนันทวัฒน์ ค่ะ"),
    ),
    "51056109-c070-4adc-84e7-eded3085b017": (
        "ท่านอธิบดีกรมสรรพากร นายสมศักดิ์ อนันทวัฒน์ ค่ะ",
        _kc_content("GENERAL", "ผู้บริหาร_ชื่ออธิบดีของกรมสรรพากร_2",
                    "ท่านอธิบดีกรมสรรพากร นายสมศักดิ์ อนันทวัฒน์ ค่ะ"),
    ),
    "f42708ba-3003-43e6-9e2b-642a786a3643": (
        _DEPUTIES,
        _kc_content("GENERAL", "ผู้บริหาร_ชื่อรองอธิบดีกรมสรรพากร", _DEPUTIES),
    ),
    "41a164bb-16b4-4b21-9b05-68d7758ac425": (
        "ท่านที่ปรึกษาด้านยุทธศาสตร์การจัดเก็บภาษี (กลุ่มธุรกรรมทางการเงินการธนาคาร) "
        "นางสาวสลักจิต พงษ์ศิริจันทร์ ค่ะ",
        _kc_content("GENERAL", "ผู้บริหาร_ที่ปรึกษาฯ(ธุรกรรมการเงินการธนาคาร)",
                    "ท่านที่ปรึกษาด้านยุทธศาสตร์การจัดเก็บภาษี "
                    "(กลุ่มธุรกรรมทางการเงินการธนาคาร) นางสาวสลักจิต พงษ์ศิริจันทร์ ค่ะ"),
    ),
    "779dcca7-6d3f-476d-a03f-233753c3e045": (
        "ท่านที่ปรึกษาด้านพัฒนาฐานภาษี นางสาวจิตรา ณีศะนันท์ ค่ะ",
        _kc_content("GENERAL", "ผู้บริหาร_ที่ปรึกษาด้านพัฒนาฐานภาษี",
                    "ท่านที่ปรึกษาด้านพัฒนาฐานภาษี นางสาวจิตรา ณีศะนันท์ ค่ะ"),
    ),
    # same person, the stored spelling is wrong (สุกานญจน์ → สุกาญจน์)
    "0c1f1e63-62a7-4bfa-8a00-dfd5c96e501a": (
        "ท่านที่ปรึกษาด้านประสิทธิภาพ นายเกรียงศักดิ์ ประสงค์สุกาญจน์ ค่ะ",
        _kc_content("GENERAL", "ผู้บริหาร_ชื่อที่ปรึกษาด้านประสิทธิภาพ",
                    "ท่านที่ปรึกษาด้านประสิทธิภาพ นายเกรียงศักดิ์ ประสงค์สุกาญจน์ ค่ะ"),
    ),
    # the roster lists her in the post, no longer acting
    "941999f7-a719-4650-92e7-ddaca915fab2": (
        "ท่านที่ปรึกษาด้านเทคโนโลยีสารสนเทศและการสื่อสาร นางสาวภิญญู กำเนิดหล่ม ค่ะ",
        _kc_content("GENERAL", "ผู้บริหาร_ชื่อที่ปรึกษาด้านICT",
                    "ท่านที่ปรึกษาด้านเทคโนโลยีสารสนเทศและการสื่อสาร "
                    "นางสาวภิญญู กำเนิดหล่ม ค่ะ"),
    ),
}


def _headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if QDRANT_KEY:
        headers["api-key"] = QDRANT_KEY
    return headers


def _normalize(value: str) -> str:
    return re.sub(r"[^0-9a-zก-๙]+", "", value.lower())


def _embed(client: httpx.Client, text: str) -> list:
    """The embedding host sits behind Cloudflare and 403s urllib — httpx only."""
    resp = client.post(
        os.environ["EMBEDDING_BASE_URL"].rstrip("/") + "/embeddings",
        headers={"Authorization": f"Bearer {os.environ['EMBEDDING_API_KEY']}"},
        json={"input": text, "model": os.environ["EMBEDDING_MODEL"]},
        timeout=60.0,
    )
    resp.raise_for_status()
    return resp.json()["data"][0]["embedding"]


def fetch(client: httpx.Client, ids: list) -> dict:
    resp = client.post(
        f"{QDRANT_URL}/collections/{COLLECTION}/points",
        headers=_headers(),
        json={"ids": ids, "with_payload": True, "with_vector": False},
        timeout=30.0,
    )
    resp.raise_for_status()
    return {p["id"]: p for p in resp.json()["result"]}


def correct_in_place(client: httpx.Client) -> int:
    print("=" * 78)
    print("1. CORRECTING EXISTING CHUNKS (payload only — vectors untouched)")
    print("=" * 78)
    existing = fetch(client, list(CORRECTIONS))
    changed = 0
    for point_id, (text_clean, page_content) in CORRECTIONS.items():
        point = existing.get(point_id)
        if point is None:
            print(f"!! {point_id} not found — skipped")
            continue
        metadata = dict(point["payload"].get("metadata") or {})
        before = str(metadata.get("text_clean", ""))
        if before.strip() == text_clean.strip():
            print(f"== {metadata.get('cluster_id')} already correct")
            continue
        changed += 1
        print(f"\n-- {metadata.get('cluster_id')}  {metadata.get('title')}")
        print(f"   before: {' '.join(before.split())[:150]}")
        print(f"   after : {' '.join(text_clean.split())[:150]}")
        if DRY_RUN:
            continue
        metadata["text_clean"] = text_clean
        metadata["norm_key"] = _normalize(text_clean)
        metadata["traceability_ref"] = "rd.go.th:ผู้บริหารระดับสูง:2026-07-21"
        resp = client.post(
            f"{QDRANT_URL}/collections/{COLLECTION}/points/payload?wait=true",
            headers=_headers(),
            json={"payload": {"page_content": page_content, "metadata": metadata},
                  "points": [point_id]},
            timeout=30.0,
        )
        resp.raise_for_status()
    return changed


def add_roster(client: httpx.Client) -> int:
    print("\n" + "=" * 78)
    print("2. ADDING THE ROSTER (one record, one point per question phrasing)")
    print("=" * 78)
    print(ROSTER_TEXT)
    points = []
    for index, question in enumerate(ROSTER_QUESTIONS, 1):
        point_id = str(uuid.uuid5(NAMESPACE, f"RD-EXEC-2026-07-21#{index}"))
        print(f"\n-- [{index}/{len(ROSTER_QUESTIONS)}] {point_id}")
        print(f"   embeds: {question}")
        if DRY_RUN:
            continue
        vector = _embed(client, question)
        points.append({
            "id": point_id,
            "vector": {VECTOR_NAME: vector},
            "payload": {
                "page_content": (
                    "[GENERAL] [executives]\n"
                    "หัวข้อ: รายชื่อผู้บริหารระดับสูงกรมสรรพากร\n"
                    "คำถามตัวอย่าง: " + " | ".join(ROSTER_QUESTIONS) + "\n"
                    "คำตอบ: " + ROSTER_TEXT
                ),
                "metadata": {
                    "record_id": f"RD-EXEC-2026-07-21-{index}",
                    "cluster_id": "KC-EXEC-ROSTER",
                    "title": "ผู้บริหาร_รายชื่อผู้บริหารระดับสูงกรมสรรพากร",
                    "text_clean": ROSTER_TEXT,
                    "domain": "GENERAL",
                    "subdomain": "executives",
                    "knowledge_role": "answer_text",
                    "source_priority": 5,
                    "canonical_score": 1000.0,
                    "traceability_ref": "rd.go.th:ผู้บริหารระดับสูง:2026-07-21",
                    "norm_key": _normalize(ROSTER_TEXT),
                    "question": question,
                    "review_flags": "[]",
                    "ref_links": "[]",
                    "image_urls": "[]",
                    "has_image_asset": False,
                },
            },
        })
    if points:
        resp = client.put(
            f"{QDRANT_URL}/collections/{COLLECTION}/points?wait=true",
            headers=_headers(),
            json={"points": points},
            timeout=60.0,
        )
        resp.raise_for_status()
    return len(ROSTER_QUESTIONS)


def main() -> int:
    print(f"qdrant     : {QDRANT_URL}/collections/{COLLECTION}")
    print(f"mode       : {'DRY RUN — nothing is written (pass --yes to apply)' if DRY_RUN else 'APPLYING'}")
    with httpx.Client() as client:
        corrected = correct_in_place(client)
        added = add_roster(client)
        resp = client.get(f"{QDRANT_URL}/collections/{COLLECTION}", headers=_headers(),
                          timeout=30.0)
        total = resp.json()["result"]["points_count"]
    print("\n" + "=" * 78)
    verb = "would correct/add" if DRY_RUN else "corrected/added"
    print(f"{verb}: {corrected} corrected, {added} roster points | collection now {total} points")
    if not DRY_RUN:
        print("RESTART THE AGENT — graph/retriever.py caches every payload once per process.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
