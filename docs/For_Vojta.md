# Pro Vojtu: data pro SQL databázi

Ahoj Vojto, tady je všechno, co potřebuješ vědět o datech, abys mohl postavit SQL databázi
(PostgreSQL). Stav k 10. 11. 2026, větev `data/off-acquisition-v1`.

*Spanish version: [`For_Vojta_es.md`](For_Vojta_es.md).*

**Zkrácená verze:** všechno důležité je v jedné tabulce,
`data/processed/products_matched.parquet` (2 443 řádků, jeden řádek = jeden produkt v jednom
řetězci). Pro analýzu (H1, H2) je použitelných **1 045 produktů**, které mají cenu za 100 g/ml,
Nutri-Score i společnou kategorii. Ostatní tabulky jsou mezikroky nebo zdrojová data.

---

## 1. Odkud data jsou

| Zdroj | Co dává | Jak jsme ho získali |
|---|---|---|
| **Aldi Suisse** (aldi-suisse.ch) | ceny, velikost balení, značka, kategorie, složení | veřejné JSON API e-shopu, 3. 11. 2026 |
| **Volgshop** (volgshop.ch) | ceny, velikost balení, nutriční tabulka, země výroby, složení | veřejné JSON API e-shopu (WooCommerce), 3. 11. 2026 |
| **Open Food Facts (OFF)** | nutriční hodnoty, Nutri-Score, NOVA, kategorie, EAN | kompletní CSV export (~1,5 GB), 2.–3. 11. 2026 |
| **Open Prices** | ceny z Migros, Coop, Lidl, Denner (podle EAN) | veřejné API, 10. 11. 2026 |

Migros a Coop blokují scraping (anti-bot ochrana), proto jejich ceny bereme z Open Prices.
To je komunitní projekt OFF, kde dobrovolníci fotí cenovky a účtenky. Aldi ani Volgshop
nezveřejňují EAN, takže jejich produkty jsme s OFF spárovali podle **značky a názvu**
(fuzzy matching).

## 2. Soubory

Všechny tabulky existují ve dvou formátech: `.parquet` (se správnými datovými typy, doporučuji
pro import) a `.csv` (UTF-8, oddělovač `,`, seznamy spojené znakem `|`).

### Hlavní tabulka (tu potřebuješ)

| Soubor | Řádků | Klíč | Obsah |
|---|---:|---|---|
| `data/processed/products_matched.parquet` | 2 443 | (`retailer`, `retailer_id`) | všechny řetězce: cena + výživa + Nutri-Score + kategorie |

### Podpůrné tabulky (volitelné)

| Soubor | Řádků | Klíč | Obsah |
|---|---:|---|---|
| `off_ch_clean.parquet` | 73 738 | `code` (EAN) | vyčištěné švýcarské produkty z OFF (pro clustering) |
| `off_aldi_ext_clean.parquet` | 15 162 | `code` | německé a rakouské záznamy OFF pro značky Aldi |
| `off_openprices_ext_clean.parquet` | 105 | `code` | záznamy OFF z jiných zemí pro EAN z Open Prices |
| `aldi_clean.parquet` | 1 577 | `sku` | vyčištěný katalog Aldi |
| `volg_clean.parquet` | 445 | `product_id` | vyčištěný katalog Volgshop |
| `openprices_clean.parquet` | 435 | (`chain`, `code`) | vyčištěné ceny z Open Prices |
| `matches.parquet` | 2 022 | (`retailer`, `retailer_id`) | nejlepší kandidát z OFF pro každý produkt Aldi/Volg, se skóre |
| `*_cleaning_log.csv` | | | kolik řádků odstranilo které pravidlo |
| `*_metadata.json` | | | původ dat (URL, datum, SHA-256) |

Surová data jsou v `data/raw/`; pro databázi je nepotřebuješ.

## 3. Sloupce hlavní tabulky `products_matched`

**Identifikace a obchod**

