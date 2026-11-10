# Deploy the backend on Render and the frontend on Vercel

The deployment branches are independent:

- `main` keeps the combined source project.
- `deploy/render-backend` contains the Python backend, sample fixtures, tests, Render Blueprint and deployment instructions. Use repository root as the Render root directory.
- `deploy/vercel-frontend` contains the frontend at repository root, its lockfile and `vercel.json`. Use repository root as the Vercel root directory.

These branches deploy the simulated assignment application. Live vendor ingestion and network execution are outside its scope. No changes need to be merged into `main` to deploy these branches.

## 1. Configure authentication

Production rejects all public `demo-*` tokens. Configure an identity provider to issue **RS256-signed access tokens** for this API with these claims:

```json
{
  "iss": "https://YOUR-IDENTITY-PROVIDER/",
  "aud": "signal-api",
  "sub": "unique-user-id",
  "iat": 1794355200,
  "exp": 1794356100,
  "customer_id": "atlas",
  "role": "alarm"
}
```

The timestamps above illustrate the claim format; actual tokens need current issue and expiry times. Configure short token lifetimes at the provider. Customer IDs are `atlas`, `horizon`, `meridian`, `nova`, and `summit`. Roles are `alarm`, `performance`, `change`, and `approver`. Only identity-provider administrators may assign these claims; do not derive them from editable user profile metadata. The provider's API audience must differ from browser/client ID-token audiences.

The frontend accepts an access token issued through your organization's authentication tooling, verifies it with the backend, and retains it only in memory. Refresh and sign-out discard the token and sign-out clears cached tenant data. Customer and role selectors are locked to the verified claims. An OAuth redirect/PKCE login flow is not included.

## 2. Deploy Render

1. In Render, create a Blueprint from this GitHub repository and select branch `deploy/render-backend`. The branch includes `render.yaml`.
2. Keep root directory empty (repository root). The Blueprint sets the build and start commands, `/api/health` health check, one service instance, and a 1 GB persistent disk mounted at `/var/data`.
3. Supply the prompted environment values:

```dotenv
SIGNAL_ALLOWED_ORIGINS=["https://YOUR-FRONTEND.vercel.app"]
SIGNAL_OIDC_ISSUER=https://YOUR-IDENTITY-PROVIDER/
SIGNAL_OIDC_AUDIENCE=signal-api
SIGNAL_OIDC_JWKS_URL=https://YOUR-IDENTITY-PROVIDER/.well-known/jwks.json
```

Use an exact frontend origin with no trailing slash or path. If the Vercel URL is not known yet, `[]` allows the backend to start while denying browser cross-origin access; replace it after Vercel assigns the production domain. Arbitrary Vercel previews are intentionally not allowed. Add individually trusted preview origins explicitly if needed.

The Blueprint defaults to deterministic/offline investigations. To enable Gemini, set `GEMINI_API_KEY`, set `SIGNAL_AGENT_MODE=auto` or `llm`, and optionally select `GEMINI_MODEL` in Render. These values belong only in Render. Model mode sends scoped investigation evidence to Google, so configure it according to your data-sharing requirements.

The native Python runtime is selected with `.python-version`. The backend binds to Render's `PORT`, trusts the Render proxy's forwarding headers and automatically permits Render's `RENDER_EXTERNAL_HOSTNAME`. For a custom backend domain, set `SIGNAL_ALLOWED_HOSTS` to a JSON array containing the custom domain, Render domain and `localhost`.

