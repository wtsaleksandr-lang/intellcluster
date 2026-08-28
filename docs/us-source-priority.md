# USA source ingestion priority

Do not treat SEC listing/exchange membership as proof that a company is U.S.-domiciled. Foreign issuers trade and file in EDGAR, so ticker-only ingestion must not assign `country=US`.

## Recommended order

### 1. U.S. identity anchors

Prefer sources that expose an authoritative country/address identifier:

- SAM.gov registered entities / UEI where API access is configured
- USASpending recipient entities and addresses
- FMCSA entities for transportation companies
- EPA ECHO facilities/entities

These can establish U.S. canonical entities with location evidence.

### 2. SEC EDGAR evidence

Attach SEC evidence by CIK/name/address matching after the entity exists or after EDGAR submission metadata confirms domicile/address. Do not use ticker-only files as a blanket U.S. company directory.

Useful SEC evidence:

- CIK
- tickers/exchanges
- SIC
- filing history
- company facts / financial context
- former names

### 3. ImportYeti trade intelligence

ImportYeti remains a paid, selective trade-enrichment layer. Normal browsing remains cached-only. Paid acquisition happens only when explicitly enabled/triggered.

### 4. Additional public layers

- USASpending / SAM.gov: contracts and federal identity
- FMCSA: DOT/fleet/authority
- EPA ECHO: facilities/environmental compliance
- OSHA: inspection/enforcement signals
- USPTO: patents/trademarks

## Entity-resolution rule

No U.S. source should create a canonical entity with a guessed country. Country must be explicit in the source record or established through sufficiently strong address/identity evidence.
