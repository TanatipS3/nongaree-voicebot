# app/api/ — API routes and problem reporting

Loaded when working under `app/api/`. Moved out of the root `CLAUDE.md` on 2026-09-14 (snapshot: `CLAUDE.md.before-doctor-trim-2026-09-14`). Auth (`proxy.ts`, `lib/sso/`, `app/api/auth/`) is off-limits without asking — see `HANDOFF.md` §1.

## API routes

- `app/api/livekit/token/route.ts` — far more than a token mint. It derives the room name **server-side** from the session (`nongaree-${safeUser}`, sanitized) so a client can't request another user's room, optionally resets the room (`LIVEKIT_RESET_ROOM_ON_TOKEN=true` + `?reset=true`), then **explicitly dispatches** the agent: serialized per-room by a `dispatchLocks` promise map, clearing stale dispatches and removing duplicate agent participants, because dev refresh / StrictMode double-fetches used to stack multiple bots in one room. Also fire-and-forget-logs an SSO `Load` transaction.
- `app/api/report/route.ts`, `app/api/admin/reports/route.ts` — see below.
- `app/api/session/memory/route.ts` — session-gated `DELETE`, clears the caller's stored conversation memory. Called from `handleLogout` **before** the SSO logout, while the cookie is still valid. A separate route on purpose: the alternative was editing `app/api/auth/sso/logout/route.ts`, which `HANDOFF.md` §1 lists as off-limits. Identity comes from the cookie and there is no user parameter, so one user cannot clear another's.
- `app/api/login/route.ts`, `app/api/logout/route.ts`, `app/api/auth/sso/*` — see Authentication in the root `CLAUDE.md`.

## Problem reporting

A user-facing "report a problem" flow, deliberately backed by files rather than a database (a DB service would mean another image in the prebuilt-release handoff):

- `app/api/report/route.ts` — POST, session-gated. Identity comes from the session cookie, **never** the body. Appends one sanitized JSON line to `${REPORT_DIR}/reports-YYYY-MM.jsonl`. Captures the reported turn, its `sources`, the `chat_sources` diagnostics, and client state (mic error *name*, connection status, viewport). `schema_version` is there to make a later lift into Postgres mechanical.
- `app/api/admin/reports/route.ts` — GET (`?format=summary|json|csv|files`, `since`/`until`) and POST `?action=rotate`. There is **no admin role in the auth model**, so this route carries its own gate: a shared secret in `REPORT_ADMIN_TOKEN`, compared with `timingSafeEqual`. Unset ⇒ 404 (so it doesn't advertise itself). It is exact-match allowlisted in `proxy.ts` so a cookie-less `curl` can reach it.
- `scripts/reports.mjs` — the same read/rotate operations as a CLI, meant to be run against the `report_data` named volume on the server. Also `purge`, which enforces the **6-month retention policy** (decided 2026-09-10; `REPORT_RETENTION_MONTHS` overrides). Dry-run by default, `--yes` to delete, and **manual on purpose** — nothing should silently destroy the only copy of user-reported data on an unwatched timer. The `docker run` example in that file mounts the volume `:ro`, which purge cannot use.
