# AI usage log

Running log of AI tool usage: what was asked, whether the output was usable, and what had to be corrected by hand.

| Date | Tool | Task | Usable? | Manual corrections |
|---|---|---|---|---|
| 2026-11-03 | Claude Code (Opus 5.5) | Open Food Facts pipeline: download of the CSV export, Swiss extraction and cleaning (`src/openfoodfacts.py`), decision log (`docs/off_cleaning_decisions.md`) | Yes | First version of the kJ/kcal rule removed 2,896 rows; profiling showed 93 % had a correct kJ value, so the rule was changed to cross-check against macronutrients (196 rows removed). Retailer brand lists to be reviewed by the team. |
| 2026-11-03 | Claude Code (Opus 5.5) | Aldi and Volgshop scrapers (`src/scraping.py`) via their public JSON APIs; parser for Volgshop's free-text nutrition field | Yes | First nutrition parser matched 1 of 433 texts; rewritten after profiling the label variants (418 of 433 parsed). Remaining misses are mineral waters or ingredient lists in the nutrition field. |
| 2026-11-03 | Claude Code (Opus 5.5) | Aldi and Volgshop cleaning (`src/retail_cleaning.py`), decision log (`docs/retail_cleaning_decisions.md`) | Yes | Fixed during review: egg weight "53g+" read as package size; portion column ("1 Portion (30g)") taken as nutrition basis; theme sub-categories ("Grillsaucen & Gewürze") used as product categories; scraped_at labelled UTC but formatted in local time; F5 breakdown in the doc first overstated count-based items. Non-food brand list for Aldi to be reviewed by the team. |
