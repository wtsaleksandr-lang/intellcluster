# IntellCluster Intelligence Platform

## Goal

Turn large public/open datasets into reusable, searchable business-intelligence verticals without duplicating application logic for every directory.

The platform separates four concerns:

1. **Source adapters** download and normalize public data while preserving provenance.
2. **Entity resolution** links records from different sources that represent the same company/facility/entity.
3. **Enrichment** adds websites, contacts and AI-derived classifications lazily and caches them.
4. **Vertical products** expose purpose-built search/filtering experiences such as importers, industrial facilities, food plants and aviation.

## Current source layers

### Canada business/buyer intelligence
- Corporations Canada bulk records
- Canadian Importers Database
- HS/product/origin relationships
- lazy website/contact enrichment

### U.S. public intelligence
- FMCSA Company Census / fleet evidence
- USAspending recipient and federal-contract evidence
- EPA ECHO facilities/environmental compliance
- OSHA establishment/inspection evidence
- SEC EDGAR filings and standardized XBRL financial facts

### Selective paid trade intelligence
- ImportYeti cached company, supplier, shipment and BOL evidence
- paid acquisition is explicit and optional; it is never required for public directory browsing

### Later / external-transition sources
- USPTO company-linked intellectual property after the Open Data replacement interface is stable
- additional regulated-manufacturing and aviation datasets where they materially improve a directory vertical

## Data principles

- Keep the original source record and source URL for provenance/attribution.
- Never make paid enrichment a requirement for basic public directory pages.
- Enrich lazily rather than pre-enriching an entire public corpus.
- Cache enrichment responses to control API and infrastructure costs.
- Keep source-specific fields in `attributes` while promoting common fields to the normalized model.
- Treat entity resolution as probabilistic and retain conservative match rules.
- Prefer false-negative cross-source matches over silently joining two different companies.
- Public SEO pages should combine useful source facts rather than reproducing thin raw records.
- A missing enrichment match means no confident match was found; it is not evidence of zero activity.

## Paid enrichment safety

ImportYeti uses a deliberate multi-gate acquisition model:

1. **Normal GET/page-view code uses cached-only clients.** The default `ImportYetiClient()` cannot make a paid network request.
2. **The environment master switch must be enabled.** `IMPORTYETI_ALLOW_LIVE=true` only makes paid acquisition possible; it does not cause spending by itself.
3. **The call site must explicitly request live access.** Only `ImportYetiClient(allow_live=True)` can pass the client-level live gate.
4. **The acquisition endpoint requires caller confirmation.** A real network acquisition uses `POST /api/intelligence/company/{slug}/enrich/importyeti?confirm_paid=true`.
5. **Existing cache is returned without another purchase.** A repeat acquisition requires an explicit refresh rather than being triggered by browsing.
6. **Negative lookup results are persisted.** A failed/ambiguous lookup is reused until an explicit refresh, preventing repeated paid searches for the same unresolved company.

A fixture can exercise the same normalization/cache path in CI without making a network request or consuming credits.

## Registered bulk sources

Use:

```bash
python scripts/intelligence_sync.py --list
```

Sync Corporations Canada:

```bash
python scripts/intelligence_sync.py corporations_canada --sample 3
```

Sync Canadian Importers Database:

```bash
python scripts/intelligence_sync.py canadian_importers --sample 3
```

Downloads are cached under `data/intelligence/<source>/` by default.

## Credentials

Public-source adapters should not require private credentials when bulk/open access exists.

Optional enrichment uses environment variables such as:

```text
HUNTER_API_KEY=...
IMPORTYETI_API_KEY=...
IMPORTYETI_ALLOW_LIVE=false
SEC_EDGAR_USER_AGENT=IntellCluster/1.0 contact@intellcluster.com
```

Never commit live credentials to the repository.

## Production sequencing

Long-running corpus ingestion and application deployment are operationally separate. GitHub-safe code work can continue while ingestion runs, but production pulls/redeploys, live endpoint validation and large U.S. bootstrap jobs should occur only after the active ingestion process has completed and the production database has been checked.
