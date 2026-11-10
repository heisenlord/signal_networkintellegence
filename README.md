# Signal API — Render

Deploy branch `deploy/render-backend` with repository root as the root directory. The Render Blueprint is `render.yaml`. The frontend is in branch `deploy/vercel-frontend`; `main` keeps the combined project.

Follow [deployment and security setup](docs/deployment.md) for the required identity provider, exact Vercel CORS origin, persistent disk and verification steps. Production rejects public demo tokens. The Blueprint uses a paid Starter instance with a 1 GB disk to preserve SQLite.

## Local development

Use Python 3.12. From repository root:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r backend/requirements.lock
.venv/bin/python -m pip install -r backend/requirements-dev.txt
cp backend/.env.example backend/.env
.venv/bin/python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Local development permits documented demo identities. Production requires verified RS256 access tokens; configure `SIGNAL_ENVIRONMENT=production` and the settings in the deployment guide.

## Validation

```bash
.venv/bin/python -m pytest -q
.venv/bin/pip-audit -r backend/requirements.lock
```

All network data is simulated. Customer-scoped reads, evidence-gated proposals and independent human review are implemented. No network-change executor is installed.