| Sloupec | Typ | Hodnoty / poznámka |
|---|---|---|
| `retailer` | text | `aldi` 1 577, `volg` 445, `migros` 242, `coop` 131, `lidl` 33, `denner` 15 |
| `retailer_id` | text | ID produktu v obchodě (SKU u Aldi, id u Volg, **EAN** u Migros/Coop/Lidl/Denner) |
| `name`, `brand` | text | název a značka (u Volg často bez značky) |
| `category_main`, `category_sub` | text | vlastní kategorie obchodu (jen Aldi a Volg; **nepoužívat pro srovnání**, viz `category_common`) |
| `is_organic` | bool | bio produkt |

**Cena**

| Sloupec | Typ | Hodnoty / poznámka |
|---|---|---|
| `price_chf` | double | běžná cena (ne akční) v CHF |
| `size_value`, `size_unit` | double, text | velikost balení v `g` nebo `ml` |
| `price_per_100_chf` | double | **závislá proměnná**: cena za 100 g nebo 100 ml |
| `price_per_100_unit` | text | `g` (2 091) nebo `ml` (352); g a ml se **nesmí míchat** bez rozlišení |
| `price_source` | text | `retailer_web` (Aldi, Volg) nebo `open_prices` |
| `price_date` | date | datum ceny (3. 11. 2026 pro Aldi/Volg; 2024–2026 pro Open Prices) |

**Párování s OFF**

| Sloupec | Typ | Hodnoty / poznámka |
|---|---|---|
| `matched` | bool | produkt má záznam v OFF |
| `match_method` | text | `ean` (Open Prices), `brand`, `store_name`, `generic_brand_in_store`; NULL = nespárováno |
| `match_score` | double | podobnost názvů 0–100 (jen Aldi/Volg) |
| `off_code` | text | EAN záznamu v OFF → cizí klíč do tabulek OFF |
| `off_scope` | text | `ch` (švýcarský záznam), `de_at` (německý/rakouský), `openprices_ext` (jiná země) |
| `off_name`, `off_main_category`, `off_pnns_group_1/2`, `off_nova_group`, `off_origin_status` | | údaje převzaté z OFF |
| `off_nutriscore_grade`, `off_nutriscore_score` | | Nutri-Score přímo z OFF (bez dopočtu) |

**Výživa (na 100 g/ml)**

| Sloupec | Typ | Hodnoty / poznámka |
|---|---|---|
| `energy_kj`, `fat`, `saturated_fat`, `carbohydrates`, `sugars`, `fiber`, `proteins`, `salt` | double | gramy na 100 g/ml (energie v kJ); `fiber` často chybí |
| `nutrition_source` | text | `retailer` (vlastní tabulka Volg, 381), `off` (708), NULL = bez výživy (1 354) |

**Nutri-Score (použít tyto sloupce)**

| Sloupec | Typ | Hodnoty / poznámka |
|---|---|---|
| `nutriscore_grade` | text | **`a`–`e`, pro analýzu.** Z OFF, a když chybí, dopočítaný |
| `nutriscore_score` | double | číselné skóre (nižší = zdravější) |
| `nutriscore_source` | text | `off` (706) nebo `computed` (358) |
| `nutriscore_calc_grade`, `nutriscore_calc_score` | | náš výpočet pro všechny produkty s výživou (pro kontrolu citlivosti) |
| `nutriscore_kind` | text | typ algoritmu: `general`, `beverage`, `fat`, `cheese`, `water`, `red_meat`, `not_applicable`, `unsupported` |
| `nutriscore_category_source` | text | odkud je `nutriscore_kind`: `off_categories` nebo `retailer_name` |

**Společná kategorie (použít pro srovnání mezi obchody)**

| Sloupec | Typ | Hodnoty / poznámka |
|---|---|---|
| `category_common` | text | 9 skupin PNNS: Beverages, Cereals and potatoes, Composite foods, Fat and sauces, Fish Meat Eggs, Fruits and vegetables, Milk and dairy products, Salty snacks, Sugary snacks |
| `category_common_source` | text | `off`, `shop_category`, `name` (pravidlo podle názvu) |
| `category_rules` | text | kategorie podle našich pravidel (pro kontrolu) |

**Původ (pro H3)**

| Sloupec | Hodnoty / poznámka |
|---|---|
| `origin_status_retailer` | `domestic` / `imported`: jen Volg, **země výroby** (426 produktů) |
| `off_origin_status` | `domestic` / `imported` / `mixed`: z OFF, **původ surovin** (179 produktů) |

