import asyncio
import json
import os
import re
from functools import lru_cache

from openai import OpenAI
from qdrant_client import AsyncQdrantClient

_qdrant: AsyncQdrantClient | None = None
_payload_cache: list[tuple[str, str, str]] | None = None
# point id -> citation dict, so a fused hit can be traced back to its source chunk.
_citation_cache: dict[str, dict] = {}
_payload_cache_lock = asyncio.Lock()
_RRF_K = 60
_TAX_FORM_PATTERN = re.compile(
    r"(?:แบบ\s*)?("
    r"ภ\.?\s*ง\.?\s*ด\.?\s*\d+"
    r"|ภงด\s*\d+"
    r"|ป\.?\s*ล\.?\s*\d+(?:\.\d+)?"
    r"|ล\.?\s*ป\.?\s*\d+(?:\.\d+)?"
    r"|ค\.?\s*\d+"
    r")",
    re.IGNORECASE,
)
_TCL_CONTEXT = (
    "[GENERAL] หัวข้อ: ระบบ TCL / ระบบงานทะเบียนคุมรายการและจัดทำบัญชีผู้เสียภาษีอากร\n"
    "ระบบ TCL หรือระบบงานทะเบียนคุมรายการและจัดทำบัญชีผู้เสียภาษีอากร "
    "เป็นระบบงานภายในของกรมสรรพากรที่ใช้ดูแลทะเบียนคุมรายการและบัญชีผู้เสียภาษีอากร "
    "ระบบงานที่เกี่ยวข้องหรือทำงานสอดคล้องกัน ได้แก่ "
    "ระบบควบคุมลูกหนี้ภาษีอากรค้าง ระบบออกคำสั่งตามมาตรา 12 "
    "ระบบงานบัญชีอำเภอออนไลน์ ACCNEW Online ระบบนำเงินส่งคลัง "
    "ระบบบูรณาการหนี้กรมสรรพากร และระบบ Smart AI Assistant "
    "รวมถึงสนับสนุนการประมวลผลข้อมูล การให้คำปรึกษา แก้ไขปัญหาการใช้งานระบบ "
    "และจัดทำข้อมูลหรือรายงานเพื่อใช้ในการปฏิบัติงาน"
)
_REFUND_TERMS = ("ขอคืน", "คืนภาษี", "คืนเงิน", "ค.21", "ค10", "ค.10", "refund")
_DOCUMENT_TERMS = ("เอกสาร", "หลักฐาน", "ประกอบ")
_EXACT_MATCH_MARKER = "[EXACT_MATCH]"


def _get_qdrant() -> AsyncQdrantClient:
    global _qdrant
    if _qdrant is None:
        _qdrant = AsyncQdrantClient(
            url=os.environ["QDRANT_URL"],
            api_key=os.environ.get("QDRANT_API_KEY") or None,
        )
    return _qdrant


@lru_cache(maxsize=256)
def _get_embedding_cached(text: str) -> list[float]:
    client = OpenAI(
        base_url=os.environ["EMBEDDING_BASE_URL"],
        api_key=os.environ["EMBEDDING_API_KEY"],
    )
    response = client.embeddings.create(input=text, model=os.environ["EMBEDDING_MODEL"])
    return response.data[0].embedding


async def retrieve(query: str) -> str:
    """Context text only. Kept for callers that do not need citations."""
    text, _ = await retrieve_with_sources(query)
    return text


