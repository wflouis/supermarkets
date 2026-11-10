# Open Prices: decisions

Script: [`src/openprices.py`](../src/openprices.py) · Reproducible counts in
[`data/processed/openprices_cleaning_log.csv`](../data/processed/openprices_cleaning_log.csv) ·
Provenance in [`data/processed/openprices_metadata.json`](../data/processed/openprices_metadata.json)

[Open Prices](https://prices.openfoodfacts.org) is the sister project of Open Food Facts:
volunteers record prices from photos of shelf tags or receipts, linked to the product's
EAN and to the shop (an OpenStreetMap location). ODbL licence, like OFF.

It is used to get prices for **Migros and Coop**, which block scraping. Since every price
carries the EAN, the join with OFF is exact: the name matching used for Aldi and Volgshop is
not needed.

The identifiers (F1, C1, N1…) belong to this document.

## Funnel summary

Download of all prices in CHF on 2026-11-10 (`GET /api/v1/prices?currency=CHF`).

| Rule | What it removes | Removed | Remaining |
|---|---|---:|---:|
| — | Prices in CHF | | 1 050 |
| F1 | Price without EAN (loose-produce category) | 4 | 1 046 |
| F2 | Shop outside Switzerland (Liechtenstein 101, France 1) | 102 | 944 |
| F3 | Shop not belonging to a Swiss supermarket chain | 70 | 874 |
| F4 | Promotional price | 70 | 804 |
| F5 | Price per kg of loose goods | 0 | 804 |
| C1 | One price per (chain, EAN) | 136 | 668 |
| F6 | EAN without a clean OFF entry (no complete nutrition) | 139 | 529 |
| F7 | No package size in g or ml in OFF | 94 | 435 |
| F8 | Price per 100 g/ml outside CHF 0.01–50 | 0 | **435** |

| Chain | Products | With Nutri-Score | Price dates |
|---|---:|---:|---|
| Migros | 242 | 226 | 2024-04 – 2026-10 |
| Coop | 131 | 122 | 2024-04 – 2026-11 |
| Lidl | 33 | 32 | 2024-06 – 2026-06 |
| Denner | 15 | 13 | 2025-01 – 2026-08 |
| Aldi | 14 | 14 | (not used, M11) |

---

## F. Filters (remove rows)

**F1. Only prices of products with an EAN.** Open Prices also accepts prices per category
("apples, 1 kg") without a code. *Rationale:* without an EAN there is no join with OFF's
nutrition.

**F2. Only shops in Switzerland** (`osm_address_country_code = 'CH'`). The CHF query also
returns Liechtenstein (Coop Schaan: 100 prices). *Rationale:* the question is about
Switzerland, and Liechtenstein has a different tax regime.

**F3. The shop must belong to a Swiss supermarket chain.** The chain comes from the shop's
OSM brand (`osm_brand`) or, failing that, its name (`osm_name`), when it starts with Migros,
Coop, Denner, Lidl, Aldi or Volg. The location must also be a shop (`osm_tag_value` in
supermarket, convenience, department_store, mall, kiosk, general).
- *Formats with their own price list are excluded:* Coop Pronto, Migrolino and Denner
  Express (franchised convenience stores with higher prices), Coop Vitality (pharmacy),
  Migros Restaurant and Migros Online.
- *Two shopping centres are assigned by hand* (`LOCATION_CHAIN`), because OSM names the
  centre, not the shop. The assignment comes from the own brands bought there: at "La
  Maladière centre" (Neuchâtel, 41 prices) they are Coop, Naturaplan and Betty Bossi; at
  "Métropole Centre" (La Chaux-de-Fonds, 39 prices) Migros, M-Budget and M-Classic.
- *What is removed* (70): other shops (Manor 9, Seelan Market 9, Aligro 5, Sapori d'Italia
  5, VOI 2…), the excluded formats (12) and locations that are not shops (car-sharing
  stations, a stadium, Lidl Switzerland's head office).

**F4. Only regular prices** (`price_is_discounted = false`). *Rationale:* the same rule as
for Aldi (C1 of the retail cleaning). A promotion measures one week's commercial strategy,
not the product's price.

**F5. Only per-item prices** (`price_per` empty). Prices per kg are for loose products. No
cases after F1.

**F6. The EAN must be in a clean OFF table.** First the Swiss one (`off_ch_clean.parquet`).
If the entry is not tagged Switzerland, the entry of the same EAN from another country is
used (`off_openprices_ext_clean.parquet`, E8 of
[`off_cleaning_decisions.md`](off_cleaning_decisions.md)): it contributes 58 products. 139
are removed: almost all have an OFF entry, but the OFF cleaning dropped it for incomplete
nutrition (F6 of OFF), or the EAN is not in the export.

**F7. The package size in g or ml is needed** (OFF's `product_quantity`) for the price per
100 g/ml. *Using the size carried by Open Prices as a fallback was tested:* it agrees with
OFF in 496 of 505 cases, but it would have recovered only 1 product, so it is not used.

**F8. Price per 100 g/ml between CHF 0.01 and 50**, as F6 of the retail cleaning. No cases.

## C. Transformations

**C1. One price per (chain, EAN): the most recent.** If there are several prices that day
(from different shops), the median is taken. The number of observations (`price_n_obs`),
of shops (`price_n_shops`) and the first date (`price_first_date`) are also kept.
*Rationale:* our Aldi and Volgshop prices are from 2026-11-03, and the most recent price is
the closest. Repeated regular prices of the same product vary little: across the 90
products with more than one observation, the max–min difference has a median of 0 % and a
90th percentile of 8 %.

**C2. Nutrition, Nutri-Score, NOVA and PNNS category come from OFF**, joined by EAN.
`off_scope` says whether the entry is Swiss (`ch`) or from another country
(`openprices_ext`).

## N. What was deliberately not done

**N1. No filter on date.** 7–8 % of the Migros and Coop prices are from 2024, 62 % from 2025
and the rest from 2026. Food inflation in Switzerland is low (about 1 % a year), and
`price_date` allows controlling for date or a sensitivity analysis (e.g. 2025–2026 only).

**N2. No validation against the Aldi scrape.** The plan was to compare Open Prices prices
with the Aldi catalogue for the same EANs, but none of the 14 Aldi products on Open Prices is
among the 273 Aldi matches with OFF.

**N3. No correction by shop.** Migros is a federation of regional cooperatives, and prices
vary a little between regions. The prices come mostly from French-speaking Switzerland
(Geneva, Nyon, Neuchâtel).

## Known biases

- **Not a random sample of the range.** There are 123 contributors, and the 5 most active
  provide about 60 % of the prices. The products reflect what these people buy (more sweet
  snacks and cereals at Migros, few fresh products at both chains).
- **Packaged products.** Because of F1 and F7, loose fruit, vegetables, meat and bread barely
  appear, as at Aldi and Volgshop after matching.
- **Lidl and Denner** have too few products (33 and 15) to be compared as groups of their
  own.