Pozor: jsou to dva různé pojmy. Čokoláda vyrobená ve Švýcarsku z ghanského kakaa je u Volg
`domestic` a v OFF `imported`.

## 4. Návrh schématu (PostgreSQL)

Odpovídá plánu z README (products, nutrition 1:1, categories n:1, retailers n:1), doplněnému
o tabulku produktů OFF. Je to jen návrh, uprav si ho podle potřeby.

```sql
CREATE TABLE retailers (
    retailer_id   TEXT PRIMARY KEY,          -- 'aldi', 'volg', 'migros', 'coop', 'lidl', 'denner'
    name          TEXT NOT NULL,
    price_source  TEXT NOT NULL              -- 'retailer_web' | 'open_prices'
);

CREATE TABLE categories (
    category_id   SERIAL PRIMARY KEY,
    pnns_group_1  TEXT UNIQUE NOT NULL       -- 9 PNNS groups
);

-- Union of off_ch_clean, off_aldi_ext_clean and off_openprices_ext_clean.
-- 17 codes appear in both extensions: deduplicate by code (priority ch > de_at > openprices_ext).
CREATE TABLE off_products (
    code              TEXT PRIMARY KEY,      -- EAN-13 / EAN-8
    scope             TEXT NOT NULL,         -- 'ch' | 'de_at' | 'openprices_ext'
    product_name      TEXT,
    brands            TEXT,
    main_category     TEXT,
    pnns_group_1      TEXT,
    pnns_group_2      TEXT,
    nutriscore_grade  CHAR(1),
    nutriscore_score  INTEGER,
    nova_group        SMALLINT,
    origin_status     TEXT
    -- + nutrients, if you want to do the clustering on all 73 738 products in SQL
);

CREATE TABLE products (
    product_id          SERIAL PRIMARY KEY,
    retailer_id         TEXT NOT NULL REFERENCES retailers,
    retailer_product_id TEXT NOT NULL,       -- products_matched.retailer_id
    name                TEXT NOT NULL,
    brand               TEXT,
    shop_category_main  TEXT,
    shop_category_sub   TEXT,
    category_id         INTEGER REFERENCES categories,   -- from category_common
    category_source     TEXT,
    size_value          DOUBLE PRECISION,
    size_unit           TEXT CHECK (size_unit IN ('g', 'ml')),
    price_chf           NUMERIC(8, 2) NOT NULL,
    price_per_100_chf   NUMERIC(10, 4) NOT NULL,
    price_per_100_unit  TEXT NOT NULL CHECK (price_per_100_unit IN ('g', 'ml')),
    price_source        TEXT NOT NULL,
    price_date          DATE NOT NULL,
    is_organic          BOOLEAN,
    origin_status_retailer TEXT,
    off_code            TEXT REFERENCES off_products,
    match_method        TEXT,
    match_score         DOUBLE PRECISION,
    UNIQUE (retailer_id, retailer_product_id)
);

CREATE TABLE nutrition (
    product_id        INTEGER PRIMARY KEY REFERENCES products,   -- 1:1
    nutrition_source  TEXT NOT NULL,         -- 'retailer' | 'off'
    energy_kj         DOUBLE PRECISION,
    fat               DOUBLE PRECISION,
    saturated_fat     DOUBLE PRECISION,
    carbohydrates     DOUBLE PRECISION,
    sugars            DOUBLE PRECISION,
    fiber             DOUBLE PRECISION,
    proteins          DOUBLE PRECISION,
    salt              DOUBLE PRECISION,
    nutriscore_grade  CHAR(1) CHECK (nutriscore_grade IN ('a','b','c','d','e')),
    nutriscore_score  DOUBLE PRECISION,
    nutriscore_source TEXT,                  -- 'off' | 'computed'
    nutriscore_kind   TEXT,
    nutriscore_calc_grade CHAR(1),
    nutriscore_calc_score DOUBLE PRECISION
);
```

Poznámky k importu:
- **Do `nutrition` dávej jen řádky s `nutrition_source IS NOT NULL`** (1 089 řádků). Ostatní
  produkty (hlavně nespárované Aldi) výživu nemají.
