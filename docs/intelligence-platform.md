# IntellCluster Intelligence Platform

## Goal

Turn large public/open datasets into reusable, searchable business-intelligence verticals without duplicating application logic for every directory.

The platform separates four concerns:

1. **Source adapters** download and normalize public data while preserving provenance.
2. **Entity resolution** links records from different sources that represent the same company/facility/entity.
3. **Enrichment** adds websites, contacts and AI-derived classifications lazily and caches them.
4. **Vertical products** expose purpose-built search/filtering experiences such as importers, industrial facilities, food plants and aviation.

## Initial source roadmap

### Phase 1 — Canada business/buyer intelligence
- Corporations Canada bulk CSV
- Canadian Importers Database (2023)
- domain/website discovery
- Hunter contact enrichment
- AI industry/product classification

### Phase 2 — Industrial
- EPA ECHO
- OSHA establishment/inspection data

### Phase 3 — Regulated manufacturing
- USDA facility datasets
- FDA datasets

### Phase 4 — Aviation
- FAA Aircraft Registry

### Later
- SAM/USAspending and tenders
- EU TED procurement
- patent datasets

## Data principles

- Keep the original source record and source URL for provenance/attribution.
- Never make paid enrichment a requirement for basic public directory pages.
- Enrich lazily on viewed/searched/exported entities rather than the full corpus.
- Cache enrichment responses to control API costs.
- Keep source-specific fields in `attributes` while promoting common fields to the normalized model.
- Treat entity resolution as probabilistic and retain confidence scores.
- Public SEO pages should combine useful source facts rather than reproducing thin raw records.

## Registered sources

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
OPENAI_API_KEY=...
```

Never commit live credentials to the repository.

## Next implementation slice

1. Persistence layer (PostgreSQL in production, lightweight local option for development).
2. Canonical entity/entity-source tables.
3. Deterministic company-name/address normalization.
4. Fuzzy entity matching with auditable confidence signals.
5. HS6/HS10 taxonomy loader and importer relationship tables.
6. Search API with structured filters.
7. Canada business/importer profile pages.
8. Lazy website/contact/AI enrichment queue.
