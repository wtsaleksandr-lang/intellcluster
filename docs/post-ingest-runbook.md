# IntellCluster post-ingestion launch runbook

Use this sequence after the long production Canada ingestion finishes. It is intentionally short: the goal is to get the directory live safely without mixing deployment, paid enrichment or multi-million-row U.S. ingestion into the same step.

## 1. Confirm the Canada ingestion has actually stopped

Do **not** pull, redeploy, switch workspaces or start another large database job while the current ingestion shell is still running.

After it finishes:

```bash
python -m intelligence.ingest status
```

The Corporations Canada run should no longer show `running`. A resumable full-source run should normally have a `completed` checkpoint.

## 2. Pull the latest `main`

Only after ingestion has stopped, bring production to the current GitHub build. IntellCluster must run through `main_data:app`; starting `main:app` omits the business-intelligence layer.

## 3. Run the single strict launch gate

Before public deployment:

```bash
python -m intelligence.launch_gate --production --strict
```

This is the authoritative pre-launch verdict. It combines the old readiness and data-quality checks with production environment safety. It performs **zero external network calls** and **zero paid-source calls**.

It blocks launch when it detects any of the following:

- Canada ingestion is still running or materially incomplete
- blocking canonical-graph integrity errors
- missing or SQLite production `DATABASE_URL`
- missing/non-HTTPS `PUBLIC_BASE_URL`
- weak/missing admin password or signing key
- `IMPORTYETI_ALLOW_LIVE=true`
- disabled API rate limiting
- enabled debug mode

Warnings are reported separately. For example, an empty supplier index is expected before the cached supplier backfill and does not by itself make the site unsafe to launch.

For deeper troubleshooting, the component checks remain available:

```bash
python -m intelligence.post_ingest_readiness --strict
python -m intelligence.data_quality --strict
```

Do not bypass the launch gate just to obtain a green deployment. Resolve blockers and rerun it.

## 4. Deploy and smoke-test the public site

Deploy the latest `main_data:app`, then verify:

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

The root homepage should expose the Business Intelligence product, and the shared desktop/mobile/footer navigation should link to `/data`.

Authenticated administrators can inspect the read-only operational endpoints:

```text
GET /api/intelligence/admin/sync-status
GET /api/intelligence/admin/post-ingest-readiness
GET /api/intelligence/admin/launch-gate
GET /api/intelligence/admin/data-quality
```

The operational console is available at `/admin/intelligence`.

## 5. Populate named suppliers from existing cache

Canada public datasets do not provide named foreign suppliers. `intel_supplier_relationships` is populated from ImportYeti profiles that IntellCluster has already cached.

Run:

```bash
python -m intelligence.supplier_backfill
```

The backfill:

- scans canonical entities by keyset ID
- reads only existing `enrichment.importyeti.suppliers_table` values
- writes `intel_supplier_relationships`
- stores a resumable checkpoint
- makes **zero network calls**
- consumes **zero ImportYeti credits**

For a controlled first pass:

```bash
python -m intelligence.supplier_backfill --limit-entities 10000
python -m intelligence.supplier_backfill
```

## 6. Validate the U.S. FMCSA bootstrap

First perform the no-download safety check:

```bash
python -m intelligence.fmcsa_ingest --validate-fast-seed
```

If it reports that fast seed is safe, validate only 1,000 rows:

```bash
python -m intelligence.fmcsa_ingest --fast-seed --limit 1000
```

Review entity/source counts, USDOT/status fields, search/profile rendering, duplicate behavior, checkpoint state and representative records before starting the full U.S. load.

Only after the sample looks correct:

```bash
python -m intelligence.fmcsa_ingest --fast-seed
```

The FMCSA loader uses USDOT keyset checkpoints and can resume after interruption.

## 7. Optional offline intelligence layers

These improve profiles but are not blockers for the initial public launch.

### USPTO patents

Use an official PatentsView annualized CSV. Validate before attaching:

```bash
python -m intelligence.uspto_bulk --csv /path/to/patentsview.csv --dry-run --limit-assignees 10000
python -m intelligence.uspto_bulk --csv /path/to/patentsview.csv
```

The loader creates no new canonical companies, matches conservatively and makes zero network calls while running.

### CanadaBuys federal contracts

Use the official CanadaBuys/Open Government contract-history CSV:

```bash
python -m intelligence.canadabuys_bulk --csv /path/to/contractHistoryComplete-contratsOctroyesComplet.csv --dry-run --limit-suppliers 10000
python -m intelligence.canadabuys_bulk --csv /path/to/contractHistoryComplete-contratsOctroyesComplet.csv
```

This loader also creates no new canonical companies and makes zero network calls while running.

## Paid-data rule

Keep this setting for normal launch and normal browsing:

```text
IMPORTYETI_ALLOW_LIVE=false
```

A stored ImportYeti key does not authorize spending. Paid acquisition is intentionally separated behind the signed admin session, the live master switch, an explicitly live-enabled client and `confirm_paid=true`. Normal profile views, BOL views, supplier indexing, Canada ingestion, launch/readiness checks, FMCSA ingestion, USPTO bulk ingestion and CanadaBuys bulk ingestion do not need paid ImportYeti access.