- Každý produkt s Nutri-Score má i nutriční tabulku, takže `nutrition` obsáhne všech 1 064
  produktů se známkou.
- `nutriscore_kind` je vyplněný u všech řádků, ale smysl má jen tam, kde existuje
  `nutriscore_calc_grade`.
- Více produktů může ukazovat na stejný `off_code` (stejný výrobek ve více obchodech): 816
  odkazů na 790 různých EAN. Vztah je tedy n:1.
- Parquet čte přímo DuckDB (`SELECT * FROM 'file.parquet'`) nebo pandas
  (`pd.read_parquet`). `requirements.txt` zatím obsahuje jen `duckdb` a `rapidfuzz`; pro
  PostgreSQL bude potřeba přidat `sqlalchemy` a `psycopg`.

Užitečný kontrolní dotaz po importu (mělo by vyjít 1 045):

```sql
SELECT count(*)
FROM products p JOIN nutrition n USING (product_id)
WHERE n.nutriscore_grade IS NOT NULL AND p.category_id IS NOT NULL;
```

## 5. Jak data znovu vygenerovat

```bash
python src/openfoodfacts.py all             # OFF: stažení, švýcarský výběr, čištění
python src/scraping.py all                  # Aldi a Volgshop
python src/retail_cleaning.py               # čištění katalogů obchodů
python src/openfoodfacts.py aldi-ext        # německé/rakouské záznamy OFF pro Aldi
python src/scraping.py aldi-details         # složení produktů Aldi
python src/openprices.py all                # ceny Migros/Coop/Lidl/Denner
python src/openfoodfacts.py openprices-ext  # záznamy OFF pro EAN z Open Prices
python src/matching.py                      # párování + products_matched (Nutri-Score, kategorie)
```

Pozor: OFF se mění každý den, takže nové stažení nedá přesně stejná čísla. Snapshoty, které
jsme použili, jsou uložené v gitu (`data/raw/*.parquet`).

---

## 6. Rozhodnutí při čištění (shrnutí)

Podrobnosti a zdůvodnění jsou v `docs/*_decisions.md` (anglicky). Tady je to nejdůležitější.

### Open Food Facts (107 342 → 73 738 produktů)

- Bereme jen produkty označené jako prodávané ve **Švýcarsku**.
- **Odstraněno:** neplatný EAN (1 775, většinou kódy z vah s cenou uvnitř), alkohol (cenu určuje
  spotřební daň, ne výživa), dětská výživa, nepotraviny.
- **Musí být všech 6 základních živin:** energie, tuky, nasycené tuky, cukry, bílkoviny, sůl
  (odstraněno 29 025). Vláknina povinná není, chybí u 46 % produktů.
- **Odstraněny fyzikálně nemožné hodnoty:** živina > 100 g na 100 g, energie > 3800 kJ, nasycené
  tuky > tuky, součet makroživin > 105 g, nesouhlasící kJ a kcal (celkem 578 řádků).
- **Nic se nedopočítává (žádná imputace)** a neodstraňují se statistické odlehlé hodnoty:
  olej s 90 g tuku je extrémní, ale skutečný.
- Energie se uvádí v kJ, sůl místo sodíku.
- Řetězec (`at_migros`, `at_coop`…) se odvozuje z pole „obchody“ a z vlastních značek
  (M-Classic → Migros, Naturaplan → Coop). `false` znamená „nevíme“, ne „neprodává se tam“.

### Aldi a Volgshop (2 406 → 1 577 a 696 → 445 produktů)

- **Odstraněno:** nepotraviny, alkohol a tabák (nealkoholické pivo a víno zůstávají), dětská
  výživa.
- **Musí jít spočítat cena za 100 g/ml.** Odstraněny produkty bez velikosti balení, prodávané
  na kusy (kapsle, vejce, ovoce na kusy) nebo s rozsahem hmotnosti.
- **Odstraněna cena za 100 g mimo 0,01–50 CHF** (6 produktů: koření a zdobení po pár gramech
  a jedna chyba v datech).
