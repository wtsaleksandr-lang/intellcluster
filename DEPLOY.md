# Deploying IntellCluster

The app deploys to any Python-hosting platform. Recommended: **Railway** (simplest for SaaS).

## Railway (recommended)

1. `gh repo sync` the latest `main` on `wtsaleksandr-lang/intellcluster`
2. Go to https://railway.app → **New Project** → **Deploy from GitHub repo** → select `intellcluster`
3. Railway auto-detects the `Dockerfile` and `railway.json`
4. Add environment variables (Settings → Variables):
   ```
   OPENAI_API_KEY=...
   ANTHROPIC_API_KEY=...
   GOOGLE_API_KEY=...
   DEEPSEEK_API_KEY=...
   XAI_API_KEY=...
   ADMIN_USERNAME=admin@intellcluster.com
   ADMIN_PASSWORD=<strong password>
   ADMIN_SECRET_KEY=<32+ random chars>
   RATE_LIMIT_ENABLED=true
   RATE_LIMIT_PER_MINUTE=30
   # Optional:
   SMTP_HOST=...
   SMTP_USERNAME=...
   SMTP_PASSWORD=...
   SMTP_FROM=noreply@intellcluster.com
   # Add Stripe keys when ready (see shared/stripe_integration.py)
   STRIPE_SECRET_KEY=
   STRIPE_PUBLISHABLE_KEY=
   STRIPE_WEBHOOK_SECRET=
   STRIPE_PRICE_STARTER_MONTHLY=
   STRIPE_PRICE_STARTER_ANNUAL=
   STRIPE_PRICE_PRO_MONTHLY=
   STRIPE_PRICE_PRO_ANNUAL=
   STRIPE_PRICE_CREDITS_5=
   STRIPE_PRICE_CREDITS_15=
   STRIPE_PRICE_CREDITS_30=
   ```
5. Settings → Networking → **Generate Domain** (gives you a `*.up.railway.app` URL for testing)
6. Once `intellcluster.com` is purchased, add custom domain in Railway and update DNS records

## Render (alternative)

1. https://render.com → **New Web Service** → connect repo
2. Environment: **Docker**
3. Same env vars as above
4. Health check path: `/api/health`

## Fly.io (alternative)

1. Install the `flyctl` CLI
2. `fly launch` — it reads the `Dockerfile`
3. `fly secrets set OPENAI_API_KEY=...` for each env var
4. `fly deploy`

## DNS (when you buy intellcluster.com)

Point these records at your host:
```
A     @                <Railway/Render IP>
CNAME www              <app>.up.railway.app
```

## Post-deploy verification

```bash
curl https://intellcluster.com/api/health
# Expected: {"status":"ok","tools":["phronesis","synthesis"],...}

curl https://intellcluster.com/robots.txt
curl https://intellcluster.com/sitemap.xml
```

## Stripe webhook setup (once billing goes live)

1. Stripe Dashboard → Developers → Webhooks → Add endpoint
2. URL: `https://intellcluster.com/api/stripe/webhook`
3. Events:
   - `checkout.session.completed`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.payment_succeeded`
4. Copy the **Signing secret** into `STRIPE_WEBHOOK_SECRET`
5. Redeploy for the secret to take effect