async def retrieve_with_sources(
    query: str, *, allow_low_score_rescue: bool = True
) -> tuple[str, list[dict]]:
    if _is_tcl_topic(query):
        return _TCL_CONTEXT, [{
            "n": 1,
            "title": "ระบบ TCL",
            "domain": "GENERAL",
            "subdomain": "",
            "cluster_id": "",
            "record_id": "",
            "excerpt": _excerpt(_TCL_CONTEXT),
            "url": "",
            "outdated": False,
        }]

    limit = int(os.getenv("RAG_TOP_K", "3"))
    score_threshold = float(os.getenv("RAG_SCORE_THRESHOLD", "0") or "0")
    dense_limit = max(limit * 5, 15)
    exact_terms = _exact_code_terms(query)
    # The exact-code shortcut returns a chunk BEFORE the score gate — a second way around
    # it, so it obeys the same rule as the low-score rescue: it may only fire on words the
    # user actually used. A query that contains its own form code gets exactly one
    # candidate (flag True), so a code reaching here with the flag False is always
    # BORROWED — from the conversation opener or the previous answer. Without this, any
    # rag-routed question that missed the gate in a conversation which OPENED on a form
    # code was answered with that form's chunk: `ภาษีคาร์บอนเครดิตฟาร์มกุ้งคำนวณยังไง` after
    # a `ภ.ง.ด.90 คืออะไร` opener retrieved 471 chars of ภ.ง.ด.90 instead of abstaining. On
    # the dense path that candidate scores 0.6627 and the gate rejects it, as it should.
    if exact_terms and allow_low_score_rescue:
        lexical_hits = await _lexical_search(query, dense_limit)
        if lexical_hits:
            matched = ", ".join(exact_terms)
            # `{chunk}`, not `{text}`: inside the genexp `text` resolves as a free
            # variable from this scope, which is unbound while the assignment to
            # `text` is still in flight — every exact-code query raised NameError
            # and surfaced to the user as "ขอโทษค่ะ ระบบใช้เวลานาน...".
            text = "\n\n".join(
                f"คำค้น/รหัสที่ตรงกับข้อมูล: {matched}\n{chunk}"
                for _, chunk in lexical_hits[:1]
            )
            return text, _citations_for([hit_id for hit_id, _ in lexical_hits[:1]])

    loop = asyncio.get_event_loop()
    vector = await loop.run_in_executor(None, _get_embedding_cached, query)

    response = await _get_qdrant().query_points(
        collection_name=os.environ["QDRANT_COLLECTION"],
        query=vector,
        using=os.environ.get("QDRANT_VECTOR_NAME", "dense"),
        limit=dense_limit,
        with_payload=True,
    )
    top_dense_score = float(response.points[0].score) if response.points else 0.0
    for hit in response.points:
        _remember_citation(str(hit.id), hit.payload or {})

    if score_threshold > 0 and top_dense_score < score_threshold:
        rescued = (
            allow_low_score_rescue
            and await _should_rescue_low_score(query, top_dense_score)
        )
        if not rescued:
            return "", []
    exact_match_score = float(os.getenv("RAG_EXACT_MATCH_SCORE", "0.999") or "0.999")
    if response.points and top_dense_score >= exact_match_score:
        top_payload_text = _payload_text(response.points[0].payload or {})
        if top_payload_text:
            text = (
                f"{_EXACT_MATCH_MARKER} คะแนนความตรงของข้อมูลสูงมาก "
                "ให้รักษาตัวเลข เงื่อนไข ข้อยกเว้น และคำแนะนำจากข้อมูลนี้ให้ครบ\n"
                f"{top_payload_text}"
            )
            return text, _citations_for([str(response.points[0].id)])

    lexical_hits = await _lexical_search(query, dense_limit)

    dense_hits = [
        (str(hit.id), _payload_text(hit.payload or {}))
        for hit in response.points
    ]
    fused = _reciprocal_rank_fusion(
        [(dense_hits, 1.0), (lexical_hits, 2.5)],
        limit,
    )
    fused = _prefer_domain(query, fused)

    return (
        "\n\n".join(text for _, text in fused),
        _citations_for([hit_id for hit_id, _ in fused]),
    )


