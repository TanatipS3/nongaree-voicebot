export const SESSION_COOKIE_NAME = "nongaree_sso_session";
export const SESSION_TTL_SECONDS = 7 * 24 * 60 * 60;

export type SsoSession = {
  username: string;
  tokenId: string;
  email: string;
  name: string;
  issuedAt: number;
  expiresAt: number;
};

const encoder = new TextEncoder();
const decoder = new TextDecoder();

function bytesToBase64Url(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function base64UrlToBytes(value: string): Uint8Array<ArrayBuffer> {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(value.length / 4) * 4, "=");
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

function sessionSecret(): string {
  const secret = process.env.SSO_SESSION_SECRET || process.env.SSO_KEY;
  if (!secret) throw new Error("SSO_SESSION_SECRET or SSO_KEY is not configured");
  return secret;
}

async function hmacKey(): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "raw",
    encoder.encode(sessionSecret()),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"],
  );
}

export async function createSessionToken(
  input: Omit<SsoSession, "issuedAt" | "expiresAt">,
): Promise<string> {
  const issuedAt = Math.floor(Date.now() / 1000);
  const payload: SsoSession = {
    ...input,
    issuedAt,
    expiresAt: issuedAt + SESSION_TTL_SECONDS,
  };
  const encodedPayload = bytesToBase64Url(encoder.encode(JSON.stringify(payload)));
  const signature = await crypto.subtle.sign("HMAC", await hmacKey(), encoder.encode(encodedPayload));
  return `${encodedPayload}.${bytesToBase64Url(new Uint8Array(signature))}`;
}

export async function verifySessionToken(token?: string | null): Promise<SsoSession | null> {
  if (!token) return null;
  const [encodedPayload, encodedSignature, extra] = token.split(".");
  if (!encodedPayload || !encodedSignature || extra) return null;

  try {
    const valid = await crypto.subtle.verify(
      "HMAC",
      await hmacKey(),
      base64UrlToBytes(encodedSignature),
      encoder.encode(encodedPayload),
    );
    if (!valid) return null;

    const payload = JSON.parse(decoder.decode(base64UrlToBytes(encodedPayload))) as Partial<SsoSession>;
    const now = Math.floor(Date.now() / 1000);
    if (
      typeof payload.username !== "string" ||
      typeof payload.tokenId !== "string" ||
      typeof payload.email !== "string" ||
      typeof payload.name !== "string" ||
      typeof payload.issuedAt !== "number" ||
      typeof payload.expiresAt !== "number" ||
      payload.expiresAt <= now
    ) {
      return null;
    }
    return payload as SsoSession;
  } catch {
    return null;
  }
}
