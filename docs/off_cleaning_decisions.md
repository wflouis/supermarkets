# Open Food Facts: extraction, filtering and cleaning decisions

Script: [`src/openfoodfacts.py`](../src/openfoodfacts.py) · Reproducible counts in
[`data/processed/off_ch_cleaning_log.csv`](../data/processed/off_ch_cleaning_log.csv) ·
Snapshot provenance in [`data/processed/off_ch_metadata.json`](../data/processed/off_ch_metadata.json)

The identifiers (E1, F1, C1, N1…) appear as comments in the code, so every rule can be
traced to the line that implements it.

- **E**: extraction, i.e. what is downloaded and what enters the Swiss subset.
- **F**: filters that **remove rows**.
- **C**: cleaning and transformations that **do not remove rows**.
- **N**: things that were deliberately **not** done.

## Funnel summary

Snapshot of the export downloaded on 2026-11-02.

| Rule | What it removes | Removed | Remaining |
|---|---|---:|---:|
| E3 | Products not tagged as sold in Switzerland | ~4.78 M | 107 342 |
| F1 | Code that is not a valid EAN-8/EAN-13 | 1 775 | 105 567 |
| F2 | Duplicate code | 1 | 105 566 |
| F3 | Alcoholic beverages | 1 818 | 103 748 |
| F4 | Baby food | 290 | 103 458 |
| F5 | Non-food | 117 | 103 341 |
| F6 | Incomplete nutrition table | 29 025 | 74 316 |
| F7a | Nutrient outside 0–100 g | 25 | 74 291 |
| F7b | Energy outside 0–3800 kJ | 4 | 74 287 |
| F7c | Saturated fat > fat, or sugars > carbohydrates | 123 | 74 164 |
| F7d | Sum of macronutrients > 105 g | 230 | 73 934 |
| F7e | Inconsistent energy | 196 | **73 738** |

Of the 73 738 final products, 42 230 have a Nutri-Score A–E; 12 534 can be attributed to
Migros (7 185 with a Nutri-Score) and 9 561 to Coop (5 873 with a Nutri-Score).

---

## E. Extraction

**E1. Source: the full OFF CSV export, not the API or the Hugging Face parquet.**
URL: `static.openfoodfacts.org/data/en.openfoodfacts.org.products.csv.gz` (~1.5 GB).
*Rationale:* the search API returns at most 100 products per page and rate-limited our
requests (503, then 401), so it cannot deliver ~100 000 products. The Hugging Face parquet
is ~8 GB and also rate-limited partial reads. The CSV is the official full dump, is
downloaded with a single request and is what OFF recommends for bulk use. The download
identifies itself with a User-Agent naming the project, as OFF asks.

**E2. Only 37 of the ~210 columns are kept.**
Kept: identifier, name, brand, quantity, stores, categories, Nutri-Score, NOVA, origin,
labels, the per-100 g nutrients used in the analysis and quality metadata.
*Rationale:* the other columns (images, URLs, additives, vitamins and minerals, specific
fatty acids, allergens) play no role in any hypothesis. Dropping them shrinks the file
from 1.5 GB to 9 MB, small enough to version in git.

**E3. Country filter: `countries_tags` contains `en:switzerland`.**
*Rationale:* the research question is about the Swiss market. The normalised tag
(`en:switzerland`) is used, not the free-text `countries` field, which mixes languages
("Suisse", "Schweiz", "Svizzera"). The tag is matched exactly within the list, not with
`LIKE`, so substrings are not captured.
*Note:* 21 248 of the final products are also tagged in other countries. They are kept: a
product sold in Switzerland and Germany is still a Swiss product for our analysis.

**E4. Everything is read as text; typing happens later.**
The CSV is tab-separated and unquoted (`quote=''`).
*Rationale:* if DuckDB guessed types, one malformed row could drop or corrupt a whole
column. `quote=''` stops a stray quote inside a product name from "swallowing" the
following lines. Unparseable rows are logged with `store_rejects`; in this snapshot there
were 0 out of 4.89 M lines.

**E5. The raw Swiss subset (`data/raw/off_ch_raw.parquet`) is versioned in git. The
1.5 GB CSV is not.**
*Rationale:* OFF is edited daily, so downloading again does not reproduce the same data.
Versioning the extract freezes the snapshot we used. The full CSV exceeds GitHub's 100 MB
limit. The extract's SHA-256 is stored in the metadata JSON.

