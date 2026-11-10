# Aldi and Volgshop: cleaning decisions

Scripts: [`src/scraping.py`](../src/scraping.py) (download) and
[`src/retail_cleaning.py`](../src/retail_cleaning.py) (cleaning) · Reproducible counts in
[`data/processed/retail_cleaning_log.csv`](../data/processed/retail_cleaning_log.csv) ·
Snapshot provenance in [`data/processed/retail_metadata.json`](../data/processed/retail_metadata.json)

The identifiers (F1, C1, N1…) appear as comments in the code. They belong to this document
and do not match those in [`off_cleaning_decisions.md`](off_cleaning_decisions.md).

- **F**: filters that **remove rows**.
- **C**: cleaning and transformations that **do not remove rows**.
- **N**: things that were deliberately **not** done.

## Funnel summary

Snapshots downloaded on 2026-11-03 from each shop's public JSON API.

| Rule | What it removes | Aldi | Remaining | Volgshop | Remaining |
|---|---|---:|---:|---:|---:|
| — | Products downloaded | | 2 406 | | 696 |
| F1 | Duplicate identifier | 0 | 2 406 | 0 | 696 |
| F2 | Non-food | 377 | 2 029 | 114 | 582 |
| F3 | Alcohol and tobacco | 140 | 1 889 | 103 | 479 |
| F4 | Baby food | 9 | 1 880 | 0 | 479 |
| F5 | No computable price per 100 g/ml | 297 | 1 583 | 34 | 445 |
| F6 | Price per 100 g/ml outside CHF 0.01–50 | 6 | **1 577** | 0 | **445** |

Of the 445 Volgshop products, 381 have a complete nutrition table (C6). Aldi publishes no
nutrition values: its nutrition has to come from Open Food Facts through matching (N1).

---

## F. Filters (remove rows)

**F1. Duplicate identifier** (SKU at Aldi, product id at Volgshop).
No cases. The Aldi scraper already deduplicates by SKU, because a product appears in
several categories of the crawl. *Rationale:* the identifier is the primary key in the
database.

**F2. Non-food is excluded.**
- *Aldi* (377): the top categories "Gesundheit, Körperpflege & Baby" and "Haushalt &
  Wohnen"; the non-food sub-categories of "Aktionen" (clothing, decoration, toys, cleaning,
  pet food, plants…; the list is in `ALDI_NONFOOD_SUB`); and 13 non-food brands that appear
  without a sub-category under "Aktionen" (Whiskas, Sheba, Domestos, Pantene, Varta…;
  `ALDI_NONFOOD_BRANDS`). The brand list was built by manually reviewing the 332 products
  in generic or theme categories with a size in g/ml.
- *Volgshop* (114): the category "Körperpflege, Reinigung, Haushalt & Tierbedarf".

*Rationale:* out of scope, and their price "per 100 g" has no nutritional meaning. Same
criterion as F5 of OFF.

**F3. Alcohol and tobacco are excluded.**
- *Aldi* (140): the category "Alkohol & Tabakwaren"; wines, beers and spirits on
  promotion, which appear only under "Aktionen" and are recognised by name (AOC, DOC, IGT,
  vino, Bier, Vodka, grape varieties…); and the Feldschlösschen brand except "alkoholfrei".
  The name rule is applied **only** to the generic "Aktionen" category: elsewhere the same
  words are flavours ("Rotwein Sauce", "Edelmarzipan, Rum-Traube") and the rule would have
  removed them by mistake.
- *Volgshop* (103): the categories "Jugendschutz" (Volg's 18+ category, which groups all
  alcohol and tobacco) and "Tabakwaren".

Alcohol-free drinks (beer, wine and sparkling wine labelled "alkoholfrei") **are kept**.
*Rationale:* same as F3 of OFF. No Nutri-Score is computed for alcohol, and its price in
Switzerland depends mainly on tax, not on nutritional quality.

**F4. Baby food is excluded.**
- *Aldi* (9): the sub-category "Baby & Kinderartikel" and the brands Aptamil and Mamia
  (fruit purées for babies).
- *Volgshop* (0): the online range has no baby food. The rule looks for "Baby" or
  "Säugling" in the name and excludes "Babybel".

*Rationale:* same as F4 of OFF. Baby food has its own regulation and gets no Nutri-Score.

