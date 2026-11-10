# Are healthy foods more expensive in Switzerland?

## Research question

> **Is there a measurable "health premium" on Swiss groceries, and does it differ
> between retailers, product categories and domestic versus imported products?**

In other words: "Is there a correlation between the price per 100 g of food and its nutritional quality, and does this correlation vary across different retail chains and product categories?"

The question studies more than just a price:

1. **Group comparison.** We fit the price model separately per retailer and test
   whether the nutrition coefficients differ.
2. **Origin effect.** We treat country of origin as a predictor, which lets us
   separate a health premium from an import premium.
3. **Structure discovery.** We cluster products by nutritional profile and compare
   price distributions across clusters, rather than assuming the official
   Nutri-Score categories are the relevant grouping.

**Hypotheses**

| # | Hypothesis |
|---|---|
| H1 | Price per 100 g rises as Nutri-Score worsens from A to E, after controlling for category |
| H2 | The size of the health premium differs significantly between retailers |
| H3 | Imported products are more expensive than domestic ones at comparable nutritional quality |

---

## Data sources

| Source | What it gives | How | Snapshot |
|---|---|---|---|
| **Aldi Suisse** (aldi-suisse.ch) | price, package size, brand, category, ingredients | scraping of the shop's public JSON API | 2026-11-03 |
| **Volgshop** (volgshop.ch) | price, package size, nutrition table, production country, ingredients | scraping of the shop's public JSON API (WooCommerce) | 2026-11-03 |
| **Open Food Facts** (ODbL) | nutrients per 100 g, Nutri-Score, NOVA, categories, EAN | full CSV export (the API is capped at 100 results per page and rate-limited) | 2026-11-02/03 |
| **Open Prices** (ODbL) | crowdsourced shelf and receipt prices for Migros, Coop, Lidl, Denner, by EAN | public API | 2026-11-10 |

Scraping is rate-limited to one request per second, identifies itself with a descriptive
`User-Agent` and only uses paths that `robots.txt` allows. Migros, Coop and Lidl block
automated access, and that protection was not circumvented; their prices come from Open
Prices instead. Every raw snapshot is versioned in `data/raw/` with its SHA-256 in the
metadata files, so the analysis is reproducible without downloading again (OFF changes
daily).

---

## Data integration

```
Aldi, Volgshop (no EAN)          Open Prices (EAN)
        │                               │
        │ brand + fuzzy name            │ exact EAN
        │ (rapidfuzz, score ≥ 90,       │
        │  or ≥ 75 with same size)      │
        ▼                               ▼
              Open Food Facts (CH; DE/AT for Aldi brands)
                          │
                          ▼
   products_matched: price per 100 g/ml + nutrition + Nutri-Score + common category
```

| Step | Aldi | Volgshop | Migros | Coop | Lidl | Denner |
|---|---:|---:|---:|---:|---:|---:|
| Clean products with price per 100 g/ml | 1 577 | 445 | 242 | 131 | 33 | 15 |
| Matched to OFF | 273 | 122 | 242 | 131 | 33 | 15 |
| With nutrition (shop or OFF) | 273 | 395 | 242 | 131 | 33 | 15 |
| With Nutri-Score (OFF or computed) | 265 | 387 | 238 | 127 | 33 | 14 |
| **Analysable** (+ common category) | **257** | **386** | **233** | **123** | **33** | **13** |

In total, **1 045 products** have a price per 100 g/ml, a Nutri-Score and a common
category.

The main steps beyond the join:
- **Nutri-Score.** It is computed with the 2023 algorithm where OFF has none (358
  products, mostly Volgshop with its own nutrition table). Validated against OFF's grades:
  97.7 % agreement.
- **Common category.** Every product gets one of the 9 PNNS groups: OFF's group where it
  exists, otherwise from the shop category and the product name.
- **Matching validation.** For Volgshop, 90 % of the matches agree on nutrition with the
  shop's own table. A manual review of 100 matches found no errors.

Known sources of loss:
- Aldi's Swiss-exclusive own brands (Saveurs Suisses, Panetteria) are absent from OFF.
- Fresh and loose goods have no package size or EAN.
- Open Prices is a volunteer sample, not a random one.

Every filter and its row count is documented in `docs/` (see below).

---

## Analysis pipeline

| Stage | Where | What happens | Status |
|---|---|---|---|
| Collection | `src/openfoodfacts.py`, `src/scraping.py`, `src/openprices.py` | Download OFF, scrape Aldi and Volgshop, download Open Prices | done |
| Cleaning | `src/openfoodfacts.py`, `src/retail_cleaning.py`, `src/openprices.py` | Filters and transformations, each logged with before/after counts | done |
| Integration | `src/matching.py` (+ `nutriscore.py`, `categories.py`) | Match to OFF, compute missing Nutri-Scores, common category → `products_matched` | done |
| Database | `sql/`, `src/db.py` | Load into PostgreSQL | to do |
| Exploration | `notebooks/04_eda.ipynb` | Distributions, missingness, correlations, category breakdowns, origin | to do |
| Modelling | `notebooks/05_modeling.ipynb` | Regression, k-means, hypothesis tests, evaluation | to do |

### Methods

- **Regression**: price per 100 g on nutritional composition, category, retailer,
  organic flag and origin. Evaluated with R², adjusted R², RMSE and MAE on a held-out
  test set, with residual diagnostics.
- **k-means clustering**: products grouped by standardised nutrient profile, with
  *k* selected by elbow and silhouette score.