**E6. Aldi extension: German and Austrian entries** (`python src/openfoodfacts.py
aldi-ext`, `data/raw/off_aldi_ext_raw.parquet`).
From the export downloaded on 2026-11-03, products **not** tagged Switzerland but tagged
Germany or Austria (`en:germany`, `en:austria`) are extracted when their brand is one Aldi
Suisse sells (a whole `brands` entry, excluding generic brands such as "Bio") or their
store mentions Aldi or Hofer. The same 37 columns are extracted and cleaned with exactly
the same rules F1–F7 and C1–C12 as the Swiss subset: 23 824 rows become 15 162
(`off_aldi_ext_cleaning_log.csv`, `off_aldi_ext_clean.parquet`).
*Rationale:* many Aldi Suisse own brands are the same as Aldi Süd's and Hofer's, and
without this step only 6.5 % of Aldi's range was matched. That a German entry can stand in
for the Swiss product is checked in M10 of [`matching_decisions.md`](matching_decisions.md).
This extract comes from a newer snapshot than the Swiss one (2026-11-02). The Swiss subset
was **not** re-extracted, so the data that earlier steps depend on did not change.

**E7. Ingredients** (`data/raw/off_ingredients.parquet`). `ingredients_text` for every code
in the Swiss and E6 extracts, from the same snapshot as E6. Used only to confirm or veto
matches (M9) and to detect sweeteners in the Nutri-Score validation. The export has no language
column; German is detected in `matching.py`. Provenance (URL, download date, SHA-256) is in
`off_ch_metadata.json` under `aldi_extension`.

**E8. Open Prices extension: non-Swiss entries of products with a price in Switzerland**
(`python src/openfoodfacts.py openprices-ext`, `data/raw/off_openprices_ext_raw.parquet`).
Of the EANs with a price in a Swiss shop on Open Prices
([`openprices_decisions.md`](openprices_decisions.md)), 177 are not in the Swiss extract.
Their entries from any country are taken from the 2026-11-03 export (137 found) and
cleaned with the same rules F1–F7 and C1–C12: 105 remain
(`off_openprices_ext_cleaning_log.csv`). *Rationale:* the price proves the product is sold
in Switzerland, and the EAN identifies the exact product. Unlike E6, there is no need to
assume that an entry from another country describes a product with the same name.
Provenance in `off_ch_metadata.json` under `openprices_extension`.

## F. Filters (remove rows)

**F1. The code must be a valid EAN-8 or EAN-13 with a correct check digit.**
Codes are normalised first: a 12-digit UPC-A gets a leading `0`; a GTIN-14 starting with
`0` loses it (see C3).
- 889 codes of non-standard length are removed. Most have 24 digits, such as
  `2776108499298…000260`: these are Coop/Migros scale labels that encode the price or
  weight, so the same product gets a different code on every pack.
- 886 codes with an invalid check digit are removed, which points to typing or scanner
  errors.

*Rationale:* the EAN is the main key for joining OFF to the retailer data. An invalid code
cannot be joined by EAN and probably misidentifies the product.

**F2. Duplicate codes: the most recently modified entry is kept.**
There was only 1 case (`7613269480952`, "Croquets").
*Rationale:* the code must be a primary key in the database. The most recent version
carries the community's corrections.

**F3. Alcoholic beverages are excluded (`en:alcoholic-beverages`).**
*Rationale:* no Nutri-Score is computed for alcohol, and its price in Switzerland depends
mainly on excise duty (Alkoholsteuer), not on nutritional quality. Including it would mix
a tax effect into the "health premium" we want to measure.

**F4. Baby food is excluded** (categories `en:baby-foods`, `en:baby-milks`, `en:infant…`
or PNNS group "Baby foods").
*Rationale:* it has its own composition rules, gets no Nutri-Score, and its nutritional
profile serves babies' needs, not adults'.

**F5. Non-food is excluded** (pet food, cosmetics, household products that slipped into
OFF).
*Rationale:* out of scope, and their nutrition values are meaningless.

**F6. All 6 core nutrients per 100 g are required: energy, fat, saturated fat, sugars,
protein and salt.** This filter removes the most rows (29 025).
*Rationale:* they are the variables of the clustering (k-means) and the regression, and the
inputs of the Nutri-Score. A product without them contributes nothing to the research
question. They are not imputed (see N2).
- Fibre is **not** required: it is missing for 46 % of the remaining products (it is not
  mandatory on EU labels). Requiring it would remove half the sample.
- Carbohydrates are not required either; they are missing in only 20 rows.
- *Side effect:* this filter also removes almost all entries not edited since 2025 or
  earlier, which come without nutrients in the export (old, incomplete entries). The final
  dataset is therefore, in practice, entries reviewed in 2024–2026.

**F7. Physically impossible or internally inconsistent nutrition tables are removed.**
The whole row is removed, not just the value: OFF computes the Nutri-Score from the same
numbers, so if the table is wrong, so is the grade.
- **F7a** (25 rows): any nutrient in grams < 0 or > 100 g per 100 g. Impossible by
  definition. Real examples: fat = 2800, salt = 97 500, which are unit errors.
