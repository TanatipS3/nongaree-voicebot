import { NextRequest, NextResponse } from "next/server";
import {
  createSessionToken,
  SESSION_COOKIE_NAME,
  SESSION_TTL_SECONDS,
} from "@/lib/auth/session";
import { getSsoUser, logSsoTransaction } from "@/lib/sso/soap";
import { verifySsoSignature } from "@/lib/sso/signature";

export const runtime = "nodejs";

async function requestParameters(req: NextRequest): Promise<Record<string, string>> {
  const contentType = req.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    const value = (await req.json()) as Record<string, unknown>;
    return Object.fromEntries(
      Object.entries(value).filter((entry): entry is [string, string] => typeof entry[1] === "string"),
    );
  }

  if (contentType.includes("multipart/form-data")) {
    const form = await req.formData();
    return Object.fromEntries(
      [...form.entries()].filter((entry): entry is [string, string] => typeof entry[1] === "string"),
    );
  }

  return Object.fromEntries(new URLSearchParams(await req.text()).entries());
}

function pick(parameters: Record<string, string>, ...names: string[]): string {
  const acceptedNames = new Set(names.map((name) => name.toLowerCase()));
  for (const [name, value] of Object.entries(parameters)) {
    if (value && acceptedNames.has(name.toLowerCase())) return value;
  }
  return "";
}

export async function POST(req: NextRequest) {
  try {
    const parameters = await requestParameters(req);
    const username = pick(parameters, "Username", "username");
    const timestamp = pick(parameters, "Timestamp", "ReqTime", "Reqtime", "timestamp", "reqtime");
    const signature = pick(parameters, "Signature", "signature");
    const callbackTokenId = pick(parameters, "TokenID", "tokenId", "tokenid");

    if (!username || !timestamp || !signature) {
      return NextResponse.json({ error: "Missing required SSO parameters" }, { status: 400 });
    }
    if (!verifySsoSignature(timestamp, signature)) {
      return NextResponse.json({ error: "Invalid SSO signature" }, { status: 401 });
    }

    const user = await getSsoUser(username);
    const tokenId = callbackTokenId || user.tokenId;
    if (!tokenId) {
      console.warn("[SSO] TokenID was not provided; continuing with a signed local session", {
        callbackFields: Object.keys(parameters),
      });
    }

    const name = [user.firstName, user.lastName].filter(Boolean).join(" ");
    const sessionToken = await createSessionToken({
      username,
      tokenId,
      email: user.email,
      name,
    });

    if (tokenId) {
      void logSsoTransaction(username, tokenId, "Load").catch((error) => {
        console.error("[SSO] Failed to record login transaction", error);
      });
    }

    const appUrl = process.env.APP_URL || req.nextUrl.origin;
    const response = NextResponse.redirect(new URL("/", appUrl), 303);
    response.cookies.set(SESSION_COOKIE_NAME, sessionToken, {
      httpOnly: true,
      secure: new URL(appUrl).protocol === "https:",
      sameSite: "lax",
      path: "/",
      maxAge: SESSION_TTL_SECONDS,
      priority: "high",
    });
    response.cookies.set("site_auth", "", { path: "/", maxAge: 0 });
    return response;
  } catch (error) {
    console.error("[SSO] Callback failed", error);
    return NextResponse.json({ error: "Unable to complete SSO login" }, { status: 502 });
  }
}
