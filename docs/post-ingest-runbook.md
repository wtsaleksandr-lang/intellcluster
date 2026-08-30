# IntellCluster post-ingestion rollout runbook

Use this sequence after a long production public-data ingestion has finished. The goal is to separate database completion checks, deployment, cached-only indexing and the first U.S. bootstrap validation so one step cannot accidentally interfere with another.

## 1. Confirm the Canada ingestion is finished

Do not pull, redeploy or start another large database job while the current ingestion is still running.

After it finishes, check persisted state:

```bash
python -m intelligence.ingest status
```

The Corporations Canada run should no longer show `running`. For a resumable full-source run, its checkpoint should normally be `completed`.

## 2. Run the no-network readiness preflight

```bash
python -m intelligence.post_ingest_readiness --strict
```

This reads the existing database only. It does not call public websites, SEC, EPA, OSHA, FMCSA or ImportYeti.

A strict preflight exits with status 2 if a Canada ingestion blocker remains. The report also shows:

- Canada source-record counts and completion hints
- current supplier-index state
- whether the cached-only supplier backfill is recommended
- FMCSA fast-seed safety for the current U.S. canonical graph
- whether the ImportYeti live master switch is enabled

## 3. Pull and deploy the latest `main`

Only after the active ingestion is finished should production pull/redeploy the application code.

After deployment, authenticated administrators can open the read-only operations console at:

- `/admin/intelligence`

The console shows persisted sync/checkpoint state, progress and ETA estimates, readiness blockers, supplier-index status and the recommended rollout sequence. Its **Run data-quality audit** button performs only database reads.

The same information is also available as admin-only JSON:

- `GET /api/intelligence/admin/sync-status`
- `GET /api/intelligence/admin/post-ingest-readiness`
- `GET /api/intelligence/admin/data-quality` (manual audit; may scan large tables)

These routes require the signed admin session. They do not trigger paid enrichment.

## 4. Run the database-only quality audit

```bash
python -m intelligence.data_quality --strict
```

This checks the canonical intelligence graph for structural problems without making network calls. It reports orphan source/importer/supplier rows, duplicate source identities, duplicate corporation numbers, Canada records linked to the wrong country, importer-flag inconsistencies, source-less entities and unexpected country codes.

Blocking integrity findings should be investigated before a multi-million-row U.S. bootstrap. Some findings, such as duplicate corporation numbers or source-less entities, are reported as warnings because they can have legitimate explanations and should be reviewed rather than automatically treated as corruption.

## 5. Populate the supplier index from existing cache

The Canada public datasets do not provide named foreign suppliers. Supplier relationships are built only from already-cached ImportYeti company profiles.

Run:

```bash
python -m intelligence.supplier_backfill
```

This job:

- scans canonical entities by keyset ID
- reads `enrichment.importyeti.suppliers_table` only when it is already cached
- writes `intel_supplier_relationships`
- stores a resumable checkpoint in `intel_sync_checkpoints`
- makes **zero network calls**
- consumes **zero ImportYeti credits**

For a controlled test:

```bash
python -m intelligence.supplier_backfill --limit-entities 10000
python -m intelligence.supplier_backfill
```

The second command resumes from the saved entity-ID checkpoint.

## 6. Validate FMCSA bootstrap safety without downloading data

```bash
python -m intelligence.fmcsa_ingest --validate-fast-seed
```

Fast seed is intended only for a fresh or previously FMCSA-only U.S. canonical graph. If unrelated U.S. entities already exist, the preflight intentionally fails and the conservative entity-resolution path should be used instead.

## 7. Run a 1,000-record FMCSA validation

If fast-seed preflight is safe:

```bash
python -m intelligence.fmcsa_ingest --fast-seed --limit 1000
```

Then review:

- entity/source-record counts
- USDOT values and status fields
- search cards/profile rendering
- duplicate behavior
- checkpoint position
- representative company matches

Do not proceed directly from preflight to a multi-million-row run without reviewing this sample.

## 8. Start the full FMCSA bootstrap only after validation

If the 1,000-record result is correct:

```bash
python -m intelligence.fmcsa_ingest --fast-seed
```

The FMCSA job uses a USDOT keyset checkpoint and can resume after interruption.

## Paid-data rule

Keep:

```text
IMPORTYETI_ALLOW_LIVE=false
```

unless an authenticated administrator is intentionally purchasing missing ImportYeti intelligence through the dedicated acquisition endpoint. Normal profile views, BOL views, supplier indexing, Canada ingestion, readiness checks, data-quality auditing and FMCSA ingestion do not require live ImportYeti access.
