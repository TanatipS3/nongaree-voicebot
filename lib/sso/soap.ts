import https from "node:https";

export type SsoUser = {
  email: string;
  firstName: string;
  lastName: string;
  tokenId: string;
};

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is not configured`);
  return value;
}

function escapeXml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function decodeXml(value: string): string {
  return value
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, "&");
}

function extractTag(xml: string, tag: string): string {
  const pattern = new RegExp(`<(?:[\\w.-]+:)?${tag}\\b[^>]*>([\\s\\S]*?)<\\/(?:[\\w.-]+:)?${tag}>`, "i");
  const match = pattern.exec(xml);
  return match ? decodeXml(match[1].trim()) : "";
}

function normalizedResponse(xml: string): string {
  let value = xml;
  for (let index = 0; index < 2; index += 1) value = decodeXml(value);
  return value;
}

async function callSoap(action: string, body: string): Promise<string> {
  const endpoint = new URL(required("SSO_SOAP_URL"));
  const namespace = required("SSO_NAMESPACE");
  const envelope = `<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>${body}</soap:Body>
</soap:Envelope>`;

  return new Promise((resolve, reject) => {
    const request = https.request(
      {
        protocol: endpoint.protocol,
        hostname: endpoint.hostname,
        port: endpoint.port || 443,
        path: `${endpoint.pathname}${endpoint.search}`,
        method: "POST",
        rejectUnauthorized: process.env.SSO_TLS_REJECT_UNAUTHORIZED !== "false",
        timeout: Number(process.env.SSO_TIMEOUT_MS || 15_000),
        headers: {
          "Content-Type": "text/xml; charset=utf-8",
          SOAPAction: `"${namespace}/${action}"`,
          "Content-Length": Buffer.byteLength(envelope),
        },
      },
      (response) => {
        let responseBody = "";
        response.setEncoding("utf8");
        response.on("data", (chunk) => {
          responseBody += chunk;
        });
        response.on("end", () => {
          if (!response.statusCode || response.statusCode < 200 || response.statusCode >= 300) {
            reject(new Error(`SSO SOAP ${action} returned HTTP ${response.statusCode || "unknown"}`));
            return;
          }
          resolve(normalizedResponse(responseBody));
        });
      },
    );
    request.on("timeout", () => request.destroy(new Error(`SSO SOAP ${action} timed out`)));
    request.on("error", reject);
    request.end(envelope);
  });
}

function credentials() {
  return {
    appId: escapeXml(required("SSO_APP_ID")),
    password: escapeXml(required("SSO_PWD_AUTHEN")),
    namespace: required("SSO_NAMESPACE"),
  };
}

export async function getSsoUser(username: string): Promise<SsoUser> {
  const { appId, password, namespace } = credentials();
  const xml = await callSoap(
    "Get_SSO_User",
    `<Get_SSO_User xmlns="${namespace}">
      <UserID>${escapeXml(username)}</UserID>
      <AppId>${appId}</AppId>
      <Pwd_Authen>${password}</Pwd_Authen>
    </Get_SSO_User>`,
  );

  return {
    email: extractTag(xml, "UserEMail") || extractTag(xml, "UserEmail") || `${username}@rd.go.th`,
    firstName: extractTag(xml, "UserNameTH") || extractTag(xml, "UserNameEN") || username,
    lastName: extractTag(xml, "UserSurNameTH") || extractTag(xml, "UserSurNameEN"),
    tokenId: extractTag(xml, "TokenID"),
  };
}

export async function logSsoTransaction(username: string, tokenId: string, transactionId: string): Promise<boolean> {
  const { appId, password, namespace } = credentials();
  const xml = await callSoap(
    "SSO_APP_Transaction_Log",
    `<SSO_APP_Transaction_Log xmlns="${namespace}">
      <UserID>${escapeXml(username)}</UserID>
      <AppId>${appId}</AppId>
      <TokenID>${escapeXml(tokenId)}</TokenID>
      <AppTransID>${escapeXml(transactionId)}</AppTransID>
      <Pwd_Authen>${password}</Pwd_Authen>
    </SSO_APP_Transaction_Log>`,
  );
  const result = extractTag(xml, "SSO_APP_Transaction_LogResult");
  return result === "P" || result.toLowerCase() === "true";
}

export async function logoutSso(username: string, tokenId: string): Promise<boolean> {
  const { appId, password, namespace } = credentials();
  const xml = await callSoap(
    "SSO_App_LogOut",
    `<SSO_App_LogOut xmlns="${namespace}">
      <UserID>${escapeXml(username)}</UserID>
      <AppId>${appId}</AppId>
      <TokenID>${escapeXml(tokenId)}</TokenID>
      <Pwd_Authen>${password}</Pwd_Authen>
    </SSO_App_LogOut>`,
  );
  const result = extractTag(xml, "SSO_App_LogOutResult");
  return result === "P" || result.toLowerCase() === "true";
}
