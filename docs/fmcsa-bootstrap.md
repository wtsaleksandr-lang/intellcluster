# FMCSA U.S. Bootstrap Runbook

This runbook covers the initial U.S. Company Census bootstrap for IntellCluster.
It is intentionally separate from ordinary recurring enrichment.

## Why there are two ingestion modes

`python -m intelligence.fmcsa_ingest` uses the normal conservative entity resolver.
It is appropriate when the canonical graph already contains U.S. companies from
other sources because every FMCSA record gets a chance to match an existing entity.
That safety costs database round trips and is not ideal for a multi-million-row
initial seed.

`python -m intelligence.fmcsa_ingest --fast-seed` is the initial-bootstrap mode.
It creates one canonical entity per USDOT registration and writes the FMCSA fleet
summary directly onto that entity. PostgreSQL can insert a whole page with a small
number of database round trips. The mode is resumable by USDOT checkpoint.

## Hard safety rule

Fast seed is allowed only when every existing U.S. canonical entity is already
linked to an FMCSA source record. In practice that means either:

- the U.S. graph is fresh; or
- a previous FMCSA fast-seed run is being resumed.

If unrelated U.S. entities already exist, fast seed refuses to run. Do not bypass
this guard. Use conservative ingestion instead so cross-source entity resolution
can prevent duplicate company profiles.

## No-network preflight

Before any fast-seed validation run, check the production database without
fetching or writing FMCSA data:

```bash
python -m intelligence.fmcsa_ingest --validate-fast-seed
```

A safe result reports `safe: True` and zero `non_fmcsa_us_entities`. An unsafe
result exits with status 2 and should be treated as a stop condition.

## Recommended rollout

After the current database ingestion is idle and the latest application code is
deployed:

1. Run the no-network preflight above.
2. If safe, validate a small page first:

   ```bash
   python -m intelligence.fmcsa_ingest --limit 1000 --fast-seed
   ```

3. Check entity counts, source-record counts, sample company profiles, USDOT
   uniqueness, fleet fields, search performance, and checkpoint position.
4. Resume only after the 1,000-row validation looks correct. The same command can
   be repeated with a larger limit because the saved USDOT checkpoint is used by
   default.
5. For the full bootstrap, omit `--limit` only after throughput and database load
   are acceptable.

The default FMCSA query is U.S. active carriers only. Use `--all-statuses` only
when the product decision is to include inactive and pending registrations too.

## Checkpoints and interruption

The ingestion uses the `fmcsa_company_census` checkpoint. Each committed page
updates the last USDOT number. A stopped process can therefore resume without
starting the dataset from zero.

Do not run a second FMCSA ingestion process against the same production database
at the same time. Keyset pagination makes one process predictable; parallel writers
would add contention and make canonical/entity-count validation harder.

## Promotion pass

Fast seed writes the compact FMCSA fleet/status enrichment directly onto each new
canonical entity. The separate `intelligence.fmcsa_promote` pass is primarily for
records created by the lean/conservative ingestion path or older FMCSA rows that
lack canonical fleet enrichment. It should not be necessary for newly fast-seeded
rows unless a later schema change requires re-promotion.

## Recurring updates after bootstrap

Fast seed is a bootstrap optimization, not the default long-term cross-source
resolver. Once U.S. data from USAspending, ImportYeti caches, EPA, OSHA, SEC, or
other sources has been merged into the canonical graph, use conservative matching
for new/changed records unless a future staging-table merge explicitly preserves
cross-source identity guarantees.

## ImportYeti cost boundary

FMCSA bootstrap is independent of ImportYeti and must not enable live paid
ImportYeti lookups. Profile views and tests should continue to use cached trade
evidence unless an explicit paid unlock is requested.