**Persistence:** the Blueprint uses Render's paid `starter` plan because SQLite needs a persistent disk. Free web services do not preserve this database across restarts/redeployments. Keep one instance and one Uvicorn worker. A multi-instance production system requires a shared database and shared rate/admission controls. See [Render's disk documentation](https://render.com/docs/disks).

For a manually created Render Web Service, select Python and configure:

```text
Branch: deploy/render-backend
Root Directory: (empty)
Build Command: pip install --upgrade pip==26.3 && pip install --require-hashes -r backend/requirements.lock
Start Command: bash scripts/start-render.sh
Health Check Path: /api/health
Disk Mount Path: /var/data
SIGNAL_ENVIRONMENT=production
SIGNAL_DATABASE_URL=sqlite:////var/data/signal.db
```

Add the OIDC and CORS environment values above as well. Do not change the environment to development to bypass authentication.

## 3. Deploy Vercel

1. Import the same repository into Vercel. Set the production branch to `deploy/vercel-frontend` under the project's Git settings.
2. Use repository root, framework preset **Vite**, Node.js **22.x**, install command `npm ci`, build command `npm run build`, and output directory `dist`.
3. Production builds default to the deployed Render backend. If setting a public build-time override for Production, use:

```dotenv
VITE_API_BASE_URL=https://signal-networkintellegence.onrender.com/api/v1
```

4. Deploy. Copy the stable Vercel production origin into Render's `SIGNAL_ALLOWED_ORIGINS` and redeploy/restart the backend after changing it.

Vercel environment changes require a new frontend build. No backend key, private signing key or access token belongs in a `VITE_` variable. `vercel.json` includes SPA routing and browser security headers. Its CSP permits API connections to HTTPS `*.onrender.com` services; if using a custom API domain, add that exact HTTPS origin to `connect-src` in `vercel.json` and redeploy.

## 4. Verify deployment

```bash
curl -fsS https://YOUR-BACKEND.onrender.com/api/health
curl -i https://YOUR-BACKEND.onrender.com/api/v1/overview
curl -i -X OPTIONS https://YOUR-BACKEND.onrender.com/api/v1/investigations \
  -H 'Origin: https://YOUR-FRONTEND.vercel.app' \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: authorization,content-type'
```

Expect health `200`, unauthenticated overview `401` with a bearer challenge, and preflight `200` with your exact frontend origin. Demo tokens must return `401`; `/docs`, `/redoc`, `/openapi.json`, and `/api/v1/demo/sessions` must return `404`. Open the Vercel site, enter a valid access token, and confirm that only the assigned customer's network and role are available. Test an approver using a different user subject before recording review.

If the UI cannot connect, check the browser's network panel and verify the built API URL, exact CORS origin and CSP. A `401` means token verification failed; validate issuer, audience, current expiry, signing key and required claims. A `429` indicates the request or investigation limit was reached. Public health responses intentionally contain no provider configuration or credentials.

## Operations and security

- Runtime Python dependencies are pinned with artifact hashes in `backend/requirements.lock`; frontend dependencies use `package-lock.json`. CI builds, tests and audits the branch's component. Audit results describe known published dependency issues at check time.
- Production validates configuration on startup. OIDC signature, algorithm, issuer, audience, issue time, expiry, subject, customer and role are checked. JWKS retrieval uses HTTPS, a five-second timeout and a cached key set.
- Production disables demo identities, the demo MCP process and interactive API documentation. All customer records and audit entries retain server-derived tenant scope and existing role checks.
- HTTP requests are limited to 16 KiB bodies and 300 requests per client IP per minute. Investigations are limited to six attempts per verified customer/subject per minute and two simultaneous investigations per process. Limits are configurable through the matching `SIGNAL_` settings. Global admission is also limited by Uvicorn.
- Render and Vercel terminate HTTPS. Responses include CSP, HSTS, frame protection, content-type protection and restrictive referrer/permissions policies. Backend data responses disable caching. Browser authentication uses an Authorization header and no ambient credential cookies.
- Preserve `/var/data` and take consistent SQLite backups. In the Render shell, use Python's `sqlite3.Connection.backup()` API, then export the resulting backup to separate storage. Copying only a live `.db` file can omit WAL transactions. Test restoration before relying on a backup. Disk snapshots and a single disk are not a complete retention strategy.
- SQLite and audit retention are appropriate for a controlled sample-data deployment. Benchmark and migrate storage, cancellation, tenant policies and audit export before handling the assignment's full production scale. The application never executes network changes.

Configuration references: [Render Blueprints](https://render.com/docs/blueprint-spec), [Render environment variables](https://render.com/docs/environment-variables), [Vercel project configuration](https://vercel.com/docs/project-configuration/vercel-json), [Vercel environment variables](https://vercel.com/docs/environment-variables), and [PyJWT verification](https://pyjwt.readthedocs.io/en/latest/usage.html).
