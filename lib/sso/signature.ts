import { createHash, timingSafeEqual } from "node:crypto";

function safeEqual(left: string, right: string): boolean {
  const leftBytes = Buffer.from(left);
  const rightBytes = Buffer.from(right);
  return leftBytes.length === rightBytes.length && timingSafeEqual(leftBytes, rightBytes);
}

export function verifySsoSignature(timestamp: string, incoming: string): boolean {
  const key = process.env.SSO_KEY;
  if (!key) throw new Error("SSO_KEY is not configured");

  const digest = createHash("sha1").update(key + timestamp, "utf8").digest();
  const hexThenBase64 = Buffer.from(digest.toString("hex"), "utf8").toString("base64");
  const rawBase64 = digest.toString("base64");
  return safeEqual(incoming, hexThenBase64) || safeEqual(incoming, rawBase64);
}