- **F7b** (4 rows): energy > 3800 kJ/100 g. Pure fat gives ~3700 kJ, the physical maximum
  for a food; 3 % margin.
- **F7c** (123 rows): saturated fat > fat or sugars > carbohydrates. A part cannot exceed
  its total. 0.5 g tolerance for label rounding.
- **F7d** (230 rows): fat + carbohydrates + fibre + protein + salt > 105 g. More than
  100 g of components in 100 g of product is impossible; the 5 g margin is the threshold
  OFF uses in its own quality check.
- **F7e** (196 rows): inconsistent energy. When the declared kJ and kcal disagree (kJ/kcal
  outside 3.6–4.8 in products above 40 kcal), the kJ value is compared with the energy
  computed from the macronutrients (fat 37, carbohydrates 17, protein 17 and fibre
  8 kJ/g). The row is removed only if the kJ value is also off by more than 20 %.
  *Rationale:* of 3 742 cases with disagreeing kJ/kcal, in 93 % the kJ value matches the
  macros and the kcal value is the wrong one (typically kcal entered as kJ, ratio ≈ 1.0).
  Removing them all would have discarded 2 900 valid products. Since kJ is what we use
  (C5), it is enough that kJ is reliable. The 40 kcal threshold avoids false positives
  from rounding in products with almost no energy, such as light drinks or spices.

## C. Cleaning and transformations (do not remove rows)

**C1. Typing.** Nutrients, quantity, completeness and scans are cast to numbers with
`try_cast`, which turns non-numeric values into NULL instead of failing. Dates go from
epoch to `TIMESTAMP` in UTC.
*Rationale:* losing a single non-numeric value is better than losing the whole run.

**C2. Text:** spaces are trimmed, repeated spaces collapsed and an empty string becomes
NULL (name, generic name, brands, quantity, stores).
*Rationale:* name matching does not fail on invisible spaces, and "empty" and "unknown"
mean the same.

**C3. Codes normalised to EAN-13/EAN-8.** The original value is kept in `code_raw`.
*Rationale:* shops usually publish EAN-13. Without normalisation a 12-digit UPC would not
join its 13-digit equivalent.

**C4. Nutri-Score and NOVA:** only `a`–`e` and `1`–`4` are accepted. "unknown" and
"not-applicable" become NULL. `nutriscore_score` is set to NULL when there is no valid
grade. `has_nutriscore` is added for easy filtering.
*Rationale:* sentinel strings would otherwise slip in as one more category in a
`GROUP BY` or a chi-squared test.

**C5. Energy in kJ.** The declared kJ value is used, and kcal × 4.184 if it is missing. The
declared energy columns are dropped after F7e.
*Rationale:* the Nutri-Score uses kJ, which is the label unit in Switzerland and the EU. A
single energy column avoids collinearity in the regression.
- **Salt** is used, not sodium: in OFF one is computed from the other (salt = sodium ×
  2.5), so sodium is redundant.

**C6. Package size (`product_quantity`).** Set to NULL if ≤ 0 g or > 10 kg, and
`product_quantity_unit` is added (`ml` if the quantity text indicates ml/cl/dl/l, `g`
otherwise).
*Rationale:* there are 197 zeros, from texts such as "1pcs" or "25 sachets", and 17 values
above 10 kg ("1000 kg", "100 x 550 g"), which are wholesale formats, not supermarket ones.
NULL is used instead of removing the row because the size can come from the shop during
matching. The unit matters because "per 100 g" and "per 100 ml" are not comparable without
a density. OFF already converts litres to ml and kg to g in `product_quantity` (checked:
"1.5L" → 1500, "150 cl" → 1500).

**C7. Main brand (`brand_main`):** the first brand in the list, lower-case, hyphens turned
into spaces. `brands` is kept in full.
*Rationale:* used for fuzzy matching (brand + name); unifies variants such as "M-Classic",
"M Classic" and "m-classic".

**C8. `code_is_internal`:** EAN-13 starting with `2` (GS1 restricted-circulation range).
10 265 products, **not removed**.
*Rationale:* these are in-store codes (Migros uses them for fresh and bakery products,
prefix 21). They are not globally unique but are unique within the chain that issues them,
so they can still be joined with that chain's data. The flag allows excluding them if
matching produces collisions.

**C9. Retail chain (`at_migros`, `at_coop`, `at_denner`, `at_aldi`, `at_lidl`,
`at_volg`).** There are two sources of evidence, stored separately (`store_*` and
`own_brand_*`); `at_*` is their union.
1. **`stores` field** (free text): explicit patterns per chain. Formats of the same group
   are included (migrolino, Coop Pronto, Coop City); "Aldi Süd"/"Aldi Nord" (Germany),
   "Biocoop" (a French chain) and "coopérative" are excluded.
