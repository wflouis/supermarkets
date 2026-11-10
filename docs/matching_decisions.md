# Matching shops ↔ Open Food Facts, and the combined table: decisions

Script: [`src/matching.py`](../src/matching.py) · Results in
`data/processed/matches.parquet` (best OFF candidate per Aldi/Volgshop product, with score)
and `data/processed/products_matched.parquet` (one row per product of every chain: price,
nutrition, Nutri-Score, common category). Manual review sample:
`data/processed/match_review_sample.csv`.

The identifiers (M1…M13) appear as comments in the code. The OFF candidates are the
cleaned Swiss subset and, for Aldi only, the German and Austrian entries of the brands Aldi
sells (E6 of [`off_cleaning_decisions.md`](off_cleaning_decisions.md)).

## Summary

| | Aldi | Volgshop |
|---|---:|---:|
| Clean products | 1 577 | 445 |
| Matched to OFF | **273** (17.3 %) | **122** (27 %) |
| with a Swiss entry | 100 | 122 |
| with a DE/AT entry (M10) | 173 | — |
| With nutrition (shop or OFF) | 273 | 395 |
| with the shop's nutrition | 0 | 381 |
| with OFF's nutrition | 273 | 14 |
| With a Nutri-Score from OFF | 214 | 99 |
| With origin | 24 | 427 |
| "Probable" matches, not used (M9) | 38 | 4 |

Before M9 and M10, Aldi had 103 matches (6.5 %). Migros, Coop, Lidl and Denner do not go
through name matching: their products come from Open Prices with an EAN (M11).

**Validation**
- *Against Volgshop's nutrition:* of the 108 accepted Volgshop matches that also have a
  complete table of their own, 97 (90 %) agree with OFF. Agreement criterion: energy ±12 %
  (min. 40 kJ); fat, sugars and protein ±20 % (min. 1.5 g). The 11 that disagree all have
  the same name in both sources, and the difference comes from a data error (Bschüssig
  pasta with 361 "kJ" at Volg, which are kcal; Emmi Magerquark with 98 kJ in OFF) or a
  different recipe (Balisto, Stimorol). The 90 % is therefore a lower bound on precision.
- *Manual review:* in a random sample of 50 accepted matches per shop (seed 42), all 100
  are the same product. In a second sample of 50 new Aldi matches (DE/AT entries and
  ingredient rescues), the 36 name matches against DE/AT entries are correct, and only 6 of
  the 10 ingredient rescues are. That is why rescues are not used (M9). Both reviews were
  done by Claude Code (see `docs/ai_usage.md`). `match_review_sample.csv` has empty
  `correct` and `comment` columns for the team's own review.

---

**M1. Blocking by brand.** Only products of the same brand are compared.
- *Aldi* publishes the brand separately.
- *Volgshop* does not, so the brand is the longest OFF brand (1–3 words) the name starts
  with ("Hilcona Pizza Prosciutto…" → "hilcona"). Only OFF brands of 3 letters or more with
  at least 2 products count for this.
- An OFF brand counts if it appears anywhere in the `brands` field, not only first.

*Rationale:* without an EAN, the brand is what cuts false positives most, leaving a few
hundred candidates per product instead of 73 000. Of the 1 532 Aldi products with a brand,
1 375 have that brand in OFF.

**M2. Name normalisation.** Lower case, no accents (ü → u, ß → ss), no sizes ("500g",
"6x50cl"), no punctuation and without the brand itself. Words with no identifying value are
dropped ("mit", "und", "de", "bio", "classic", "original"…).

**M3. Name score: coverage in both directions.**
`score = harmonic mean of (share of shop words present in OFF, share of OFF words present in
the shop name)`, from 0 to 100. Two words match if their character similarity
(`rapidfuzz.fuzz.ratio`) is at least 85, which absorbs plurals and typos
("Pangasiusfilet" ↔ "Pangasiusfilets", "Muesli" ↔ "Müsli").
- *Why not `token_set_ratio`:* it gives 100 when one name is contained in the other, e.g.
  "Müsli-Riegel, Schoko" → "Schoko Müsli".
