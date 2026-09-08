# Deploying IntellCluster

IntellCluster must be started through **`main_data:app`**. That entrypoint imports the core application and then mounts the `/data` business-intelligence directory, enrichment APIs, SEO/discovery routes and operational safeguards. Starting `main:app` directly serves the core Phronesis/Synthesis product but omits the intelligence layer.

The app deploys to any Python-hosting platform. The current Replit run/deployment configuration already uses `main_data:app`. Railway, Docker and Procfile commands are kept aligned with the same entrypoint.

## Production environment

At minimum, configure the application credentials required by the product plus the intelligence database:

```text
DATABASE_URL=<production PostgreSQL URL>
PUBLIC_BASE_URL=https://intellcluster.com

ADMIN_USERNAME=admin@intellcluster.com
ADMIN_PASSWORD=<strong 12+ character password>
ADMIN_SECRET_KEY=<32+ random chars>

RATE_LIMIT_ENABLED=true
RATE_LIMIT_PER_MINUTE=30
DEBUG=false

# Paid trade intelligence stays disabled by default.
IMPORTYETI_API_KEY=<stored key if used>
IMPORTYETI_ALLOW_LIVE=false

# Free SEC automation should identify the application/operator.
SEC_EDGAR_USER_AGENT=IntellCluster/1.0 contact@intellcluster.com

# Recommended for launch analytics.
PLAUSIBLE_DOMAIN=intellcluster.com
```

Optional LLM, SMTP and Stripe variables remain configured as required by the rest of the product. Never commit live credentials.

## Replit

`.replit` starts the development workflow with:

```text
uvicorn main_data:app --host 0.0.0.0 --port 5000
```

and the autoscale deployment uses Gunicorn/Uvicorn workers against `main_data:app`.

For long-running intelligence ingestion jobs, application deployment and data ingestion are operationally separate. **Do not pull/redeploy the production workspace while an active ingestion shell must remain alive.** Complete the ingestion first, then follow `docs/post-ingest-runbook.md`.

## Railway

1. Connect the GitHub repository to a Railway project.
2. Railway uses `railway.json` and the repository `Dockerfile`.
3. Add the production environment variables above plus any LLM/SMTP/Stripe variables in use.
4. Configure the public domain after the service is healthy.

The configured Railway start command is:

```text
uvicorn main_data:app --host 0.0.0.0 --port $PORT
```

## Render

1. Create a new Web Service from the GitHub repository.
2. Environment: **Docker**.
3. Add the same environment variables.
4. Health check path: `/api/health`.

The Docker image starts `main_data:app` automatically.

## Fly.io

1. Install the `flyctl` CLI.
2. `fly launch` — it reads the `Dockerfile`.
3. Configure secrets/environment variables.
4. `fly deploy`.

## Procfile-compatible hosts

The repository `Procfile` starts:

```text
uvicorn main_data:app --host 0.0.0.0 --port $PORT
```

## Strict launch gate

After a production ingestion has finished and the latest `main` code is present, run the single no-network launch verdict before exposing the new build:

```bash
python -m intelligence.launch_gate --production --strict
```

The command combines:

- Canada ingestion completion/readiness
- canonical database integrity checks
- production PostgreSQL configuration
- HTTPS public-base URL configuration
- admin credential/signing-key safety
- rate-limit and debug-mode safety
- the requirement that paid ImportYeti acquisition remain disabled by default

It performs **zero external network calls**, never invokes ImportYeti, and exits with status `2` when a launch blocker remains. Warnings such as missing analytics or an empty cached supplier index are reported separately and do not automatically block launch.

The same report is available to a signed-in administrator at:

```text
GET /api/intelligence/admin/launch-gate
```

Do not weaken or bypass the strict gate to make a deployment appear ready; resolve its blockers instead.

## Post-deploy verification

Verify both the core application **and** the intelligence layer:

```bash
curl https://intellcluster.com/api/health
curl https://intellcluster.com/api/intelligence/health
curl https://intellcluster.com/data
curl https://intellcluster.com/data/canada
curl https://intellcluster.com/data/usa
curl https://intellcluster.com/data/companies
curl https://intellcluster.com/robots.txt
curl https://intellcluster.com/sitemap.xml
curl https://intellcluster.com/sitemaps/site.xml
```

`/api/intelligence/health` should report an `ok` status and the current entity count. A deployment where `/api/health` works but `/data` or `/api/intelligence/health` returns 404 is using the wrong entrypoint.

Authenticated administrators also have read-only operational checks after deployment:

```text
GET /api/intelligence/admin/sync-status
GET /api/intelligence/admin/post-ingest-readiness
GET /api/intelligence/admin/launch-gate
```

Before beginning the first large U.S. bootstrap, follow `docs/post-ingest-runbook.md` rather than jumping directly to a full FMCSA run.

## Stripe webhook setup (once billing goes live)

1. Stripe Dashboard → Developers → Webhooks → Add endpoint.
2. URL: `https://intellcluster.com/api/stripe/webhook`.
3. Events:
   - `checkout.session.completed`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.payment_succeeded`
4. Copy the signing secret into `STRIPE_WEBHOOK_SECRET`.
5. Redeploy for the secret to take effect.
