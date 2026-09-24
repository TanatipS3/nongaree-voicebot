import { NextRequest, NextResponse } from "next/server";
import { appendFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { SESSION_COOKIE_NAME, verifySessionToken } from "@/lib/auth/session";

export const runtime = "nodejs";

// Append-only JSONL, one report per line. Deliberately not a database: adding a DB
// service would mean a new image in the prebuilt-release handoff, credentials and
// backups, for a feature that has not proven itself yet. `schema_version` in the
// payload makes lifting this into Postgres later mechanical.
//
// Files rotate monthly (reports-YYYY-MM.jsonl) so a retention policy can be enforced
// by deleting a file rather than migrating rows.
const REPORT_DIR = process.env.REPORT_DIR || "/data/reports";

const REPORT_TYPES = new Set([
  "wrong_answer",
  "incomplete",
  "outdated",
  "no_response",
  "audio_mic",
  "other",
]);

const MAX_MESSAGE_LEN = 2000;
const MAX_PRECEDING_TURNS = 3;
const MAX_SOURCES = 8;

function clip(value: unknown, max: number): string {
  if (typeof value !== "string") return "";
  const trimmed = value.trim();
  return trimmed.length > max ? trimmed.slice(0, max) : trimmed;
}

function sanitizeTurn(raw: unknown) {
  if (!raw || typeof raw !== "object") return null;
  const turn = raw as Record<string, unknown>;
  return {
    history_id: clip(turn.history_id, 80),
    asked_at: clip(turn.asked_at, 40),
    question: clip(turn.question, 4000),
    voice_answer: clip(turn.voice_answer, 8000),
    detail_answer: clip(turn.detail_answer, 20000),
    input_mode: clip(turn.input_mode, 16),
  };
}

// Excerpt text is intentionally dropped: the ids identify the chunk, and storing the
// excerpt would duplicate the corpus into the report file for no gain.
function sanitizeSources(raw: unknown) {
  if (!Array.isArray(raw)) return [];
  return raw.slice(0, MAX_SOURCES).map((item) => {
    const source = (item ?? {}) as Record<string, unknown>;
    return {
      n: Number(source.n) || 0,
      record_id: clip(source.record_id, 120),
      cluster_id: clip(source.cluster_id, 60),
      title: clip(source.title, 200),
      domain: clip(source.domain, 40),
      subdomain: clip(source.subdomain, 60),
      outdated: Boolean(source.outdated),
    };
  });
}

export async function POST(req: NextRequest) {
  // Identity comes from the session cookie, never from the request body — a
  // client-supplied username would be forgeable.
  const session = await verifySessionToken(req.cookies.get(SESSION_COOKIE_NAME)?.value);
  if (!session) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  let body: Record<string, unknown>;
  try {
    body = (await req.json()) as Record<string, unknown>;
  } catch {
    return NextResponse.json({ error: "invalid json" }, { status: 400 });
  }

  const type = clip(body.type, 40);
  const message = clip(body.message, MAX_MESSAGE_LEN);
  if (!REPORT_TYPES.has(type)) {
    return NextResponse.json({ error: "invalid type" }, { status: 400 });
  }
  if (!message) {
    return NextResponse.json({ error: "message required" }, { status: 400 });
  }

  const safeUser = session.username.replace(/[^a-zA-Z0-9_-]/g, "_");
  const client = (body.client ?? {}) as Record<string, unknown>;
  const diagnostics = (body.diagnostics ?? {}) as Record<string, unknown>;

  const report = {
    schema_version: 1,
    report_id: randomUUID(),
    created_at: new Date().toISOString(),

    username: session.username,
    room: `nongaree-${safeUser}`,

    type,
    message,

    // Null when the user reports without a completed turn — which is exactly the
    // "ระบบค้าง / ไม่ตอบ" case, the one most worth reporting.
    turn: sanitizeTurn(body.turn),
    sources: sanitizeSources(body.sources),

    diagnostics: {
      route: clip(diagnostics.route, 40),
      retrieval_empty: diagnostics.retrieval_empty === true,
      query_widened: diagnostics.query_widened === true,
      job_id: clip(diagnostics.job_id, 80),
      agent_name: clip(diagnostics.agent_name, 80),
    },

    preceding_turns: Array.isArray(body.preceding_turns)
      ? body.preceding_turns.slice(0, MAX_PRECEDING_TURNS).map(sanitizeTurn).filter(Boolean)
      : [],

    client: {
      connection_status: clip(client.connection_status, 40),
      mic_ready: client.mic_ready === true,
      // The DOMException NAME, not the localized message: names are stable and
      // aggregatable, the Thai copy is presentation and will change.
      mic_error: clip(client.mic_error, 80),
      turn_active: client.turn_active === true,
      queued_questions: Number(client.queued_questions) || 0,
      viewport: clip(client.viewport, 40),
      user_agent: clip(req.headers.get("user-agent"), 400),
    },
  };

  const now = new Date();
  const file = `reports-${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, "0")}.jsonl`;

  try {
    await mkdir(REPORT_DIR, { recursive: true });
    // O_APPEND keeps concurrent single-line writes from interleaving.
    await appendFile(path.join(REPORT_DIR, file), `${JSON.stringify(report)}\n`, "utf8");
  } catch (error) {
    console.error("[report] failed to persist report", error);
    return NextResponse.json({ error: "failed to save" }, { status: 500 });
  }

  return NextResponse.json({ ok: true, report_id: report.report_id });
}