- *Why compound-word containment is not accepted:* the first version accepted one word
  containing the other, for German compounds such as "Knuspermüesli" ↔ "Müesli". The
  manual review showed that this hides exactly the modifier that tells products apart:
  "Magermilch" → "Milch 3,5 %", "Senf halbscharf" → "Senf scharf", "Eierravioli" →
  "Ravioli". It was removed, at the cost of some hits.

**M4. Acceptance.** A match is accepted if:
- the score is ≥ 90, **or**
- the score is ≥ 75, the package size agrees (±10 %) **and** every word of the shop name
  is in OFF.

*Rationale for the third condition:* at score 80, what is missing is usually the variant on
the shop side ("Red Bull **Sugarfree**" → "Red Bull Energy Drink", "Mix-it **Waldbeer**" →
"Mix it"), and the nutrition disagrees. Requiring full coverage on the shop side raised
nutrition agreement from 86 % (95/111) to 88 % (95/108) and removed those cases, but it also
drops correct matches where the shop adds a generic word ("Ziegenkäse **Scheiben**,
Bockshornklee", "**Instantkaffee** Gold Finesse"). Precision was preferred: a false match
puts wrong nutrition into the regression; a missed match only shrinks the sample.

**M5. Tie-break between candidates:** accepted first, then score, Swiss entry before DE/AT
(it is the recipe sold in Switzerland), ingredient similarity, matching size, product
tagged with the shop in OFF, and number of OFF scans (`unique_scans_n`).

**M6. Generic brands.** "Bio", "No brand" and brands that are common words used by several
companies ("American", "BBQ", "Halloween", "Gourmet", "Premium") are not enough as a block.
For them only OFF products tagged with the shop itself are considered.
*Real case:* Aldi's "AMERICAN Sandwichtoast" matched Jowa's (Migros) "American Toast".

**M7. No usable brand: only the shop's OFF products, strict rule.** If the product has no
brand, or its brand is not in OFF, it is compared with the OFF products tagged with that
shop (`store_aldi`/`store_volg` or own brand) whose brand the shop also sells. Score ≥ 90
**and** matching size are required.
*Real case:* without the brand condition, Aldi's "Schwarzwälder Schinken" matched a
K-Classic (Kaufland) product mistagged as Aldi in OFF.

**M8. Combined table (`products_matched`).**
- Nutrition: Volgshop's own table if complete (C6 of `retail_cleaning_decisions.md`); else
  OFF's; else NULL. `nutrition_source` says which.
- From the OFF product: Nutri-Score, NOVA, category (`main_category`, PNNS) and origin
  (`off_*` columns).
- Price, size and shop category always come from the shop.
- `off_scope` says whether the OFF entry is Swiss (`ch`), German/Austrian (`de_at`, M10) or
  a non-Swiss entry of an Open Prices EAN (`openprices_ext`, E8).

**M9. Ingredients veto a match, they do not create one.**
Aldi publishes the ingredient list on its detail page (`scraping.py aldi-details`: 903 of
1 575 products), Volgshop in the "Zutaten" attribute. OFF has its own
(`off_ingredients.parquet`, E7). Similarity is computed like the name score (M3), on the
words of the list without numbers or filler words. Only German lists are compared: the OFF
export does not give the language, so it is detected by counting frequent words of each
language; some Aldi lists are also in Italian.

*Calibration*, at Aldi, with 50 near-certain matches (score 100 and same size) against
32 920 pairs of the same brand and different products (name score ≤ 20):

| Similarity ≥ | Certain matches | Different products |
|---:|---:|---:|
| 30 | 98 % | 26.6 % |
| 40 | 86 % | 14.0 % |
| 70 | 44 % | 1.2 % |

- *Veto:* if similarity is below 30, the match is rejected even if the name agrees. At 40,
  14 % of correct matches would have been lost, because Aldi often shortens its lists
  ("Gnocchi" has similarity 14 with its own OFF product).
- *Rescue:* a candidate with name score 60–89 and similarity ≥ 70 is kept as **probable**
  (`probable = true` in `matches.parquet`) and is **not** used in `products_matched`. At
  Volgshop, 11 of 13 such cases agreed on nutrition, but in the Aldi review only 6 of 10
  were the same product. The errors are variants that share the ingredient list in other
  proportions ("Weichkäse **Leicht**" → the regular version, "Tortilla Wraps **Weizen**" →
  "Vollkorn"). They remain available for a sensitivity analysis.

**M10. German and Austrian entries for Aldi.** Many Aldi Suisse own brands (Golden Bridge,
Cucina, Snack Fun, Asia Green Garden, My Vay…) are the same as Aldi Süd's and Hofer's, and
in OFF their entries are tagged Germany or Austria, not Switzerland. DE/AT entries follow
the same acceptance rule as Swiss ones.
*Rationale:* `cross_country_check.parquet` compares pairs of OFF entries, one Swiss and one
DE/AT, with the same brand, name (score 100) and size: 69 % agree on nutrition (255 of 371).
During development the same comparison was run within each scope, with similar agreement:
about 67 % for Swiss–Swiss pairs and 66 % for DE/AT–DE/AT pairs. Those two figures are not
written to a file. Using an entry from another country therefore adds no disagreement. The
~67 % measures the noise of matching OFF entries with generic names by name alone, not the
country, and it is lower than the 90 % of M4 because there is no size or shop-coverage check
here. Requiring ingredients only for DE/AT entries would have been an unfounded rule. Swiss
entries win the tie-break (M5). Volgshop does not use DE/AT entries: almost its whole range
is Swiss and has its own nutrition.

**M11. Migros, Coop, Lidl and Denner from Open Prices, joined by EAN.** `products_matched`
includes the 421 products of these chains from `openprices_clean.parquet`
([`openprices_decisions.md`](openprices_decisions.md)), with `match_method = 'ean'`, OFF
nutrition and an empty `category_main` (the common category is `category_common`, M13). Two
columns on every row:
- `price_source`: `retailer_web` (scraped Aldi and Volgshop catalogues) or `open_prices`.
- `price_date`: date of the scrape (2026-11-03) or of the Open Prices price.

The 14 Aldi products on Open Prices are not added: the scraped Aldi catalogue is complete and
from a single date. The Aldi and Volgshop rows are unchanged.

| Chain | Price source | Products | With OFF Nutri-Score |
|---|---|---:|---:|
| Aldi | web catalogue | 1 577 | 214 |
| Volgshop | web catalogue | 445 | 99 |
| Migros | Open Prices | 242 | 226 |
| Coop | Open Prices | 131 | 122 |
| Lidl | Open Prices | 33 | 32 |
| Denner | Open Prices | 15 | 13 |
| **Total** | | 2 443 | **706** |

15 EANs appear in more than one chain, which allows comparing the price of the same product
across chains, although on a small sample.

**M12. Nutri-Score computed where OFF has none.** When `products_matched` is built, the 2023
Nutri-Score is computed from the nutrition table (`nutriscore.py`). OFF's grade takes
priority. Products with a Nutri-Score go from 706 to 1 064. Rules and validation in
[`nutriscore_decisions.md`](nutriscore_decisions.md).

**M13. Common category (`category_common`).** It is OFF's PNNS group 1 and, if the product
has none, the one given by rules on the shop category and the name (`categories.py`). 98 %
of the products with a Nutri-Score have a category (1 045 of 1 064). Rules and validation in
[`category_decisions.md`](category_decisions.md).

## Limitations

**L1. Aldi coverage is still low (17.3 %).** With DE/AT entries (M10) it went from 103 to
273 products, but Swiss-exclusive brands have no entries in any country: Saveurs Suisses
(117 products, 0 matches) and Panetteria (62, 0). Also the "Bio" brand (104, 8). The result
is still biased towards manufacturer brands and brands shared with Aldi Süd. Covering the
Swiss-exclusive brands would need manual label capture.

**L2. Language.** The OFF name is in the entry's main language, which in Switzerland is often
French ("Soupe de pâtes ABC" against "Beutelsuppe, ABC-Suppe"). Such cases are not matched.

**L3. Recipe variants.** The same name can have another recipe in another country or year
(Balisto, Stimorol in the validation). For Volgshop this matters little, because its own
table is used.

**L4. Nutri-Score coverage (solved by M12).** OFF only grades matched products, so 294 of
the 381 Volgshop products with a complete table had no grade. M12 computes one from the
table, estimating the fruit/vegetable/legume share that Volg does not publish.
