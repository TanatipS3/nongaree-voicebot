import { NextRequest, NextResponse } from "next/server";
import { unlink } from "node:fs/promises";
import path from "node:path";
import { SESSION_COOKIE_NAME, verifySessionToken } from "@/lib/auth/session";

export const runtime = "nodejs";

// Clears the caller's stored conversation memory. Called by handleLogout BEFORE the SSO
// logout, so signing out does not leave a transcript of someone's salary, dependants and
// ages sitting on disk.
//
// A separate route on purpose: the alternative was adding an unlink to
// app/api/auth/sso/logout/route.ts, which is in the "won't touch at all" list in
// HANDOFF.md §1. This achieves the same thing without going near it.
//
// Identity comes from the session cookie, never the request body — same rule as
// app/api/report/route.ts. There is no user parameter, so one user cannot clear another's.
const MEMORY_DIR = process.env.MEMORY_DIR || "/data/memory";

export async function DELETE(req: NextRequest) {
  const session = await verifySessionToken(req.cookies.get(SESSION_COOKIE_NAME)?.value);
  if (!session) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  // Must match room_to_key() in graph/conversation_store.py, which derives the key from
  // the LiveKit room name `nongaree-${safeUser}`. Same sanitisation as the token route.
  const safeUser = session.username.replace(/[^a-zA-Z0-9_-]/g, "_");

  try {
    await unlink(path.join(MEMORY_DIR, `${safeUser}.json`));
    return NextResponse.json({ ok: true, cleared: true });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      // Nothing stored — a fresh session, or the TTL already expired it.
      return NextResponse.json({ ok: true, cleared: false });
    }
    console.error("[session/memory] failed to clear conversation memory", error);
    // Deliberately not a 500: logout must proceed even if the unlink fails, and the
    // 30-minute TTL will remove the file anyway.
    return NextResponse.json({ ok: false, cleared: false });
  }
}
