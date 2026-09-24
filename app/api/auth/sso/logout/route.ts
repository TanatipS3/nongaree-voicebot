import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE_NAME, verifySessionToken } from "@/lib/auth/session";
import { logoutSso } from "@/lib/sso/soap";

export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  const session = await verifySessionToken(req.cookies.get(SESSION_COOKIE_NAME)?.value);
  let ssoNotified = false;

  if (session?.tokenId) {
    try {
      ssoNotified = await logoutSso(session.username, session.tokenId);
    } catch (error) {
      console.error("[SSO] Logout notification failed", error);
    }
  }

  const response = NextResponse.json({ ok: true, ssoNotified });
  response.cookies.set(SESSION_COOKIE_NAME, "", {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });
  response.cookies.set("site_auth", "", { path: "/", maxAge: 0 });
  return response;
}
