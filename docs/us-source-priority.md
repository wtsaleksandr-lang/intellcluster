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

SEC EDGAR is implemented as a free, on-demand enrichment layer after a canonical U.S. entity already exists. The current matcher uses SEC ticker/CIK associations conservatively, requires one strong company-name match, then caches submission metadata. Normal company-profile views reuse the cache and do not call SEC network endpoints.

Useful SEC evidence currently cached:

- CIK
- tickers/exchanges
- SIC and SIC description
- recent filing history with official filing links
- state of incorporation
- fiscal year end
- former names

The ticker association file is not exhaustive. A missing match is not evidence that the entity has never filed with the SEC. SEC evidence also does not override the canonical entity's country.

### 3. ImportYeti trade intelligence

ImportYeti remains a paid, selective trade-enrichment layer. Normal browsing remains cached-only. Paid acquisition happens only when explicitly enabled/triggered.

### 4. Additional public layers

- USASpending / SAM.gov: contracts and federal identity
- FMCSA: DOT/fleet/authority
- EPA ECHO: facilities/environmental compliance
- OSHA: inspection/enforcement signals
- SEC EDGAR: public-company filings and issuer metadata
- USPTO PatentsView / Open Data Portal: patents and assignee intelligence

## USPTO status

Do not build against the legacy PatentsView API right now. USPTO moved PatentsView to the Open Data Portal in March 2026 and temporarily paused or migrated several search/API functions during the transition. Bulk PatentsView datasets remain available and are a viable later ingestion path, but company-linked API enrichment should wait until the replacement ODP interface is stable enough to avoid building against a moving contract.

## Entity-resolution rule

No U.S. source should create a canonical entity with a guessed country. Country must be explicit in the source record or established through sufficiently strong address/identity evidence.