- **Vždy běžná cena, ne akční** (u Aldi 64 produktů v akci, akční cena je uložena zvlášť).
- Opraveny chyby „kg místo g“ (např. „Müsli 750 kg“).
- **Volgshop:** vlastní nutriční tabulka se parsuje z textu a kontroluje stejnými pravidly
  jako OFF. Když je chybná, produkt zůstane, jen bez výživy.
- **Volgshop:** země výroby: Švýcarsko a Lichtenštejnsko = `domestic`.

### Párování Aldi/Volg s OFF (Aldi 273 z 1 577, Volg 122 z 445)

- **Bez EAN:** porovnává se jen v rámci stejné značky, a pak podobnost názvů (0–100).
  Přijímá se skóre ≥ 90, nebo ≥ 75 se shodnou velikostí balení.
- **Raději přesnost než počet:** špatný pár by do regrese vnesl špatnou výživu. Ruční kontrola
  100 párů: všechny správně. U Volg se 90 % párů shoduje i v nutričních hodnotách.
- **Složení slouží jen k vyřazení páru,** ne k jeho vytvoření.
- **Pro Aldi se používají i německé a rakouské záznamy OFF** (stejné značky jako Aldi Süd a
  Hofer). Bez nich by se spárovalo jen 6,5 % sortimentu.
- **Slabina:** švýcarské vlastní značky Aldi (Saveurs Suisses, Panetteria) v OFF vůbec nejsou.

### Open Prices (1 050 cen → 435 produktů)

- **Jen obchody ve Švýcarsku** (bez Lichtenštejnska) a jen řetězce Migros, Coop, Lidl, Denner,
  Aldi a Volg. Bez formátů s vlastním ceníkem (Coop Pronto, Migrolino, Denner Express).
- **Bez akčních cen.**
- **Pro každý produkt v každém řetězci nejnovější cena.** Ceny jsou z let 2024–2026; sloupec
  `price_date` umožňuje to kontrolovat.
- **Není to náhodný vzorek:** 123 dobrovolníků, hlavně francouzská část Švýcarska.

### Dopočítaný Nutri-Score (706 → 1 064 produktů se známkou)

- **OFF dává známku jen spárovaným produktům.** Pro ostatní s kompletní tabulkou (hlavně
  Volg) ji počítáme algoritmem 2023, stejným jako OFF.
- **Validace:** na 42 232 produktech OFF dává náš výpočet stejnou známku v 97,7 % případů.
  U Volg 86 % přesně a 97 % s odchylkou nejvýš jeden stupeň.
- **Nejistá část je podíl ovoce, zeleniny a luštěnin.** Volg ho neuvádí, takže se odhaduje ze
  složení.
- **`nutriscore_source`** umožňuje udělat analýzu jen se známkami z OFF (kontrola citlivosti).

### Společná kategorie (1 045 z 1 064 produktů)

- **Kategorie obchodů nejsou srovnatelné,** proto používáme 9 skupin PNNS z OFF.
- **Produkty bez PNNS** dostanou kategorii podle podkategorie obchodu a klíčových slov v názvu.
  Shoda s OFF je 88–93 %.
- **PNNS má své zvyklosti:** chipsy a luštěniny patří do „Cereals and potatoes“, ořechy a olivy
  do „Salty snacks“, polévky do „Fruits and vegetables“.

## 7. Na co si dát pozor

- **Cena za 100 g a za 100 ml nejsou srovnatelné.** V dotazech a modelech je rozlišuj přes
  `price_per_100_unit`.
- **Ceny z Open Prices jsou z jiných dat** než ceny Aldi a Volg.
- **Lidl (33) a Denner (15) mají málo produktů** na srovnání po kategoriích. Rozumné je
  srovnávat Aldi, Volg, Migros a Coop.
- **Nespárované produkty Aldi** (1 304) mají cenu, ale nemají výživu ani Nutri-Score. Do
  analýzy H1/H2 nevstupují, ale v databázi je klidně měj.
- **Ještě to musí zkontrolovat tým:** soubor `match_review_sample.csv` s ruční kontrolou párů
  (sloupce `correct` a `comment` jsou prázdné) a seznamy klíčových slov v `src/categories.py`
  a `src/nutriscore.py`. Zatím je kontroloval jen Claude Code.

Kdyby něco nebylo jasné, napiš mi.
