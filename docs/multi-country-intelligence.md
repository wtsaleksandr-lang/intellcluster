# IntellCluster multi-country intelligence architecture

IntellCluster is one company-intelligence directory, not separate Canada and USA products.

## Universal entity model

Each canonical company has one profile. Country-specific data sources attach evidence to that entity through source records and enrichment caches.

Primary markets:

- Canada (`CA`)
- United States (`US`)

Search and APIs should support `country=CA`, `country=US`, or no country filter for all markets.

## Universal profile layout

Keep the same section order across markets:

1. Overview
2. Trade
3. Suppliers
4. Products
5. Geography
6. Relationships
7. Facilities
8. Compliance
9. Contracts
10. Fleet
11. Patents
12. Contacts

A section carries an evidence status instead of disappearing or presenting missing data as zero. Supported states include `available`, `cached`, `unlockable`, `market_context`, `on_demand`, `planned`, `pending`, and `not_available`.

## United States

### Trade layer

Use the ImportYeti API selectively and cache purchased responses. Normal profile browsing must remain cached-only by default. A paid call is an intentional acquisition event, not a page-view dependency.

Target trade fields where exposed by the API:

- shipment count
- most recent shipment
- supplier relationships
- products / descriptions
- HS codes
- source countries
- ports / lanes
- containers / TEU / weight where available
- BOL evidence
- shipment frequency / time series

### Free/public intelligence layers

Planned adapters:

- SAM.gov / USASpending: federal entity and contract evidence
- FMCSA: DOT authority, fleet and carrier evidence
- EPA ECHO: regulated facilities and environmental/compliance evidence
- OSHA: inspections and workplace enforcement evidence
- SEC EDGAR: public-company filing and identifier evidence
- USPTO: patent/trademark evidence

These sources should enrich the same canonical company rather than create separate directory silos.

## Canada

### Company/public-record layer

Current sources:

- Corporations Canada
- Canadian Importers Database

### Trade presentation

Do not imply that unavailable company-level shipment data equals zero shipments.

If company-level shipment evidence is unavailable, the Trade section should explicitly say that shipment-level intelligence is not currently available for that Canadian company. Where importer/HS evidence exists, show `market_context` instead.

Planned market context sources:

- Statistics Canada commodity/trade time series
- country-of-origin share
- province-level market activity where available
- monthly/annual growth and seasonality

Market-level statistics must be visibly labelled as market context and must not be attributed to the individual company.

### Commercial Canadian shipment providers

Panjiva and ImportGenius remain evaluation candidates for company-level Canadian shipment/supplier data. Do not subscribe until the free/public build demonstrates the value of the missing shipment layer and licensing/API economics are reviewed.

## Product principle

The target is not a visual clone of ImportYeti. U.S. company profiles should be capable of ImportYeti-level trade density where purchased API fields permit it, then exceed a trade-only product by adding regulatory, facility, fleet, contract, patent, web and contact intelligence.
