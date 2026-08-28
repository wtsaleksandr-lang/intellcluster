# IntellCluster isolated UI preview

The visual preview is deliberately separated from the development/ingestion database.

## Why

Long-running Canada/USA ingestion can continue against PostgreSQL while a second process renders the latest UI against a tiny representative SQLite database. Visual development must not require restarting or modifying the ingestion process.

## Preview data

The fixture includes:

- a Canadian importer with registry evidence, HS codes and origin countries;
- a U.S. company with cached ImportYeti-style shipment/supplier metrics;
- USAspending-style contract intelligence;
- FMCSA-style fleet intelligence.

This makes Canada and USA layouts testable without paid API calls or the multi-million-row database.

## Run locally or in a separate Replit preview workspace

```bash
uvicorn main_preview:app --host 0.0.0.0 --port 5001
```

The preview entrypoint:

1. sets `INTELLIGENCE_PREVIEW=1`;
2. removes `DATABASE_URL` from that preview process;
3. forces `INTELLIGENCE_DB_PATH=data/intelligence-preview.db`;
4. seeds representative fixture data on first run;
5. imports the normal `main_data` application/UI.

To rebuild fixture data on startup:

```bash
INTELLIGENCE_PREVIEW_RESEED=1 uvicorn main_preview:app --host 0.0.0.0 --port 5001
```

## Safety rule

Do not change the existing Replit workspace process while a long ingestion is running. For a browser-accessible preview, create a separate Replit workspace/deployment from the same GitHub branch and use `main_preview:app` there. The preview must not be given the ingestion PostgreSQL `DATABASE_URL`.

No ImportYeti live flag or API key is required for the fixture preview.
