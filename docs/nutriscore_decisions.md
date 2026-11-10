# Computed Nutri-Score: decisions

Script: [`src/nutriscore.py`](../src/nutriscore.py) (algorithm and validation) · Applied in
[`src/matching.py`](../src/matching.py) when `products_matched` is built (M12 of
[`matching_decisions.md`](matching_decisions.md)) · Reproducible validation with
`python src/nutriscore.py validate` → `data/processed/nutriscore_validation.csv`

The identifiers (S1, S2…) belong to this document.

## Why

OFF only gives a Nutri-Score to products that are matched and have a complete entry.
Volgshop publishes its own nutrition table for 381 products, but only 99 Volgshop products
had an OFF Nutri-Score. Computing it from the table adds 358 products to the H1 and H2
analysis.

| Chain | OFF Nutri-Score | Computed | Total | Not applicable |
|---|---:|---:|---:|---:|
| Volgshop | 99 | 288 | 387 | 10 |
| Aldi | 214 | 51 | 265 | 42 |
| Migros | 226 | 12 | 238 | 4 |
| Coop | 122 | 5 | 127 | 4 |
| Lidl | 32 | 1 | 33 | 0 |
| Denner | 13 | 1 | 14 | 1 |
| **Total** | **706** | **358** | **1 064** | |

## New columns in `products_matched`

| Column | Meaning |
|---|---|
| `nutriscore_grade`, `nutriscore_score` | **For the analysis.** OFF's if it exists; otherwise the computed one |
| `nutriscore_source` | `off` or `computed` |
| `nutriscore_calc_grade`, `nutriscore_calc_score` | Computed for **every** product with a complete table, including those with an OFF grade (sensitivity analysis) |
| `nutriscore_kind` | Algorithm category: `general`, `cheese`, `red_meat`, `fat`, `beverage`, `water`, `not_applicable`, `unsupported` |
| `nutriscore_category_source` | Where the category comes from: `off_categories` (matched OFF entry) or `retailer_name` (shop category and name) |

`off_nutriscore_grade` is unchanged.

---

## S. Rules

**S1. 2023 algorithm.** It is the version OFF has used since 2024, so the computed grades are
comparable with OFF's. The three point tables (general foods, beverages, and
fats/oils/nuts/seeds) and their grade boundaries are implemented.
- *Negative points:* energy, sugars, saturated fat and salt. In the fats group, the energy
  from saturated fat and the saturated/total fat ratio are used instead. Beverages get 4
  extra points if they contain non-nutritive sweeteners.
- *Positive points:* protein, fibre and FVL (fruit, vegetables and legumes share).
- *Water:* always A.

**S2. Protein rule.** If the negative points reach 11 (7 in the fats group), protein does not
count, except for cheese. For red meat, protein is capped at 2 points. Cured meats are
treated as general food: in OFF, that cap almost never changes the score of hams and
sausages.

**S3. Algorithm category, from OFF tags.** The rule was derived from the data: for each
product, we tested which category reproduces OFF's score exactly, and looked at which tags
predict it.
- *Fats:* `en:fats`, `en:seeds` and `en:nuts`, except chestnuts, mixed nuts and mixes with
  dried fruit. **Note:** in OFF's taxonomy, `en:seeds` includes dried legumes and cereal
  grains (rice, maize). OFF scores them with the fats table, and so does this code, so the
  grades are consistent with OFF's.
- *Beverages:* `en:beverages`, except powdered preparations and syrups.
- *Cheese:* `en:cheeses`. *Water:* `en:waters` without flavouring.
- *Not applicable:* OFF's `not-applicable` is kept (coffee, tea, spices, salt, vinegar,
  chewing gum, supplements).

**S4. FVL when the entry does not give it.** 100 % for fruit and vegetable juices, olive,
rapeseed and walnut oil, fresh fruit and vegetables, mushrooms, dates and berries; 0 %
otherwise. Also derived from the data: canned, frozen, compote and dried-fruit products
reproduce OFF's score sometimes with 0 % and sometimes with 100 %, so they are not given
100 %.

**S5. Products without an OFF entry (Volgshop): category from the shop and the name.**
- *Beverage:* sub-category "Alkoholfreie Getränke", or dairy drinks in the milk
  sub-category (since 2023 milk counts as a beverage). Cream, condensed milk and powders
  (Caotina, Ovomaltine) do not count.
- *Water:* names of unflavoured mineral waters.
- *Cheese:* sub-category "Käse & Frischkäse".
- *Fats:* butter, margarine, cream, oils, nuts and seeds. Following S3, also rice, lentils,
  chickpeas, beans and maize.
- *Not applicable:* salt, vinegar, yeast, spice mixes, Aromat, instant coffee, tea and
  chewing gum. *Not computed (`unsupported`):* syrups, because OFF scores them as diluted
  while the label gives the concentrate.
- *FVL:* the sum of the declared percentages of fruit, vegetable and legume ingredients in
  the ingredient list (potatoes do not count). If the list gives no percentages: 100 % for
  vegetables, salads, juices and canned vegetables by name, 0 % otherwise.
- *Sweeteners:* detected in the ingredient list (aspartame, acesulfame, sucralose,
  steviol, E950–E969).

**S6. Priority.** OFF's grade takes priority over the computed one. For a matched Volgshop
product, the category comes from its OFF entry (S3) and the nutrition from Volgshop's table
(M8).

## V. Validation

**V1. Implementation against OFF** (42 232 Swiss products with an OFF grade):

| Category | Products | Same grade (with OFF's FVL) | Same grade (without OFF's FVL) |
|---|---:|---:|---:|
| General | 32 485 | 98.0 % | 94.9 % |
| Beverages | 3 779 | 98.3 % | 92.3 % |
| Fats, nuts, seeds | 2 720 | 92.1 % | 92.2 % |
| Cheese | 2 588 | 99.6 % | 99.4 % |
| Red meat | 468 | 100 % | 100 % |
| Water | 192 | 83.9 % | 83.9 % |
| **Total** | 42 232 | **97.7 %** | **94.8 %** |

"Without OFF's FVL" uses only rule S4, as for a product whose FVL is unknown. The gap comes
from products for which OFF estimated the FVL from the ingredients (soy drinks, vegetable
dishes).

**V2. Volgshop path against OFF.** Rules S5 are applied to the 86 Volgshop products that
have an OFF grade and their own table, and compared with that grade:

| Nutrition table used | Same grade | Within one grade |
|---|---:|---:|
| Volgshop's | 86 % | 97 % |
| OFF's for the same product | 91 % | 100 % |

Rules S5 account for about 9 points of error. The other 5 come from Volgshop's and OFF's
tables disagreeing for the same product (Zwieback, Camembert), which is not a computation
error.

Remaining errors with rules S5: juices with a doubtful FVL in OFF (Ramseier Süessmost is E in
OFF; with 90 % juice the algorithm gives C), some nut snacks (Nic Nac's) and lemon juice (OFF
treats it as a beverage).

## Limitations

- **The computed grade is an estimate.** `nutriscore_source` allows comparing results with
  and without the computed grades (sensitivity analysis).
- **FVL is the most uncertain component.** A wrong estimate moves the score by at most 5
  points (6 for beverages), usually one grade.
- **Products without an OFF category.** The 51 Aldi and 19 Migros/Coop/Lidl/Denner products
  that were computed have an OFF entry without a grade. For 54 of these 70 the entry has no
  category, so they are treated as general food.
