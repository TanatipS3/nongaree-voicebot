# Session Handoff — Aree (อารี) Voicebot

Written 2026-08-31; updated the same day (session 2 — §3b), and again
**2026-09-08/09** (session 3 — multi-turn harness + a production crash it found: **§3c**;
self-hosted LiveKit brought up and verified working: **§3d**), **2026-09-10/14**
(session 4 — §3e), and **2026-09-16** (session 5 — §3f: the supervisor "ขอโทษ ระบบใช้เวลานาน"
item finally verified end to end, phone numbers, the mic button, and the first real run
against the self-hosted LiveKit).
Context for a fresh Claude Code session with no prior history.
Read `CLAUDE.md` first for architecture; this file covers **the rules, the work done
in the last session, and the traps**.

---

## 1. Hard rules from the user — read before touching anything

This checkout was `scp`'d from a server for **local development only**. Deploys happen
separately by `rsync`-ing back to the server and running Docker there.

**Deployment is ONE event, when the work is finished — not a trickle.** The user
(2026-09-10): *"if i need to deploy it on production it will happen only when all work
done, i cant just ship unfinish work many time."* Each deploy costs them something
outside this repo, so **do not recommend shipping an individual fix ahead of the rest**,
however safe or self-contained it looks. Everything accumulates locally and goes out
together. The practical consequence for planning: sequence work by *what makes the release
complete and verified*, never by *what could ship first*.

**The user has no SSO access and cannot test against production.** Local dev with SSO
bypassed (`docker-compose.local.yml`) is the only environment available to them. Anything
whose verification requires the RD portal is **permanently blocked, not pending** — say so
plainly rather than listing it as owed work.

**Never modify these without asking the user first:**

| Area | Files |
|---|---|
| SSO | `lib/sso/`, `app/api/auth/sso/` — *"won't touch at all; ask permission first"* |
| Authentication | `lib/auth/session.ts`, `proxy.ts`, `app/api/login/` |
| Ports | `VOICEBOT_PORT`, `QDRANT_PORT`, port mappings in `docker-compose.yml` |
| Deployment | `docker-compose.yml`, `docker container/` (Dockerfiles + env files) |

Application code (`agent.py`, `graph/`, `components/`, non-auth `app/` routes) is fair
game. If a task *requires* touching the protected list, **stop and ask.**

The user is Thai; the UI is **Thai-only** (see §3). Replying in Thai is welcome when the
user writes in Thai.

---

## 2. Environment traps (these cost time last session)

- **Not a git repository.** No `git diff`, no history, no revert. Read files to confirm
  state; be careful with destructive edits.
- **`node_modules` is NOT installed** and shouldn't be. All builds/lint run inside
  Docker (see §5). Do not `npm install` locally without asking.
- **Windows host, PowerShell + Git Bash.** `rg` is not on PATH — use the Grep tool, not
  `rg` via Bash.
- **Windows reserves TCP port ranges** (Hyper-V). Check with
  `netsh interface ipv4 show excludedportrange protocol=tcp`. Port `8102` sits inside the
  reserved `8071-8170` block, which is why the local Qdrant host port is `6333`.
  **This affects local Docker only — the Linux server is unaffected.**
- **Host-side scripts must override `QDRANT_URL=http://localhost:6333`.** Root `.env` says
  `8102` (the reserved port above), so `rag_node_test.py` and anything else run from the
  host fails against `.env` as written *even when the stack is up*. The containers are
  fine — they use `http://qdrant:6333` internally.
  `scripts/multiturn_benchmark.py` bakes this default in; older scripts do not.
- **Reserved ranges move.** On 2026-09-09 the block was `3000-3099`, so the local stack
  needed `LOCAL_WEB_PORT=4300 LOCAL_LOGIN_PORT=4301`. Re-run
  `scripts/mint-local-session.mjs` after changing them or the login button points at the
  wrong port.
- **Docker Desktop is often not running.** Start it with
  `"/c/Program Files/Docker/Docker/Docker Desktop.exe" &` then poll
  `until docker info >/dev/null 2>&1; do sleep 2; done`.
- **RESOLVED (see §3b Fix 7): the local agent used to compete with the server agent for
  jobs.** Kept here because the symptom is so confusing. Both registered under
  `agent_name="nongaree-agent"` against the *same* LiveKit cloud project
  (`wss://stt-tts-ad50wayf.livekit.cloud`, identical in root `.env` and
  `docker container/.env`), and `app/api/livekit/token/route.ts` dispatches to that
  hardcoded name. LiveKit load-balances the dispatch across **every** registered worker,
  so a local question can be answered entirely on the server (and a real user's question
  can be answered by your dev machine). Rooms are per-user (`nongaree-${safeUser}`) so
  nothing leaks *between* rooms — the issue is **which build of the code** serves a turn.
  **Consequence: a local test proves nothing unless you confirm your container took the
  job.** After every test run, check for a `job_id` line:
  `docker logs nongaree-local-agent-1 | grep job_id` — no line means your build was never
  involved. Stop the local agent when not testing: `docker stop nongaree-local-agent-1`.
- **`docker logs` output is summarized by the `rtk` hook** into a "Log Summary" with
  counts instead of lines, which silently breaks `grep`. Use `rtk proxy docker logs <c>`
  to get raw output. A `grep -c` against the summary returns 0 and looks like success.
- **`docker logs --since <timestamp>` is read in the CLIENT's timezone unless it ends in
  `Z`.** This machine is UTC+7, so `--since 2026-09-11T08:08:40` (a UTC value without the
  `Z`) actually means 7 hours earlier and matches stale lines from previous runs. It fooled
  a regression probe into reporting "agent session started after 0s" off a line from an
  earlier job. Use a trailing `Z`, or a relative value (`--since 5m`).
- **Headless browser testing works here without installing anything.** Playwright's
  Chromium is cached under `%LOCALAPPDATA%\ms-playwright`, and the interpreter at
  `E:\Projects\dokkan\.venv\Scripts\python.exe` already has the `playwright` package —
  used read-only to run scratchpad probes. Launch with
  `--use-fake-ui-for-media-stream --use-fake-device-for-media-stream` so the mic path
  does not error, and inject the `nongaree_sso_session` cookie from
  `local-login/index.html` rather than clicking through the login page.
- **Chrome blocks pasting into the DevTools console** until you type `allow pasting` —
  that is why the local login is a clickable page rather than a console snippet.

---

## 3. Work completed last session

All changes are in `components/VoiceRoom.tsx` unless noted. **No SSO, auth, port, or
deployment file was modified.**

### Feature / UX changes

1. **Removed the full-screen START gate.** It predated SSO. That button was also the
   browser gesture that unblocks audio autoplay, so a fallback was added: any
   `pointerdown`/`keydown` resumes the AudioContext and calls `room.startAudio()`, plus a
   "แตะเพื่อเปิดเสียงอารี" pill shown only when `RoomEvent.AudioPlaybackStatusChanged`
   reports playback is blocked. *(This matters: `agent.py` greets the user immediately on
   join, so without a gesture that greeting could be silently muted.)*
2. **Hold-to-talk indicator.** Caption under the mic button reading **กดค้างไว้เพื่อพูด**
   (switches to กำลังฟัง / กำลังตอบ / กำลังคิด by state), plus a hint line naming both the
   button and Spacebar. Hidden below 900px wide or 700px tall so it cannot push the mic
   button out of `botStage`'s clipped area.
3. **AI disclaimer bar** at the bottom of the answer column:
   *"⚠️ ข้อมูลนี้ประมวลผลโดยระบบ AI อาจคลาดเคลื่อนได้ โปรดตรวจสอบกับกรมสรรพากรอีกครั้งก่อนนำไปใช้"*
4. **Browser title** (`app/layout.tsx`): "Create Next App" → **ระบบน้องอารี AI Voicebot**
5. **Favicon** (`app/favicon.ico`): was the default Next.js triangle, now a mini Aree
   avatar — circular `#ecf7fb` plate, `#3ea3cb` ring, cropped from
   `public/avatar/aree_cutout.png`. Multi-size ICO (16/32/48/64/128), 47.5KB.
   **Replaced in place on purpose:** an `app/icon.png` would route through `proxy.ts`,
   which only allowlists `/favicon.ico`, so it would 401 on `/login`.
6. **Session / logout** (user approved explicitly — it is auth-adjacent): idle timeout
   **10 → 30 min**; both idle and manual logout now call `window.close()` instead of
   redirecting to `/login`, with an "ออกจากระบบแล้ว" fallback screen because browsers
   cannot close tabs they did not open via script.

### Bug found and fixed during self-review

