Are healthy foods more expensive in Switzerland?

### Research question
Is there a correlation between the price per 100 g of food and its nutritional quality, and does this correlation vary across different retail chains and product categories?

---

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

Both sources are collected by us. No ready-made datasets are used as a primary
source.

### 1. Retailer product catalogue — web scraping

| | |
|---|---|
| **Source** | Swiss online grocery retailer (product listing and detail pages) |
| **Method** | `requests` + `BeautifulSoup`, paginated category crawl |
| **Fields** | product name, brand, price, package size, category path, organic flag, EAN |
| **Volume** | ~ *TODO* products across *TODO* categories |
| **Collected** | *TODO: date range* |

Scraping is rate-limited to one request per second, identifies itself with a
descriptive `User-Agent`, and respects the site's `robots.txt`. Raw HTML responses
are cached locally so the analysis is reproducible without re-scraping.

### 2. Open Food Facts — public API

| | |
|---|---|
| **Source** | https://world.openfoodfacts.org (open database, ODbL licence) |
| **Method** | REST API, product lookup by EAN with a name-based fallback |
| **Fields** | energy, sugar, fat, saturated fat, salt, protein, fibre (per 100 g), Nutri-Score, NOVA group, countries of origin |

---

## Data integration

The two sources are joined in two passes, and both the matches and the losses are
documented in `notebooks/03_integration_db.ipynb`.

```
retailer products          Open Food Facts
       │                          │
       ├──── exact match on EAN ──┤   pass 1
       │                          │
       └─ fuzzy match on brand ───┘   pass 2 (rapidfuzz, threshold TODO)
          + normalised name
```

| Step | Records |
|---|---|
| Scraped products | *TODO* |
| Matched by EAN | *TODO* |
| Additionally matched by name | *TODO* |
| Unmatched (dropped) | *TODO* |
| Complete nutrition after cleaning | *TODO* |

Known sources of loss: retailer private labels are under-represented in Open Food
Facts, fresh unpackaged goods carry no EAN, and some entries have partial nutrition
tables. The unmatched set is profiled rather than silently discarded — if private
labels drop out systematically, that biases the price comparison and has to be
stated as a limitation.

---

## Analysis pipeline

| Stage | Notebook | What happens |
|---|---|---|
| Collection | `01_scraping.ipynb` | Crawl catalogue, parse, write raw CSV |
| Collection | `02_api_openfoodfacts.ipynb` | Query API, cache JSON responses |
| Integration | `03_integration_db.ipynb` | Match, clean, normalise to price per 100 g, load into PostgreSQL |
| Exploration | `04_eda.ipynb` | Distributions, missingness, correlations, category breakdowns, origin map |
| Modelling | `05_modeling.ipynb` | Regression, k-means, hypothesis tests, evaluation |

### Methods

- **Regression** — price per 100 g on nutritional composition, category, retailer,
  organic flag and origin. Evaluated with R², adjusted R², RMSE and MAE on a held-out
  test set, with residual diagnostics.
- **k-means clustering** — products grouped by standardised nutrient profile, with
  *k* selected by elbow and silhouette score.
- **Statistical tests** — chi-squared on the Nutri-Score distribution across
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
           └── retailers      (n:1)
```

Connection settings live in `.env` (not committed). See `.env.example` for the
expected variables.

---

## Repository structure

```
.
├── notebooks/            # analysis, in execution order
├── src/                  # reusable functions imported by the notebooks
│   ├── scraping.py
│   ├── openfoodfacts.py
│   ├── matching.py
│   └── db.py
├── data/
│   ├── raw/              # scraper and API output (gitignored)
│   └── processed/        # cleaned, joined dataset
├── docs/
│   ├── ai_usage.md       # running log of AI tool usage
│   └── presentation.pdf
├── sql/                  # schema and query definitions
├── requirements.txt
└── .env.example
```

## Getting started

```bash
git clone https://github.com/TODO/TODO.git
cd TODO

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # then fill in your database credentials
```

Run the notebooks in numerical order. Stages 01 and 02 write to `data/raw/` and can
be skipped if that directory is already populated — the later notebooks read from
disk, not from the network.

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

- Prices are a single snapshot, so no seasonal or temporal variation is captured.
- Nutri-Score coverage in Open Food Facts is incomplete and skewed towards branded
  products.
- Shelf price is not the same as price paid: promotions and loyalty discounts are
  outside the scope of this data.
- Nutritional quality is operationalised through Nutri-Score and raw nutrient
  values, which is a simplification of a contested concept.