2. **Exclusive own brand**: M-Classic, M-Budget, Migros Bio, Migros Sélection, Anna's
   Best, V-Love, TerraSuisse and Optigal → Migros. Naturaplan, Prix Garantie, Qualité &
   Prix, Karma, Betty Bossi, Fine Food and Naturafarm → Coop. Denner → Denner. Volg → Volg.

*Rationale:* `stores` is filled in only 14 % of the entries. With own brands, Migros grows
from 8 003 to 12 534 products and Coop from 1 686 to 9 561. Own brands are sold only in
their chain, so the inference is almost certain.
*Conservative choices:*
- Migros' industrial brands (Frey, Jowa, Midor, Bischofszell) are **not** included: they
  also produce for third parties and are sold through other channels.
- For Aldi and Lidl only `stores` is used, because their brands (Milbona, Milfina…) are
  sold the same way in Germany and Austria and do not prove the product is in the Swiss
  shop.
- **Limitation:** `at_* = false` means "no evidence", not "not sold there". With this
  rule Aldi has 338 products, Lidl 305 and Volg 186; prices for these chains come from
  scraping (Aldi, Volgshop) or Open Prices (Lidl), not from this flag.

**C10. `is_organic`:** the row has `en:organic`, `en:eu-organic`, `en:bio-suisse` or an
organic certifier code (`en:xx-bio-NNN`).
*Rationale:* the regression includes an organic flag. OFF tags organic products in
several ways, and every tag implying certification is accepted.

**C11. `origin_status`:** `domestic` if all origins are Switzerland, `imported` if none is,
`mixed` if both occur and NULL if there is no data.
*Rationale:* this is the H3 variable (import premium).
*Decisions:*
- `origins_tags` (origin of the ingredients) is used, not `manufacturing_places_tags`
  (place of manufacture), because they are different concepts. The place of manufacture is
  kept in case it is needed later.
- **Important limitation:** only 8 % of the final products have an origin. Volgshop
  publishes its own production country (C7 of
  [`retail_cleaning_decisions.md`](retail_cleaning_decisions.md)), which measures a
  different concept.

**C12. Lists as lists.** Categories, labels, origins, manufacturing places and countries
are stored as `LIST` in the parquet. In the CSV they are joined with `|`.
*Rationale:* this allows filtering by tag without parsing text with regular expressions.
`|` is used instead of `,` so the CSV separator is not broken.

## N. What was deliberately NOT done

**N1. The Nutri-Score in this table is OFF's own; it is not recomputed here.**
*Rationale:* OFF computes it with the current official algorithm (2023 version), including
the fruit/vegetable/legume share estimated from the ingredients. A Nutri-Score is computed
only later, in `products_matched`, for products that have a nutrition table but no OFF
grade (M12 of [`matching_decisions.md`](matching_decisions.md),
[`nutriscore_decisions.md`](nutriscore_decisions.md)).

**N2. Missing nutrients are not imputed.**
*Rationale:* imputing the variable we want to explain or cluster would invent signal.
Fibre (46 % missing) stays NULL; if a model needs it, the decision is made and documented
in the modelling notebook.

**N3. No filter on entry age.**
*Rationale:* 88 % of the Swiss extract has a 2026 modification date because of OFF's
automatic bulk edits, so the date says nothing about how recent the label information is.
In practice F6 already removes the old, empty entries.

**N4. Products without an assigned chain are not removed.**
*Rationale:* they are the candidate pool for name matching with the scraped Aldi and Volg
products, which have no EAN. Restricting to products with a known chain before matching
would lose those candidates.

**N5. Products without a Nutri-Score are not removed if their nutrients are complete**
(31 508 rows).
*Rationale:* they are useful for clustering, which uses nutrients, not the grade. H1 and H2
filter on the grade.

**N6. No deduplication by name or brand.**
*Rationale:* the same product in different sizes has different EANs and different prices
per 100 g. They are different SKUs, and the price per size is part of what is measured.

**N7. Statistical outliers are not removed** (for example by z-score).
*Rationale:* F7 removes only the physically impossible. A product with 90 g of fat (oil) or
99 g of sugar (table sugar) is extreme but real, and those extremes are exactly the
products the Nutri-Score penalises.

## Known biases these decisions do not correct

- OFF is fed by a community: big brands and the Migros/Coop own brands are better covered
  than fresh, loose or small-chain products.
- Coverage per chain is very uneven: Migros 12.5 k and Coop 9.6 k, against Aldi 338,
  Lidl 305 and Volg 186. For these chains the products come from our scraping (Aldi,
  Volgshop) or from Open Prices (Lidl).
- The chain attribution (C9) has false negatives by construction.