- **Statistical tests**: chi-squared on the Nutri-Score distribution across
  retailers, ANOVA on price across categories, and Pearson/Spearman correlations
  between individual nutrients and price. All reported with p-values and effect
  sizes.

---

## Database

Data is stored in **PostgreSQL** and queried from Python via SQLAlchemy. Joins and
aggregations run in SQL rather than in pandas wherever the operation belongs in the
database.

```
products ──┬── nutrition      (1:1 on product_id)
           ├── categories     (n:1)
           ├── retailers      (n:1)
           └── off_products   (n:1 on EAN)
```

The load source is `data/processed/products_matched.parquet` (one row per product and
chain). Its columns, keys and a proposed schema are described in
[`docs/For_Vojta.md`](docs/For_Vojta.md) (in Czech). Connection settings live in `.env`
(not committed). See `.env.example` for the expected variables.

---

## Documentation of decisions

| Document | Covers |
|---|---|
| [`docs/off_cleaning_decisions.md`](docs/off_cleaning_decisions.md) | Open Food Facts extraction and cleaning (107 342 → 73 738 products) |
| [`docs/retail_cleaning_decisions.md`](docs/retail_cleaning_decisions.md) | Aldi and Volgshop cleaning |
| [`docs/openprices_decisions.md`](docs/openprices_decisions.md) | Open Prices cleaning (Migros, Coop, Lidl, Denner) |
| [`docs/matching_decisions.md`](docs/matching_decisions.md) | Matching to OFF and the combined table |
| [`docs/nutriscore_decisions.md`](docs/nutriscore_decisions.md) | Computed Nutri-Score and its validation |
| [`docs/category_decisions.md`](docs/category_decisions.md) | Common category across shops and its validation |
| [`docs/For_Vojta.md`](docs/For_Vojta.md) | Data guide for building the database (Czech) |
| [`docs/ai_usage.md`](docs/ai_usage.md) | Log of AI tool usage |

The rule identifiers in these documents (F1, C1, M1…) appear as comments in the code.

---

## Repository structure

```
.
├── notebooks/            # EDA and modelling, in execution order
├── src/
│   ├── openfoodfacts.py  # OFF download, Swiss extract, cleaning (+ DE/AT and Open Prices extensions)
│   ├── scraping.py       # Aldi and Volgshop scrapers
│   ├── retail_cleaning.py
│   ├── openprices.py     # Open Prices download and cleaning
│   ├── matching.py       # matching to OFF, builds products_matched
│   ├── nutriscore.py     # Nutri-Score 2023 algorithm and validation
│   ├── categories.py     # common PNNS category and validation
│   └── db.py             # PostgreSQL connection (to do)
├── data/
│   ├── raw/              # snapshots: versioned parquet extracts; large dumps and API logs gitignored
│   └── processed/        # cleaned tables, products_matched, cleaning logs, metadata
├── docs/                 # decision logs, data guide, AI usage log
├── sql/                  # schema and query definitions
├── requirements.txt
└── .env.example
```

## Getting started

```bash
git clone https://github.com/wflouis/supermarkets.git
cd supermarkets

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # then fill in your database credentials
```

The processed data is in the repository, so the notebooks can be run directly. To
rebuild it from scratch (the OFF download is ~1.5 GB):

```bash
python src/openfoodfacts.py all             # OFF: download, Swiss extract, cleaning
python src/scraping.py all                  # Aldi and Volgshop
python src/retail_cleaning.py               # shop catalogue cleaning
python src/openfoodfacts.py aldi-ext        # German/Austrian OFF entries for Aldi brands
python src/scraping.py aldi-details         # Aldi ingredient lists
python src/openprices.py all                # Migros/Coop/Lidl/Denner prices
python src/openfoodfacts.py openprices-ext  # OFF entries for Open Prices EANs
python src/matching.py                      # matching + products_matched
```

---

## Use of AI

AI assistance was used throughout and is documented in [`docs/ai_usage.md`](docs/ai_usage.md),
which records what each tool was asked for, whether the output was usable, and what
had to be corrected by hand. The log is written as we go rather than reconstructed
at the end, so that the failures are recorded as faithfully as the successes.

Summary of findings on AI usage: *TODO — fill in before the presentation.*

---

## Team

| Name | Focus |
|---|---|
| *TODO* | Data collection (scraping, API) |
| *TODO* | Database and integration |
| *TODO* | EDA, modelling, statistical testing |

Every member can explain the full pipeline, not only their own part.

---

## Limitations

- **Prices come from different dates.** Aldi and Volgshop are a single snapshot
  (2026-11-03). Open Prices prices are from 2024–2026 (`price_date` allows controlling for
  this). No seasonal variation is captured.
- **Regular shelf prices only.** Promotions and loyalty discounts are excluded.
- **The sample is not the full range.** Open Prices reflects what its 123 contributors buy,
  mostly in French-speaking Switzerland. Aldi's coverage is biased towards brands shared
  with Aldi Süd, because its Swiss-exclusive brands are not in OFF.
- **A third of the Nutri-Scores are computed by us** (358 of 1 064), with an estimated
  fruit/vegetable/legume share. `nutriscore_source` allows a sensitivity check with OFF
  grades only.
- **Origin is thin and means two things.** Volgshop gives the country of manufacture (426
  products); OFF gives the origin of the ingredients (179 products). H3 is mainly testable
  within Volgshop.
- **Small groups.** Lidl (33) and Denner (15) are too small for comparisons by category;
  H2 by category is limited to Aldi, Volgshop, Migros and Coop.
- **Nutritional quality is a simplification.** It is operationalised through the
  Nutri-Score and raw nutrient values, which simplifies a contested concept.
