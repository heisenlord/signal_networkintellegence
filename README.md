# Signal frontend — Vercel

Deploy branch `deploy/vercel-frontend` with repository root as the root directory. The Vercel configuration is `vercel.json`. The backend is in branch `deploy/render-backend`; `main` keeps the combined project.

Use framework **Vite**, Node.js **22.x**, install command `npm ci`, build command `npm run build`, and output directory `dist`. Set the Vercel production branch to `deploy/vercel-frontend`.

Production builds default to the deployed Render backend. If overriding the public Production environment value in Vercel, use:

```dotenv
VITE_API_BASE_URL=https://signal-networkintellegence.onrender.com/api/v1
```

On Render, set `SIGNAL_ALLOWED_ORIGINS` to the exact Vercel production origin, such as `["https://YOUR-FRONTEND.vercel.app"]`. Never put API keys or access tokens in Vercel build variables. Changing environment values requires redeployment.

See [the complete deployment guide](docs/deployment.md) for backend setup, signed-token authentication, CORS and persistence. Production uses the customer and role in a verified access token; the token stays in memory and is cleared on refresh or sign-out. All network data is simulated.

## Local development

```bash
npm ci
cp .env.example .env
npm run dev
```

The local Vite server proxies `/api` to `http://127.0.0.1:8000` by default; run the backend separately. To use Render locally, set `VITE_API_BASE_URL=https://signal-networkintellegence.onrender.com` (with or without `/api/v1`) in `.env`. Vite proxies the local API requests to that backend, avoiding localhost CORS issues. Production builds use the normalized HTTPS API URL directly. For production custom API domains, also update the `connect-src` policy in `vercel.json`.

## Validation

```bash
npm audit
npm run build
```