def _payload_text(payload: dict) -> str:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    if metadata:
        text = metadata.get("text_clean") or payload.get("page_content") or str(payload)
        title = _clean_title(metadata.get("title") or payload.get("title") or "")
        domain = metadata.get("domain") or payload.get("domain") or ""
        header = " ".join(
            part
            for part in (
                f"[{domain}]" if domain else "",
                f"หัวข้อ: {title}" if title else "",
            )
            if part
        )
        return f"{header}\n{text}".strip()

    text = (
        payload.get("text")
        or payload.get("content")
        or payload.get("page_content")
        or str(payload)
    )
    return str(text)


def _clean_title(title: str) -> str:
    title = str(title).replace("_", " ").strip()
    title = re.sub(r"^(PIT|VAT|CIT|WHT|SBT|REFUND|STD|GENERAL|COVID)\s+", "", title)
    title = re.sub(r"\s+\d{3}$", "", title)
    return title.strip()


def _json_list(value) -> list:
    """review_flags / ref_links / image_urls are stored as JSON-encoded strings."""
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except ValueError:
            return [value]
        return parsed if isinstance(parsed, list) else [parsed]
    return []


def _excerpt(text: str, limit: int = 480) -> str:
    text = re.sub(r"\s+", " ", str(text)).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _citation_from_payload(payload: dict) -> dict:
    """Everything the UI needs to credit one chunk. Kept small: it crosses the wire."""
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    flags = _json_list(metadata.get("review_flags"))
    links = [str(link) for link in _json_list(metadata.get("ref_links")) if link]
    return {
        "title": _clean_title(metadata.get("title") or payload.get("title") or "") or "ข้อมูลอ้างอิง",
        "domain": str(metadata.get("domain") or ""),
        "subdomain": str(metadata.get("subdomain") or ""),
        "cluster_id": str(metadata.get("cluster_id") or ""),
        "record_id": str(metadata.get("record_id") or ""),
        "excerpt": _excerpt(metadata.get("text_clean") or payload.get("page_content") or ""),
        "url": links[0] if links else "",
        # Surfaced so the panel can caveat a chunk the knowledge base itself
        # marks as stale. ~11% of the collection carries this.
        "outdated": "possibly_outdated" in flags,
    }


def _remember_citation(point_id: str, payload: dict) -> None:
    if point_id not in _citation_cache:
        _citation_cache[point_id] = _citation_from_payload(payload)


def _citations_for(ids: list[str]) -> list[dict]:
    out = []
    for index, point_id in enumerate(ids, start=1):
        cite = _citation_cache.get(point_id)
        if not cite:
            continue
        out.append({"n": index, **cite})
    return out


def _payload_search_text(payload: dict) -> str:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    parts = [
        str(payload.get("page_content") or ""),
        str(payload.get("text") or ""),
        str(payload.get("content") or ""),
        str(metadata.get("title") or ""),
        str(metadata.get("text_clean") or ""),
        str(metadata.get("traceability_ref") or ""),
    ]
    return "\n".join(part for part in parts if part)


