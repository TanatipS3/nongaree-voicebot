#!/usr/bin/env node
// Mints a session cookie for the LOCAL demo stack (docker-compose.local.yml).
//
// Mirrors lib/auth/session.ts exactly: base64url(payload).base64url(HMAC-SHA256)
// signed with SSO_SESSION_SECRET. It only produces a token — no app code, and
// nothing under lib/sso/ or app/api/auth/, is touched or imported.
//
//   node scripts/mint-local-session.mjs
//
// Writes local-login/index.html, a one-click page served by the "local-login"
// service on port 3001. Cookies are scoped by domain (not port), so a cookie
// set there is sent to the app on port 3000.
//
// The secret below must match SSO_SESSION_SECRET in docker-compose.local.yml.
// It is deliberately a throwaway, so this token is invalid against production.

import { createHmac } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const SECRET = process.env.SSO_SESSION_SECRET || 'local-demo-secret-not-for-production';
const WEB_PORT = process.env.LOCAL_WEB_PORT || '3000';
const LOGIN_PORT = process.env.LOCAL_LOGIN_PORT || '3001';
const TTL_SECONDS = 7 * 24 * 60 * 60;

const b64url = (buf) =>
  Buffer.from(buf).toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');

const issuedAt = Math.floor(Date.now() / 1000);
const payload = {
  username: 'localdev',
  tokenId: 'local-demo',
  email: 'localdev@example.local',
  name: 'Local Demo User',
  issuedAt,
  expiresAt: issuedAt + TTL_SECONDS,
};

const encodedPayload = b64url(JSON.stringify(payload));
const signature = b64url(createHmac('sha256', SECRET).update(encodedPayload).digest());
const token = `${encodedPayload}.${signature}`;

const outDir = join(dirname(fileURLToPath(import.meta.url)), '..', 'local-login');
mkdirSync(outDir, { recursive: true });
writeFileSync(
  join(outDir, 'index.html'),
  `<!doctype html>
<meta charset="utf-8">
<title>Local demo login</title>
<style>
  body{font-family:system-ui,sans-serif;background:#f8fafc;color:#102a36;
       display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}
  .card{text-align:center;max-width:460px;padding:32px}
  h1{font-size:20px;margin:0 0 6px}
  p{font-size:14px;opacity:.72;line-height:1.6;margin:0 0 20px}
  button{background:#3ea3cb;color:#fff;border:0;border-radius:999px;
         font-size:16px;font-weight:700;padding:14px 34px;cursor:pointer}
  small{display:block;margin-top:18px;font-size:12px;opacity:.55;line-height:1.5}
</style>
<div class="card">
  <h1>Aree — Local Demo</h1>
  <p>SSO is bypassed for local development.<br>This sets a locally signed session cookie.</p>
  <button id="go">เข้าสู่ระบบ (Local Demo)</button>
  <small>Signed with a throwaway local secret.<br>This session is not valid against production.</small>
</div>
<script>
document.getElementById('go').onclick = function () {
  document.cookie = 'nongaree_sso_session=${token}; path=/; max-age=${TTL_SECONDS}';
  location.href = 'http://localhost:${WEB_PORT}/';
};
</script>
`,
  'utf-8',
);

console.log(`
Local demo session ready (expires in 7 days).

  ->  Open http://localhost:${LOGIN_PORT}  and click the button.

That sets the cookie and drops you into the app on port ${WEB_PORT}.
Wrote local-login/index.html
`);
