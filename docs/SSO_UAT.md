# RD SSO UAT

Nongaree Voicebot receives the RD SSO POST callback at:

```text
https://ari-chatbot.rd.go.th/api/auth/sso/callback
```

## Current status

- `SSO_APP_ID` is `ARICHATBOT`.
- `SSO_PWD_AUTHEN` is `ARICHATBOT`.
- `SSO_KEY` uses the same value as DocChat.
- The UAT SOAP URL, namespace, and internal hostname mappings follow DocChat.
- Direct access shows an SSO-only information page; there is no local login form or portal URL dependency.

## Runtime configuration

Copy `docker container/.env.sso.example` to `docker container/.env.sso` and configure every value. The real file is ignored by Git and is loaded only by the `web` service.

The callback accepts `application/x-www-form-urlencoded`, multipart form data, or JSON with these fields:

- `Username`
- `Timestamp`, `ReqTime`, or `Reqtime`
- `Signature`
- `TokenID`

After verification, the server calls `Get_SSO_User`, creates a signed HttpOnly cookie, records a `Load` transaction, and redirects to `APP_URL`.

## Verification

Before UAT testing:

1. Confirm the callback URL is registered exactly as shown above.
2. Confirm the web container can reach the UAT SOAP endpoint over port 443.
3. Run `npm run build` and deploy the rebuilt web image.