async def _all_payload_texts() -> list[tuple[str, str, str]]:
    global _payload_cache
    if _payload_cache is not None:
        return _payload_cache

    async with _payload_cache_lock:
        if _payload_cache is not None:
            return _payload_cache

        rows: list[tuple[str, str, str]] = []
        offset = None
        while True:
            points, offset = await _get_qdrant().scroll(
                collection_name=os.environ["QDRANT_COLLECTION"],
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in points:
                _remember_citation(str(point.id), point.payload or {})
            rows.extend(
                (
                    str(point.id),
                    _payload_text(point.payload or {}),
                    _payload_search_text(point.payload or {}),
                )
                for point in points
            )
            if offset is None:
                break
        _payload_cache = rows
        return rows


def _normalize(value: str) -> str:
    return re.sub(r"[^0-9a-zก-๙]+", "", value.lower())


def _is_tcl_topic(query: str) -> bool:
    normalized = _normalize(query)
    return any(
        marker in normalized
        for marker in (
            "tcl",
            "ทะเบียนคุมรายการ",
            "จัดทำบัญชีผู้เสียภาษี",
            "บัญชีผู้เสียภาษีอากร",
            "ควบคุมรายการผู้เสียภาษี",
            "ระบบงานทะเบียน",
        )
    )


def _query_terms(value: str) -> list[str]:
    return [
        term.lower()
        for term in re.findall(r"[0-9a-zA-Z]+|[ก-๙]+", value)
        if term.strip()
    ]


def _exact_code_terms(value: str) -> list[str]:
    terms = [
        term.lower()
        for term in re.findall(r"[0-9a-zA-Z]+", value)
        if re.search(r"[0-9]", term) and re.search(r"[a-zA-Z]", term)
    ]
    terms.extend(_normalize(match.group(1)) for match in _TAX_FORM_PATTERN.finditer(value))
    return [term for term in dict.fromkeys(terms) if term]


def _char_ngrams(value: str, size: int = 3) -> set[str]:
    normalized = _normalize(value)
    if len(normalized) < size:
        return {normalized} if normalized else set()
    return {normalized[index : index + size] for index in range(len(normalized) - size + 1)}


# --- rescuing questions the dense gate rejects ----------------------------------------
#
# RAG_SCORE_THRESHOLD is a single number compared against the top DENSE score, and it is
# simultaneously too strict and too loose. Measured over 30 labelled queries against the
# live index (scripts/threshold_sweep.py has the population, HANDOFF.md §3f the analysis):
# genuine tax follow-ups sit at 0.72-0.73 while off-topic questions reach 0.82, so no
# threshold separates them and lowering the gate is not an option.
#
# What DOES separate is the lexical score, which the gate never sees because it is
# computed after this point. Across the labelled set:
#
#   off-topic  lexical top score   max 6.8   (`จดทะเบียนสมรสใช้เอกสารอะไร`)
#   on-topic   (the rescued ones)  20.5, 40.1
#
# So lexical is a high-precision POSITIVE signal: a strong lexical hit means the query's
# own words are in the corpus. It cannot be used to reject — plenty of on-topic questions
# score ~1.0 — only to rescue.
#
# The cut sits at 12.0, which is not a fitted number: _lexical_scored awards exactly +12.0
# when the whole normalized query appears verbatim in a chunk, so this is the boundary
# between "the corpus contains this phrasing" and "some words happened to overlap". A
# lower cut leaks — `จดทะเบียนสมรสใช้เอกสารอะไร` reaches 6.8 purely from the +6.0
# _DOCUMENT_TERMS bonus on "เอกสาร", which says nothing about the topic being tax.
#
# The second rescue covers questions whose wording is explicitly about tax but whose
# embedding is weak (`ต้องยื่นแบบไหน`, `ภาษีเงินได้บุคคลธรรมดาคืออะไร`). It needs a floor,
# because `ภาษีคาร์บอนเครดิตฟาร์มกุ้งคำนวณยังไง` is also explicitly about tax and MUST keep
# abstaining — the corpus has nothing for it, and the unanswerable_guard fixture exists
# precisely because a plausible-looking check let that one through. It measures 0.6984, so
# the floor sits at 0.72: a 0.02 margin, not a coincidence to be tightened later.
_LEXICAL_RESCUE_MIN = 12.0
_TAX_VOCAB_RESCUE_FLOOR = 0.72
_TAX_VOCAB_TERMS = (
    "ภาษี", "สรรพากร", "ยื่นแบบ", "ยื่น", "ลดหย่อน", "หัก ณ ที่จ่าย", "หักณที่จ่าย",
    "คืนภาษี", "ขอคืน", "ใบกำกับ", "ภ.ง.ด", "ภงด", "อากร", "เงินได้", "แวต",
)


async def _should_rescue_low_score(query: str, top_dense_score: float) -> bool:
    """Should a query the dense gate rejected be answered anyway?

    Deliberately narrow. Everything not matched here still abstains to the 1161 handoff,
    which is the safe default — answering from an unrelated chunk is the failure mode
    _no_source_response() exists to prevent.
    """
    normalized = _normalize(query)
    if any(term in normalized for term in _TAX_VOCAB_TERMS):
        if top_dense_score >= _TAX_VOCAB_RESCUE_FLOOR:
            return True

    # Lexical is scanned only for queries already headed for the handoff, so this costs
    # nothing on the happy path.
    lexical_hits = await _lexical_scored(query, 1)
    return bool(lexical_hits) and lexical_hits[0][0] >= _LEXICAL_RESCUE_MIN


async def _lexical_search(query: str, limit: int) -> list[tuple[str, str]]:
    """Ranked lexical hits, scores discarded. See _lexical_scored when you need them."""
    return [(point_id, text) for _, point_id, text in await _lexical_scored(query, limit)]


async def _lexical_scored(query: str, limit: int) -> list[tuple[float, str, str]]:
    rows = await _all_payload_texts()
    normalized_query = _normalize(query)
    query_terms = _query_terms(query)
    exact_terms = _exact_code_terms(query)
    query_ngrams = _char_ngrams(query)
    scored: list[tuple[float, str, str]] = []

    for point_id, text, full_search_text in rows:
        search_text = re.sub(r"https?://\S+", " ", full_search_text)
        lower_text = search_text.lower()
        normalized_text = _normalize(search_text)
        score = 0.0
        exact_code_match = False
        if normalized_query and normalized_query in normalized_text:
            score += 12.0
        for term in exact_terms:
            if term in normalized_text:
                exact_code_match = True
                score += 25.0
        for term in query_terms:
            if not term:
                continue
            if re.search(r"[0-9a-z]", term):
                if re.search(fr"(?<![0-9a-z]){re.escape(term)}(?![0-9a-z])", lower_text):
                    exact_code_match = exact_code_match or term in exact_terms
                    score += 20.0
            elif term in normalized_text:
                score += 1.0
        if any(term in normalized_query for term in _REFUND_TERMS):
            if "[refund]" in lower_text or "[refund]" in text.lower() or "[REFUND]" in text:
                score += 8.0
            if any(term in normalized_text for term in _REFUND_TERMS):
                score += 6.0
        if any(term in normalized_query for term in _DOCUMENT_TERMS):
            if any(term in normalized_text for term in _DOCUMENT_TERMS):
                score += 6.0
        if exact_terms and not exact_code_match:
            continue
        text_ngrams = _char_ngrams(search_text)
        if query_ngrams and text_ngrams:
            overlap = len(query_ngrams & text_ngrams)
            if overlap:
                score += overlap / len(query_ngrams)
        if score:
            scored.append((score, point_id, text))

    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[:limit]


def _reciprocal_rank_fusion(
    ranked_lists: list[tuple[list[tuple[str, str]], float]],
    limit: int,
) -> list[tuple[str, str]]:
    scores: dict[str, float] = {}
    texts: dict[str, str] = {}
    for ranked, weight in ranked_lists:
        for rank, (point_id, text) in enumerate(ranked, 1):
            scores[point_id] = scores.get(point_id, 0.0) + weight / (_RRF_K + rank)
            texts.setdefault(point_id, text)
    ordered = sorted(scores, key=scores.get, reverse=True)
    return [(point_id, texts[point_id]) for point_id in ordered[:limit]]


def _prefer_domain(query: str, hits: list[tuple[str, str]]) -> list[tuple[str, str]]:
    normalized = query.lower()
    preferred = None
    compacted = _normalize(query)
    if any(term in compacted for term in _REFUND_TERMS):
        preferred = "[REFUND]"
    elif any(term in normalized for term in ("เงินเดือน", "รายได้", "บุคคลธรรมดา", "ภ.ง.ด.90", "ภงด90")):
        preferred = "[PIT]"
    elif any(term in normalized for term in ("vat", "แวต", "ภาษีมูลค่าเพิ่ม", "ใบกำกับ")):
        preferred = "[VAT]"
    if not preferred:
        return hits
    return sorted(hits, key=lambda item: 0 if item[1].startswith(preferred) else 1)
