# Common category across shops: decisions

Script: [`src/categories.py`](../src/categories.py) · Applied in
[`src/matching.py`](../src/matching.py) when `products_matched` is built (M13 of
[`matching_decisions.md`](matching_decisions.md)) · Validation: `python src/categories.py validate`

The identifiers (K1, K2…) belong to this document.

## Why

H1 controls for category, and H2 compares the premium across chains within each category.
That needs a category that means the same in every shop. The shops' own categories do not
work for this:
- Aldi groups by shop section ("Vorräte", "Tiefgekühlte Produkte").
- Volgshop mixes food types ("Milchprodukte, Eier & frische Fertiggerichte").
- Migros, Coop, Lidl and Denner have no category of their own (Open Prices does not carry
  one).

OFF's PNNS category is common to all, but it only exists for matched products: only 95 of
the 387 Volgshop products with a Nutri-Score had one.

## Result

Of the 1 064 products with a Nutri-Score, 1 045 (98 %) have a common category: 666 from OFF,
181 from the shop category and 198 from the name.

| Category (PNNS group 1) | Aldi | Volg | Migros | Coop | Lidl | Denner | Total |
|---|---:|---:|---:|---:|---:|---:|---:|
| Sugary snacks | 40 | 84 | 68 | 13 | 2 | 4 | 211 |
| Cereals and potatoes | 43 | 58 | 43 | 28 | 7 | 1 | 180 |
| Milk and dairy products | 18 | 63 | 38 | 15 | 7 | 3 | 144 |
| Beverages | 21 | 64 | 21 | 16 | 3 | 0 | 125 |
| Fat and sauces | 35 | 28 | 19 | 19 | 10 | 1 | 112 |
| Fish Meat Eggs | 29 | 36 | 9 | 6 | 2 | 3 | 85 |
| Fruits and vegetables | 29 | 23 | 14 | 7 | 0 | 0 | 73 |
| Salty snacks | 20 | 17 | 9 | 10 | 1 | 1 | 58 |
| Composite foods | 22 | 13 | 12 | 9 | 1 | 0 | 57 |
| No category | 8 | 1 | 5 | 4 | 0 | 1 | 19 |

New columns in `products_matched`:
- `category_common`: the category for the analysis.
- `category_common_source`: where it comes from (`off`, `shop_category` or `name`).
- `category_rules`: the category given by the rules, for every product (for validation and
  sensitivity analysis).

---

## K. Rules

**K1. Priority and level.** If the product has an OFF PNNS group, it is used. Otherwise rules
K2–K4 apply. **Group 1** (9 categories) is used rather than group 2 (about 40), so that every
chain × category cell has enough products.

**K2. Homogeneous shop sub-categories decide first,** e.g. "Softdrinks", "Käse",
"Schokolade", "Müesli & Flakes", the meat and the fruit-and-vegetable ones.
*Rationale:* in the validation, all their matched products have the same PNNS group. The name
also misleads: in "Softdrinks", "Orange, Zero" is a soft drink, not a fruit.

**K3. Name keywords** (German, French and Italian, because the OFF names of Migros and Coop
products are often French). The first matching rule wins. The order follows PNNS conventions
that are not obvious and that came out of the errors of the first version:
- Composite dishes first (pizza, lasagne, sandwich, fondue), because they contain words of
  every other group.
- Soups are "Fruits and vegetables".
- Legumes and tofu are "Cereals and potatoes", as are potato crisps.
- Sauces, pestos, stocks and condiments are "Fat and sauces", ahead of the vegetable or meat
  words they contain ("Tomatensauce", "Burger sauce").
- Ice cream and dairy desserts are "Milk and dairy products". Milk chocolate is "Sugary
  snacks", so the sweets rule comes before the dairy rule.
- Nuts, olives and pickles are "Salty snacks".
- Maize is "Cereals and potatoes".

**K4. Any other mapped shop sub-category,** if no keyword matches. Mixed sub-categories
("Konserven", "Backzutaten") are not mapped.

## V. Validation

**V1. Against OFF's PNNS group**, on products that have both:

| Chain | Products | With a rule category | Same group as OFF |
|---|---:|---:|---:|
| Volg (shop + name) | 97 | 99 % | 93 % |
| Aldi (shop + name) | 202 | 93 % | 88 % |
| Migros (name only) | 217 | 71 % | 88 % |
| Coop (name only) | 119 | 77 % | 90 % |
| Lidl (name only) | 32 | 66 % | 86 % |
| All Swiss OFF entries (name only) | 39 791 | 67 % | 75 % |

**Note:** the rules were tuned by looking at the errors in the first five rows, so those
figures are optimistic. The last row was not used for tuning and is the more honest estimate
for the name rules alone. It has names in every language, many of them generic ("Classic",
"Bio"). The name rules alone are used for only 24 Migros, Coop, Lidl and Denner products. The
289 Volgshop ones also use the shop sub-category.

## Limitations

- **Small cells.** Outside Aldi, Volgshop, Migros and Coop the cells are too small to compare
  categories, and some Coop ones too (Fish Meat Eggs 6, Fruits and vegetables 7). H2 by
  category should be limited to the four large chains, or merge categories.
- **PNNS is OFF's convention, not the only possible one.** Potato crisps in "Cereals and
  potatoes" looks odd, but it is what OFF does for the 666 products that already have a PNNS
  group, and mixing conventions would be worse.
- **19 products have no category:** spices, vinegar and brand names without context ("bueno",
  "Pancroc"). They drop out of models that control for category.