**Logout left the LiveKit session alive.** Rendering the logged-out screen does *not*
unmount the component, so the room-effect cleanup never ran — the mic track stayed
published and the room connected after "logout". `handleLogout` now stops the local
track, aborts speech recognition, and disconnects the room *before* notifying SSO.
**VERIFIED in a browser in session 3** — see §4. (This line previously read "never been
exercised in a browser"; it stood unverified for two sessions.)

### Lint cleanup — 9 problems (2 errors) → 2 problems (0 errors)

- Fixed `react-hooks/purity`: `useRef(Date.now())` → `useRef(0)` seeded on mount.
  *(Careful: `useRef(0)` alone would cause instant logout — the idle check compares
  against `lastActivityRef.current`, so it must be seeded in the effect.)*
- Removed unused `_pub`/`_participant` params and their now-unused imports.
- Removed two stale `eslint-disable` directives.
- Suppressed `react-hooks/set-state-in-effect` on the queue-flush effect with a
  justification comment (user chose suppress over restructure — restructuring risked
  silently dropping queued questions).

### Large deletion: English / translation feature — REMOVED

Discovered **English mode was completely unreachable** — no TH/EN button existed anywhere
in the JSX, so `detailLanguage` was permanently `'th'`. The user chose full deletion:

- Frontend (~230 lines): `detailTranslationKey`, `looksMostlyThai`,
  `getLocalDetailTranslation`, the `detailLanguage` / `translatedDetailPreview` /
  `isTranslatingDetail` state, translation refs, `requestDetailTranslation`,
  `toggleDetailLanguage`, the `chat_translation`(`_error`) handlers, the auto-translate
  effect, and `visibleDetailPreview`. **26** `detailLanguage === 'th' ? … : …` ternaries
  collapsed to their Thai branch.
- `agent.py` (~90 lines): `translate_detail_answer()`, the dedicated `translation_llm`,
  `_markdown_table_row_count`, `_is_missing_markdown_table_rows`, `_looks_mostly_thai`,
  the `translate_detail` handler, and the orphaned `send_json_event()` helper.
- `CLAUDE.md` updated to record this. **Do not reintroduce `detailLanguage` ternaries —
  write Thai strings directly.**

---

## 3b. Work completed — session 2 (2026-08-31, later)

All changes are in `agent.py`. **No SSO, auth, port, or deployment file was modified.**
This session fixed one supervisor feedback item end to end (see §7, item "ขอโทษ ระบบใช้เวลานาน...").

### The bug: a spoken-path failure wiped a correct on-screen answer

Reproduced in a browser. The detail-panel answer streamed through **completely and
correctly**, then got replaced by "ขอโทษ ระบบใช้เวลานาน...". Chain:

1. A participant leaves (reload, tab close, network drop) and the `AgentSession` for that
   job stops.
   *(Correction: an earlier draft of this file blamed `roomService.deleteRoom()` in the
   token route. That is wrong — the reset is double-gated behind
   `LIVEKIT_RESET_ROOM_ON_TOKEN=true` **and** `?reset=true`; the env var is unset
   everywhere and `components/VoiceRoom.tsx` never sends the param, so that path never
   runs. Do not go looking there.)*
2. The **room outlives the session** — the
   `ctx.room.on("data_received")` and `on("participant_connected")` handlers registered in
   `entrypoint()` stay live.
3. Those handlers call `session.say()` on the dead session →
   `RuntimeError: AgentSession isn't running`.
4. The exception unwinds into the catch-all in `_process_text_and_speak`, which fires the
   fallback `chat_delta` + `chat_answer` — **overwriting the good panel answer**.
   `voiceAnswer` in the session history was untouched (the fallback only sends `chat_*`),
   which is exactly why the supervisor saw the correct answer in ประวัติการถาม but an
   apology in the panel.

*Identifying detail:* the on-screen text has no ค่ะ/นะคะ while `agent.py` writes them —
`cleanPreviewText` strips polite particles (`components/VoiceRoom.tsx:126`). The string
exists **only** in `agent.py`; the frontend's own timeout message is different
("ยังไม่ได้รับคำตอบจากบอท..."). Use this to tell the two apart.

### Fix 1 — the fallback no longer clobbers a delivered answer

New helper `_detail_answer_if_delivered(text_task)` + `DETAIL_GRACE_TIMEOUT_S = 5.0`. The
error path now only writes the fallback to the panel when the detail task produced
nothing. The **spoken** fallback still always plays. A still-running detail task gets a
bounded grace window, awaited under `asyncio.shield` so a merely-slow task is **not
cancelled** by the guard.

### Fix 2 — root cause: don't act on a stopped session

- `session_closed` flag, set from the **public** `close` event (`@session.on("close")`) —
  no private attrs. (`session.say` itself guards on `self._activity is None`.)
- `_say_if_running(text, **kwargs) -> bool` wraps **all three** `session.say()` call sites
  (greeting, per-sentence playback, fallback). Returns `False` instead of raising; also
  catches the `RuntimeError` to cover the check-then-call race.
- Per-sentence loop `break`s when it returns `False` — no error storm, and no fallback
  fires from a dead session.
- `_greet_rejoined_user` and `on_data_received` bail out early when `session_closed`, so a
  stopped session no longer runs a whole RAG turn for nothing.

Data-channel publishing goes through `ctx.room`, not the session, so the detail panel is
unaffected by any of this — that is why the fix works.

### Fix 3 — "ข้อความคำตอบหายเร็วเกินไป" (supervisor item), in `components/VoiceRoom.tsx`

**Investigated first: nothing clears the answer on a timer.** `setSmartDetailPreview` is a
plain passthrough and `settleTimerRef` only flips `turnActive`. The answer vanished
because **a new turn wiped the panel instantly**, leaving it blank for the whole
routing + retrieval + LLM latency:

- typed — `sendTextMessage` blanked both previews;
- voice — the `chat_user` handler blanked them, and the agent sends `chat_user` on *any*
  committed STT transcript (`agent.py:746`), so a partial or mistaken recognition erased
  an answer the user was still reading, with nothing coming to replace it. **This is the
  likely real-world trigger** — from the user's side the text disappears for no reason.

**Fix:** keep the previous question **and** answer on screen until the first token of the
new answer arrives. Two helpers: `beginPendingAnswer(question)` (start a turn without
clearing; placeholder shown only when the panel is genuinely empty) and
`commitPendingAnswer()` (swap question + answer together on first content). Wired into
both `chat_user` and `sendTextMessage`.

Three traps that each would have broken it on their own — **do not undo these**:

1. **`chat_status` was a second wipe.** The agent sends it right after `chat_user`
   (`agent.py:747`) and it overwrote the panel unconditionally. Now suppressed while an
   answer is retained; the `LOADING` badge carries the status instead.
2. **The settle timer read busy-ness from the placeholder string.** With content retained
   `rawBusy` went false, so the turn settled early and flushed a queued question
   mid-answer. `awaitingAnswer` is now part of that check **and its dep array**.
3. **The 35s timeout would have left stale content** attributed to the new question. It
   now commits the swap and shows the timeout message; the old answer stays in
   `ประวัติคำถามในรอบนี้` (80 entries, collapsed by default — users likely don't know it exists).

Pending state is also cleared on `RoomEvent.Disconnected` so a dropped connection cannot
strand the panel in `LOADING`.

**Verified in a browser:** at the moment that previously blanked, the old question and
answer are both still shown with a `LOADING` badge; they swap together when the answer
arrives. `tsc` clean, ESLint 0 errors / 2 warnings (same pre-existing pair, now also
naming `beginPendingAnswer`).

### Fix 4 — "ถามต่อเนื่องไม่ได้" (supervisor item): multi-turn

Multi-turn was **half-wired**, not missing. History is built, summarised past
`MAX_WINDOW=10`, and genuinely consumed by both generators (`graph/nodes.py:567`), with
follow-up-aware routing via `_is_tax_followup`. Two real gaps:

**Defect A — retrieval ignored the conversation** (`graph/nodes.py`, was
`retrieve(state["query"])`). A follow-up carries no searchable subject, so Qdrant got a
bare fragment. **Measured on the live index: a bare follow-up retrieved 0 characters,
every time.** The generator had correct history but empty/wrong RAG context.

*Fix:* `build_retrieval_query(query, messages)` widens **only the retrieval query** — what
is routed, answered and displayed is untouched. Fires only when the query is
≤ `_FOLLOWUP_MAX_CHARS` (40) **and** contains an `_ANAPHORA_MARKERS` entry. Skips
form-code / mixed-alphanumeric queries, which are self-contained and must keep the
lexical-first `[EXACT_MATCH]` path clean.

- **Do not reuse `_FOLLOWUP_KEYWORDS` for this.** It contains "ค่ะ"/"ครับ", which appear in
  ordinary self-contained questions; widening those adds lexical noise for no gain.
- **Order is `follow-up + previous`, and it matters — do not "tidy" it.** The reverse was
  measured at **0 chars** on one pair where this order gave 1894 (the combined vector fell
  under `RAG_SCORE_THRESHOLD=0.75`). This order was never worse on the pairs tested.

**Evidence** (through the real `retrieve_node`, no-history vs with-history):

| follow-up | before | after |
|---|---|---|
| แล้วถ้าอายุเกิน 65 ล่ะ | 0 | 1894 |
| แล้วถ้ามีลูก 3 คนล่ะ | 0 | 3355 |
| กรณีนี้ต้องใช้เอกสารอะไร | 0 | 1276 |

**Caveat:** `_ANAPHORA_MARKERS` was tuned against 3 pairs. Expect to extend it once real
supervisor questions are available; it is a deliberately conservative list.

### Fix 5 — "ระบบค้างและ error บ่อย เช่น การเชื่อมต่อไมค์" (supervisor item)

Three causes, all in `components/VoiceRoom.tsx`:

1. **No retry existed anywhere in the component.** Token fetch + `room.connect` +
   `createLocalAudioTrack` share one try block. `createLocalAudioTrack` is the flaky step
   (device busy, another tab holding the mic, permission race); one transient failure set
   `micReady=false` **permanently**, recoverable only by the user reloading the page. Mic
   was also acquired once on mount, so granting permission afterwards did nothing.
2. **English errors in a Thai UI.** The catch surfaced raw `error.message`, so users saw
   "Permission denied" / "Could not start audio source".
3. **A dropped connection was unrecoverable and invisible.** `Disconnected` only set
   status and cleared the queue — no reconnect. Since `textControlReady === (status ===
   'connected')`, every control disabled, and `'disconnected'` was never rendered
   anywhere. A frozen page with no explanation: this is the best "ค้าง" candidate.

**Fix:** a `connectAttempt` counter in the room effect's dep array. Bumping it re-runs the
effect, whose existing cleanup already tears the room down completely — so one state bump
gives a full reconnect + mic re-acquire with **no restructuring** of the effect. Exposed
via `handleRetryConnection` behind a "ลองเชื่อมต่ออีกครั้ง" button, shown whenever
`micError` is set **or** status is `disconnected`, plus a Thai banner for the dropped
connection and `describeMicError()` mapping `NotAllowedError` / `NotFoundError` /
`NotReadableError` / `AbortError` / `SecurityError` / `OverconstrainedError` to Thai.

**Verified in a browser:** the Thai permission message and retry button render; clicking
retry clears the error, returns to "กำลังเชื่อมต่อ", re-runs the effect with a fresh
token/room/mic, and lands back on the error state (the pane blocks mic by design). `tsc`
clean, ESLint 0 errors / 2 warnings.

**Not verified:** a *genuine* device failure (mic busy, no device). The browser pane blocks
microphone access outright, so only the wiring was exercised, not a real `NotReadableError`.

### Fix 6 — answer citations [1][2][3] (supervisor item)

Supervisor asked for references on answers. Chunk-level citation **is** enough credit here,
because the chunks are not anonymous — each Qdrant payload carries `title`, `domain`,
`subdomain`, `cluster_id`, `record_id`, `traceability_ref`, `source_priority`.

**Facts established by inspecting the live index (1311 points):**

| Finding | Number |
|---|---|
| chunks with real `ref_links` (rd.go.th URLs) | **23 / 1311 (1.8%)** |
| chunks with `image_urls` | 29 |
| flagged `needs_tax_review` | **969 (74%)** |
| flagged `possibly_outdated` | **143 (11%)** |
| no flags (the vetted `callcenter_corrected_answer`, `source_priority` 5) | 339 (26%) |

So document-level citation is **not** viable as the mechanism — at 1.8% coverage a
link-based design looks broken 98% of the time. A URL is shown only when one exists.

**Watch out:** `review_flags`, `ref_links` and `image_urls` are stored as **JSON-encoded
strings**, not arrays. `if md.get("ref_links")` is true for the string `"[]"`. Parse them
(`_json_list()`), or every count comes back as 1311.

**Open risk the user has not yet ruled on:** citation raises perceived authority, and 74%
of the corpus is self-flagged as not tax-reviewed. Current behaviour surfaces a Thai
warning inside the hover card for `possibly_outdated` chunks only; `needs_tax_review` is
carried in the data but not shown.

**Implementation** (retriever → nodes → state → agent → frontend):

- `graph/retriever.py`: new `retrieve_with_sources(query) -> (text, sources)`;
  `retrieve(query) -> str` is now a thin wrapper so existing callers (`rag_node_test.py`)
  keep working. `_citation_cache` maps point id → citation, filled both from the payload
  scroll and from dense hits. Every return path (TCL, exact-code, exact-match, score gate,
  fused) returns sources.
- `graph/nodes.py` / `graph/state.py`: `sources` carried beside `context` on the `rag`
  branches, including the LLM-router path (`sources = []` where retrieval is cancelled).
  **Correction (verified 2026-09-10):** this originally read "on **all** `parallel_node`
  branches", which is not true — the manual-emotion, `curated`, `direct` and
  `out_of_scope` branches omit the key entirely. Harmless, because `agent.py:send_sources`
  reads `state.get("sources") or []`, but don't rely on the key existing.
- `agent.py`: `send_sources()` publishes `{"type":"chat_sources","sources":[...]}` once per
  turn right after state prep, before the answer streams. Non-rag routes send `[]`, which
  clears the previous turn's markers.
- `components/VoiceRoom.tsx`: numbered buttons at the end of the detail card, hover/click/
  focus opens a card with title, `domain · subdomain · cluster_id`, excerpt, the outdated
  warning, and the URL when present.

**Verified in a browser:** ที่มา [1] [2] [3] render at the end of a real answer, and the
hover card shows the chunk (e.g. "บุตรหักลดหย่อนได้เท่าไรในการยื่น ภ.ง.ด.94" ·
`B · callcenter_corrected · CALLCENTER-31`). `tsc` clean, ESLint 0 errors / 2 warnings.

**JSX trap fixed during build:** `{sources.length && …}` renders a literal `0` when empty.
Must be `sources.length > 0 &&`.

**Still to do on this item:** the "contact staff directly" fallback when Aree cannot
answer. The user said the staff contact itself is not a problem — citations were the part
worth solving first.

### Fix 7 — agent-name split (unblocks all agent-side verification)

`agent.py` now registers as `os.getenv("AGENT_NAME", "nongaree-agent")` and
`app/api/livekit/token/route.ts` dispatches to `process.env.AGENT_NAME || "nongaree-agent"`.
`docker-compose.local.yml` sets `AGENT_NAME: nongaree-agent-local` on **both** web and
agent.

- **Deployment is unaffected.** Both sides default to `"nongaree-agent"`, so an
  environment that sets nothing behaves byte-identically to before. The server needs no
  change.
- **Verified not build-inlined:** `process.env.AGENT_NAME` survives in
  `.next/server/chunks/*` and is read at runtime, so no build arg is needed.
- **The two names MUST match.** A mismatch is silent — LiveKit creates a dispatch no
  worker serves and Aree simply never joins.
- **One-time transition trap:** a room still occupied by an old-name agent participant
  makes the token route log `Skipping agent dispatch because an agent is already
  connected` — `ensureSingleAgentParticipant()` matches on `participant.kind` **or**
  `participant.name === AGENT_NAME` **or** `participant.identity.includes(AGENT_NAME)`
  (`app/api/livekit/token/route.ts`). An earlier draft of this line said "matches on
  `participant.kind`, not name" — corrected 2026-09-10. The `kind` match is still what
  makes an old-name agent count, so the trap itself stands.
  Delete the room once (LiveKit `RoomServiceClient.deleteRoom`) and it clears.

### Fix 8 — REGRESSION I introduced in Fix 2, then fixed

`session_closed` was one-way and never reset. LiveKit closes the `AgentSession` when a
participant disconnects but **keeps the job alive and reuses it on rejoin**, so after any
reload `on_data_received` returned early forever and every question was silently dropped.

- `ctx.shutdown()` now runs in the `close` handler, so the job ends and a rejoin is
  dispatched a **fresh** job with a working session. One job per session.
- `on_data_received` is **no longer gated** on `session_closed`: the detail-panel answer
  publishes over `ctx.room` and works without a live session, so dropping the packet threw
  away an answer that could still be delivered. `_say_if_running()` covers the speech half.

### Fix 9 — follow-ups never reached retrieval (found only by end-to-end testing)

Fix 4 widened the retrieval query, but end-to-end the follow-up never got that far:
`_fast_route()` classified "แล้วถ้ามีลูก 3 คนล่ะ" as **out_of_scope** and the user got
"เรื่องนี้อยู่นอกขอบเขต…". Two causes, both fixed in `graph/nodes.py`:

1. `_is_tax_followup()` only checked `_FOLLOWUP_KEYWORDS` (affirmatives, "คำนวณ"). It now
   also checks `_ANAPHORA_MARKERS`, which is what catches the "แล้วถ้า… ล่ะ" shape.
2. A rescued follow-up routed to **`direct`** — answering with no context at all. It now
   routes to **`rag`** so `retrieve_node` runs and the widening applies.

**This is why offline verification was not enough:** the earlier test called
`retrieve_node`/`parallel_node` with the route already set, bypassing the classifier.

### Fix 10 — no-source handoff to RD staff, and the three-way separation

Completes the supervisor item whose citation half was Fix 6. Goal: **when there is not
enough source to answer, apologise and hand off to a human instead of hallucinating.**

**The hallucination hole this closed:** when the `RAG_SCORE_THRESHOLD` gate returned `""`,
the route stayed `rag` and `generate_node` ran with **empty context** — i.e. the model
answered from its own knowledge rather than the knowledge base.

**Fix:** `_no_source_response()` in `graph/nodes.py` returns route **`curated`**, which
short-circuits *both* answer generators to `NO_SOURCE_ANSWER` with **no LLM call at all**.
Guarded at both places retrieval can come back empty: the fast-route `rag` branch and the
LLM-router branch.

`NO_SOURCE_ANSWER` line order is deliberate — `compact_spoken_answer()` speaks only the
**first two lines**, so the apology + "โทร 1161" are spoken and the contact table stays
screen-only. Do not reorder it. `sources` is `[]`, so no citation markers appear, which is
honest: there were none.

### The three-way separation (read before touching the router)

`_fast_route()` returns `"out_of_scope"` as a **fallthrough**, not a decision — it means
"none of the 32 `_FAST_RAG_KEYWORDS` / 5 `_FAST_DIRECT_KEYWORDS` matched". That bucket
contains **both** genuinely off-topic questions **and** real tax questions phrased outside
those 37 keywords. Getting this wrong breaks in both directions:

- put the staff handoff on `out_of_scope` → someone asking about the weather is told to
  call 1161, wasting the call centre's time;
- leave it asserting "outside our scope" → a misclassified tax question is told it is
  off-topic with no way forward.

So there are **three** outcomes, and they must stay distinct:

| Case | Route | Response |
|---|---|---|
| Tax question with data | `rag` | Real answer + citations |
| Tax-shaped, retrieval empty | `curated` | Apology + **full contact table** (1161 + hours, e-Appointment, office finder) |
| Keyword fallthrough | `out_of_scope` | **Conditional** wording + **one-line** 1161 pointer |

The `out_of_scope` copy no longer asserts the topic is out of scope. It reads "หนูตอบได้
เฉพาะเรื่องภาษี… และยังไม่มีข้อมูลสำหรับคำถามนี้ / ถ้าเป็นเรื่องภาษี … โทร 1161" — honest either
way. The two fallbacks are also deliberately **different in weight**: the full table only
where we know it is a tax question, so the distinction is visible in the UI, not just in
the code.

A comment now sits on the `return "out_of_scope"` line itself, because the return value
reads like a classification and is the thing most likely to be quietly collapsed later.

**Untouched:** the `OUT_OF_SCOPE_USE_LLM=true` branch. That path *is* a genuine
determination, so it keeps a plain decline and needs no hedging. The flag defaults to
`false`, so the conditional wording is what ships.

**Contact details** (verified against rd.go.th on 2026-09-01; the KB itself references
1161 fifteen times):

- **1161**, 20 คู่สาย, **จันทร์–ศุกร์ 08.30–18.00 น. (ไม่พักกลางวัน)**
- e-Appointment `https://interapp2.rd.go.th/e-appointment/public/`
- Office finder (RDmap) `https://www.rd.go.th/41225.html`
- Address: เลขที่ 90 อาคารกรมสรรพากร ชั้น 16 ซอยพหลโยธิน 7 … พญาไท กรุงเทพฯ 10400
- ⚠️ `e-mail.saraban@rd.go.th` came from search results, **not** from the contact page
  fetched directly — confirm before putting it in the UI. It is deliberately **not** in
  the shipped copy.
- Web Collaboration requires calling 1161 first, so it is not offered as an entry point.

**Verified** (in-container against the live Qdrant): `ลดหย่อนบุตรได้เท่าไหร่` → `rag`, 949
chars, 3 sources · `ภาษีคาร์บอนเครดิตฟาร์มกุ้ง…` → `curated`, 0 context, 0 sources,
no-source handoff · `วันนี้อากาศเป็นยังไง` → `out_of_scope`, conditional wording. The
no-source panel render was also confirmed in a browser screenshot.

**Caveat:** after that screenshot the copy was tightened (a duplicated apology block
removed). The tightened text is verified by printing the exact strings from the running
container, **not** by a fresh screenshot — the browser pane stopped accepting synthetic
keyboard input at that point. Worth one human glance.

### Fix 11 — problem-report button, storage, and admin API

Supervisor asked for an in-the-moment report button. Deliberately **separate from the
existing แบบประเมิน**, which is an external Google Form (`forms.gle/...`) for whole-session
satisfaction and carries no context at all:

| | แบบประเมิน | แจ้งปัญหา (new) |
|---|---|---|
| Scope | whole session | one turn |
| Timing | afterwards | the moment it breaks |
| Context | none | question + answer + cited chunks + diagnostics |
| Destination | Google Forms, outside RD | our own storage |

**The button is always enabled, never gated on a completed turn.** "ระบบค้าง / ไม่ตอบ"
happens precisely when there is no answer, so a turn-anchored button would block the most
important report. `turn` is nullable and the dialog says
"ยังไม่มีคำถามในรอบนี้ — จะส่งเฉพาะสถานะระบบ".

**Data decisions**

- **`preceding_turns` capped at 3, NOT the whole session.** History holds up to
  `MAX_SESSION_HISTORY_ENTRIES` (80); shipping all of it would mean dozens of turns of
  someone's salary and children for one complaint. Three covers context-dependent bugs —
  the Fix 9 follow-up bug was only understandable *with* the previous turn.
- **Chunk ids are the high-value, zero-PII part.** `record_id`/`cluster_id` turn "the
  answer was wrong" into "chunk KC-0073 is wrong". Given 74% of the corpus is
  `needs_tax_review`, this is effectively a crowdsourced review queue.
- **Excerpt text is dropped** from stored sources — the ids identify the chunk; storing
  excerpts duplicates the corpus into the report file.
- **`mic_error` stores the DOMException NAME**, not the Thai message: names are stable and
  aggregatable, copy is presentation.
- **Identity is server-side only** (session cookie), never from the body.
- **Consent by transparency:** the dialog shows exactly what will be sent, above the
  submit button, rather than a buried policy line. This is the mitigation for storing
  personal financial details.

**Storage — append-only JSONL, not a database.** `app/api/report/route.ts` appends one JSON
line to `/data/reports/reports-YYYY-MM.jsonl` on a `report_data` named volume. A DB service
would mean a new image in the prebuilt-release handoff, credentials and backups for an
unproven feature. `schema_version` makes lifting to Postgres later mechanical. Monthly
rotation exists so **retention is enforced by deleting a file**, not migrating rows.
Move to Postgres when a team queries reports regularly or volume passes a few thousand.

**Admin API — `app/api/admin/reports/route.ts`**, curl'd from the server.

There is **no admin role** in the auth model (`SsoSession` is username/tokenId/email/name/
issuedAt/expiresAt), so the route carries its own gate: `REPORT_ADMIN_TOKEN`, compared with
`timingSafeEqual`. **Disabled unless that env var is set**, and 404s when disabled so it
does not advertise itself.

```bash
TOKEN=...; BASE=http://localhost:3000/api/admin/reports
curl -H "Authorization: Bearer $TOKEN" $BASE                     # summary
curl -H "Authorization: Bearer $TOKEN" "$BASE?format=csv" -o r.csv
curl -H "Authorization: Bearer $TOKEN" "$BASE?format=json"
curl -H "Authorization: Bearer $TOKEN" "$BASE?format=files"
curl -X POST -H "Authorization: Bearer $TOKEN" "$BASE?action=rotate"   # seal now
```

Rotation is **on demand**, not only at the month boundary — and the summary still reads
sealed files, so rotating is a batch boundary, never a data cutoff.

**Protected files touched (approved in conversation):**

- `proxy.ts` — allowlisted `/api/admin/reports`, **exact match, no `/api/admin/*`
  wildcard**. Safe because the route enforces its own token and 404s when unset; curl has
  no SSO cookie and the gate 401s every `/api/` request without one.
- `docker-compose.yml` **and** `docker-compose.local.yml` — `report_data:/data/reports` on
  `web` plus the named volume. **No new service**, so the prebuilt-image handoff is
  unaffected.

**Agent change:** `send_sources()` now also publishes `diagnostics` (`route`,
`retrieval_empty`, `job_id`, `agent_name`) on the **existing** `chat_sources` message —
already sent once per turn, so no new round trip. `job_id` is the highest-value field:
it correlates a report straight to the agent log for that turn.

**Verified end to end in a browser, both cases:**

- *No turn:* stored `turn: null`, `mic_error: "NotAllowedError"`, identity from cookie.
- *With turn:* `route: "rag"`, `retrieval_empty: false`,
  `job_id: "AJ_GbEwGssPAXc8"`, `agent_name: "nongaree-agent-local"`,
  `input_mode: "typed"`, sources `CALLCENTER-116/-34/-112`, 783-char detail answer.
- Gate: no token → 403, wrong token → 403, env unset → 404, user POST without cookie → 401.
- Thai round-trips intact through storage (an earlier test *looked* corrupted; that was the
  shell's encoding, not the API).
- `tsc` clean, ESLint 0 errors / 2 warnings.

**`REPORT_ADMIN_TOKEN` — DECIDED 2026-09-10: leave it unset. Not a blocker.**

An earlier draft of this file (and my own release checklist) called setting it a
pre-deploy requirement. That was overstated. With the variable unset:

- reports are still **collected** normally — nothing is lost;
- the admin HTTP endpoint answers **404** and does not advertise itself;
- the reports remain readable on the server with `node scripts/reports.mjs`, which reads
  `REPORT_DIR` off the `report_data` volume **directly and never touches the token**.

So the only thing unset costs is the convenient *remote* read path. Set it later if
anyone wants to triage reports over HTTP: `openssl rand -hex 32` into
`docker container/.env`, then rebuild `web`. No secret was written into that file from
here on purpose — it is on the §1 protected list, and a generated one would end up in a
chat transcript.

**Retention — DECIDED 2026-09-10: 6 months.** Implemented as
`node scripts/reports.mjs purge` (dry run) / `purge --yes` (delete), overridable with
`REPORT_RETENTION_MONTHS`. Boundary is *strictly older than* 6 months, so a file exactly
6 months old is kept; the sealed-file naming (`reports-YYYY-MM.sealed-<stamp>.jsonl`)
parses correctly and unrecognised filenames are skipped, never deleted.

**Deliberately MANUAL, not a cron job.** Nothing should silently destroy the only copy
of user-reported data on a timer nobody is watching, and dry-run is the default so the
first invocation cannot delete anything. Note the `docker run` example at the top of
that script mounts the volume `:ro` — fine for reading, but purge needs it writable.

Why 6: these reports are effectively a crowdsourced review queue over a corpus that is
74% `needs_tax_review`, so a complaint needs to stay actionable long enough to be
triaged — but a queue nobody drains in six months will not be drained at twelve either,
and each line holds a named user's salary, dependants and ages.

**Note:** the browser pane's synthetic keyboard input into the question field became
unreliable; the with-turn test was driven with `javascript_tool` using the React native
value setter. The app itself is fine — this is a test-harness limitation.

**Defect B — interrupted turns never entered memory** (`agent.py`, both paths). The append
sat under `if yielded_sentences:`, so a barge-in or a spoken-path failure dropped the whole
exchange and left a hole that broke the *next* follow-up. Now records whenever **either**
answer produced content. The `generation != interrupt_generation` guard still precedes it,
so a genuinely superseded turn is still (correctly) not recorded.

---

## 3c. Work completed — session 3 (2026-09-08/09): multi-turn, and a crash it found

The user's framing was the right one: *"multi turn chat is not something you just do and
finish — it needs test and a precise window and preserve-context logic carefully
calibrated."* So this session built the **measuring instrument first** and took a
baseline before changing any behaviour. That decision paid for itself immediately — the
harness found a production crash and a design bug on its first two runs.

### Stage 0a — memory logic extracted to `graph/conversation.py`

Pure move out of `agent.py`, no behaviour change: `new_memory()`,
`build_messages_for_graph()`, `append_turn()`, `summarize_history()`, `maybe_summarize()`,
`MAX_WINDOW`/`KEEP_RECENT`, plus a lazy `_get_summary_llm()` matching the
`graph/nodes.py` singleton convention. `agent.py` lost ~65 lines and the two duplicated
append blocks (`:875`, `:1102`) collapsed to one line each.

**Why it had to happen first:** `agent.py` cannot be imported without `livekit`, which is
not installed on the host. A harness that reimplemented the memory loop would drift from
production — the same class of bug as the duplicated emotion tables `CLAUDE.md` already
warns about.

> **Trap — `docker container/Dockerfile.agent` copies files individually**
> (`COPY agent.py`, `COPY latency.py`, `COPY graph ./graph`). There is **no `COPY *.py`**.
> A new top-level module passes `py_compile`, works in the harness, and then
> `ModuleNotFoundError`s in the deployed image — fixable only by editing a protected file.
> **Put new Python modules under `graph/`.** Verified: `/app/graph/conversation.py` is
> present in the rebuilt image and `import agent` succeeds inside the container.

### Stage 0b — `scripts/multiturn_benchmark.py`

10 conversations, 46 turns. Drives the **real** `compiled_graph` (entered at
`parallel_node`, so the full classifier chain runs) and the **real** `graph.conversation`
memory code. Asserts on routing and retrieval only — never answer text, which is far too
noisy to gate on.

```bash
QDRANT_URL=http://localhost:6333 PYTHONIOENCODING=utf-8 \
  python scripts/multiturn_benchmark.py --stage s0-baseline
# later stages:
python scripts/multiturn_benchmark.py --stage s1 --baseline reports/multiturn/s0-baseline.json
```

**Pinned baseline** (`reports/multiturn/s0-baseline.json`, `reports/` is gitignored):

| metric | value |
|---|---|
| route_match | 0.783 (36/46) |
| retrieval_match | 0.783 (36/46) |
| cluster_hit | 1.0 (3/3) |
| widen_match | 0.765 (13/17) |
| fact_retention | 0.6 (3/5) |
| no_source_turns | 8 |
| turns_passed | 35/46 |
| history_chars | median 427, max 4290 |

Several conversations (`markerless_coref`, `long_followup`, `reconnect`) are **designed to
fail at baseline** — they are the targets of later stages. A harness where everything
passes on day one measures nothing.

### Fix 12 — `graph/retriever.py` crashed on EVERY tax form-code question

```python
text = "\n\n".join(
    f"คำค้น/รหัสที่ตรงกับข้อมูล: {matched}\n{text}"   # {text}, not {chunk}
    for _, chunk in lexical_hits[:1]
)
```

The genexp binds `chunk` but interpolates `text` — the very name being assigned. Inside a
genexp that resolves as a **free variable** from the enclosing scope, which is unbound
while the assignment is still in flight, so it raised
`NameError: cannot access free variable 'text'`.

**Reachable from ordinary questions**, verified against the live index: `ภ.ง.ด.90 คืออะไร`,
`ภ.ง.ด.91 ล่ะ`, `ค.10 คืออะไร` all crashed (`_exact_code_terms` non-empty **and**
`lexical_hits` non-empty). Form codes are core RD vocabulary.

**This is a SECOND, independent cause of "ขอโทษค่ะ ระบบใช้เวลานาน..."** — the supervisor
item §3b treats as fixed. The exception propagates through `parallel_node` →
`prepare_response_state` → the catch-all in `_process_text_and_speak`, which fires exactly
that fallback string. Fixes 1/2/8 addressed the dead-`AgentSession` race; they do not
touch this path, and unlike that race **this one is deterministic, not intermittent**.

Fix: `{text}` → `{chunk}`. After: `ภ.ง.ด.90` → 471 chars / KC-0740, `ภ.ง.ด.91` → 1054 /
KC-0916, `ค.10` → 469 / KC-0740. Scanned `graph/` for the same shadowing pattern
elsewhere — no other instances.

**Not yet browser-verified** (no RD VPN at the time). Worth one click-through on a form-code
question. **Deploy-worthy independently of the rest of the multi-turn work.**

### Finding — `build_retrieval_query` anchors on the wrong turn (3 faces, 1 root cause)

`_last_user_question()` returns the previous user message with **no notion of whether that
message is a usable anchor**. Three failure shapes, all measured against the live index
(`RAG_SCORE_THRESHOLD = 0.75`):

1. **Anchor was `curated`.** `find_curated_answer()` handles the salary calculator, so
   *"คำนวณภาษีเงินเดือน 100,000"* → *"แล้วถ้ามีลูก 3 คนล่ะ"* widens with a question that has
   no chunk behind it. **0 chars**, abstain, user gets the 1161 handoff. This is the most
   natural follow-up pair in the product.
2. **Anchor was `out_of_scope`.** A weather aside (`วันนี้อากาศเป็นยังไง`) becomes the anchor
   for the next real tax follow-up. **0 chars.**
3. **Anchor was itself a follow-up** — two subject-less fragments glued together:

| retrieval query | top dense | chars |
|---|---|---|
| bare `ประกันสุขภาพล่ะ` | 0.6674 | 0 |
| **+ previous turn (itself a follow-up) — current behaviour** | **0.5605** | 0 |
| + nearest **self-contained** anchor (`ประกันชีวิตลดหย่อนได้เท่าไหร่`) | **0.8776** | 1274 |

Widening scored **below the bare query**. Independently confirmed: an earlier run produced
1274 chars on that turn because its previous answer came back empty, `append_turn` skipped
it, and the self-contained t0 became the anchor by accident.

**§3b Fix 4's measured 3355 chars came from pairing the follow-up with a *retrievable*
question**, which is exactly why none of this was visible then. The two Fix 4 invariants
still hold and must be preserved: order stays `follow-up + previous`, and form-code /
alphanumeric queries stay excluded from widening.

**Spec for the fix:** anchor on the most recent **self-contained, retrievable** question —
not merely the previous user message. One rule closes all three faces.

### Stage 6a — retrieval candidate cascade (LANDED, `graph/nodes.py`)

**No single anchor rule works** — measured, not assumed. Each candidate wins on turns the
others return 0 on: the previous user question rescues `ต้องใช้เอกสารอะไรบ้าง` (1482), the
bare query rescues a long self-contained follow-up (3729, and 0 when widened), the
conversation opener rescues `ประกันสุขภาพล่ะ` (1274). Picking one trades one set of failures
for another. So `build_retrieval_candidates()` returns an ordered list and `retrieve_node`
takes the first that returns anything:

1. today's widened query (previous user question, if anaphoric and short)
2. the bare query
3. `query + conversation opener`
4. `query + previous answer[:240]` — **only if the query is anaphoric**

Form-code / mixed-alphanumeric questions return `[query]` only, preserving the Fix 4
`[EXACT_MATCH]` invariant.

**Why this cannot over-widen a working turn:** the cascade only advances after a candidate
has already come back empty, i.e. on turns already headed for `_no_source_response()` and
the "call 1161" handoff. First-try successes cost exactly what they cost before.

**The anaphora gate on candidate 4 is load-bearing — do not remove it.** The previous
*answer* is the only candidate that rescues the salary-calculator chain (after a curated
turn the question has no chunk behind it but the answer carries real tax vocabulary). It
is also the only one that can inject a *different topic's* vocabulary: the self-contained
`ภาษีคาร์บอนเครดิตฟาร์มกุ้งคำนวณยังไง` returned 0 chars on every other candidate and **275 chars
of CHILD-DEDUCTION context** on this one — topic drift feeding the generator unrelated
context, exactly what `_no_source_response()` exists to prevent. The gate encodes a real
distinction: an anaphoric query is the user pointing back at the previous turn, so
inheriting it is what they asked for; a self-contained question is a fresh topic and
inherits nothing, however badly it is retrieving.

**`RETRIEVAL_CASCADE=false`** restores one-query-one-attempt. Rollback switch, and how the
benchmark measures legacy vs cascade on an identical fixture.

**Measured, identical 49-turn fixture** (`s0-baseline-v2.json` vs `s6a-gated.json`):

| metric | legacy | cascade |
|---|---|---|
| route_match | 0.796 (39/49) | **0.878 (43/49)** |
| retrieval_match | 0.796 | **0.878** |
| fact_retention | 0.6 | **0.8** |
| no_source_turns | 10 | **6** |
| turns_passed | 39 | **43** |
| cluster_hit | 1.0 (4/4) | 1.0 (4/4) |
| elapsed_ms median | 2249 | 2427 |

Two of the remaining 6 abstains are the **correct** ones in `unanswerable_guard`, so
genuine incorrect abstains went **8 → 4**. Latency +178ms median; note that rescued turns
are *inherently* slower because an abstain makes no LLM call at all, so answering costs
more than giving up.

**The `unanswerable_guard` fixture exists because a hand-written safety check passed and
the real one failed.** A standalone test with an invented short history said the cascade
was safe; the fixture ran the real conversation with its real 165-char answer and caught
the 275-char drift. Do not delete that conversation, and do not trust hand-written history
for this class of check.

### Fix 13 — LiveKit dispatch race (`app/api/livekit/token/route.ts`)

```js
await clearRoomDispatches(agentService);
const dispatch = await agentService.createDispatch(roomName, AGENT_NAME);
await new Promise((resolve) => setTimeout(resolve, 100));
await removeDuplicateDispatches(agentService);   // deleted what was just created
```

`removeDuplicateDispatches()` classifies any dispatch with `jobs.length === 0` as stale.
A dispatch created 100ms earlier normally has no job yet — LiveKit has not assigned one —
so it deleted its own dispatch. LiveKit then had nothing to assign and **the agent
silently never joined**: no error, no log, just a room the bot does not enter.

Fix is structural, not a longer timeout: `clearRoomDispatches()` runs immediately before
`createDispatch()`, so on that branch a duplicate is impossible by construction and the
dedupe can only do damage. It now runs **only** on the `existingParticipant` branch, where
nothing was just created. No age/`createdAt` grace period was added — that would depend on
an SDK field that cannot be checked here (`node_modules` is not installed).

**Verified by dispatch-ID correlation**, which is stronger than counting:

```
created by web:  AD_RE3LLD3j49zG, AD_YrfMCbvsVazj, AD_oBaPZUXt3pK5
served to agent: AD_RE3LLD3j49zG, AD_YrfMCbvsVazj, AD_oBaPZUXt3pK5
orphaned:        (none)
```

Before the fix the signature was the opposite — `AD_cjfqU9868fCC` and `AD_F57qVesNU9xV`
created and never served.

> **Two probe traps that cost time here, both mine, both worth avoiding:**
> - **The greeting is audio-only.** `session.say()` emits TTS without a `voice_delta` data
>   message, so the greeting never appears as on-screen text. A browser probe that greps
>   the DOM for it reports "AGENT NEVER JOINED" while the agent is demonstrably answering.
>   Use the agent's own `received job request` log line.
> - **"Skipping agent dispatch" is usually correct**, not a failure. If a previous load's
>   agent is still in the room, the route reuses it. Only "created but never served" is
>   the bug — count that, not page loads.

### Stage 6b — markerless follow-ups (LANDED, `graph/nodes.py`)

`ต้องใช้เอกสารอะไรบ้าง` after a child-deduction question was answered with "this is outside
our scope". `_fast_route()` fell through, and `_is_tax_followup()` could not rescue it
because the query has **no `_FOLLOWUP_KEYWORDS` and no `_ANAPHORA_MARKERS`** — so
`retrieve_node` never ran and the Stage 6a cascade could not reach it either.

Added `_PROCEDURAL_FOLLOWUP_TERMS` as a third trigger: the user asking for a detail about
something already established — which documents, which steps, by when, where.

**The rule is concrete NOUNS, never bare interrogatives, and that is the whole design.**
`ยังไง` and `อะไร` appear in `วันนี้อากาศเป็นยังไง` just as readily; keying on those would
rescue the weather question and collapse the three-way separation. Measured on 6 tax
follow-ups vs 6 off-topic questions: **12/12 correct**. Second safety layer: the existing
`_is_tax_followup()` body still requires the RECENT CONTEXT to contain a tax keyword, so
these terms can only fire inside a conversation already about tax.

Measured 6a -> 6b: `route_match` 0.878 -> **0.898**, `turns_passed` 43 -> **44**.
`markerless_coref` goes 4/4. `no_source_turns` is unchanged at 6 — correctly, because this
was a ROUTING failure, not an abstain. Guards all held: `scope_bounce` t1 still
`out_of_scope`, `unanswerable_guard` both abstains intact, `topic_switch` 4/4.

> **Harness footgun, now fixed:** `--only` wrote its partial report to
> `reports/multiturn/<stage>.json`, silently overwriting the full report of the same name.
> That destroyed the 6a reference and produced a nonsense delta table on the next stage
> (baseline shown as 3 turns). Partial runs now write `<stage>-only.json`.
> **Current reference for future stages: `reports/multiturn/s6b.json` (44/49).**

### Stage 6a + 6b verified END TO END through the real agent path

The harness drives `compiled_graph.ainvoke()` directly; production goes through
`prepare_response_state()` in `agent.py`, which builds `messages` from its own `memory`
dict. Same graph, different entry point — and §3b Fix 9 is the standing proof that bugs
live in that seam. Browser-verified on the local stack:

- `ภ.ง.ด.90 คืออะไร` -> structured answer + citation, no crash fallback (**Fix 12**)
- `ลดหย่อนบุตรได้เท่าไหร่` -> `ต้องใช้เอกสารอะไรบ้าง` -> **answered, 3 citations**
  (**Stage 6b**; this second turn was "outside our scope" before)

### OPEN — a follow-up asked too soon loses its context

Reproducible, mechanism NOT yet established. Same two-turn conversation, varying only the
gap after turn 1:

| gap after turn 1 | turn 2 (`ต้องใช้เอกสารอะไรบ้าง`) |
|---|---|
| ~0s (agent not yet joined) | never answered — LiveKit drops data for absent participants |
| ~11s (voice still playing) | **`out_of_scope`** |
| ~39s (voice finished) | **answered, 3 citations** |

**Why a real user can hit this:** the send button returns to `ส่ง` when the PANEL answer
completes, which is seconds before the SPOKEN answer finishes. Anyone who reads the answer
and immediately types a follow-up is inside that window. This is a plausible slice of the
supervisor's *"ถามต่อเนื่องไม่ได้"* that neither the harness nor §3b Fix 4 covers, because
both only exercise cleanly-completed turns.

**Do NOT assume the cause is the `interrupt_generation` guard.** I made that inference from
the `Interrupted current speech: new_text_input` log line and it was wrong:
`_cancel_current_speech()` bumps `interrupt_generation` **unconditionally** at the top of
every `text_input`, so that line fires whether or not any speech was in flight. It is not
evidence of an interrupt. Establishing the real cause needs instrumentation — log
`len(memory["history"])` at the top of `prepare_response_state`, then re-run the 11s case.

**Suggested next step:** add an `interrupt_then_followup` fixture to
`scripts/multiturn_benchmark.py` so the effect is measurable before anything is changed.
Reversing "superseded turns are not recorded" would partly undo §3b Fix 4 Defect B, which
was itself a deliberate fix — do not do it on argument alone.

> **Two browser-probe traps, both mine:**
> - **Citation markers mean the turn STARTED, not finished.** `chat_sources` is published
>   before the answer streams. A probe that waits on markers fires the next question into
>   the middle of the current turn.
> - **The send button returning to `ส่ง` does not mean the turn is over.** It tracks the
>   panel answer, not the voice.

### Stage 1 — conversation memory persists across a reload (LANDED)

Memory was a local in `entrypoint()`, so it lived and died with the LiveKit *job* — and
§3b Fix 8 deliberately ends the job on session close. **Every page reload wiped the
conversation.** New `graph/conversation_store.py`: one JSON per user under `MEMORY_DIR`
(default `/data/memory`).

- **Key = the LiveKit room name** minus the `nongaree-` prefix. The token route derives
  the room server-side as `nongaree-${safeUser}` and a client cannot request another
  user's room, so the key is both sanitised and unspoofable. Do **not** switch this to
  `participant.identity` — that is the raw username.
- **Atomic write** (temp + `os.replace`): a reload can briefly overlap two jobs, and a
  half-written file must never be readable. Cross-process races resolve last-write-wins.
- **30-minute idle TTL**, matching `IDLE_LIMIT_MS` in `VoiceRoom.tsx`. Pruned lazily on
  write, throttled to once a minute, using mtime so nothing has to be parsed. No cron —
  same "retention is deleting a file" reasoning as the report rotation.
- **Degrades quietly.** If `MEMORY_DIR` is unwritable it warns ONCE and falls back to
  in-process memory. An operator who pulls a new prebuilt image without adding the volume
  gets the previous behaviour, not a crash loop. This is not optional given the
  release-handoff model.
- **`schema_version` mismatch discards** rather than migrates. Stage 2 will change the
  shape; with a 30-minute TTL, incompatible files disappear almost immediately.

**Logout clearing — `app/api/session/memory/route.ts` (NEW FILE, deliberately).** Session-
gated `DELETE`, called from `handleLogout` BEFORE the SSO logout so the cookie is still
valid. Identity comes from the cookie and there is no user parameter, so one user cannot
clear another's. **A new route was chosen specifically to avoid touching
`app/api/auth/sso/logout/route.ts`**, which §1 lists as "won't touch at all".

**Protected files changed (approved in conversation):** `docker-compose.yml` and
`docker-compose.local.yml` — `memory_data:/data/memory` on **both** `web` and `agent`
(the agent had no `volumes:` key at all) plus the named volume. **No new service**, so the
prebuilt-image handoff is unaffected. Both configs validated with `docker compose config`.

**Privacy:** this writes salary, dependants and ages to disk — the same data class §3b
Fix 11 capped at 3 preceding turns for exactly this reason. The 30-minute TTL and
clear-on-logout are the mitigations. **Memory retention was never actually open** — the
30-minute idle TTL (`DEFAULT_TTL_MINUTES`, `MEMORY_TTL_MINUTES`) IS the policy, files are
pruned automatically by `_prune()`, and logout clears immediately. Earlier drafts listed
this as an outstanding decision alongside report retention; only the latter was open, and
it is now decided at 6 months (§3b Fix 11).

**Measured 6b -> s1:** `reconnect` t3 (the turn right after the reload) **out_of_scope ->
rag, 0 -> 504 chars**, widening restored, `60,000` carried. `route_match` 0.898 -> 0.918,
`widen_match` 0.929 -> **1.0**.

`turns_passed` stayed at 44 because `long_session` t11 flipped the other way — **route and
context identical (rag, 1483 chars both runs)**, so it failed only `carry_facts`. After
compaction the history holds just the last two turns, so `80,000` could only have survived
in the summary, and it did not. **That is defect 2 (a <=3-sentence summary on
`ROUTER_MODEL`), it is nondeterministic, and it is the Stage 4 target — not a Stage 1
regression.** Treat `fact_retention` as noisy until Stage 4 lands.

**The harness mirrors the agent now:** `drop_memory` RELOADS from the store instead of
wiping, and it persists after every turn. Without that change the `reconnect` fixture
would still measure the old behaviour and pass for the wrong reason.

### Stage 1 verification — what IS and IS NOT proven

- **Save path — PROVEN.** `/data/memory/<user>.json` written with correct schema and
  content, including during the user's own UI session (9 turns, 8.7KB).
- **Load path — PROVEN.** Run directly inside the agent container:
  `load_conversation(room_to_key('nongaree-localdev'))` -> 2 turns restored, logging
  `Restored conversation memory for localdev: 2 turns`.
- **`reconnect` fixture — PASSES** in the harness, which drives the same save/load code.
- **Browser tab-close round trip — NOT PROVEN.** Turn 2 answered, but the post-restart job
  logged no `Restored conversation memory` line, so which memory it used cannot be
  determined from the logs. Not counted as evidence.

> **A fast `page.reload()` does NOT exercise persistence.** LiveKit does not mark the
> participant gone, the AgentSession survives, and the follow-up is answered from the
> in-process dict — one job, one pid, no restart. Verified by log. Persistence earns its
> keep on **tab close, network drop and longer gaps**, not on F5. Test it by closing the
> browser context and waiting ~25s for `ctx.shutdown()`, not by reloading.

> **RULE FOR BROWSER TESTS IN THIS PROJECT: a green verdict means very little without a
> corroborating line in the AGENT log.** Five times in session 3 a test failure or success
> was an artefact of the probe, not the product: greeting detection (the greeting is audio
> only, never in the DOM), citation markers (published BEFORE the answer, so they signal a
> turn starting), the send button (tracks the panel answer, not the voice), a missing
> `--ignore-certificate-errors`, and this one. Four would have been silent false results.

### Fix 15 — `_say_if_running()` missed the "is closing" state (`agent.py`)

§3b Fix 2 claims the guard "catches the RuntimeError to cover the check-then-call race".
It caught only ONE of the two messages livekit-agents raises:

```
"AgentSession isn't running"                 -> caught
"AgentSession is closing, cannot use say()"  -> re-raised   <-- the reconnect case
```

`session_closed` cannot cover it either: that flag is set from the `close` event, which
fires AFTER closing completes, so the entire `closing` window slips past the guard. A
participant reconnecting mid-teardown sent `_greet_rejoined_user` into an unretrieved task
exception. Found while verifying Stage 1 in a browser. Now matches both messages.

### Benchmark reports on disk (`reports/multiturn/`, gitignored)

Contents verified 2026-09-10 by reading each file, because the list below had drifted from
what is actually on disk. Anything ending `-only.json` is a **partial** run (`--only`) and
is not comparable to a full one — check `turns_total` before using any file as a baseline.

| file | turns | what it is |
|---|---|---|
| `s0-baseline.json` | 35/46 | fixture v1, pre-cascade. Historical only |
| `s0-baseline-v2.json` | 39/49 | fixture v2, `RETRIEVAL_CASCADE=false` — **the legacy control** |
| `s6a.json` | 40/46 | Stage 6a on fixture v1. Historical |
| `s6a-v2.json` | 43/49 | **the real Stage 6a full run** — this is the 43/49 the §3c table quotes |
| `s6a-final.json` | 42/49 | a later 6a run; superseded, kept only to explain the name |
| `s6a-gated.json` | 3/4 | **CORRUPT — a `--only salary_chain` partial that overwrote the full run.** Never use as a baseline. The harness now writes `<stage>-only.json` so this cannot recur |
| `s6b.json` | 44/49 | Stage 6b |
| `s1.json` | 44/49 | after Stage 1 persistence |
| `s4-factpin.json` | 46/49 | §3e Fix 17, fact pinning |
| `s5-alias.json` / `s5-alias-routing.json` | 45/49 | §3e Fix 18; the 45 vs 46 is the flaky turn, not a regression |
| `s6-ontopic.json` | 49/49 | §3e Fix 19 |
| `s6-confirm.json` | 49/49 | independent re-run of the above; 49/49 is reproducible, not a lucky run |
| `s7-final.json` | 49/49 | after Fix 20 (emotion tables) |
| `s8-regression-fixes.json` | 51/51 | after Fixes 21–24; adds the `formcode_opener_guard` fixture (11 conversations) |
| `s9-compaction-race.json` | 51/51 | after Fix 26 (compaction race) |
| `s10-followup-classifier.json` | 57/57 | after Fix 27; adds `unlisted_followups` (12 conversations) |
| `s11-scenario-fixes-final.json` | **57/57** | after Fixes 28–29; `long_session` t2 expectation corrected to `rag` — **the current reference** |
| `s11-scenario-fixes.json` | 57/57 | same fixes minus the `juristic` / `tax_form` topic groups; superseded by `-final` |
| `s10-unlisted-only.json` | partial (6) | the new fixture on its own; not a baseline |
| `flake1/2/3-only.json`, `s4-guardcheck-only.json`, `smoke.json` | partial | throwaway probes, not baselines |

> §3c's Stage 6a table says the reference report is `s6a-gated.json`. **It is not** — that
> file is the corrupt 4-turn partial. The full run behind those numbers is `s6a-v2.json`.

### Trap — `route: "curated"` is ambiguous, never read it raw

It means **either** a genuine `find_curated_answer()` hit (a good answer) **or**
`_no_source_response()` abstaining. Opposite outcomes. The first baseline had 17 curated
turns: **10 genuine, 7 abstains.** The harness now records a `no_source` flag and reports
`no_source_turns`. Any metric that does not split these is unreadable.

### Nine multi-turn defects on record (worst first)

Full audit and staged plan are in the session plan file; the short list:

1. **Memory is per-job** — `agent.py:906` creates it in `entrypoint()`, and §3b Fix 8's
   `ctx.shutdown()` means a reload gets a fresh job. **A page reload wipes all history.**
2. Summary drops the numbers follow-ups need (`ROUTER_MODEL`, `max_tokens=200`, "ไม่เกิน 3 ประโยค")
3. Window counted in turns, not tokens
4. Assistant turn stores the full Markdown panel answer, not what was heard
5. Widening anchors on the wrong turn (above)
6. Coreference = 17-entry `_ANAPHORA_MARKERS` tuned on 3 pairs
7. Summarization is fire-and-forget, races the next turn, unbounded on failure
8. `_FOLLOWUP_MAX_CHARS = 40` is an untested cliff
9. ~~No multi-turn test~~ — closed by Stage 0b

---

## 3d. Self-hosted LiveKit on the RD server (2026-09-09) — WORKING

Until now every session ran against **LiveKit Cloud** (`wss://stt-tts-ad50wayf.livekit.cloud`).
A self-hosted server was built in July, parked waiting on the RD network team, and the
release went out on Cloud instead. On 2026-09-09 the network side landed and the voicebot
was made to work against self-host end to end — **verified by the user in a browser, text
and audio both**.

> **The July/August self-host sessions no longer exist.** Their transcripts were deleted
> (oldest surviving transcript in this project starts 2026-08-28; that work ran 07-20 to
> 08-04). Only the user's prompts survive in `~/.claude/history.jsonl`, never the replies.
> Everything below was reconstructed from those prompts plus live probing. **Do not assume
> it can be recovered again — keep this section current.**

### The server

| | |
|---|---|
| Host | `nectec@ubuntu24-4` |
| Live stack | `~/livekit/server/` (compose project name `server`, hence `server-livekit-1` etc.) |
| Generator output (placeholders, NOT live) | `~/livekit/livekit.placeholder.com/` |
| Containers | `server-livekit-1`, `server-redis-1`, `server-caddy-1` |
| Internal IP | **10.223.5.31** — routed by the OpenVPN profile (`10.223.5.0/24`) |
| Public IP | 167.94.112.79 — **filtered from the internet**, not reachable from a VPN client |
| LiveKit | 1.9.11, HTTP 7880, RTC TCP 7881, ICE 50000-60000, TURN TLS 5349 / UDP 3478, relay 30000-40000 |

Ports opened by the RD network team: 80/tcp, 443/tcp+udp, 7881/tcp, 3478/udp, 50000-60000/udp.
This resolved the July blocker `could not validate RTC config: could not resolve external IP`.

### Domains — internal DNS only, and that is deliberate

`livekit.rd.go.th` and `turn.rd.go.th` exist on RD internal DNS only; both are **NXDOMAIN in
public DNS** (verified). The parent zone resolves fine publicly, so this is a choice, matching
the requirement that the voicebot be reachable only on the RD network.

**Consequence: ACME cannot work.** Let's Encrypt failed with
`DNS problem: NXDOMAIN looking up A for livekit.rd.go.th`. Note it failed at **DNS lookup**,
never reaching the ports — opening the firewall does not help.

**Current state: Caddy issues from its own local CA** (`caddy.yaml` uses
`certificates.automate` + `automation.policies` with `issuers: [{module: internal}]`).
Handshakes succeed; browsers do not trust it. **Both blocks are required** — `automate` says
*which* names to manage, `automation.policies` says *who issues*. Deleting `automate` leaves
Caddy managing nothing and answering TLS with `internal_error` and no certificate.

**Certificate — in progress (2026-09-10).** RD will issue **one certificate covering both
names as SANs**. To avoid emailing a private key, generate the keypair + CSR on the server
(`openssl req -new -newkey rsa:2048 -nodes -keyout livekit.key -out livekit.csr -addext
"subjectAltName=DNS:livekit.rd.go.th,DNS:turn.rd.go.th"`) and send RD only the CSR — a CSR
and a certificate are both public; the private key never leaves the machine. Ask for the
**full chain**: a missing intermediate looks exactly like an untrusted cert.

**Certificate — RECEIVED 2026-09-10.** RD supplied a **wildcard** they already hold:

| | |
|---|---|
| subject | `CN=*.rd.go.th` — SANs `*.rd.go.th`, `rd.go.th` |
| issuer | DigiCert / RapidSSL TLS RSA CA G1 — **public CA, so browsers trust it with no client setup** |
| valid | 2026-04-07 -> **2026-10-22** |
| files | `rd_go_th_fullchain.pem` (leaf -> RapidSSL G1 -> DigiCert Global Root G2), `private_key_11.key` |

Verified before install: SANs cover both names, key modulus matches the cert, key has no
passphrase (`RSA key ok`), chain is complete and leaf-first. This removes the internal-CA /
Group Policy plan entirely — nothing has to be installed on user machines.

> **DIAGNOSTIC NOTE — the cert EXPIRES 2026-10-22.** Renewal is RD's responsibility, not
> ours, and this is recorded only so a future debugging session recognises the symptom
> instead of chasing it: once it lapses, browsers refuse `wss://livekit.rd.go.th` and the
> voicebot shows *"การเชื่อมต่อหลุด"* with the agent side looking perfectly healthy — the
> server logs show nothing wrong because nothing on the server IS wrong. Check the expiry
> first: `openssl s_client -connect 10.223.5.31:443 -servername livekit.rd.go.th </dev/null
> 2>/dev/null | openssl x509 -noout -dates`. It is a SHARED wildcard covering every
> `*.rd.go.th` service, so RD renews it on their own schedule — the ask is to be on the
> distribution list, not to drive the renewal.

> **It is a shared wildcard private key** — the same key protects every `*.rd.go.th`
> service RD runs. Keep it `chmod 600`, do not copy it around, and delete the delivery
> zip from Downloads and the mailbox once installed.

**Earlier note now corrected:** this file previously said RD held no wildcard and one would
have to be issued. That was true of the **EV** cert on their public site (`rd.go.th`,
`www.rd.go.th`, `cbcr.rd.go.th`) — they hold a *separate* RapidSSL wildcard as well. RD holds a DigiCert EV cert
for `rd.go.th` / `www.rd.go.th` / `cbcr.rd.go.th` — **not a wildcard**, so it cannot be reused.
Ask RD PKI for either a cert covering both names (then switch to `certificates.load_files`),
or `_acme-challenge` TXT records in the **public** zone so DNS-01 can run.

### Fix 14 — dispatch is INCOMPATIBLE between Cloud and self-host

`app/api/livekit/token/route.ts`, `listExistingDispatches()`. Calling `listDispatch()` on a
room that does not exist yet reports differently:

| | missing room |
|---|---|
| LiveKit Cloud | **404** |
| self-hosted | **503** `twirp error unknown: no response from servers` |

Only the 404 shape was handled, so self-host rethrew and **dispatch never happened — the agent
never joined and every question was silently dropped**. No error in the UI, just the 35s
timeout. It looks identical to the §3c Fix 13 dispatch race and has a completely different
cause. Fixed by treating 503 / "no response from servers" as "room missing" too.

Probed directly against the server: `ListDispatch`/`CreateDispatch` on an existing room -> 200;
`ListParticipants` on a missing room -> 200 with an empty list (so that path needs no change).

### `rtc.node_ip` — advertise the address clients can actually reach

`livekit.yaml` had `use_external_ip: false` with `node_ip: "167.94.112.79"` — the **public** IP,
explicitly pinned. LiveKit therefore advertised ICE candidates at an address that is filtered
from everywhere clients live. Signalling succeeded, media did not:
`failed to connect: Connection("wait_pc_connection timed out")`.

Measured, from a VPN client: STUN to `10.223.5.31:3478` replies; to `167.94.112.79:3478`
silence. Changing to `node_ip: "10.223.5.31"` fixed it — agent session then started in 408ms.

> **RESOLVED 2026-09-10.** RD confirmed office clients reach the server at **10.223.5.31**,
> the internal address — not the public `167.94.112.79`. So `node_ip: "10.223.5.31"` is correct
> for production, not just for VPN testing, and NAT 1-to-1 is not needed. This was the item
> that would otherwise have produced "connects fine, no audio" after cutover.

### ACCEPTANCE TEST PASSED (2026-09-10) — self-host is complete

After installing the RapidSSL wildcard, the Caddy local CA root was **removed from the dev
machine's Windows trust store** (`certutil -delstore ROOT b09fe5250ee7519500488f7b95453511`)
and the voicebot was loaded again. **It connected and answered.** With no project CA
trusted, the only thing validating the connection was the public DigiCert/RapidSSL chain —
i.e. exactly what a normal RD user's machine has. Corroborated server-side by activity in
the `server-livekit-1` container log.

Verified independently from the dev machine, against SYSTEM roots with no `-CAfile`:
`Verify return code: 0 (ok)` for both SNIs, `curl` `tls_verify=0`, and `/rtc/validate` still
answered by LiveKit through the layer4 proxy.

**Self-host is therefore done.** What remains is on the voicebot side only: `LIVEKIT_URL`
and the keys in `docker container/.env`, which ride out with the single release.

> The dev machine needs `10.223.5.31 livekit.rd.go.th` in its hosts file to browse the
> service, because it resolves DNS via NSTDA and cannot see RD's internal zone. **This is a
> dev-machine artefact only** — RD DNS resolves the name for office clients, which is why
> `node_ip: 10.223.5.31` is right. The hosts entry does not affect trust; it substitutes
> for DNS, not for the certificate.

### Testing the local app against self-host

`docker-compose.selfhost.yml` (new, additive — delete it to revert; production untouched):

```bash
SELFHOST_LIVEKIT_KEY=... SELFHOST_LIVEKIT_SECRET=... LOCAL_WEB_PORT=4300 LOCAL_LOGIN_PORT=4301 docker compose -p nongaree-local -f docker-compose.local.yml -f docker-compose.selfhost.yml up -d
```

- **agent** -> `ws://10.223.5.31:7880` (plain, bypassing Caddy). Server-to-server on an internal
  network, and it sidesteps certificate trust in the Rust WebSocket layer, which does not honour
  `SSL_CERT_FILE` the way Python HTTP clients do.
- **web** -> `wss://livekit.rd.go.th` with `NODE_EXTRA_CA_CERTS=/certs/caddy-local-root.crt`
  (Node honours that reliably). CA root committed at `certs/caddy-local-root.crt` — it is a
  public certificate, not a secret.
- Both get `extra_hosts: livekit.rd.go.th:10.223.5.31`, since the name resolves nowhere else.

**A browser on the dev laptop additionally needs**, as Administrator:
`10.223.5.31 livekit.rd.go.th` in `C:\Windows\System32\drivers\etc\hosts`, plus the CA in the
trust store (`certutil -addstore -f "ROOT" certs\caddy-local-root.crt`). A non-elevated shell
fails on the hosts file **silently** — that cost time.

### Testing voice without a usable microphone

There is no `test.wav` in the repo (it is only a multipart filename in `benchmark.py`).
Generate one from the project's own TTS and feed it to Chromium as a fake mic:

- TTS `/audio/speech` with `response_format: pcm` -> raw PCM, 24kHz mono 16-bit -> wrap in a WAV header.
- Round-trip check: posting it to STT `/audio/transcriptions` returned the input text **exactly**.
- Chromium: `--use-fake-device-for-media-stream --use-file-for-fake-audio-capture=<file.wav>`
  (add `--user-data-dir` to keep it off the normal profile). The file loops while held.

### Verified working

Text **and** audio, confirmed by the user in a real browser against self-host. Server-side chain
proven independently: TLS + SNI routing per name, token minting with the self-host key, agent
registration on `ws://10.223.5.31:7880`, dispatch-ID correlation, and a multi-turn answer
(`ต้องใช้เอกสารอะไรบ้าง` resolved against the previous turn, detail-panel table rendered).

**Production still runs on LiveKit Cloud.** Cutover needs: a trusted certificate, the `node_ip`
decision above, and `LIVEKIT_URL` + keys switched in `docker container/.env` (protected file).

---

## 3e. Work completed — session 4 (2026-09-10)

Scope was set by the user: **skip the open supervisor/retention decisions and the
CLAUDE.md doc-drift patch; SSO and production verification are permanently out of reach**
(no SSO access at all — local dev with SSO bypassed is the only environment); self-hosted
LiveKit is parked pending the network side; **the corpus is fixed and cannot be changed.**
So this session took the items that are exercisable on local dev alone.

All changes are in `graph/conversation.py` and `agent.py`. **No SSO, auth, port, or
deployment file was modified.**

### Fix 16 — the "follow-up asked too soon" bug (§3c OPEN item) — ROOT CAUSE FOUND

§3c recorded this as reproducible with the mechanism NOT established, and suggested
instrumenting `prepare_response_state`. **No instrumentation was needed — the cause is
visible statically, and §3c's own warning pointed at the right place.**

Both answer paths appended to memory only after the **last audio frame had played**:
`agent.py` voice path (`tts_node`, was `:829`) and typed path (`_process_text_and_speak`,
was `:1062`). So the previous turn was **absent from `memory` for the entire duration of
its spoken answer**. `_is_tax_followup()` requires a tax keyword in the RECENT CONTEXT, so
with an empty history `_fast_route()` fell through and the follow-up was answered
"เรื่องนี้อยู่นอกขอบเขต". That is exactly the §3c table: answered with 3 citations at ~39s
(voice finished), `out_of_scope` at ~11s (voice still playing).

**It was worse than a delay on the typed path.** `_cancel_current_speech()` calls
`active_text_response_task.cancel()` (`agent.py:938`) — not merely a generation bump — so
the previous turn's coroutine is **cancelled**, `except asyncio.CancelledError: raise`
runs, and the tail append is never reached. The turn was lost for the rest of the
conversation, which is why a *later* follow-up stayed broken too.

> §3c said "do NOT assume the cause is the `interrupt_generation` guard" and that the
> `Interrupted current speech` log line is not evidence. **Both correct.** The cause is
> the `.cancel()` two lines below that log line, and the tail append sitting after it.

**Fix:** `make_turn_recorder()` in `graph/conversation.py`. Recording hangs off the
**detail (panel) task** via `add_done_callback`, which:

- completes seconds before the audio does, so the turn is in memory while the user is
  still reading it — which is exactly when they type the follow-up;
- survives cancellation of the parent coroutine;
- stores **byte-identical content**, because `append_turn` already stores `detail or
  spoken` and detail wins whenever it exists.

The tail call remains as a guarded fallback for a turn that produced speech but no panel
answer, so §3b Fix 4 Defect B is preserved, not reversed. `on_recorded` is injected
(`_persist_and_summarize` in `agent.py`) so the helper stays importable without `livekit`.

**Verified offline, 11 checks** — including the two that pin the mechanism:
`_is_tax_followup("ต้องใช้เอกสารอะไรบ้าง", …)` is **True** with the turn in memory and
**False** without. Not browser-verified.

### Fix 17 — defect 2: numbers no longer depend on the summariser (Stage 4)

`summarize_history` runs on `ROUTER_MODEL` (**thaillm-8b**) at `max_tokens=200` asking for
"ไม่เกิน 3 ประโยค". An 8B model writing three sentences of Thai prose drops "80,000" most
of the time, which is why §3c called `fact_retention` nondeterministic and told later
stages to treat it as noisy.

**Prompting cannot make this reliable, so it is no longer asked to.** `extract_user_facts()`
pulls the numbers the **user** stated and `pin_facts()` puts them on their own line
**after** the LLM has written the summary. The model can no longer drop them.

Design points that are load-bearing, each forced by a failing test:

- **Only user turns are read.** What the user said about themselves (salary, dependants,
  age) is what a follow-up needs; numbers Aree quoted are re-derivable from the KB.
- **Facts are ranked, not truncated by recency.** Keeping the most recent eight let filler
  digits evict the salary from turn 1 — the one fact that matters. `_salience()` scores by
  salient unit/noun, with a money-shape fallback; incidental digits score 0 and are
  dropped. Verified: `ภ.ง.ด.90`, `มาตรา 40`, `ข้อ 2` all correctly excluded.
- **Dedupe keys on number + what it measures.** Keying on the digits alone let "ข้อ 3"
  silently overwrite "ลูก 3 คน".
- **Known units are matched before the generic short-word fallback.** Thai is unspaced, so
  a plain 1-6 character match on "100,000 บาทต้องจ่าย" yields `บาทต้อ`.
- `max_tokens` 200 → 320 so three Thai sentences cannot truncate mid-word. Background
  task, off the critical path. The pin does not depend on this.

**Measured, full 49-turn harness run** (`reports/multiturn/s4-factpin.json` vs `s1.json`):

| metric | s1 | s4-factpin |
|---|---|---|
| route_match | 0.918 | **0.939 (46/49)** |
| retrieval_match | 0.918 | **0.939** |
| fact_retention | 0.8 | **1.0 (5/5)** |
| turns_passed | 44 | **46** |
| no_source_turns | 6 | **5** |
| widen_match | 1.0 | 1.0 |
| cluster_hit | 1.0 (4/4) | 1.0 (4/4) |

**All guards held:** `unanswerable_guard` both abstains intact, `scope_bounce` t1 still
`out_of_scope`, `markerless_coref` 4/4, `long_followup` 3/3. `fact_retention` is now
**deterministic** — it no longer depends on an 8B model's sentence budget.

### Finding — `RAG_SCORE_THRESHOLD` is now tested, and it must NOT be lowered

§3c listed this as untested and suspected the gate was rejecting answerable questions.
**Half right.** `scripts/threshold_sweep.py` (new, re-runnable) measures three populations
against the live index: turns that should retrieve, off-topic questions that must not, and
core questions that must keep working.

The three turns §3c flagged as *possibly a KB gap* are **not** a KB gap — the chunks exist:

| | dense score |
|---|---|
| RESCUE `ต้องยื่นแบบไหน` / `แล้วถ้าอายุเกิน 65 ล่ะ` / `แล้วถ้ามีลูก 2 คนล่ะ` | 0.7223 / 0.7302 / 0.7335 |
| GUARD `ควรซื้อกองทุนรวมตัวไหนดี` / `จดทะเบียนสมรสใช้เอกสารอะไร` / `ซื้อคอนโด` | 0.7221 / 0.7241 / 0.7248 |
| GUARD `ค่าจ้างขั้นต่ำปีนี้เท่าไหร่` / `ธนาคารไหนให้ดอกเบี้ยเงินฝากสูงสุด` | **0.7404 / 0.7439** |

**The populations interleave, and two off-topic questions score higher than every rescue.**
No threshold separates them: 0.72 rescues all three and admits five banking/registry
questions the three-way separation exists to keep out. **Leave it at 0.75.** These turns
need a different mechanism — an on-topic check separate from the score gate, or gating on
the fused rather than the top-dense score — not a knob turn. The `salary_chain` and
`scope_bounce` fixtures now say so in their `why` strings, so this is not re-litigated.

Two by-products, **both pre-existing at 0.75**, neither introduced here:

- `ประกันชีวิตบริษัทไหนดีที่สุด` (0.8223) and `ประกันสังคมจ่ายเดือนละเท่าไหร่` (0.7588)
  **already retrieve today.** The gate keeps adjacent domains out less cleanly than assumed.
- **`VAT คิดกี่เปอร์เซ็นต์` scores 0.6811 and retrieves nothing**, so a core VAT question
  abstains to the 1161 handoff right now. `vat` is in `_FAST_RAG_KEYWORDS`, so it routes
  `rag` and then finds nothing. Worth investigating on its own.

### New artefacts and status as of Fix 17 (superseded below — kept for history)

| file | what it is |
|---|---|
| `scripts/test_conversation.py` | 28 offline checks over `graph/conversation.py`. No Qdrant, no LiveKit, no network. The only automated check on Fixes 16 and 17 at this point |
| `scripts/threshold_sweep.py` | the threshold measurement above. **Run it before anyone proposes lowering the gate again** |
| `reports/multiturn/s6-ontopic.json` | 49/49 as of this point — see the later table for the actual current reference |

Multi-turn defect list at this point: closed 1 (Stage 1), 2 (**Fix 17**), 5 (Stage 6a), 9
(Stage 0b), and the §3c OPEN too-soon-follow-up item (**Fix 16**). Still open: 3 (window in
turns not tokens), 4 (assistant turn stores panel Markdown, not what was heard), 6
(17-entry `_ANAPHORA_MARKERS`), 7 (summarisation fire-and-forget), 8 (`_FOLLOWUP_MAX_CHARS
= 40` untested cliff).

**Not verified at this point:** neither Fix 16 nor Fix 17 had been exercised in a browser.
The seam §3b Fix 9 warned about — harness enters at `compiled_graph`, production enters at
`prepare_response_state` — applies to **Fix 16 in particular**.

### Fix 18 — English tax terms retrieved nothing (`VAT`, `CIT`, `e-filing`)

Found while chasing the `VAT คิดกี่เปอร์เซ็นต์` abstain noted above. The corpus is Thai and
bge-m3 does not map English abbreviations onto it — **an English token actively drags the
whole query vector down.** Measured against the live index:

| query | dense | chars |
|---|---|---|
| `VAT คิดกี่เปอร์เซ็นต์` | 0.6811 | **0** |
| `ภาษีมูลค่าเพิ่ม VAT คิดกี่เปอร์เซ็นต์` (Thai **added**) | 0.7193 | **0** |
| `ภาษีมูลค่าเพิ่มคิดกี่เปอร์เซ็นต์` (English **replaced**) | 0.7721 | **2983** |

**So the English term has to be replaced, not augmented** — the first thing tried, adding
the Thai alongside, does not clear the gate. `_ENGLISH_TERM_ALIASES` +
`_alias_expanded_query()` in `graph/nodes.py` add a **cascade candidate**, so a query that
already works is untouched (verified: `จด VAT ต้องทำยังไง` and `withholding tax คืออะไร`
still retrieve via their original query).

**Two halves — and the second only showed up in-container.** The alias candidate rescued
nothing for `CIT คืออะไร` because `_fast_route()` sent it to `out_of_scope` first, so
`retrieve_node` never ran. `vat` was already a `_FAST_RAG_KEYWORDS` entry, which is exactly
why VAT worked and CIT did not. Routing now also consults the alias table:

> **Do NOT "simplify" this by adding `cit`/`pit`/`wht` to `_FAST_RAG_KEYWORDS`.** That list
> is matched as a **bare substring** on the lowercased query — `"cit"` fires inside
> `"citizen"` and `"facility"`. The alias patterns are word-bounded, so routing off them is
> both safer and self-consistent. Regression-checked: `citizen registration คืออะไร` and
> `facility management คืออะไร` still route `out_of_scope`.

Rescued end to end (route + retrieval, verified inside the agent container):
`VAT คิดกี่เปอร์เซ็นต์` 0 → 3035 · `CIT คืออะไร` 0 → 2091 · `e-filing ยื่นยังไง` 0 → 2768.

`PIT` / `SBT` / `WHT` / `e-Donation` are in the table because the mapping is correct and
costs nothing, but they still score 0.63-0.73 in Thai and stay below the gate. They now
route `rag` and abstain to the **contact-table** handoff instead of "outside our scope",
which is the correct three-way outcome for a tax-shaped question with no data.

### Defect 4 — MEASURED, and deliberately not fixed

"Assistant turn stores the full Markdown panel answer, not what was heard" sounds worse
than it is. Measured over the 49 stored answers in `s4-factpin.json`: **16% contain any
Markdown**, median answer 225 chars, longest 827; `history_chars_max` 4357 across the whole
window. It is not crowding the context.

Stripping the tables would also remove the structured figures that **both**
`extract_user_facts()` and cascade candidate 5 read. Changing the memory representation a
second time in one session, immediately before a single-shot release, is regression risk
for a gain that measures small. **Left alone on purpose** — reopen it with a measurement,
not the description.

### Two harness turns are FLAKY — 45/49 and 46/49 are the same result

`แล้วถ้าอายุเกิน 65 ล่ะ` and `ต้องยื่นแบบไหน` sit at 0.7302 / 0.7223 against the 0.75 gate,
and cascade candidate 5 feeds on the **previous answer**, which is LLM-generated and
differs every run. Running `reconnect` three times in a row gave t3 `ctx` of **368, 229 and
1340 chars** — all passes, 5x spread — while the same query returned 0 in another run.

**Do not chase a one-turn delta on these.** Confirm the failing set instead: everything in
`{ต้องยื่นแบบไหน, แล้วถ้ามีลูก 2 คนล่ะ, แล้วถ้าอายุเกิน 65 ล่ะ}` was the known
threshold-blocked group. A failure OUTSIDE that set is the thing worth investigating.

**Superseded by Fix 19 below:** all three now pass deterministically, because the rescue
rules put them well clear of the gate instead of leaving them balanced on it. The harness
is 49/49. Treat any failure at all as real now — the flaky band is gone.

*(Method note: when a metric moved after the alias change, the first check was whether the
change could even touch those queries — `_alias_expanded_query` returns them unchanged, so
their candidate lists are byte-identical. Prove inertness before debugging a delta.)*

### In-container verification — what it does and does NOT prove

Production enters at `prepare_response_state()`; the harness enters at `compiled_graph`.
§3b Fix 9 is the standing proof that bugs live in that seam, and **Fix 16's whole subject is
`agent.py`'s turn lifecycle, which no harness touches.** So the checks were re-run inside
the rebuilt agent container against the live index, through `parallel_node` with routing
live (`/app/prodcheck.py`, 10/10):

- **Fix 16 both ways:** the follow-up `ต้องใช้เอกสารอะไรบ้าง` routes `out_of_scope` / 0 chars
  with the previous turn unrecorded (the old behaviour, reproduced), and `rag` / 1482 chars
  once the detail-ready callback has recorded it — with the turn in memory **before** the
  audio would have finished.
- Fix 18 all three rescues, and the `out_of_scope` / `rag` / `direct` guards.
- `import agent` succeeds in the image, so the `Dockerfile.agent` COPY trap is clear.

**Still not proven: anything above the graph.** No LiveKit session, no data channel, no
TTS, no browser. The timing premise of Fix 16 — that the detail task completes well before
the audio does — is *argued from the architecture*, not measured against real TTS. **A human
click-through is still owed** (type a follow-up while Aree is still speaking); it is the
one check that exercises the real clock.

### Fix 19 — the on-topic gate: harness goes 45/49 → **49/49**

The user chose to fix the known-broken table before shipping rather than ship around it,
on the reasoning that a single-shot release raises the bar for what goes in rather than
lowering it. Three of those rows turned out to be **one root cause**.

`RAG_SCORE_THRESHOLD` is a single number compared against the top DENSE score, and it is
**simultaneously too strict and too loose**: genuine tax follow-ups sit at 0.72-0.73 while
off-topic questions reach 0.82. §3e already proved no threshold separates them. The fix is
therefore not a threshold at all — it is signals the gate never consulted.

**Measured first, over 30 labelled queries** (18 must-retrieve, 14 must-not — the eval set
is in `scripts/threshold_sweep.py` and the session scratchpad). No single continuous signal
separated the two populations; dense, top-1/top-3 margin and lexical all overlapped. But
lexical overlapped **asymmetrically**, and that asymmetry is what the fix rests on:

| | lexical top score |
|---|---|
| off-topic, own-words candidates | max **6.8** |
| the two rescuable follow-ups | **20.5**, **40.1** |

So lexical is a high-precision **positive** signal — a strong lexical hit means the user's
own words are in the corpus. It can rescue; it can never reject (many on-topic questions
score ~1.0).

Three rules, all in the "rescue, never reject" direction except the last:

1. **Lexical rescue** (`retriever._LEXICAL_RESCUE_MIN = 12.0`). Not a fitted number:
   `_lexical_scored` awards exactly +12.0 when the whole normalized query appears verbatim
   in a chunk, so 12.0 is the boundary between "the corpus contains this phrasing" and
   "some words overlapped". **A lower cut leaks** — `จดทะเบียนสมรสใช้เอกสารอะไร` reaches 6.8
   purely from the +6.0 `_DOCUMENT_TERMS` bonus on "เอกสาร", which says nothing about tax.
   (I had it at 5.0 first; the eval set caught it.)
2. **Tax-vocabulary rescue** above a **0.72** floor. The floor exists because
   `ภาษีคาร์บอนเครดิตฟาร์มกุ้งคำนวณยังไง` is *also* explicitly about tax and MUST keep
   abstaining — it measures 0.6984, so the floor has a 0.02 margin. **Do not tighten it.**
3. **Provider-recommendation rejection** (`nodes._is_provider_recommendation`), checked
   FIRST in `_fast_route`. "Which bank / which company / which fund is best" is not a
   question RD answers at any confidence. It has to be checked before the keyword lists,
   because `ประกันชีวิตบริษัทไหนดีที่สุด` contains "บริษัท", routes `rag`, and then retrieves
   at 0.8223 — the score gate never had a chance. Keyed on a **provider noun + "ไหน"**,
   never "ไหน" alone: `ต้องยื่นแบบไหน` ("which form") is a good tax question.

> **The rescue may only argue from words the USER used.** `build_retrieval_candidates` now
> returns `(query, allow_low_score_rescue)` pairs, with the flag **False** for the opener-
> and previous-answer candidates. Without this the rescue double-dips: an off-topic question
> inherits tax vocabulary from the conversation opener and then uses the *inherited* words
> to argue past the gate. Measured — `ค่าจ้างขั้นต่ำปีนี้เท่าไหร่`, `จดทะเบียนสมรสใช้เอกสารอะไร`
> and `แล้วถ้าอยากซื้อคอนโดล่ะ` each leaked exactly that way in the first cut, and each stops
> when the flag is honoured. This is the same topic-drift hazard §3c flagged for candidate 5.

**Results.** Labelled eval: on-topic 11/18 → **15/18**, leaks 2/14 → **1/14**. Full harness
(`reports/multiturn/s6-ontopic.json`):

| metric | s4-factpin | s6-ontopic |
|---|---|---|
| route_match / retrieval_match | 0.939 | **1.0 (49/49)** |
| turns_passed | 46 | **49** |
| no_source_turns | 5 | **2** |
| fact_retention / widen_match / cluster_hit | 1.0 | 1.0 |

**`no_source_turns` = 2, and both are the `unanswerable_guard` pair** — i.e. every remaining
abstain is a *correct* one, and incorrect abstains are now zero. The only `out_of_scope`
turn is the weather question. The three-way separation is intact and now visible in one
report. Verified again in-container against the live index (16/16), including all three
rejects and the shrimp/weather/form-code/greeting guards.

`scripts/threshold_sweep.py` now prints its own conclusion at the unchanged gate:
`0.75: rescued 3/3  control 5/5  new leaks 0  SAFE`, with every lower setting still leaking.

**Known limits — deliberately not chased:**

- `ภาษีธุรกิจเฉพาะ` (0.6724), `ภาษีหัก ณ ที่จ่าย` (0.7033), `บริจาคออนไลน์` (0.6374) still
  abstain. Rescuing them needs a floor below the shrimp-farm guard at 0.6984, which is not
  safe. They now route `rag` and abstain to the **contact table** rather than "outside our
  scope", which is the correct three-way outcome ("บริจาค" was added to
  `_FAST_RAG_KEYWORDS`, now **33** entries, not 32).
- `ประกันสังคมจ่ายเดือนละเท่าไหร่` (0.7588) still retrieves. It clears the gate outright on
  the opener-widened candidate, so no rescue rule is involved. Borderline anyway — RD
  answers about ประกันสังคม*ลดหย่อน*, just not contribution rates.

### Fix 20 — the drifted emotion tables, resolved

`CLAUDE.md` has always said `_ANGRY/_SAD/_HAPPY/_WOW_CONTEXT_TERMS` are duplicated in
`agent.py` and `graph/nodes.py` and must be changed together. **Nothing enforced it, and
they had drifted:** `_ANGRY_CONTEXT_TERMS` was 13 entries in `agent.py` and 15 in
`graph/nodes.py` (the latter also had `ปรับ`, `เงินเพิ่ม`), so a penalty-related answer could
be scored `angry` by `normalize_emotion()` on the graph path and downgraded to `idle` by
`normalize_stream_emotion()` on the spoken path.

The user's call: *"do what best rn — avatar still don't have emotion change, just speak, so
it was future work anyways."* Correct, and it sets the stakes: `LumoFace` is a static `<img>`
and `setMode`/`setAmplitude`/`setGazeState` are no-ops, so **none of this is visible today**.
That makes it low-risk to settle now, and the thing to optimise for is being right whenever
animation is restored.

**Resolved by trimming `graph/nodes.py` to match `agent.py` (13 terms).** `agent.py` was the
correct side, on evidence rather than seniority:

- `_ANGRY_CONTEXT_TERMS` is an **allow-list** — it lets an LLM-proposed `angry` STAND and
  downgrades everything else to `idle`. It never forces angry.
- It is matched as a **bare substring**, and both extra terms are false-positive generators.
  Measured against the real function: `ขอปรับปรุงข้อมูลผู้เสียภาษี` → **angry** (`ปรับ` inside
  `ปรับปรุง`), `ต้องจ่ายเงินเพิ่มเติมไหม` → **angry** (`เงินเพิ่ม` inside `เงินเพิ่มเติม`). Both
  entirely benign.
- `เบี้ยปรับ` is the precise term and was already in **both** lists, so `ปรับ` only subsumed it
  while adding noise.
- `AREE_SYSTEM_PROMPT` scopes angry to "หนีภาษี ทุจริต เอกสารปลอม คดีอาญา หรือโทษหนัก" and
  says "ห้ามใช้กับคำอธิบายภาษีทั่วไป". Its own worked example is `[EMOTION:happy]` on an answer
  containing "ค่าปรับนิดเดียวมาก" — so `ปรับ` licensing anger contradicted the prompt directly.

A genuine severe case still works: `หนีภาษีมีโทษยังไง` → `angry`.

**The durable half: `scripts/test_conversation.py` now asserts all four tables are identical**
across the two files, parsed with `ast` (agent.py cannot be imported without `livekit`), plus
the three behavioural cases above. A one-sided edit now fails a test instead of silently
diverging. Suite is **35/35**.

> **Trap for whoever edits these next:** all four tuples end with the same lines, so a naive
> `str.replace` hits more than one table. That is exactly how `บริจาค` briefly landed in
> `_ANGRY_CONTEXT_TERMS` during this session while being added to `_FAST_RAG_KEYWORDS`.

### Fix 21 — the UI froze permanently after ANY unanswered turn (`components/VoiceRoom.tsx`)

Found by the first automated end-to-end regression pass (2026-09-11), driven headlessly
with Playwright against the local stack. **Likely a real share of the supervisor's
"ระบบค้าง" reports** — §3b Fix 5 covered disconnects and mic errors; this is neither.

**Symptom.** One question gets no answer within `RESPONSE_THINKING_TIMEOUT_MS` (35s). The
panel correctly shows "ยังไม่ได้รับคำตอบจากบอท กรุณาลองถามอีกครั้ง" — but the caption under the
mic stays on **กำลังคิด**, the input reads **"พิมพ์คำถามถัดไป (จะส่งเมื่ออารีพูดจบ)..."** and
the button reads **เข้าคิว**. Every later question is queued client-side and never sent. The
agent logs nothing, because nothing arrives. Frozen until reload.

**Mechanism.** `willQueue = turnActive || …`; `turnActive` only clears through the settle
timer; the settle timer only starts when `rawBusy` is false. After the timeout,
`awaitingAnswer` is cleared and `detailPreview` becomes the timeout text, so the one `rawBusy`
term still true is `speechPreview === 'กำลังเตรียมคำตอบสั้น...'`. The timeout cleared that
placeholder only `if (speechPreviewRef.current === 'กำลังเตรียมคำตอบสั้น...')` — but
`sendTextMessage` and the `chat_user` handler set the **ref to `''`** and only the **state** to
the placeholder (deliberately: `voice_delta` appends into the ref). The check could never be
true. The placeholder survived, and the turn never ended.

**Fix.** Clear it from state with an updater (the timeout closure holds stale state):
`setSpeechPreview((c) => (c === 'กำลังเตรียมคำตอบสั้น...' ? '' : c))`. One line.

**Proved with a deterministic repro, not the race that found it** (`repro_timeout_freeze.py`
in the session scratchpad): stop the agent container so no question can ever be answered,
ask once, wait 35s + the 1.2s settle debounce, read the input state.
Before: `FROZEN — placeholder 'จะส่งเมื่ออารีพูดจบ', button 'เข้าคิว', thinking=True`.
After, same conditions: `RECOVERED — placeholder 'พิมพ์คำถามที่นี่...', button 'ส่ง'`.

**Triggers, any of which a real user can hit:** the agent still cold-starting when the
first question is typed (see below), a dropped data packet, an agent restart or deploy
mid-session, an LLM call slower than 35s.

> **Related, pre-existing, NOT fixed — the first question can be lost on a cold start.**
> The input enables on `status === 'connected'`, i.e. when the *browser* joins the room, not
> when the *agent* does. Measured on this run: job received 08:00:48, then **"no warmed
> process available, waiting for one to be created"**, agent in the room at 08:00:57 — a 9s
> window in which a typed question is silently dropped by LiveKit (it drops data for absent
> participants — the `~0s` row of the §3c table). Before Fix 21 that lost question also
> froze the UI; now it costs a 35s wait and a retry. A proper fix would hold typed questions
> in the existing `pendingQueue` until an agent participant is present. Not done — it is a
> behaviour change to the input, and the user is verifying for a single release.

### Fix 22 — removing a duplicate agent killed the analyser watching the REAL one

Second freeze, same symptom class, found in the same regression pass. `isAgentSpeaking`
comes from a Web Audio analyser on the agent's audio track (`rms > 0.01`, every animation
frame), and the analyser always runs on the **last subscribed** track. `TrackUnsubscribed`
called `stopAnalyser()` **unconditionally** and never reset `isAgentSpeaking`.

So: agent A joins → analyser on A; agent B joins → analyser moves to B; A is removed as a
duplicate → `TrackUnsubscribed(A)` cancels **B's** analyser, and `isAgentSpeaking` freezes
at that frame's value. B mid-greeting → frozen `true` → `rawBusy` forever → caption stuck
on **กำลังตอบ**, everything after the next question queued. Duplicate agents are routine,
not exotic: the token route removes them *after* they join (a stale dispatch, a reconnect,
a StrictMode double fetch — §3c Fix 13 is about exactly this).

**Ruled out first: headless audio.** An instrumented probe (wrapping
`AnalyserNode.getFloatTimeDomainData` to record the app's exact `rms`, the AudioContext
state and a frame counter) showed headless Chromium drives `rms` 0.25 → ~4e-6 through a
greeting and a full turn, and the UI settles normally. Not an artefact.

**Deterministic repro** (`repro_unsubscribe_freeze.py` + `lkctl.py`, session scratchpad):
dispatch a second agent into the room through the LiveKit server API, then remove the
first while the second is greeting. Before: the analyser's frame counter stopped dead at
1829 and never moved, `rms` frozen at 0.195, caption stuck. After: counter keeps climbing,
greeting ends naturally, caption returns to idle.

**Fix:** track `analysedTrack` and every subscribed agent track; `TrackUnsubscribed` only
stops the analyser when *its own* track leaves, then hands it to a surviving track; and
`stopAnalyser()` now always resets `isAgentSpeaking` to `false`, since a stopped analyser
can never update it again.

### Fix 23 — a turn whose spoken side produced nothing froze the UI (agent + frontend)

Third freeze. Observed live on `ลดหย่อนบุตรได้เท่าไหร่`: retrieval ran, both LLM streams
(spoken and panel run concurrently) returned `200` and **closed normally**, the panel answer
was delivered — and TTS was never called. The spoken reply yielded no speakable sentence.
`ptm-oss-120b` is a reasoning model and `voice_sentence_stream` swallows everything inside an
unclosed `<think>`, which fits — but the raw output is not in the logs, so that cause is
**suspected, not proven**. The freeze does not depend on the cause:

- the agent sent `voice_answer` **only if something was spoken**, so no voice event at all;
- the frontend cancels its 35s backstop on the first **panel** token, and the
  `กำลังเตรียมคำตอบสั้น...` placeholder is cleared only by a voice event;
- so nothing was left that could clear it. Caption stuck on **กำลังคิด**.

The agent's **error fallback had the same hole**: it speaks through `session.say()`, which
emits no `voice_delta`, and never sent `voice_answer`.

**Deterministic repro without the LLM** (`repro_novoice_freeze.py`): stop the agent, let the
page ask, then **impersonate the agent** through the LiveKit server API (`lkctl.py send`,
run in a throwaway container from the agent image) — sending the panel events and
deliberately no voice events. Before: 40s later still กำลังคิด / เข้าคิว. After: idle again,
with the delivered answer still on screen.

**Fix, both sides:**
- **agent** — `_close_voice_turn()` always sends `voice_answer`, empty if nothing was
  spoken (and logs a warning, so the empty-spoken-answer rate is now visible), including on
  the error-fallback path;
- **frontend** — `noteAnswerProgress('panel' | 'voice')`: the timeout stays armed until
  **both** halves have reported, so it backstops whichever one goes missing. Its handler
  already leaves a delivered panel answer alone.

### Fix 24 — a form-code OPENER leaked into unrelated questions (`graph/retriever.py`)

Not a freeze — a topic-drift bug of exactly the kind `_no_source_response()` exists to
prevent. The retriever's **exact-code shortcut** returns a chunk *before* the score gate.
Cascade candidate 4 appends the conversation opener. So when a conversation **opened on a
form code**, any later rag-routed question that missed the gate got the opener's form chunk:
`ภาษีคาร์บอนเครดิตฟาร์มกุ้งคำนวณยังไง` after a `ภ.ง.ด.90 คืออะไร` opener retrieved **471 chars of
ภ.ง.ด.90** instead of abstaining. The `allow_low_score_rescue` flag didn't help, because the
shortcut never consulted it.

**Fix:** the shortcut obeys the same rule as the rescue — it only fires when
`allow_low_score_rescue` is true. That flag is exactly "these are the user's own words": a
query containing its own code gets a single candidate (flag true), so any code reaching the
retriever with the flag false is *always* borrowed. Verified 4/4: the shrimp question now
abstains after a form-code opener, while the user's own code, an anaphoric follow-up that
legitimately inherits one (`แล้วต้องยื่นเมื่อไหร่ล่ะ` after `ภ.ง.ด.90 คืออะไร`, via candidate 1),
and a bare form-code question all still retrieve. On the dense path the offending candidate
scores 0.6627, so the gate rejects it on its own.

New harness fixture **`formcode_opener_guard`** holds it down — `unanswerable_guard` could
never see this, because its opener has no form code.

### Fix 25 (was OPEN) — reopening within ~25s of closing can leave the page with NO agent

Found while re-running the pass; **not fixed**, pending a decision. The token route reuses an
agent that is already connected ("Skipping agent dispatch because an agent is already
connected" — §3c's note that this is *usually* correct). But after a tab closes, the old
agent's `AgentSession` stays in the room for a while before it notices its participant is
gone and ends the job (§3c measured ~25s). Reopen inside that window and the route reuses a
**dying** agent. Measured 2026-09-11:

| time | event |
|---|---|
| 08:50:44 | new page joins; token route logs `Agent participant already connected: agent-AJ_judoDrookEsi` → **skips dispatch** |
| 08:50:45 | that agent's session closes, `ending job so a rejoin gets a fresh session` |
| after | room has **no agent**; nothing will ever dispatch one for this page |

With Fixes 21–23 the UI no longer freezes — each question times out cleanly and the next one
is sent — but every answer is "ยังไม่ได้รับคำตอบจากบอท" until a manual reload. The same
applies to any agent death mid-session (crash, worker restart, deploy).

**FIXED 2026-09-14 (user approved), `components/VoiceRoom.tsx`.** An agent-presence
watchdog inside the room effect: whenever the room has had **no agent participant for
`AGENT_ABSENT_GRACE_MS` (20s)** — after the last agent leaves, or right after this page
joins — it re-requests `/api/livekit/token`. The token route's existing logic sees no agent
and dispatches one; the returned token is ignored. Retries every 30s, capped at 3
consecutive attempts (so a dead agent worker can't cause a request loop), reset whenever an
agent joins. It never runs after logout (`roomRef.current !== room`) or unmount.

> **The proposal above this line was wrong, and it matters.** It said "re-run the room
> effect (the `connectAttempt` bump)". That tears the room down — and an agent's job ends
> when its participant disconnects, so reconnecting would make the *next* agent see the
> user leave and shut down too: the same race, recreated one level down. Re-requesting the
> token **without** leaving the room triggers the dispatch while the user stays connected.
> Don't "simplify" this back to a reconnect.

Design constraints, each measured:
- **20s grace** is longer than a cold start (dispatch → agent in room measured ~9–24s after a
  Docker restart), so a normal join or reload never adds a redundant dispatch. Verified: a
  normal join created exactly **1** dispatch.
- **Agent detection** is `kind === ParticipantKind.AGENT || identity.startsWith('agent-')`,
  mirroring `ensureSingleAgentParticipant()` in the token route.
- **Only when NONE remain.** Removing a duplicate agent while another stays must not trigger
  anything — that is the Fix 22 scenario, and it happens routinely.
- **Side effect:** each recovery request also writes one fire-and-forget SSO `Load`
  transaction log entry (the token route logs one per request). Rare, and harmless.

**Deterministic repro** (`repro_agent_gone.py` + `lkctl.py`, session scratchpad): with the
page connected and served, remove the agent participant through the LiveKit server API —
the exact end state of the race, with no timing luck. Before: no agent ever returned,
0 dispatches, the question was never received. After: `[VoiceRoom] no agent in room;
requesting dispatch (1/3)`, a new agent joined 36s after removal (20s grace + cold start),
and the question was served by it.

**Regression checked on the nearest path:** the Fix 22 repro (dispatch a second agent,
remove the first while the second is greeting) still passes — analyser alive, question
received — and the web container created exactly **1** dispatch during that run (the page's
own join), confirming the watchdog does not fire when a duplicate leaves and another stays.
`tsc` clean, ESLint 0 errors / 2 pre-existing warnings.

### Fix 26 — a question asked while memory was being summarised was silently lost (defect #7)

Found while researching fixes for the remaining multi-turn defects (2026-09-14). #7 had been
rated low ("fire-and-forget, races the next turn"); reproducing it showed **real data loss**.

**Mechanism.** Once history passes `MAX_WINDOW` (10 turns), `_persist_and_summarize` starts
`maybe_summarize()` as a fire-and-forget task. It sliced `recent = history[-4:]` **before**
awaiting the summary LLM call (2–10s on `ROUTER_MODEL`) and assigned `memory["history"] =
recent` **after** it. Any turn appended during that await went into the old list and was then
overwritten — gone from memory, and from disk on the next save, numbers included. This is
the "stale snapshot → silent message drop" hazard described for async compaction
([write-up](https://dev.to/crabtalk/async-compaction-the-race-conditions-nobody-talks-about-4ni)).

**Fix (`graph/conversation.py`, `agent.py`):**
- Record **how many** entries are summarised (`cut`), copy that prefix, and afterwards keep
  `history[cut:]`. Turns are only ever appended at the end, so this keeps everything that
  arrived during the await.
- If `memory["history"]` was **replaced** while waiting, discard the summary rather than apply
  a cut computed on a different list. A too-long history is harmless; lost turns are not.
- `agent.py` now holds the background task in `_background_tasks` until it completes — the
  event loop only keeps weak references to tasks, so an unreferenced one can be
  garbage-collected mid-run.

Unchanged: the single-compaction-at-a-time guard, fact pinning (Fix 17), a failed summary
leaving memory untouched, and the stored file schema.

**Proved test-first.** `test_compaction_race` in `scripts/test_conversation.py` (slow stub
summariser, a turn appended mid-call) was written **before** the fix and failed 4 checks on
the old code: the mid-summary turn was lost (history came back as just `คำถามที่ 9, 10`), and a
replaced history was overwritten with the stale cut. After the fix: **40/40**. Harness
**51/51** unchanged (`reports/multiturn/s9-compaction-race.json`), including `long_session`,
which crosses the compaction threshold, with `fact_retention` 1.0. Agent image rebuilt;
`import agent` succeeds in the container and the fixed code is present.

**Not exercised end-to-end in a browser.** The race needs a question typed inside a
multi-second window at exactly the 11th turn, which a probe can't hit reliably. The unit test
reproduces the exact interleaving deterministically instead.

### Fix 27 — LLM follow-up classifier (multi-turn defect #6, and #8 with it)

The user asked whether follow-up *detection* is needed at all ("isn't every turn after the
first a follow-up?"), then whether a small LLM could just answer yes/no. Both were measured
before anything was built.

**"Every turn after the first is a follow-up" — rejected on existing measurements.** Users
switch topics mid-conversation. Forcing it would route `วันนี้อากาศเป็นยังไง` after a tax turn
into retrieval widened with the tax question, and widening already measured as *harmful* for
self-contained questions: a long self-contained follow-up 3,729 chars bare vs 0 widened; the
shrimp-farm question 0 bare vs 275 chars of child-deduction context via borrowed words;
`ค่าจ้างขั้นต่ำปีนี้เท่าไหร่` leaked on inherited tax vocabulary.

**Yes/no classifier — measured, 14 labelled cases × 3 repeats** (9 follow-ups incl. 5 no
keyword list catches; 5 must-not: weather, coffee shop, off-corpus tax, and two fresh tax
questions asked mid-conversation):

| method | correct | extra delay |
|---|---|---|
| keyword lists | 8/14 | 0 |
| `thaillm-8b` | 11/14 | median 1.8s — `<think>` on 42/42 calls despite the prompt |
| **`ptm-oss-120b`** | **14/14**, 0 inconsistent | median 0.84s, p90 1.4s, no `<think>` |

The "small" model lost on both axes. And a *classifier* is safer than a *rewriter*: on the
same cases an LLM rewrite (tested first) turned the weather and coffee-shop questions into
the previous tax question; the classifier never mixed topics.

**Implementation (`graph/nodes.py`, `graph/state.py`):**
- `_should_classify_followup()` gates the call to the only place its answer can change the
  outcome: `_fast_route` said `out_of_scope`, there is an earlier user question, and it is not
  a provider recommendation. Normal tax questions, first questions and "which bank is best"
  never trigger it.
- `classify_followup()` sends the last 2 turns (answers clipped to 300 chars) with the tested
  prompt, `asyncio.wait_for` timeout `FOLLOWUP_CLASSIFIER_TIMEOUT_S` (2.5s). Timeout, error or
  unparseable → `None` → today's keyword behaviour. Logs every verdict with its latency.
- On **1**: route `rag` and pass `is_followup=True` to retrieval, so candidate 1 widens with
  the previous question and candidate 5 (previous answer) is allowed — without this an
  unlisted follow-up would route correctly and still retrieve nothing. All downstream safety
  still applies: the score gate, the `allow_low_score_rescue` rule, and the no-source handoff.
- Rollback: `FOLLOWUP_CLASSIFIER=false`. Model override: `FOLLOWUP_CLASSIFIER_MODEL`.
- **The keyword rescue path is deliberately unchanged** (it does not set `is_followup`), to
  keep the blast radius to turns that previously failed.

**Pre-existing hole closed in the same place.** `แล้วธนาคารไหนดอกเบี้ยสูงสุดล่ะ` after a tax turn:
`_fast_route` correctly said `out_of_scope`, but `_is_tax_followup()` returned **True** on the
"ล่ะ" and the old code rescued it to `rag` — undoing the provider-recommendation rule. Both
rescues now skip provider-recommendation questions. Verified directly on the old predicate.

**Verified:**
- End to end through the real `parallel_node` (live LLM + Qdrant), classifier off vs on:
  follow-ups answered **5/9 → 9/9**, guards held **5/5 → 5/5** (weather, coffee shop,
  shrimp-farm, the "ธนาคารไหน…ล่ะ" hole, `จดทะเบียนสมรส`); the classifier was called on
  **6/14** turns only.
- Timeout fallback: with a 0.01s timeout the same follow-up returns `out_of_scope`, logs the
  timeout, no exception.
- In the rebuilt agent container through `agent.prepare_response_state()`:
  `ของพ่อแม่ใช้ได้ด้วยหรือเปล่า` after a health-insurance turn → `rag`, 2,249 chars.
- Harness on the existing 51 turns: **51/51** unchanged, median latency 2,453ms (was 2,543) —
  no hot-path cost. New fixture **`unlisted_followups`** (6 turns: two unlisted follow-ups,
  weather and the provider hole as guards) **6/6**. Full 12-conversation run
  **57/57** (`reports/multiturn/s10-followup-classifier.json`). Its median (2,820ms) is
  not comparable to the 51-turn runs — it includes the new conversation's classifier calls
  and run-to-run LLM variance; the like-for-like 51-turn comparison above is the one that
  shows no hot-path cost.
- Offline suite **53/53** (13 new checks: answer parsing, the gate, and widening on
  `is_followup`, none needing an LLM).

**Known limits:**
- 14 hand-written cases. Promising, not proof — re-check against real follow-ups from the
  report button once they exist.
- Adds ~0.8–2s on the turns it rescues (they previously got "outside our scope", so the
  trade is intended), and one LLM call per rescued turn.
- `มันต่างจากแบบ 91 ยังไง` retrieves via the widened `ภ.ง.ด.90` exact-code path, so the context
  is the ภ.ง.ด.90 chunk only, not a 90-vs-91 comparison. Routed correctly; answer quality on
  comparisons depends on the corpus.

### Supervisor scenario test (2026-09-14) — 4 sets × 5 turns

The user supplied four 5-turn scenarios (individual tax & deductions, SME VAT, withholding
tax & gross-up, real-estate sale). Run through the **production path inside the agent
container**: `agent.prepare_response_state()` → the real panel generator
(`stream_text_answer`) → `agent.clean_text_output` → `append_turn` from the panel answer,
exactly as a user turn. Runner: `scenario_runner.py` (session scratchpad). Full transcripts
before/after: `scenario_results.json` / `scenario_results_after.json` (scratchpad).

**Scope the user set:** fix what code can fix. **LLM reasoning quality and the RAG corpus are
out of scope** — they cannot be changed here. So the findings split in two.

**Code bugs — fixed (Fixes 28, 29 below).**

**Not fixable here (LLM / corpus) — recorded, not acted on.** Outside personal income tax the
corpus has little matching content: VAT, withholding and real-estate questions retrieved
chunks that pass the score gate but are off-topic (the late-ภ.พ.30-penalty question cited
"ค่าซื้อหน่วยลงทุน"; the tax-invoice one cited "Refund" and life insurance), and the
generator then answered largely from model knowledge. Likely factual errors observed — **not
verified by an RD tax expert; flagged for review, not asserted**: public-hospital donation
said *not* 2× deductible; salary expense given as "60% under ม.40(8)" (salary is ม.40(1),
50% capped at 100,000); freelance expense added on top of the salary cap; form names
"ภ.ภ.1 / ภ.ภ.3" (ภ.พ.01 / ภ.พ.30); abbreviated tax invoice said usable for input-tax credit;
late-filing penalty formula wrong; withholding for services to a company given as 1%;
online ภ.ง.ด. filing deadline given as the 7th; ≥1 year in the house registration said *not*
to exempt specific business tax. Two turns abstained to the 1161 handoff (withholding base on
a property sale; drafting contract wording).

**Also found — hardcoded canned text, a tax fact, NOT changed:** `_home_loan_interest_answer`
in `graph/curated_answers.py` says home-loan interest is deductible up to **90,000** baht.
The commonly cited cap is **100,000**. It is code, so it is changeable — but it is a tax
fact, so it needs confirmation from someone at RD before editing.

### Fix 28 — the avatar-emotion shortcut hijacked real tax questions (agent + browser)

Set 3 turns 1–2 ("บริษัทจะจ้างโปรแกรมเมอร์ฟรีแลนซ์ (**บุคคลธรรมดา**) **ทำ**ระบบ…", "ถ้า**เปลี่ยน**คู่สัญญา
จากฟรีแลนซ์**บุคคลธรรมดา**…") were both answered **"กลับสู่อารมณ์ปกติแล้วนะคะ"**.

`_manual_emotion_command()` matched a command word (`ทำ|แสดง|เปลี่ยน|หน้า|ตา|…`) and an emotion
alias **anywhere** in the text, as substrings. "ทำ" inside ทำระบบ + "ธรรมดา" inside บุคคลธรรมดา.
Other collisions it had: "ตา" in ตามมาตรา, "หน้า" in ล่วงหน้า / หน้าที่, "ขอโทษ" / "ตกใจ" in normal
questions. **Worse in the browser:** `getManualEmotionCommand()` in `VoiceRoom.tsx` runs the
same check inside `sendTextMessage` and **returns before publishing**, so a typed question
never reached the agent at all.

**Fix, both copies:** match only a message that *is* a command, anchored `^…$` on the
space-stripped text — `(ช่วย)(ทำ|แสดง|เปลี่ยน|ขอ)(ให้)(เป็น)(หน้า|ตา|สีหน้า|อารมณ์|ท่าทาง)(แบบ|เป็น|ให้)<alias>
(ให้ดู)(หน่อย|…)(ค่ะ|…)`, or `(หน้า|ตา|อารมณ์…)<alias>`; English `show|make|set|use|do … <alias>
(face|mood|…)`. A message that is exactly an alias still counts, as before.

**Verified:** test-first — 7 real-question false positives failed on the old code, pass now;
10 genuine commands ("ทำหน้าเศร้า", "แสดงอารมณ์ตื่นเต้นให้ดูหน่อย", "เปลี่ยนเป็นอารมณ์ปกติ",
"show happy face", …) pass before and after; a parity check asserts the agent's and browser's
alias lists match. **Browser (Playwright, rebuilt web image) 3/3:** the บุคคลธรรมดา and
ขอโทษค่ะ questions now reach the agent (`Text input received` in the agent log); "ทำหน้าเศร้า"
is still intercepted in the page ("แสดงอารมณ์: sad") and never sent.

### Fix 29 — canned answers took questions they only partly covered (`graph/curated_answers.py`)

| scenario turn | old canned answer | problem |
|---|---|---|
| set 1 T1 "ปีนี้มีเงินเดือน**รวม** 600,000 บาท" | salary calculator | read as **monthly**: 7,200,000 income, ~1,979,000 tax |
| set 1 T2 "ThaiESG 50,000 **กับ** ประกันชีวิต 30,000" | insurance deduction | ignored ThaiESG |
| set 1 T3 "ฟรีแลนซ์ 100,000 หัก 3% … **หักค่าใช้จ่าย**ได้เท่าไร" | freelance withholding | ignored the expense question |
| set 3 T1 "…ใช้แบบ **ภ.ง.ด.** อะไร" (after Fix 28) | freelance withholding | no form given |
| set 3 T2 "…เปลี่ยนเป็น**บริษัท (นิติบุคคล)**" (after Fix 28) | freelance withholding | repeated "freelance 3%" |
| harness `long_session` "**ประกันสังคม**ลดหย่อนได้ไหม" | insurance deduction | answered **life/health insurance** limits ("ประกัน" in ประกันสังคม) |

Root cause for the first: `_extract_monthly_salary()` did not match "เงินเดือน**รวม** 600,000" and
fell back to "the first baht amount", treated as monthly. Root cause for the rest: each canned
answer fires on its own keyword regardless of what else the question asks.

**Fix:**
- `_is_annual_salary()` — a yearly salary figure ("เงินเดือนรวม|ทั้งปี|ต่อปี|ปีละ|รายปี", or
  "<amount> บาทต่อปี|ทั้งปี") skips both salary calculators. The marker must sit on the salary
  amount: "เงินเดือน 100,000 บาทต้องจ่ายภาษี**ปีละ**เท่าไหร่" (harness `salary_chain` t0) stays
  monthly and stays curated.
- `_covers()` — `_TOPIC_TERMS` groups (salary, freelance, wht, expense, life/health
  insurance, social security, ThaiESG/SSF, retirement, donation, home loan, spouse/child,
  VAT, property, juristic person, tax form). Each topic-specific canned answer declares
  what it covers and is skipped when the question mentions anything else. Unguarded:
  TCL, form-code patterns and the other single-purpose answers, to keep the change narrow.

**Verified:** test-first — the 6 hijacks failed on the old code, pass now; 7 simple
questions the canned answers exist for still get them (monthly salary, life insurance,
parents' health insurance, RMF, home loan, freelance withholding). Scenario re-run: set 1
T1–T3 now go through retrieval + generation (no 7.2M misread); set 3 T1–T2 no longer get
the emotion reply or the freelance-only answer (confirmed through
`agent.prepare_response_state()` in the rebuilt container): T1 retrieves and answers; T2
now **abstains to the 1161 handoff** — confirmed in the container that neither a canned
answer nor the emotion command fired, the corpus simply has no chunk on withholding rates
for a juristic-person payee. That is the corpus limit, not a code bug, and it is the honest
outcome (previously it was answered "freelance 3%", which is wrong for a company). Harness fixture `long_session`
t2 changed from `curated` to `rag` — the old expectation encoded the hijack; it now
retrieves the real "เงินสมทบประกันสังคมลดหย่อนภาษีได้ไหม" chunk. Offline suite **84/84**. Full
harness **57/57** on the final code (`reports/multiturn/s11-scenario-fixes-final.json`).
`tsc` clean, ESLint 0 errors / 2 pre-existing warnings.

### How this pass found four bugs the harness could not — and nearly missed them

Every one of Fixes 21–24 lives where §3b Fix 9 said bugs live: the seam between what the
harness drives and what production does. Three are pure frontend turn-state; the fourth
needs a conversation shape no fixture had.

**The first probe produced false passes, and this is the lesson to keep.** It checked "the
answer has a citation". When the UI froze, questions were queued client-side and never
sent — so the panel still showed the *previous* answer, which had a citation, and the checks
passed on stale data. The probe now requires, per turn, both `Text input received: <q>` in
the agent log **and** a panel that actually changed. Any browser check in this project must
assert the question *arrived*, not just that the screen looks plausible. Two more probe traps
from the same session are in §2: Docker's `--since` timezone, and waiting on the agent log
rather than a fixed sleep for the agent to join.

### New durable artefacts (current, supersedes the Fix-17-era table above)

| file | what it is |
|---|---|
| `scripts/test_conversation.py` | 96 offline checks (84 + 12 added by §3f Fix 31): `graph/conversation.py` (turn recording, fact pinning, the compaction race), the follow-up classifier's parsing / gating / widening (no LLM call), emotion-command false positives, canned-answer scope, plus parity of the emotion tables duplicated in `agent.py` / `graph/nodes.py`. No Qdrant, no LiveKit, no network |
| `scripts/threshold_sweep.py` | the threshold measurement in Fix 19. **Run it before anyone proposes lowering the gate again** |
| `reports/multiturn/s11-scenario-fixes-final.json` | **57/57 — the current reference** (after Fixes 28–29; 13 conversations). Compare new stages against this, not s10/s9/s8/s6-ontopic/s7-final/s6b/s1/s4-factpin |

### Multi-turn defect list after Fix 24

Closed: 1 (Stage 1), 2 (Fix 17), 5 (Stage 6a), 9 (Stage 0b), the §3c OPEN too-soon-follow-up
item (Fix 16), and — not on the original numbered list, but the same class of bug — Fixes
21–24 (three UI-freeze causes and one topic-drift leak, all found by the browser regression
pass). Still open: 3 (window in turns not tokens), 4 (assistant turn stores panel Markdown,
not what was heard), 6 (17-entry `_ANAPHORA_MARKERS`), 8 (`_FOLLOWUP_MAX_CHARS = 40`
untested cliff). **7 is now closed as Fix 26** — it turned out to be real data loss, not
just a race. **6 is addressed by Fix 27** (LLM follow-up classifier), which also removes the
practical cost of **8**: a long unmarked follow-up now reaches retrieval through the
classifier regardless of the 40-character cutoff. Still open: 3 and 4 (low impact).

**Researched fixes (2026-09-14)** — measured on this corpus. The #6 entry below is the
REWRITE approach, which was **not** built: it failed the guards. Fix 27 built a yes/no
classifier instead. Kept here as the reason:
- **#6 (and #8 with it):** LLM "standalone question" rewriting. Tested on 9 Thai follow-ups
  + 3 must-not-answer questions: current approach 5/9 answered; `thaillm-8b` rewrite 6/9 at
  2.9s median; `ptm-oss-120b` rewrite **9/9** at 1.5s median but it rewrote the weather and
  coffee-shop questions into the previous tax topic (1/3 guards held). An **own-words check**
  (accept only if ≥20% of the user's character 3-grams survive) accepted 9/9 real follow-ups
  and 0/2 hijacked ones. Proposed design: rewrite only on turns already headed for
  out_of_scope / abstain, with that check. Needs real report-button questions before
  trusting the thresholds.
- **#3:** summarise on a character budget (~6,000) or 10 turns, whichever first. Largest
  measured history is 4,363 chars (~1.8k–3.9k tokens); the endpoint does not expose its
  context size.
- **#4:** leave as-is — the rewrite experiment showed the stored panel answer *supplies* the
  facts good rewrites need.
- Side finding: `LLM_MODEL=ptm-minimax-2.5` in both `.env` files returns **403** for this key.
  Harmless today (every LLM getter has its own model variable) but a trap if one is removed.
The reconnect-race item above (agent-reuse within ~25s of a tab close) was open at this
point and is now **fixed as Fix 25**.

### Browser regression pass (2026-09-11) — final result: 29/31

Ran end-to-end against the local stack after Fixes 21–24 landed and were rebuilt into both
images. **The 2 failures are probe artefacts, not product bugs** — verified by reading what
each check actually asserted:

- **`[07_provider] question reached the agent and the panel updated`** — the provider
  question (`ธนาคารไหนให้ดอกเบี้ยเงินฝากสูงสุด`) and the immediately preceding weather question
  both correctly return the identical canned out-of-scope reply, so the panel text did not
  *change* between them. The agent log confirms the question was received and the dedicated
  assertion right after it (`provider recommendation: not answered from the KB`) passed. Not
  a bug — the generic "panel changed" check is just too blunt for two consecutive turns with
  the same canned answer.
- **`a FRESH agent job joins after reopen`** — the old agent's session had not yet closed
  when the tab reopened (this run it survived the full 35s+ wait; a different run the same
  day saw it close in ~1s), so the token route correctly reused the still-live agent instead
  of dispatching a new one. The follow-up was still answered correctly with full context
  (`[10_after_reopen]`, 3 citations, `"ลูก 3 คน ลดหย่อนบุตร 90,000 บาท"`), and the agent log
  confirms all 9 questions across the run were served by the local agent
  (`agent log: local agent served every question (9/9)`). This is exactly the timing
  variability the reconnect-race item above describes — the same known gap, not a new one,
  and since fixed as Fix 25.

Every check that matters for a release passed: no crash fallback, citations present,
no-source contact table, three-way separation, the problem-report round trip (identity,
turn, `job_id` all correct), and — critically — **no UI freeze anywhere in the run**, which
is what Fixes 21–23 exist to prevent. `tsc` clean, ESLint 0 errors / 2 pre-existing
warnings, offline suite 35/35.

**Still genuinely owed, not done in this pass (by design — see `regression_pass.py`'s own
docstring):** the Fix-16-specific scenario, typing a follow-up *while Aree is still
speaking*. Every turn in this pass deliberately waited for the previous answer to fully
settle before asking the next, so the mid-speech race Fix 16 fixes was never exercised here.
That click-through is still the one thing owed on Fix 16 specifically.

---

## 3f. Work completed — session 5 (2026-09-16)

Scope: verify the supervisor item still marked unverified, then whatever the user found
while testing. All changes are in `agent.py`, `graph/text_normalization.py`,
`components/VoiceRoom.tsx` and `scripts/test_conversation.py`. **No SSO, auth, port, or
deployment file was modified.**

### Fix 30 — the apology contradicted a delivered answer (`agent.py`)

The supervisor item *"การตอบคำถามบางครั้งถูกต้อง แต่ระบบแสดง 'ขอโทษ ระบบใช้เวลานาน...' แต่แสดงคำตอบในประวัติการถาม"*.
§3b Fix 1 stopped the spoken-path fallback from overwriting a delivered PANEL answer, and §4
listed that guard as unit-tested but never exercised end to end. It is now exercised.

**Method — fault injection, because no natural trigger survives.** The known causes are gone
(a stopped session no longer raises, `producer()` swallows TTS errors), so the handler is
unreachable without staging a failure. `raise RuntimeError("FAULT_INJECTION_SPOKEN_PATH")`
was inserted after `await producer_task` **inside the running container** (never in the
repo), the agent restarted, and a real browser turn driven through it.

**Result: the guard works** — the panel kept the full correct answer and the apology never
appeared on screen. But the fallback still ran three unconditional statements after it:
`send_emotion("sad")`, `_close_voice_turn(fallback)` and `_say_if_running(fallback)`. So the
apology was still SPOKEN and still stored as the spoken half of the turn, and ประวัติการถาม
showed `บอทพูด: ขอโทษค่ะ ระบบใช้เวลานาน...` directly beside the correct answer — the same
contradiction the supervisor reported, just moved.

**Fix:** two named constants replace the inline string, and the handler picks between them.

- `NO_ANSWER_FALLBACK` — the original wording, spoken **only** when the turn produced nothing
  at all. Panel gets it too, emotion `sad`. "The system took too long" is then true.
- `VOICE_FAILED_PANEL_OK` — *"ขออภัยค่ะ เสียงขัดข้องระหว่างตอบ คำตอบเต็มแสดงอยู่บนหน้าจอแล้วนะคะ"* when the
  detail answer WAS delivered. Panel untouched, emotion `idle`, and this is what
  `voice_answer` carries, so the history no longer shows an apology beside a real answer.

**Verified end to end, both branches:** fault after the panel answer → panel intact, new
wording in history, old apology absent; fault before any answer existed → apology in both
panel and history, which is correct. A clean run afterwards spoke the real answer. The
container was restored to unmodified code (hash-checked against the repo).

> **The apology is rare by construction, and that was measured, not assumed.** Across every
> clean run it fired **zero** times; it appeared only under deliberate injection. The three
> real triggers are all closed: the form-code crash (§3c Fix 12, re-tested today —
> `ภ.ง.ด.90 คืออะไร` answers in 4s), a stopped session (`_say_if_running`), and TTS errors
> (swallowed in `producer()`). Only an unexpected exception reaches it. The mic path
> (`tts_node`) has no apology fallback at all, so this text exists in exactly one place.

### Fix 31 — phone numbers were read as amounts (`graph/text_normalization.py`)

**`โทร 1161` was spoken as "หนึ่งพันหนึ่งร้อยหกสิบเอ็ด"** — one thousand one hundred sixty-one. 1161 is
the RD call centre and ships inside `NO_SOURCE_ANSWER`, whose first two lines are the spoken
half, so **every abstain turn read the hotline as a quantity**. `02-272-8000` came out as
"ศูนย์สอง-สองร้อยเจ็ดสิบสอง-แปดพัน".

**This could not be fixed in a prompt.** `normalize_for_tts()` converts digits to Thai words
before synthesis, so the model never sees "1161" — it receives finished text.

`normalize_phone_numbers_for_tts()` runs FIRST inside `normalize_numbers_for_tts`, so once a
run of digits is rewritten the later rules cannot see it. Three cases, narrowest first:
dashed / 0-leading numbers (`02-272-8000`, `0812345678`), a Thai short code after a context
word (`โทร|สายด่วน|เบอร์|ติดต่อ` + `1xxx`), and bare `1161` / `1444`.

Two guards keep money safe, and both are load-bearing:
- **Every rule refuses a number carrying a unit** (`บาท|baht|%|เปอร์เซ็นต์|คน|ปี|เดือน|วัน`), so
  `1,444 บาท` stays "หนึ่งพันสี่ร้อยสี่สิบสี่บาท".
- **The context rule accepts only `1xxx` / `1xx`.** Every Thai short code starts with 1, and
  without this `ติดต่อ 2567` — a Buddhist year — was read out digit by digit. That was a
  measured false positive, not a hypothetical.

**Verified:** 12 new checks in `scripts/test_conversation.py` covering both directions plus
the shipped `NO_SOURCE_ANSWER` line (suite **84 → 96**), then in-container, then heard by the
user in a browser. Screen text is unchanged — users still read "1161".

> Known and NOT fixed: times are still spoken oddly (`08.30-18.00 น.` →
> "แปดจุดสามศูนย์-สิบแปดจุดศูนย์ศูนย์"). It never reaches speech today because the contact table is
> screen-only, but a generated answer mentioning office hours would hit it.

### Fix 32 — the mic button was an oval (`components/VoiceRoom.tsx`)

Reported as "circle when not fullscreen, not a circle in fullscreen". **The button was the
victim, not the cause.** `.faceShell` (the avatar) is sized by WIDTH only
(`min(720px, 92%)`), so on a wide-but-short window it rendered ~520px tall inside a 600px
viewport and consumed the whole column. The button, a flex item with the default
`flex-shrink: 1`, absorbed the overflow by collapsing — **measured 116x40**, which a 50%
border-radius draws as an oval. The trigger is a short, wide window; fullscreen is incidental.

**Both halves of the fix were needed.** `flexShrink: 0` alone made it worse — it turned
"oval but visible" into "circle but clipped below the fold" under ~620px tall, because the
avatar still ate the space. So:
1. `flexShrink: 0` on the button, plus explicit sizes for short screens (92px under 700px,
   76px under 560px), always both dimensions together.
2. `.faceShell` capped against viewport height — `min(720px, 92%, 64svh)` under 700px and
   `56svh` under 560px. This is what actually frees the room.

**Verified** by measuring the rendered box at 10 viewport shapes (1920x1080 down to
1600x520): circle at every size, nothing clipped, confirmed against the REBUILT image with no
injected CSS, plus a screenshot and the user's own eyes. Cap values were tuned by injecting
CSS into a live page first, so only one rebuild was needed.

### Fix 16 click-through — VERIFIED (the item owed since §3e)

Typed `แล้วถ้ามีลูก 2 คนล่ะ` **while Aree was still speaking** the answer to a 50,000 salary
question. It was answered with the previous turn's figures carried over (600,000/year, 2
children, tax 15,500), `route: "rag"`, 3 citations, served by the local agent.

**The evidence is preserved on disk**: the user then filed a problem report on that same
turn, so report `277fea3f-3ac4-4623-b8a6-a2fbdfdc38d4` in
`/data/reports/reports-2026-09.jsonl` holds the question, both answers, the sources and
`job_id: AJ_npu8Ak2f3Ywf`. That doubles as the end-to-end check of the report flow attached
to a real turn (an earlier report had `turn: null` because nothing had been asked yet).

### Self-hosted LiveKit — first real run from the local stack

Production still runs on Cloud; this was a test of what real users will hit, using
`docker-compose.local.yml` + `docker-compose.selfhost.yml` (VPN required).

- **The agent registered on `ws://10.223.5.31:7880`** and answered a full question with audio.
- **A 401 cost time and the cause is trivial: a trailing newline in the secret.** The value
  reached the container 45 characters long, 44 after stripping, and LiveKit rejected every
  connection with `401, message='Invalid response status', url='ws://10.223.5.31:7880/agent'`.
  **Check the length before suspecting the key.**
- **RD's wildcard cert validates with nothing installed** — `curl https://livekit.rd.go.th`
  returns 200 with `ssl_verify_result=0` against system roots. Expires **2026-10-22**.
- **The dev machine needs `10.223.5.31 livekit.rd.go.th` in the hosts file** (its DNS is
  8.8.8.8 and cannot see RD's zone). A non-elevated editor fails silently and Defender may
  revert the file; `--host-resolver-rules` on a throwaway Chrome profile is the no-admin
  alternative.

> **Over the VPN the server is SLOW, and it breaks the first turn.** TCP connect from the web
> container to `livekit.rd.go.th:443` measured **~2 seconds** (versus milliseconds on Cloud),
> so dispatch calls hit Node's 10s limit (`ConnectTimeoutError`) and the agent took **over 3
> minutes** to join on the first attempt — the question went into an empty room and the user
> saw the 35s timeout copy. Office machines are on the LAN and would not see this. **When
> testing over the VPN, wait for `Agent entered room` in the agent log before asking.**

### OPEN — some turns bypass sentence chunking entirely

Sentence-by-sentence streaming works and is visible in the log (chunks of 36, 13, 2, 2, 30,
44 chars, each spoken as it is ready). But two turns (`vat คือ`, `vat คิอ`) produced **no
`TTS sentence` lines at all**, `TTS chunks count: 0` in the tracker, and a single TTS call of
**215 / 207 chars taking ~5s** — the same signature as the greeting, which is spoken through
`session.say()`. Those turns waited for the whole answer to be generated AND synthesized
before any audio, which is what "it only speaks after the full answer" feels like.

**Not root-caused.** Two wrong guesses are recorded so nobody repeats them: it is NOT the
curated path (`find_curated_answer` returns nothing for those queries) and it is NOT the
mid-speech interrupt (every typed turn logs `Interrupted current speech`, including the ones
that chunk correctly). Both cases were short English+Thai queries, so it looks reproducible.

**Latency context, measured:** first audio lands 5–7s after a typed question on a good turn,
dominated by LLM time-to-first-token (3.3–8.6s) plus 1.1–2.5s to synthesize the first chunk;
retrieval is 1.3–2.2s. `producer()` also collects every frame of a sentence before queuing
it, so a long first chunk is pure silence — capping chunk length would help, but root-cause
the bypass first.

### PRODUCTION CUT OVER to the self-hosted LiveKit (2026-09-16, user approved)

**Production no longer points at LiveKit Cloud.** Both protected deployment files were
changed on explicit request, each with a `*.before-selfhost-cutover-20260916` backup.

| Where | Value | Why |
|---|---|---|
| `docker container/.env` `LIVEKIT_URL` | `wss://livekit.rd.go.th` | Handed to the BROWSER by the token route. Must be the hostname — the RapidSSL wildcard covers `*.rd.go.th`, never the IP |
| `docker container/.env` `LIVEKIT_API_KEY` | `APIhF8XFnsit3pi` | The self-host pair |
| `docker-compose.yml` agent `environment` | `LIVEKIT_URL: ws://10.223.5.31:7880` | Overrides the env file for the agent only. Plain ws by IP: no DNS, and it sidesteps certificate trust in the Rust WebSocket layer, which ignores `SSL_CERT_FILE` |
| `docker-compose.yml` web `extra_hosts` | `livekit.rd.go.th:10.223.5.31` | The token route calls the LiveKit API server-side, so the WEB container must resolve the name. Whether that host uses RD DNS was never verified; pinning removes the question |

> **`LIVEKIT_API_SECRET` — DONE 2026-09-16 by the user** (it could not be written from here;
> reading credentials is blocked). **Verified live, not by inspection:** a `listRooms()` call
> through `livekit-server-sdk` using `docker container/.env` returned **AUTH OK** against
> `https://livekit.rd.go.th`. The same check had returned `invalid token` beforehand, while
> the file still held the self-host KEY with the Cloud SECRET — a mismatch that answers
> `401 Invalid response status` on every agent connection and looks exactly like a bad key.
>
> **Re-run this check after any credential change** (it needs no browser and no stack):
> ```bash
> docker run --rm --env-file "docker container/.env" --add-host livekit.rd.go.th:10.223.5.31 >   --entrypoint node nongaree-voicebot-web:local -e "const {RoomServiceClient}=require('livekit-server-sdk');> const c=new RoomServiceClient(process.env.LIVEKIT_URL.replace(/^ws/,'http'),process.env.LIVEKIT_API_KEY,process.env.LIVEKIT_API_SECRET);> c.listRooms().then(r=>console.log('AUTH OK',r.length)).catch(e=>console.log('AUTH FAILED',e.message))"
> ```

**Trap that already cost time once: no trailing whitespace on that secret.** A stray newline
made it 45 characters instead of 44 and produced exactly that 401. Check the length before
suspecting the key.

**Prerequisites already satisfied:** Fix 14 (self-host answers 503, not 404, for a missing
room — without it dispatch silently never happens), `rtc.node_ip = 10.223.5.31`, and the
RapidSSL wildcard, verified from this machine with system roots only (`ssl_verify_result=0`).

**Two things to watch after deploying:**
1. **The certificate expires 2026-10-22** and RD renews it on their own schedule. When it
   lapses the browser shows *"การเชื่อมต่อหลุด"* while the server logs look perfectly healthy.
   `openssl s_client -connect 10.223.5.31:443 -servername livekit.rd.go.th </dev/null | openssl x509 -noout -dates`
2. **Rotate the key pair.** It was pasted into a chat transcript. The user chose to ship the
   current pair; rotation is still owed.

**Rollback** is the two backups, or by hand: `LIVEKIT_URL=wss://stt-tts-ad50wayf.livekit.cloud`
plus the Cloud key/secret, and delete the agent override and the `livekit.rd.go.th`
extra_hosts line.

### BLOCKER 2026-09-18 — `livekit.rd.go.th` is NXDOMAIN on RD DNS, so NO browser can join

The RD test team started using the deployed build and **not one of them ever reached a
room**. The agent log tells the whole story, repeated for `TN371636`, `CB388931` and
`NN416573`:

```
Connecting to room: nongaree-CB388931
LiveKit connected in 635ms
Room participants: []          <- the browser is not there
```

`Participant connected` never appears for any user. The agent joins, finds the room empty,
and waits. **Confirmed root cause:** an RD machine opening `https://livekit.rd.go.th/`
gets **`DNS_PROBE_FINISHED_NXDOMAIN`** — RD's internal DNS has no record for that name, so
the browser never even attempts the connection. Not routing, not the certificate, not the
app. This is the DNS question §3f flagged as unverified; it is now answered, the hard way.

> **Why the §3f "PASS" did not catch it:** `scripts/e2e_livekit_turn.py` runs INSIDE the
> agent container and uses its `LIVEKIT_URL` — `ws://10.223.5.31:7880`, plain ws, by IP,
> no DNS and no TLS. Users connect to `wss://livekit.rd.go.th`. The test exercised the
> server-side pipeline perfectly and never touched the one leg that was broken. **Any
> future "end to end" claim must state which URL the client used.**

**What RD has to do** (the app needs no change):
1. Internal DNS A record: `livekit.rd.go.th` → `10.223.5.31` (and `turn.rd.go.th`).
2. Allow user networks to reach `10.223.5.31` on **443/tcp** (signalling) and
   **3478/udp + 50000-60000/udp** (audio). DNS alone can give a connection with no sound.

**Interim workaround for testers** — the same hosts-file entry used on the dev machine:
`10.223.5.31 livekit.rd.go.th` (Administrator editor; a non-elevated one fails silently,
and Defender may revert it). It also tests the ports before RD touches DNS.

**NOT rolled back.** Rollback to Cloud was prepared and declined: these are RD testers, not
real users, and the team wants self-host fixed rather than avoided. The pre-cutover backups
(`*.before-selfhost-cutover-20260916`) still make rollback a one-minute config change.

### Fixes from the first real problem report (2026-09-18, `TN371636`)

The report feature paid for itself on day one — without it nobody would have known the
testers were stuck. One report, three distinct bugs, all fixed in `components/VoiceRoom.tsx`
(backup `*.before-user-report-fixes-20260918`):

1. **A connection failure was reported as a MICROPHONE failure.** The token fetch,
   `room.connect()` and `createLocalAudioTrack()` shared one try/catch whose handler always
   wrote a mic message, so every blocked tester was told to fix their microphone and went
   hunting through browser permissions. The join now tracks a `JoinStage`
   (`token` / `connect` / `mic`): a pre-room failure says *"เชื่อมต่อเซิร์ฟเวอร์เสียงไม่สำเร็จ
   (ไม่ใช่ปัญหาไมโครโฟน)"* and only a real `getUserMedia` rejection talks about the mic.
   **`mic_error` in the problem report now carries the stage** (`connect_failed`,
   `token_failed`) instead of a useless `Error`, so the next report names the broken leg.
2. **Spacebar did nothing in the report box.** The push-to-talk handler exempted only
   `HTMLInputElement`; the box is a `<textarea>`, so every space was swallowed AND fired
   `startTalking()`, which pops "ไมโครโฟนยังไม่พร้อม" when the mic never initialised. Now
   exempts textarea and contentEditable too.
3. **Clicking beside the box discarded a half-written report.** The backdrop closed
   unconditionally; the text survived in state, which is how the reporter noticed. The
   backdrop now ignores clicks once anything is typed — ✕ and ยกเลิก still close it.

Verified: `tsc` clean, ESLint 0 errors / 2 pre-existing warnings.

### Fix: a failed join now retries itself (2026-09-18)

The DNS outage exposed a second problem: once the record appeared, affected machines still
showed a dead error because the browser and OS had cached the NXDOMAIN, and the app gave up
after ONE failed join. The only ways out were a manual retry click or `ipconfig /flushdns`.
**Neither is acceptable for ordinary users** — the user said so plainly, and they were right.

`components/VoiceRoom.tsx` now retries a failed join by itself: `JOIN_RETRY_DELAYS_MS`
(4s, 10s, 20s), tracked in `autoRejoinCountRef`, reset on a successful join and on a manual
retry. Only `token` / `connect` failures retry — a mic rejection is the user's decision and
will not fix itself, so it is reported once. The pending timer is cleared in the effect
cleanup, or it fires after the user has left and reconnects a room they closed.

**Verified in a browser against an unreachable LiveKit:** token requests at 4s, 10s and 20s
(4 in total), the message counts "ครั้งที่ N จาก 3", then it stops with a plain message and
leaves the manual button. `tsc` clean, ESLint 0 errors / 2 pre-existing warnings.

> **Negative DNS caching is why "it works for one person" happened.** `TN371636` resolved
> `livekit.rd.go.th` → `10.223.5.31` correctly once their cache expired (DNS server
> `10.20.100.2`), while `BK317412` — the one tester who worked all along — had simply never
> cached the failure. Windows caches a negative answer ~15 minutes; the resolver caches per
> the zone SOA. So the record now exists; the rest was stale cache.

### DEPLOYED 2026-09-17 — production verified end to end without a browser

rsync'd to `rd30:/home/nectec/nongaree-voicebot` (excluding `local-login/`, `reports/`,
`testporpose/`, `tts_voices/`, `*.before-*` and build artefacts), both images rebuilt,
`docker compose up -d`. Checksums of `docker container/.env`, `.env.sso`,
`docker-compose.yml`, `agent.py`, `graph/text_normalization.py` and
`components/VoiceRoom.tsx` matched the local copy after the sync.

> **Do not run commands on the server from a Claude session.** The user runs them and pastes
> the output back (decided 2026-09-17). Hand over copy-pasteable commands instead.

Verified on the server:
- agent `registered worker ... url: ws://10.223.5.31:7880`, and volumes
  `nongaree-voicebot_report_data` / `_memory_data` exist (first deploy that has them)
- `/login` 200, `/` without a cookie → 307 to `/login`
- the web container resolves `livekit.rd.go.th` → `10.223.5.31`, its own env authenticates
  to the LiveKit API, and it reaches the SSO hosts (`tstws_sso`, `ws_sso`, `securityportal`)
  on 443
- **a full turn through `scripts/e2e_livekit_turn.py`: PASS** — agent joined **5s** after
  dispatch, `route: rag`, 3 citations, panel answer 5s after the question, spoken answer
  delivered, **4227 audio frames with peak amplitude 18169** (real sound, not silence),
  served by the production worker `nongaree-agent`

**That 5s join settles the §3f VPN question:** the 3-minute join seen from the dev machine
was the VPN, not the server.

**`scripts/e2e_livekit_turn.py` is the no-browser, no-SSO test** — it plays a fake user in a
throwaway room (`nongaree-e2etest`, deleted afterwards), dispatches like the token route,
asks a typed question, and reports route, citations, both answers and whether the agent's
audio track carried real sound. Run it inside the agent container, which already has the
SDK and the credentials:

```bash
docker compose exec -T -e PYTHONIOENCODING=utf-8 agent python - < scripts/e2e_livekit_turn.py
docker compose exec -T -e PYTHONIOENCODING=utf-8 agent python - "<question>" < scripts/e2e_livekit_turn.py
```

It prints DISPLAY text, so it cannot show how a number is pronounced — digit reading
happens inside `WavTTS`. It leaves a memory file for user `e2etest` (normal 30-minute TTL).

**Still untestable without someone on the RD network:** a real SSO login, and a user's
browser reaching `wss://livekit.rd.go.th` (RD DNS must hold the record).

### TTS voice changed to `bantita` (deployment config — user approved)

`TTS_VOICE` in `docker container/.env` was `ped`, now **`bantita`** (line 30; backup at
`docker container/.env.before-voice-bantita-20260916`). This is a PROTECTED file and the
change was made on explicit request.

**How voice names are validated:** POST `/audio/speech` on `ptm-tts-1` returns **200** for a
real voice and **HTTP 500** for an unknown one, so a name can be checked in seconds without
touching config. The endpoint exposes no listing route the current key may read.

> **Cloudflare, not the key, blocks voice probing.** `/v1/models`, `/audio/voices` and even
> `/audio/speech` answer **403 `error code: 1010`** to `urllib` — from the HOST *and* from
> inside the container. The same request through `httpx` (what `WavTTS` uses) works. A 403
> here is a client-fingerprint block; do not chase it as an auth problem.

`docker-compose.voice.yml` (new, additive, deletable) overrides `TTS_VOICE` on the local
agent for A/B testing — `LOCAL_TTS_VOICE=<name>` picks the voice. Root `.env` still says
`ped`, which only affects a host-run `python agent.py dev`, not any container.

### Fix 33 — the spoken answer invented facts the panel refused (`graph/nodes.py`)

Asked `อธิบดีกรมสรรพากรคนปัจจุบันชื่ออะไร` the user got a NAME in the voice answer —
**นายอานนท์ ศรีสวัสดิ์**, and a different one, **นายสมชาย ชัยยาพาน**, on my own run — while the
panel refused on the same turn. Two different names for the same question is the signature
of a fabrication, not of stale data.

**Both generators get the SAME context.** `_build_generation_messages()` gates the context
block on `state.get("context")`, not on `include_context`, which only picks a trailing
sentence; same model (`ptm-oss-120b`), same temperature (0.2). The only asymmetry was the
prompt: `AREE_SYSTEM_PROMPT`'s ห้ามเด็ดขาด list was **100% style rules** (think tags, emoji,
markdown, 4 lines, no English) and said nothing about missing data, while the persona above
it says "พูดเหมือนเพื่อนที่เชี่ยวชาญเรื่องภาษี" and "ตอบตรงคำถามก่อน". The shared
`ห้ามเพิ่มข้อเท็จจริงนอกข้อมูลอ้างอิง` line in the message builder was already there and did not
stop it — it is passive, and a chatty persona slides past it.

Both prompts now carry the same two lines, and the spoken prompt also gets a worked refusal
example (it teaches by example, so a rule without one is weak):

- `ห้ามแต่งข้อมูลที่ไม่มีในข้อมูลอ้างอิง โดยเฉพาะ ชื่อบุคคล ตำแหน่ง ตัวเลข อัตรา วันที่ ชื่อหน่วยงาน`
- `ถ้าข้อมูลอ้างอิงไม่มีคำตอบ … ห้ามเดาเด็ดขาด ให้บอกว่ายังไม่มีข้อมูลนี้ แล้วแนะนำให้โทร 1161`

**Naming the noun classes is the whole point** — the generic "don't add facts" was already in
the builder and did not stop a name.

**Measured, old vs new prompts on the SAME retrieved state** (4 questions whose context
cannot answer them, 3 runs each, both generators per run):

| | clean refusal that hands off to 1161 | invented a name |
|---|---|---|
| old prompts | 1/12 | 0/12 |
| new prompts | **12/12** | 0/12 |

The old prompts did not invent on these four, but they leaked the plumbing instead —
"ข้อมูลอ้างอิงที่ให้มานี้ไม่ได้ระบุ…", "กรุณาระบุแหล่งข้อมูลที่ต้องการอ้างอิง" (asking the taxpayer to
supply sources) — and on `อธิบดีกรมสรรพากรคนก่อนหน้านี้` they answered with the CURRENT
director-general's name 2/3 times: grounded in the context, and wrong.

**The cost is real and was measured, not assumed.** Strict grounding turns "correct but
ungrounded" into a refusal. Over 14 everyday questions, 3 now refuse — and in all three the
old prompts had no grounded answer either, so these are **KB gaps, not a prompt regression**:

| question | what changed |
|---|---|
| `ภาษีมูลค่าเพิ่มคิดกี่เปอร์เซ็นต์` | the retrieved 2983 chars contain **no rate** (no `ร้อยละ 7`, no `7%`); the old PANEL answered "7 %" from model knowledge, the new one refuses |
| `ค่าลดหย่อนคู่สมรสเท่าไหร่` | both versions say the allowance exists but not the amount |
| `ขอคืนภาษีกี่วันได้เงิน` | old answered an adjacent question (the 3-year claim window), new refuses |

> **The fix for VAT is a curated answer or a KB chunk — not a weaker rule.** Loosening the
> grounding clause to rescue the VAT rate buys back every fabricated name with it.
> `graph/curated_answers.py` is the project's existing mechanism for exactly this kind of
> fragile, high-traffic fact. **Waiting on the user** for the wording and for whether the 7%
> rate should be stated with its validity window.

**Residual, not fixed:** on `อธิบดีกรมสรรพากรคนก่อนหน้านี้`, 1 of 3 new-prompt runs still had the
PANEL emit a table naming the current director-general while the spoken half refused. The
rule removed the invention; it does not make the two halves agree on every turn.

**Verified:** 13 new checks in `scripts/test_conversation.py` (suite **96 → 109**) asserting
both prompts carry the clause, name all four noun classes, say what to do instead, and that
the spoken prompt keeps a refusal example — a one-sided prompt edit now fails a test instead
of silently diverging. Then the A/B table above, then the 14-question sweep, all against the
local Qdrant with the real LLM. Snapshot: `graph/nodes.py.before-no-fabrication-rule-20260924`.

> **NOT deployed and not browser-tested.** The running agent image still has the old prompts;
> rebuild before any browser verdict means anything.

### KB — the executive roster was wrong, and how the corpus actually retrieves (2026-09-24)

Source: the user's copy of rd.go.th "ผู้บริหารระดับสูง" (ปรับปรุงล่าสุด 21-07-2026), kept at
`scripts/kb/rd_executives_2026-07-21.md`. Applied with `scripts/update_executive_kb.py`.

**The KB named the wrong director-general in two places**, plus five more stale or
misspelled executive entries. Adding the roster alongside them would have been worse than
leaving it: two names in one context block and the model picks.

| chunk | was | now |
|---|---|---|
| `CALLCENTER-98` | อธิบดี = นายปิ่นสาย สุรัสวดี | **นายสมศักดิ์ อนันทวัฒน์** |
| `KC-0208` | อธิบดี = นายปิ่นสาย สุรัสวดี | **นายสมศักดิ์ อนันทวัฒน์** |
| `KC-0266` | รองอธิบดี 3 ท่าน (ภาณุวัฒน์ / สุรยุทธ / กฤดา) | **4 ท่าน**, + นางสาวขวัญรัก สุวรรณรัมภา, กฤดา รักษาการ |
| `KC-0672` | ที่ปรึกษาฯ ธุรกรรมการเงิน = นายพงษ์ศักดิ์ เมธาพิพัฒน์ | **นางสาวสลักจิต พงษ์ศิริจันทร์** |
| `KC-1027` | ที่ปรึกษาด้านพัฒนาฐานภาษี = นายวินิจ วิเศษสุวรรณภูมิ | **นางสาวจิตรา ณีศะนันท์** |
| `KC-0966` | ...ประสงค์สุกา**นญ**จน์ (misspelled) | ...ประสงค์สุกา**ญ**จน์ |
| `KC-0961` | ภิญญู กำเนิดหล่ม, **รักษาการ** | in post |

`KC-0420` (ปิ่นสาย = รองปลัดกระทรวงการคลัง) is NOT contradicted by the roster and was left
alone. Plus one new record, `KC-EXEC-ROSTER`, as **5 points** carrying the full roster with
phone numbers.

> **The seven corrections are payload-only — the vectors are untouched, deliberately.**
> `CALLCENTER-98` is what answers "อธิบดีกรมสรรพากรชื่ออะไร" today (cosine **0.935** against
> that query) and that usefulness lives entirely in its vector. Re-embedding it on the
> answer text would destroy it.

**The finding that shaped all of this — dense search returns CALLCENTER-\* points and
essentially nothing else.** Top-8 dense hits for three ordinary questions were 8/8
`CALLCENTER-*` every time. Measured on an original KC point: cos(stored vector, fresh
embedding of its own `text_clean`) = **0.2463**, and against the query that should match it,
**0.18** — noise. The ~1000 original KC-* vectors are in a **different embedding space**
than today's `vllm-BAAI/bge-m3` queries (different model, or a prefix convention, at
ingest time). The CALLCENTER points, added later by `scripts/upsert_callcenter_rag.py`
which embeds the **question**, score 0.93.

Consequences, all of them load-bearing for future KB work:
- **A new chunk must be embedded from a QUESTION, not from its answer text**, or it is
  invisible to dense search. This is why the roster is 5 points, one per phrasing.
- The KC-* half of the corpus is reachable only through the **lexical** side of the hybrid
  search. That is not a bug to fix casually — re-embedding 1000 points changes what wins
  for every existing question and would invalidate the multiturn baseline.
- It also explains the VAT gap from Fix 33: `CALLCENTER-66` "ภาษีมูลค่าเพิ่มอัตรา 7% ใช้กับ
  กรณีใด" exists and scores **0.7359** — just under the 0.75 gate — so the rate never reaches
  the context. A question-phrasing point ("ภาษีมูลค่าเพิ่มคิดกี่เปอร์เซ็นต์") would fix it the
  same way the roster was fixed. **Not done — needs the user's ruling on the rate's
  validity window.**

**Phone numbers must be written DASHED in a chunk** (`02-272-8261`, not the source page's
`0 2272 8261`): `normalize_phone_numbers_for_tts()` keys on that shape, and the spaced form
is spoken as amounts. A follow-on fix went into `graph/text_normalization.py` — the
generator writes these back with a **non-breaking hyphen** (U+2011), which missed the dashed
rule and was read as "ศูนย์สอง-สองร้อยเจ็ดสิบสอง-แปดพันสองร้อยหกสิบเอ็ด". Dashes **between
digits** are now normalised to ASCII first. 2 new checks (suite **109 → 111**).

**Verified on local:** 6/6 executive questions correct, no stale name anywhere in either
answer, e.g. "อธิบดีกรมสรรพากรคนปัจจุบันชื่ออะไร" → นายสมศักดิ์ อนันทวัฒน์ with 02-272-8261 in
both halves. Local collection 1311 → **1316** points.

**Production runbook** (the user runs these on the server; the script is dry-run by
default and prints every before/after):
```bash
docker compose exec -T -e PYTHONIOENCODING=utf-8 agent python - < scripts/update_executive_kb.py         # look
docker compose exec -T -e PYTHONIOENCODING=utf-8 agent python - --yes < scripts/update_executive_kb.py   # apply
docker compose restart agent    # graph/retriever.py caches every payload once per process
```
The script is idempotent: a second run reports "already correct" and the roster ids are
`uuid5`, so they update rather than duplicate.

> **A fresh install still ships the OLD names.** `restore-qdrant-snapshot.sh` skips the
> restore when the collection exists, so an existing volume keeps these corrections — but
> `docker container/qdrant/snapshots/thai_tax_kb.snapshot.tar.gz` is still the 1311-point
> snapshot with นายปิ่นสาย in it. Regenerate it before the next company handoff.

### Probe traps found the hard way (again)

- **A fixed `--since` window matches the PREVIOUS run's identical log line.** A probe waiting
  for `FAULT_INJECTION` saw the last run's error and captured the page before this turn had
  even failed. Scope every log check to the time the question was sent.
- **Asking while Aree is greeting sends nothing.** The frontend queues it client-side (button
  reads เข้าคิว) and the agent never receives it. Wait out the greeting, and assert
  `Text input received` before trusting any browser verdict.

---

## 3g. Work completed — session 6 (2026-09-25)

Changes: `graph/nodes.py`, `scripts/test_conversation.py`, `CLAUDE.md`, `graph/CLAUDE.md`,
`scripts/mint-local-session.mjs` (local only). Snapshots `*.before-search-first-20260925`,
`HANDOFF.md.before-fix34-20260925`. **No SSO, auth, port, or deployment file was modified.**

**DEPLOYED 2026-09-25 (agent only).** `graph/nodes.py` + `scripts/test_conversation.py` copied
by scp (server backups `*.before-search-first-20260925`), `docker compose build agent && up -d
agent`; web untouched. Verified read-only: the container's `/app/graph/nodes.py` md5
`bf6d572f…` == local, search-first present, timeout 4.0. User ran `e2e_livekit_turn.py "อธิบดี"`:
**PASS**, `route: rag`, 3 citations, นายสมศักดิ์ อนันทวัฒน์ in both halves, real audio. Note the
panel also listed กรมบัญชีกลาง's director-general (นางแพตริเซีย มงคลวนิช) from an existing KB
chunk — "อธิบดี" alone is ambiguous; not verified as current.

### Server state verified (read-only — the user now allows view-only commands on rd30)

- Server source == local checkout (56 files by checksum) except `app/api/admin/reports/route.ts`,
  **missing on the server** (harmless while `REPORT_ADMIN_TOKEN` is unset). Both images were
  built 2026-09-24 11:11 UTC, after the newest source file; the running agent's 11 `.py`
  files match the server disk. Fix 33 IS deployed.
- The executive-KB update HAS been applied on the server: 1316 points, all 7 corrections and
  all 5 roster points present, no stale name in any answer.
- Tester complaints "Sign Out → SSO login page" / "sign in via RD SSO Portal shows the old
  SSO screen" are **not this app**: neither string exists in any version of the code nor in
  the running `.next` bundle. **Confirmed later the same day: they are the `docrd-deploy` app**
  (document chat, rd30 port 8081, `/home/nectec/docrd-deploy`). Its Sign Out
  (`frontend/components/KnowledgeView.tsx:698`) only removes the token and redirects to
  `/login` — no SSO logout call — and its "Sign in via RD SSO Portal" button
  (`Login.tsx:224`) is a plain link to securityportal.rd.go.th, whose session is still alive.
  Its frontend container has run unchanged for 3 months. Not our code — for its owner.

### Fix 34 — search-first on a keyword miss (`graph/nodes.py`)

**The problem, measured on the server** (44 questions: greetings, RD general, contact,
executives as full / keyword / short / misspelt, tax controls, off-topic guards): the
keyword router refused anything without one of its keywords **without searching**. "อธิบดี",
"รองอธิบดี", "สายด่วน", "เวลาทำการ", "สมศักดิ์ อนันทวัฒน์" were all refused while their answers
sat in the KB. 18/44 answered.

**Three options were measured side by side in one read-only process on the server:**

| mode | answered | off-topic leaks | invented facts | cost on keyword misses |
|---|---|---|---|---|
| A current | 18/44 | 0/8 | 0 | 0 |
| B `ROUTER_USE_LLM=true` | 21/44 real (25 scored) | 0/8 | **4** | +652 ms avg |
| C search-first | 24/44 | 0/8 | 0 | +438 ms avg |

**B is unsafe — do not turn the LLM router on.** It sends RD-general questions to `direct`,
which generates with NO context: it invented a head office at "99/9 ถนนรามคำแหง" (real: 90
ซอยพหลโยธิน 7), a call-centre number "02-123-4567", "1161 open 24 hours", and answered
"อธิบดี" with a dictionary definition. The 8B router itself returned valid JSON every time.

**C is implemented:**
- `_should_search_before_refusing()` + a branch in `parallel_node`: still `out_of_scope`
  after the keyword rescue and the follow-up classifier, and not a provider
  recommendation → `retrieve_node` with **`messages=[]`**. Anything past the score gate →
  `rag` with citations; nothing → the soft `out_of_scope` wording (never `NO_SOURCE_ANSWER`,
  or the weather gets the staff-handoff table).
- `messages=[]` is load-bearing: with history, cascade candidates 4/5 append the opener /
  previous answer, and a mid-conversation off-topic question could ride that tax vocabulary
  past the gate. Real follow-ups never reach this branch — the keyword rescue or the
  classifier already routed them.
- `OUT_OF_SCOPE_SEARCH` (default `true`, in code — no `.env` change) is the rollback switch.

**Keyword bugs found by the same run, fixed:**
- `"ชื่ออะไร"` was a bare-substring DIRECT keyword → "อธิบอดีชื่ออะไร" was answered "อารี" (Aree's
  own name) and "อธิบดีกรมสรรพกรชื่ออะไร" went to `direct` with no context. Removed; asking
  Aree her name is now matched whole by `_SELF_NAME_PATTERN`.
- Greeting typos `หวัดดี`, `สวสดี` added to `_FAST_DIRECT_KEYWORDS`.
- Misspellings `สรรพกร`, `ลดหยอน` added to `_FAST_RAG_KEYWORDS`.

**Verified:**
- Offline suite **111 → 121**, all pass (search-first routing with retrieval faked: hit →
  rag, miss → soft out_of_scope, own-words-only mid-conversation, provider recommendation
  never searches, a keyword hit still retrieves WITH history, rollback switch; plus the
  keyword fixes). Run inside the agent image — there is no `.venv` in this checkout.
- Multiturn harness **56/57 both with the switch ON and OFF** (`reports/multiturn/
  s12-search-first-{on,off}.json`). The one failure is identical in both and unrelated —
  see the classifier-latency finding below. `scope_bounce`, `unanswerable_guard`,
  `formcode_opener_guard` all still pass.
- The 44-question set on the local stack with the new code: 23/44 (was 18/44 on the server),
  **8/8 off-topic still refused**. Every routing change was an improvement; the remaining
  misses are KB gaps or generator wording (see below). Transcripts in the session
  scratchpad (`routing_compare*.out`).

### FINDING — the follow-up classifier now times out on the harness (NOT fixed)

`unlisted_followups` t5 "ใครต้องใช้บ้าง" fails **4/4 runs today, with and without Fix 34**:
`follow-up classifier timed out after 2.5s`. Measured directly with a 30s timeout it answers
correctly (1) but takes **1.5–2.85 s** — the first call 2.85 s. It passed in the s11 baseline,
so the LLM endpoint is slower than when the 2.5 s timeout was chosen. Production uses the
same endpoint, so markerless follow-ups may be silently falling back to keywords there too.
**Resolved same day (user's call): the code default is now 4.0 s** (`graph/nodes.py`, no
`.env` change — the variable is set nowhere, so the default is what production uses).
`FOLLOWUP_CLASSIFIER_TIMEOUT_S` still overrides it. Re-run with search-first + 4 s:
**57/57, zero timeouts** (`reports/multiturn/s12-search-first-timeout4.json`, the new
reference); offline suite 121/121.

### KB gaps the 44-question run exposed (content work, not routing)

Not in the KB, so no routing can answer them: RD's duties, opening hours by that phrasing
("สรรพากรเปิดกี่โมง"), the head-office address (the only chunk has map coordinates), how to
book e-Appointment, a general "how do I contact staff", "หัวหน้ากรมสรรพากร", and name-only
questions ("นายกฤดา…เป็นใคร"). "สายด่วน" retrieves the e-Withholding hotline rather than 1161.
Fix = question-phrasing points, as `scripts/update_executive_kb.py` does — needs the user to
confirm the facts.

### Self-hosted RD speech (STT/TTS) — tried in production, ROLLED BACK the same day

Servers on rd30 (another team's `pathumma-speech` images, on the A100s):
`STT_BASE_URL=http://10.223.5.30:5173/v1` (`ptm-asr-1`), `TTS_BASE_URL=http://10.223.5.30:19100/v1`
(`ptm-tts-1`), no API key (`none`). Measured: TTS returns 24 kHz mono s16 PCM (what WavTTS
wants) and **requires `voice`** (422 without; `bantita` works); STT transcribed TTS output
exactly in 0.1–0.5 s. **Neither serves `GET /v1/models` (404).**

- **`agent.py` STT probe fixed:** `_build_stt_plugin()` used `raise_for_status()` on
  `GET /models`, so the 404 silently switched server-side STT off. Now only 401/403/5xx count
  as failure. Harmless with tokenmind. The running prod IMAGE has this fix; after the rollback
  the server's `agent.py` ON DISK is the old one (`4e945eec…`) — a rebuild reverts it.
- **`docker-compose.speech.yml`** (additive, delete to revert) points the LOCAL agent at these
  servers. Verified locally with `scripts/e2e_voice_turn.py`: exact transcription, `route: rag`.
- Deployed to prod 13:44 Thai (06:44 UTC), e2e voice PASS. **Rolled back at 14:19** on the
  user's call, after **rd30's disk hit 100%**: the pathumma-speech team built ~48 GB of images
  + ~28 GB build cache that day. A `cp` during the rollback truncated `agent.py` to 0 bytes;
  restored with `mv` from the backup (rename needs no free space). `docker image prune -f`
  freed our old untagged images → 8.9 GB free. Other teams' Postgres DBs were at risk at 0 B.

**Trap — local agent-name collision.** With the repo shared, a co-worker's local stack also
registers `nongaree-agent-local`; a local e2e test was answered by THEIR worker. Start the
stack with a personal `LOCAL_AGENT_NAME` and confirm your container logged the `job_id`.

### Real users on 2026-09-25 — what they hit

Two users (TN371636 — its questions expired with the 30-min memory; SK194983). SK194983's
stored conversation shows four problems, **none fixed yet**:
1. **Spoken numbers:** "เงินเดือน**สามหมื่น**บาท ต้องเสียภาษีไหม" (the STT writes numbers as words)
   → no-source refusal, while "30,000" gets the calculator. Every voice user who says an
   amount hits this. Fix: Thai number words → digits before routing.
2. "บริจาคได้สูงสุดกี่บาท" asked twice → refused (KB lacks the limit). User then wrote
   "มันไม่มี… มันไม่รู้เรื่อง".
3. "ถ้าลืมยื่นภาษีจะโดนปรับไหม" answered with a ≤7-day 100 / >7-day 200 บาท scale — possibly
   the withholding-form scale, not ภ.ง.ด.90/91. **Unverified — needs an RD tax expert.**
4. The stored **summary contains a leaked `<think>` block** from the 8B summariser, which is
   then fed back into prompts. Fix: strip think tags in `summarize_history`.

The agent log before 14:19 was lost when the container was recreated — `docker compose
logs` covers the current container only. The web log (not recreated) still lists sessions.

---

## 4. Verification status — READ THIS

| Check | Status |
|---|---|
| `next build` (Docker builder stage) | ✅ passes |
| `tsc --noEmit` | ✅ clean |
| `eslint` | ✅ 0 errors, 2 pre-existing warnings |
| `python -m py_compile agent.py` | ✅ clean |
| `python -m py_compile agent.py` (session 2 fixes) | ✅ clean |
| `_detail_answer_if_delivered` unit check, 7 cases | ✅ all pass (run in-container) |
| Fix 3 (answer retention) in a real browser | ✅ verified — frontend-only, so unaffected by the dispatch collision |
| Fix 4 Defect A against the live Qdrant index | ✅ verified offline **and** end to end — agent log shows `widened follow-up query -> แล้วถ้ามีลูก 3 คนล่ะ ลดหย่อนบุตรได้เท่าไหร่` and the answer computed 3 children correctly |
| Fix 4 Defect B (memory on interrupted turns) | ⚠️ code review only — control-flow change, not exercised |
| **Fix 1** symptom (apology replacing a good answer) | ✅ verified: agent run with `TTS_BASE_URL=http://127.0.0.1:9/v1`, log shows `ERROR TTS producer error`, panel still rendered the full table, **zero** apology messages sent |
| **Fix 1** guard `_detail_answer_if_delivered()` itself | ⚠️ unit-tested (7 branches) but **integration path never exercised**. In that TTS test the outer handler (`Failed to process text input and speak`) ran **0 times** — `producer()` has its own try/except that swallowed the error and pushed `None`, so the fallback never fired. After Fix 8 the guard is defense-in-depth: the original trigger (say() on a dead session) is prevented by the job shutting down, and `_say_if_running()` swallows that RuntimeError. Reaching the outer handler now needs an *unexpected* consumer-loop exception, which would require fault-injection code to stage. |
| Fix 7 agent-name split | ✅ verified — worker registers as `nongaree-agent-local`, local questions now reliably served locally (citations appear) |
| Fix 8 rejoin after reload | ✅ verified — reload then ask, full answer returned; log shows `ending job so a rejoin gets a fresh session` |
| Fix 9 follow-up routing | ✅ verified end to end |
| Fix 10 three-way separation (rag / no-source / fallthrough) | ✅ verified in-container against the live index, all three cases |
| Fix 10 no-source panel render | ⚠️ verified in a browser **before** the copy was tightened; the final wording is verified by string inspection only |
| Fix 11 report button + dialog, both no-turn and with-turn | ✅ verified in a browser, payload inspected on disk |
| Fix 11 admin API (summary / json / csv / files / rotate) + token gate | ✅ verified by curl |
| Fix 5 retry on a **real** dropped connection | ✅ verified — agent rebuild dropped the room, banner appeared, retry button reconnected |
| Fix 5 retry button / Thai errors / reconnect wiring | ✅ verified in a browser |
| Fix 6 citations end to end (retriever → panel) | ✅ verified in a browser |
| Fix 5 against a *real* device failure (mic busy, no device) | ❌ not possible in the browser pane — it blocks mic access outright |
| **Real browser click-through** | ⚠️ **partially done — see below** |
| **Fix 16 click-through (follow-up typed WHILE Aree speaks)** | ✅ **VERIFIED 2026-09-16** (§3f) — the item owed since §3e. Answered with context, `route: "rag"`, 3 citations; captured in problem report `277fea3f` |
| Fix 1 guard (apology must not clobber a delivered panel answer) | ✅ **VERIFIED 2026-09-16** (§3f Fix 30) by fault injection — the integration path this table previously listed as never exercised |
| Cause 1 of "ขอโทษ ระบบใช้เวลานาน" (dead `AgentSession`) | ✅ settled — `_say_if_running()` prevents the raise, and the error path itself is now verified (§3f Fix 30) |
| Phone numbers spoken as digits | ✅ verified: offline tests, in-container, and heard in a browser (§3f Fix 31) |
| Mic button stays circular at every viewport | ✅ measured at 10 viewport shapes + confirmed by the user (§3f Fix 32) |
| Self-hosted LiveKit driving the local stack end to end | ✅ 2026-09-16 (§3f) — agent registered on `ws://10.223.5.31:7880`, question answered, audio heard |

Session 2 did click through the local stack (§6) in a browser. **Verified working:**

- No start screen; login lands straight in the app
- Browser title + favicon
- Hold-to-talk caption กดค้างไว้เพื่อพูด and the Spacebar hint line; it does change with state
- The AI disclaimer bar
- The Thai-only detail panel after the translation deletion — full Markdown table renders
- The typed-question queue (button flips to เข้าคิว while Aree is answering)
- Enter submits the typed question. **There is no bug here** — an earlier claim that Enter
  did nothing was a browser-automation artifact (the key was sent as `Return`, not
  `Enter`). `onKeyDown` at `components/VoiceRoom.tsx:2501` is gated on
  `status === 'connected'`, the *same* condition as the ส่ง button's `textControlReady`.

**Still unverified:**

- ~~The logout LiveKit-teardown fix~~ **VERIFIED session 3** (browser, local stack). Agent log shows `closing agent session due to participant disconnect ... reason: "CLIENT_INITIATED"` ~9s after the click, then `session closed` and `process exiting`. CLIENT_INITIATED is the tell: the client actively disconnected the room, which is what `handleLogout`'s `room.disconnect()` does. The original bug would have shown no disconnect at all.
- Voice / mic path — the in-app browser pane blocks microphone access entirely
- Audio unlock after the **SSO** redirect (local stack bypasses SSO)
- **The session-2 `agent.py` fixes end to end.** The guard logic is unit-tested on every
  branch and the happy path is unregressed, but the production failure (a stopped
  `AgentSession`) was never re-staged. Blocked by the agent-dispatch collision in §2:
  three consecutive test turns were served by the *other* worker, and one test with the
  local agent **stopped entirely** still returned an agent answer — proof the job went
  elsewhere. Trustworthy local verification needs a window where the only registered
  `nongaree-agent` runs the fixed code.

### Known pre-existing issues (not introduced last session, not fixed)

- 2 `react-hooks/exhaustive-deps` warnings about `startResponseTimeout` (user said leave
  them).
- `npm ci` reports **4 high-severity dependency vulnerabilities**. Dependency bumps are a
  deploy-side decision — ask before touching.
- `app/api/login/route.ts` (legacy password login with a hardcoded `USERS` map) still
  exists but is unreachable — `/login` renders an SSO-only notice.
- `<html lang="en">` in `app/layout.tsx` while the content is Thai.

---

## 5. How to build / verify without node_modules

Build the Dockerfile's `builder` stage — it runs `npm ci && npm run build`:

```bash
docker build -f "docker container/Dockerfile" --target builder -t nongaree-verify:tmp .
```

**Do not run `docker compose build web`** — that overwrites the
`nongaree-voicebot-web:latest` tag the deployment uses. Use a throwaway tag.

Next.js 16 does **not** run ESLint during `next build`. Lint separately (the `builder`
stage prunes devDeps, so use the `deps` stage):

```bash
docker build -f "docker container/Dockerfile" --target deps -t nongaree-deps:tmp .
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "//e/Projects/RD/rd-nongaree/nongaree-voicebot:/repo:ro" -w /app nongaree-deps:tmp \
  sh -c "cp -r /repo/app /repo/components /repo/lib /repo/proxy.ts /repo/eslint.config.mjs \
         /repo/tsconfig.json /repo/next.config.ts /app/ && npx tsc --noEmit; npx eslint"
```

Remove the temp images afterwards.

---

## 6. Local demo stack (SSO bypassed)

The user has **no SSO access locally**, so a local-only stack was added. **Both files are
new; nothing existing was modified.**

- `docker-compose.local.yml` — qdrant + qdrant-restore + web + agent + `local-login`.
  Does **not** load `.env.sso`, drops the RD internal `extra_hosts`, and uses image tags
  `:local` with project name `nongaree-local` so it cannot collide with deployment
  containers, volumes, or tags.
- `scripts/mint-local-session.mjs` — mints a valid session cookie and writes
  `local-login/index.html` (gitignored).

**The auth gate is NOT disabled.** `proxy.ts` still validates every request. The script
mirrors `lib/auth/session.ts` (`base64url(payload).base64url(HMAC-SHA256)`) and signs with
the throwaway `SSO_SESSION_SECRET=local-demo-secret-not-for-production` pinned in the
local compose — **so the cookie is worthless against production.**

```bash
node scripts/mint-local-session.mjs
docker compose -p nongaree-local -f docker-compose.local.yml up --build -d
# then open http://localhost:3001 and click the button
docker compose -p nongaree-local -f docker-compose.local.yml down -v   # teardown
```

| Service | Port (defaults; see §2 — reserved ranges move) |
|---|---|
| `local-login` (one-click sign-in) | 3001 — **run as 4301 since 2026-09-01** |
| `web` | 3000 — **run as 4300 since 2026-09-01** |
| `qdrant` | 6333 (not 8102 — Windows reserved range) |
| `agent` | none (outbound to LiveKit cloud) |

Sanity checks: `GET :3000/` with no cookie → 307 to `/login`; with the cookie → 200.
STT/LLM/TTS live at `tokenmind.9meo.uk` and LiveKit is cloud-hosted, so **voice needs
internet**. The logout button works locally — the SOAP call to RD fails but is caught,
the cookie clears, and the tab closes.

---

## 7. Supervisor feedback deck — status

The user is working through a feedback deck, pasting screenshots into chat.

| # | Item | Status |
|---|---|---|
| 5 | Session too short; don't redirect after logout | ✅ done (30 min + close window) |
| 7 | Title should be "ระบบน้องอารี AI Voicebot" | ✅ done (+ matching favicon) |
| — | การตอบคำถามบางครั้งถูกต้อง แต่ระบบแสดง "ขอโทษ ระบบใช้เวลานาน..." แต่แสดงคำตอบในประวัติการถาม | ✅ **DONE and verified 2026-09-16 (§3f Fix 30).** Both causes closed: cause 2 (`retriever.py` NameError on every form code, §3c Fix 12 — the likely bulk of real reports) and cause 1 (dead `AgentSession`, §3b, now unreachable via `_say_if_running`). The guard itself was finally exercised end to end by fault injection, which exposed a REMAINING half: the apology was still spoken and still stored as the spoken half of the turn, so ประวัติการถาม showed it beside the correct answer. Now split into `NO_ANSWER_FALLBACK` (nothing was produced) and `VOICE_FAILED_PANEL_OK` (panel answer is fine, only the voice broke) |
| — | ข้อความคำตอบหายเร็วเกินไป | ✅ done (§3b Fix 3) — browser-verified |
| — | ถามต่อเนื่องไม่ได้ | ✅ **DONE — the owed click-through was completed 2026-09-16 (§3f).** §3b Fix 4/9 → §3c Stage 6a/6b → §3e Fix 16/17/19 + Fixes 21–23 → verified in a browser by typing `แล้วถ้ามีลูก 2 คนล่ะ` WHILE Aree was still speaking: answered with the previous turn's figures, `route: "rag"`, 3 citations. Evidence preserved in problem report `277fea3f`. Harness 57/57, offline suite 96/96 |
| — | ระบบค้างและ error บ่อย เช่น การเชื่อมต่อไมค์ | ✅ done (§3b Fix 5) — wiring browser-verified |
| — | อยากได้ reference ของคำตอบ + ช่องทางติดต่อเจ้าหน้าที่ | ✅ done — citations (§3b Fix 6) + no-source staff handoff (§3b Fix 10) |
| — | ปุ่มแจ้งปัญหาทันทีตอนเจอปัญหา | ✅ done (§3b Fix 11) — separate from แบบประเมิน, always available |
| others | not yet shown | ⏳ expect more screenshots |

Expect further items to arrive as images. Ask which item is meant if it is ambiguous.

---

## 8. Suggested first moves in a new session

**SUPERSEDED (below) — this paragraph described 2026-09-09 state; kept for history.**
~~State of the local stack as of 2026-09-09 ~10:45: running against self-hosted LiveKit via
docker-compose.selfhost.yml. Read §3e first, then §3c. The one thing owed on §3e: a browser
click-through of Fix 16.~~

**Current, as of 2026-09-11:** local stack runs against LiveKit **Cloud** (the selfhost
override from §3d was a test-only detour; production was never switched). §3e now runs
through **Fix 24** — read it in full, it is the most recent work and by far the largest
section. The browser regression pass late in §3e found and fixed three separate UI-freeze
causes (Fixes 21–23) plus one topic-drift leak (Fix 24); harness is **57/57**
(`reports/multiturn/s11-scenario-fixes-final.json` — the current reference; s10 and earlier
are superseded), offline suite **96/96** (`scripts/test_conversation.py`, after §3f Fix 31). The browser test scripts (`regression_pass.py`,
`repro_*.py`, `lkctl.py`) live in the session scratchpad, not the repo — disposable; the
durable artefacts are `scripts/multiturn_benchmark.py`, `scripts/test_conversation.py`,
`scripts/threshold_sweep.py`, and the reports.

**Still owed, requiring a decision or a human, not more coding:**
1. ~~The Fix-16-specific click-through~~ **DONE 2026-09-16 (§3f).** Typed
   `แล้วถ้ามีลูก 2 คนล่ะ` while Aree was mid-sentence; answered with the previous turn's
   salary carried over, `route: "rag"`, 3 citations. Evidence is preserved in problem report
   `277fea3f` on the `report_data` volume. **Nothing browser-side is owed before shipping.**
2. ~~The OPEN reconnect-race item~~ **FIXED as Fix 25 (2026-09-14)** — an agent-presence
   watchdog re-requests a dispatch when the room has had no agent for 20s.
3. **Multi-turn defect #7 FIXED as Fix 26 (2026-09-14)** — a question asked during
   background summarisation was being lost. Remaining open defects (#3, #4, #6, #8) have
   measured, researched fixes recorded in §3e but are deliberately deferred past the release.
4. **Multi-turn defect #6 addressed as Fix 27 (2026-09-14)** — an LLM yes/no follow-up
   classifier, called only when keyword routing would answer "outside our scope" mid-
   conversation. Rollback with `FOLLOWUP_CLASSIFIER=false`. Open defects now: #3, #4 (low).
5. **Supervisor scenario test run (2026-09-14)** — found and fixed two code bugs (Fix 28:
   the emotion shortcut swallowing tax questions containing บุคคลธรรมดา; Fix 29: canned
   answers misreading yearly salary and taking multi-part questions). Answer-quality errors
   outside personal income tax come from the LLM / corpus and were deliberately left, per the
   user. **Open question for RD:** the home-loan canned answer says 90,000 (commonly 100,000).
   ~~Only the Fix-16 click-through above remains owed before shipping.~~ **DONE 2026-09-16 (§3f) — nothing browser-side is owed before shipping.** What remains is deployment-side and decisions: the self-host cutover (§3d + §3f), the home-loan 90,000 figure needing RD confirmation, and the OPEN chunking-bypass item in §3f.

0. **Self-hosted LiveKit now works end to end (§3d)** — text and audio, verified in a
   browser. Production still runs on LiveKit Cloud. Cutover needs three things: a
   browser-trusted certificate from RD PKI, the `rtc.node_ip` decision (check from an
   OFFICE machine whether users reach 167.94.112.79 or 10.223.5.31), and `LIVEKIT_URL`
   + keys switched in `docker container/.env`. **Fix 14 is a prerequisite** — without it
   dispatch silently never happens on self-host.
   Also: regenerate the API key/secret in `livekit.yaml`; the pair used for testing was
   pasted into a chat transcript.
1. ~~Deploy Fix 12 (`graph/retriever.py`) on its own~~ **DO NOT — see §1.** Deployment is a
   single event when the work is finished; the user cannot ship partial work repeatedly.
   Fix 12 still matters (a one-token correction that stops every tax form-code question
   crashing, and a live cause of the "ขอโทษ ระบบใช้เวลานาน" reports) — it just rides out
   with everything else. Treat it as **already landed, awaiting the one release**, and put
   effort into finishing and verifying the rest instead of sequencing shipments.
2. ~~Stage 6a — anchor selection~~ **DONE** (§3c). Incorrect abstains 8 → 4.
   **Do NOT use `s6a-gated.json` as a baseline — §3c's table marks it CORRUPT** (a
   `--only salary_chain` partial that overwrote the full run). The current reference is
   `s11-scenario-fixes-final.json` (57/57):
   ```bash
   python scripts/multiturn_benchmark.py --stage s12 \
     --baseline reports/multiturn/s11-scenario-fixes-final.json
   ```
   Still open from that work, in rough value order:
   - ~~`markerless_coref` t1 routes `out_of_scope`~~ **DONE** — Stage 6b (§3c).
   - ~~`salary_chain` t2/t3 and `scope_bounce` t2 have never retrieved — possibly a KB
     gap~~ **ANSWERED (§3e): not a KB gap.** They score 0.7223-0.7335, just under the
     gate. Still failing on purpose.
   - ~~`RAG_SCORE_THRESHOLD = 0.75` is untested~~ **TESTED (§3e) — do NOT lower it.**
     Off-topic questions interleave with those three turns and two score *higher*. Run
     `python scripts/threshold_sweep.py` before reopening this. Fixing those turns needs
     an on-topic check separate from the score gate, not a threshold change.
   - ~~**NEW: `VAT คิดกี่เปอร์เซ็นต์` retrieves nothing** (0.6811)~~ **FIXED — §3e Fix 18.**
     English tax terms are now REPLACED with Thai (`_ENGLISH_TERM_ALIASES`), which moved it
     to 0.7721 / 2983 chars. Adding Thai alongside the English was measured and did not work.
3. ~~**Stage 1 — persist memory per user.**~~ **LANDED (§3c).** `graph/conversation_store.py`,
   one JSON per user under `MEMORY_DIR`, keyed on the room name, atomic write, 30-minute idle
   TTL, and `app/api/session/memory/route.ts` clears it on logout. Both protected-file gates
   (the `memory_data` volume on `web` and `agent`) were approved and are in place.
4. ~~Fix the LiveKit dispatch race~~ **DONE** — Fix 13 (§3c), verified by dispatch-ID
   correlation. Browser verification is no longer blocked.
5. ~~Browser checks owed~~ **DONE session 3**, all on the local stack: Fix 12 form-code
   question answers with a citation and no crash fallback; logout teardown shows a
   `CLIENT_INITIATED` disconnect; dispatch fix confirmed.
   **These never needed RD VPN** — `docker-compose.local.yml` bypasses SSO by design;
   an earlier note in this file claiming otherwise was wrong. The ONLY genuinely
   SSO-gated check left is **audio unlock after a real SSO redirect**, and that needs a
   human clicking through the RD portal, so it cannot be automated.
   Measured 2026-09-09: the OpenVPN profile in use routes `10.223.5-6.0/24` and
   `172.30.52-54.0/24`, but SSO lives on `10.29.1.x` (prod) and `10.20.29.x` (UAT) —
   **not routed**, all four hosts fail at TCP connect. If SSO access is needed, it is a
   different VPN profile.
6. Ask the user for the next supervisor feedback item.

Do **not** re-run `/init`, re-derive the architecture, or re-review last session's diff
unless asked — `CLAUDE.md` already documents the architecture.