**F5. A price per 100 g or 100 ml must be computable** (C2).
This is the dependent variable of the analysis, so a product without it contributes
nothing. Removed:
- **No size** (227 of Aldi's 297): 526 Aldi products have no `sellingSize`, and the detail
  page does not have it either. 299 of them had already left in F2–F4 (non-food, alcohol).
  The remaining 227 are foods without a published size, such as "Glasnudeln", "Sbrinz" or
  "Tomatoketchup, mild".
- **Size in units** rather than weight or volume (Aldi 70, and most of Volgshop's 34):
  coffee capsules, tea bags, eggs, fruit and vegetables per piece ("Avocado Stk."),
  sweetener tablets.
- **Weight ranges** ("Lauch Stück ca. 200g – 400g"): there is no single weight to divide
  the price by.
- **Unresolved size at Volgshop** (C2): the attribute and the name disagree and the
  published unit price does not settle it. This happened only for "Kinder Milchschnitte".

*Known bias:* the 227 Aldi foods without a size are lost although they have a price. Coffee
capsules and tea bags drop out entirely. Their price per gram is very high, but they carry
no relevant nutrition, so the effect on the research question is small. Stated as a
limitation.

**F6. Price per 100 g/ml outside CHF 0.01–50.**
6 Aldi products are removed:
- One data error: "Schweinssteaks vom Hals 0.5 g" at CHF 7.85, almost certainly 0.5 kg.
  Not corrected because there is no way to confirm it.
- Five legitimate products of a few grams: a vanilla pod (4 g) and cake decorations
  (2–5 g), at CHF 52–86 per 100 g.

*Rationale:* the maximum price after the filter is CHF 28.6 per 100 ml (baking
flavourings). Above CHF 50 only products used by the gram remain, whose "price per 100 g"
would be an extreme outlier in the regression without saying anything about the health
premium.

## C. Cleaning and transformations (do not remove rows)

**C1. Price: the regular price is used, not the promotional one** (Aldi).
When Aldi shows a struck-through former price (`wasPriceDisplay`), that is the regular
price (`price_chf`), and the reduced price is stored separately in `price_promo_chf` with
`on_promotion = true`. 64 products.
*Rationale:* promotions last a week and depend on the scraping date. The regular price is
what is compared across shops. Volgshop had no promotions (`on_sale` always false).

**C2. Package size and price per 100 g/ml.**
The size is converted to g or ml (kg ×1000, dl ×100, cl ×10, l ×1000). Multipacks
("6x50cl" → 3000 ml), "Packung à 250 g" and approximate weights ("ungefähr 0.25 kg/Stück",
`size_is_approx`) are supported. `price_per_100_chf = price / size × 100`, with
`price_per_100_unit` equal to `g` or `ml`. Solids and liquids are kept apart and ml is not
converted to g, because OFF also reports nutrients per 100 ml for drinks. "53g+" (minimum
weight per egg) is not read as a size.

*Validation at Aldi:* for the 1 701 products without promotion for which Aldi publishes a
unit price, the computed price matches the published one in 100 % of cases (±2 %).

*Volgshop: size reconciliation.* The quantity is in the "Mengeneinheit" attribute and
almost always in the name as well. They agree for 563 products and differ for 8. Sometimes
the attribute is wrong ("Haus Sauce 250ml" with attribute "50ml"), sometimes the name
("Mini-Pic 90g" with attribute "5x90g"). There are also packs sold per unit: the
alcohol-free beer "6x50cl" costs CHF 1.30 per can. Rule: candidates are generated (total
and single unit, from the attribute and from the name), and the one that best reproduces
Volg's published unit price is chosen, with 25 % tolerance. Without a published price the
attribute total is used, unless attribute and name disagree; then the size stays
unresolved (F5). `size_source` records where it came from: attribute 438, name 6, single
unit 1.

*Volg's published unit price is not used as the price* (`unit_price_published_chf` is kept
for reference only). For 41 of 429 products it differs by more than 2 % from the current
price, usually by 5–20 %. It looks outdated: it is not recomputed when the price changes.
`unit_price_mismatch` flags these cases.

**C3. "kg" instead of "g" corrected** (Aldi, 6 products).
"Müsli 750 kg" at CHF 3.29, "M&M's Cookie Dough 675 kg", "Surimi-Sticks 200 kg". A size of
50 kg or more is read as grams and flagged with `size_corrected`.
*Rationale:* no supermarket product weighs 50 kg. Aldi's own unit price for these products
is absurd (CHF 0.01/kg), which confirms the error at the source.

**C4. Product category.**
- *Aldi:* the crawl walks the top categories, but 10 of them are campaigns or themes, not
  product types ("Aktionen", "Weihnachten", "Grillen", "Gourmet", "Saveurs Suisses"…;
  `ALDI_THEMES`). `category_main` is the product's own path if it is not a theme; if it is,
  the first non-theme category the product appeared in; failing that, the second level of
  the theme path when that level is a product category ("Vegetarisch & Vegan > Vorräte" →
  "Vorräte"). Otherwise NULL: 213 products, almost all Christmas sweets and promotional
  items. `category_theme_only` flags them.
- *Volgshop:* the names along the deepest path of the category tree (`category_main`,
  `category_sub`, `category_path`).

The two shops' categories are **not** harmonised here (N3).

**C5. Labels.**
- `is_organic`: "Bio" as a word in the brand, the name or Volg's labels, or Aldi's category
  "Retour aux sources (Bio)". Aldi 152, Volgshop 12.
- Aldi, from the shop's badges: `is_vegan` (223), `is_vegetarian` and `storage` (frozen,
  chilled or ambient).
