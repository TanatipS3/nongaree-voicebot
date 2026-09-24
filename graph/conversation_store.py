"""Per-user persistence for conversation memory.

Without this, memory is a local in `agent.py`'s `entrypoint()`, so it lives and dies with
the LiveKit *job* — and HANDOFF.md §3b Fix 8 deliberately ends the job when the session
closes so a rejoin gets a fresh one. Net effect: **a page reload wipes all history**, and
the next follow-up is answered with no idea what came before.

Deliberately file-backed, not a database. HANDOFF.md §3b Fix 11 rejected a DB for problem
reports because it would add a service and an image to the prebuilt-release handoff; the
same reasoning applies here, and this reuses that design so operators have one concept to
learn instead of two.

Lives under `graph/` because `docker container/Dockerfile.agent` copies files
individually (`COPY agent.py`, `COPY latency.py`, `COPY graph ./graph`) — a new top-level
module would pass every local check and then ModuleNotFoundError in the deployed image.
"""

from __future__ import annotations

import json
import logging
import os
import time

logger = logging.getLogger("nongaree-agent")

SCHEMA_VERSION = 1

# Matches IDLE_LIMIT_MS in components/VoiceRoom.tsx, which logs the user out after 30
# minutes idle. Memory outliving the session it belongs to would keep salary, dependants
# and ages on disk with nobody present.
DEFAULT_TTL_MINUTES = 30

_warned_unwritable = False
_last_prune = 0.0
_PRUNE_INTERVAL_S = 60.0


def _memory_dir() -> str:
    return os.getenv("MEMORY_DIR", "/data/memory")


def _ttl_seconds() -> float:
    try:
        return float(os.getenv("MEMORY_TTL_MINUTES", DEFAULT_TTL_MINUTES)) * 60.0
    except ValueError:
        return DEFAULT_TTL_MINUTES * 60.0


def room_to_key(room_name: str) -> str:
    """Storage key from the LiveKit room name.

    `app/api/livekit/token/route.ts` derives the room server-side as
    `nongaree-${safeUser}` where safeUser is already `[^a-zA-Z0-9_-] -> _`, and a client
    cannot request another user's room. So the room name is both sanitised and
    unspoofable — safer than `participant.identity`, which is the raw username.
    """
    key = (room_name or "").strip()
    if key.startswith("nongaree-"):
        key = key[len("nongaree-"):]
    # Defensive: never let a key escape the directory.
    return "".join(c for c in key if c.isalnum() or c in "_-") or "unknown"


def _path_for(key: str) -> str:
    return os.path.join(_memory_dir(), f"{key}.json")


def _ensure_dir() -> bool:
    """True if the store is usable. Warns once, then degrades quietly.

    An operator who pulls a new prebuilt image without adding the volume must get the
    previous behaviour (in-process memory), not a crash loop.
    """
    global _warned_unwritable
    try:
        os.makedirs(_memory_dir(), exist_ok=True)
        return True
    except Exception:
        if not _warned_unwritable:
            _warned_unwritable = True
            logger.warning(
                "MEMORY_DIR %s is not writable; conversation memory will not survive a "
                "reload. Mount a volume there to enable persistence.",
                _memory_dir(),
            )
        return False


def _prune(now: float) -> None:
    """Delete expired files. Retention is enforced by deleting a file, not migrating rows.

    Uses mtime so nothing has to be parsed, and is throttled so a busy worker does not
    stat the directory on every turn. No cron — same reasoning as the report rotation.
    """
    global _last_prune
    if now - _last_prune < _PRUNE_INTERVAL_S:
        return
    _last_prune = now
    ttl = _ttl_seconds()
    try:
        for name in os.listdir(_memory_dir()):
            if not name.endswith(".json"):
                continue
            path = os.path.join(_memory_dir(), name)
            try:
                if now - os.path.getmtime(path) > ttl:
                    os.unlink(path)
                    logger.info("Pruned expired conversation memory: %s", name)
            except FileNotFoundError:
                pass
    except Exception:
        logger.exception("Failed to prune conversation memory")


def load_conversation(key: str) -> dict:
    """Load memory for `key`, or a fresh one if absent, expired or unreadable."""
    from graph.conversation import new_memory

    if not _ensure_dir():
        return new_memory()

    path = _path_for(key)
    try:
        if not os.path.exists(path):
            return new_memory()
        if time.time() - os.path.getmtime(path) > _ttl_seconds():
            # Expired between prunes: treat as absent rather than serving stale context.
            os.unlink(path)
            return new_memory()
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except Exception:
        logger.exception("Failed to read conversation memory for %s", key)
        return new_memory()

    if raw.get("schema_version") != SCHEMA_VERSION:
        # A shape change (e.g. Stage 2 storing spoken vs panel answers separately) makes
        # older files unreadable. Discard rather than migrate — the TTL is 30 minutes, so
        # incompatible files disappear on their own almost immediately.
        logger.info("Discarding conversation memory for %s: schema %s", key, raw.get("schema_version"))
        return new_memory()

    history = raw.get("history")
    summary = raw.get("summary")
    if not isinstance(history, list) or not isinstance(summary, str):
        return new_memory()

    logger.info("Restored conversation memory for %s: %d turns", key, len(history) // 2)
    return {"history": history, "summary": summary}


def save_conversation(key: str, memory: dict) -> None:
    """Persist memory for `key`. Never raises — a storage failure must not fail a turn."""
    if not _ensure_dir():
        return

    payload = {
        "schema_version": SCHEMA_VERSION,
        "username": key,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "summary": memory.get("summary", ""),
        "history": memory.get("history", []),
    }
    path = _path_for(key)
    tmp = f"{path}.tmp"
    try:
        # Write-then-rename: a reload can briefly overlap two jobs, and a half-written
        # file must never be readable. os.replace is atomic on the same filesystem.
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        logger.exception("Failed to save conversation memory for %s", key)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return

    _prune(time.time())


def delete_conversation(key: str) -> bool:
    """Remove a user's memory. Called on logout."""
    if not _ensure_dir():
        return False
    try:
        os.unlink(_path_for(key))
        logger.info("Deleted conversation memory for %s", key)
        return True
    except FileNotFoundError:
        return False
    except Exception:
        logger.exception("Failed to delete conversation memory for %s", key)
        return False