- Volgshop: `own_brand_volg` when the name starts with "Volg " (51).

**C6. Volgshop nutrition table.**
The free text is parsed again during cleaning with the current parser
(`scraping.parse_volg_nutrition`), so a parser fix does not require scraping again. The
reference basis is 100 g/ml when the text mentions "100 g". This includes two-column
tables (100 g and portion), where the first value is the 100 g one. Then the same checks as
F7 of OFF are applied: nutrients between 0 and 100 g, energy between 0 and 3800 kJ,
saturated fat ≤ fat and sugars ≤ carbohydrates, sum of macros ≤ 105 g, and the kJ/kcal
check against the energy computed from the macros.

**Unlike OFF, the product is not removed** if its table fails: the values become NULL and
`nutrition_status` says why.

| `nutrition_status` | Products |
|---|---:|
| complete (all 6 core nutrients) | 381 |
| incomplete | 32 |
| missing (no table, or the field holds ingredients or water minerals) | 28 |
| implausible | 4 |

*Rationale:* in OFF the nutrition table is all a product contributes. Here the price is
still valid and the nutrition can come from OFF through matching. The 4 `implausible` ones
are shop errors: kJ and kcal swapped (Linzertörtli, ground almonds, curry) and a rapeseed
oil with 54 g of carbohydrates. If kJ is missing, `energy_kj` is computed from kcal
(×4.184), as in C5 of OFF.

**C7. Origin (Volgshop).**
`origin_status` comes from the "Produktionsland" attribute: Schweiz → `domestic`;
Liechtenstein (also spelled "Lichtenstein", 7 products) → `domestic`, because it is in the
Swiss customs union and pays no import duty; "diverse", "Europa", "EU" or empty → NULL; any
other country → `imported`. Result: 332 domestic, 94 imported, 19 NULL.
*Note:* "Produktionsland" is the country of **manufacture**, not the origin of the
ingredients, which is what OFF's `origin_status` uses (`origins_tags`). Keep this in mind
when comparing H3 across sources.

## N. What was deliberately not done

**N1. No nutrition or origin was sought for Aldi.** The API has no nutrition values (the
detail page only has the ingredient list) and leaves `countryOrigin` empty. Both have to
come from matching with OFF. Origin is not inferred from the "Saveurs Suisses" brand or
from "Schweizer" in the name.

**N2. Neither shop has EANs.** Matching with OFF has to be by brand and name
([`matching_decisions.md`](matching_decisions.md)). Volgshop also does not separate the
brand from the name ("ALNATURA FETA 180G"), so no brand is extracted during cleaning.

**N3. Categories are not harmonised across shops here.** Aldi and Volg use different trees,
and OFF its own taxonomy (PNNS, categories_tags). The common category is built later, in
`products_matched` (M13 of [`matching_decisions.md`](matching_decisions.md),
[`category_decisions.md`](category_decisions.md)).

**N4. Sizes and nutrients are not imputed.** A product without a size in weight or volume
leaves (F5). A missing nutrient stays NULL. (The Nutri-Score is computed later from the
nutrients that are present; nothing is imputed.)

**N5. Volg's published unit price is not used** as the price (C2): it is outdated for ~10 %
of the products.

**N6. Aldi's own brands are not flagged.** Most Aldi brands (Milsani, Le Gusto, Monarc…)
are exclusive, but there is no official list, and building one by hand would be guesswork.
It is left to matching, where the lack of a match in OFF also reveals it.
