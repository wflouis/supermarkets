"""Open Food Facts: download, Swiss extraction and cleaning.

Pipeline (each step reads the previous step's output from disk):

    download  ->  data/raw/off_products.csv.gz         full OFF CSV export (~1.5 GB, gitignored)
    extract   ->  data/raw/off_ch_raw.parquet          products sold in Switzerland, raw text
    clean     ->  data/processed/off_ch_clean.parquet  analysis-ready table (+ .csv)
                  data/processed/off_ch_cleaning_log.csv   rows removed per filter
                  data/processed/off_ch_metadata.json      snapshot provenance

Usage:
    python src/openfoodfacts.py all        # download + extract + clean
    python src/openfoodfacts.py extract    # skip the download, reuse the CSV on disk
    python src/openfoodfacts.py clean      # only re-run cleaning from off_ch_raw.parquet

Every filtering and cleaning rule is justified in docs/off_cleaning_decisions.md.
The rule ids (F1, C1, ...) in the comments below refer to that document.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"

DUMP_URL = "https://static.openfoodfacts.org/data/en.openfoodfacts.org.products.csv.gz"
USER_AGENT = "supermarkets-student-project/0.1 (academic research; https://github.com/wflouis/supermarkets)"

CSV_PATH = RAW_DIR / "off_products.csv.gz"
RAW_PATH = RAW_DIR / "off_ch_raw.parquet"
CLEAN_PATH = PROCESSED_DIR / "off_ch_clean.parquet"
CLEAN_CSV_PATH = PROCESSED_DIR / "off_ch_clean.csv"
LOG_PATH = PROCESSED_DIR / "off_ch_cleaning_log.csv"
META_PATH = PROCESSED_DIR / "off_ch_metadata.json"

# Columns kept from the ~210 in the export (decision E2).
RAW_COLUMNS = [
    "code", "product_name", "generic_name", "quantity", "product_quantity", "brands",
    "categories_tags", "main_category", "pnns_groups_1", "pnns_groups_2", "food_groups_tags",
    "origins", "origins_tags", "manufacturing_places_tags", "labels_tags", "stores",
    "countries_tags", "nutriscore_score", "nutriscore_grade", "nova_group", "states_tags",
    "data_quality_errors_tags", "completeness", "unique_scans_n", "created_t", "last_modified_t",
    "energy-kj_100g", "energy-kcal_100g", "fat_100g", "saturated-fat_100g", "carbohydrates_100g",
    "sugars_100g", "fiber_100g", "proteins_100g", "salt_100g", "alcohol_100g",
    "fruits-vegetables-legumes_100g",
]

# Nutrients that must all be present for a product to stay (F6).
CORE_NUTRIENTS = ["energy_kj", "fat", "saturated_fat", "sugars", "proteins", "salt"]

# Retailer attribution (C9). Store strings are matched after lower-casing and trimming.
STORE_PATTERNS = {
    "migros": r"\bmigros\b|\bmigrolino\b",
    "coop": r"^coop\b|\bcoop$|\bcoop (pronto|city|extra|vaud|suisse|obs)\b|\bmigros (et )?coop\b",
    "denner": r"^denner\b",
    "aldi": r"^aldi( suisse| schweiz)?$",      # excludes "aldi süd", "aldi nord" (Germany)
    "lidl": r"^lidl( schweiz)?$",
    "volg": r"^volg$",
}
# Own brands that are sold exclusively by one Swiss retailer. Matched against each
# brand after lower-casing, replacing "-" with " " and collapsing whitespace.
OWN_BRANDS = {
    "migros": ["migros", "migros bio", "migros sélection", "m classic", "mclassic", "m budget",
               "anna's best", "v love", "terrasuisse", "optigal"],
    "coop": ["coop", "coop naturaplan", "naturaplan", "coop qualité & prix", "qualité & prix",
             "coop prix garantie", "prix garantie", "karma", "coop karma", "betty bossi",
             "coop betty bossi", "fine food", "coop fine food", "naturafarm", "coop naturafarm"],
    "denner": ["denner"],
    "volg": ["volg"],
}


# --------------------------------------------------------------------------- download
def download(dest: Path = CSV_PATH, url: str = DUMP_URL) -> Path:
    """Stream the full OFF CSV export to disk (decision E1)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as out:
        shutil.copyfileobj(resp, out, length=1 << 20)
    tmp.replace(dest)
    return dest


# --------------------------------------------------------------------------- extract
def extract_swiss(src: Path = CSV_PATH, dst: Path = RAW_PATH) -> dict:
    """Keep products tagged as sold in Switzerland, selected columns, all as text (E2-E4)."""
    con = duckdb.connect()
    cols = ", ".join(f'"{c}"' for c in RAW_COLUMNS)
    # The export is tab-separated and unquoted; quote='' stops stray " characters in
    # product names from swallowing the following lines.
    reader = (f"read_csv('{src.as_posix()}', delim='\t', quote='', header=true, all_varchar=true, "
              f"ignore_errors=true, store_rejects=true, max_line_size=10000000)")
    dst.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"""COPY (SELECT {cols} FROM {reader}
                          WHERE list_contains(string_split(countries_tags, ','), 'en:switzerland'))
                    TO '{dst.as_posix()}' (FORMAT parquet)""")
    stats = {
        "swiss_rows": con.execute(f"SELECT count(*) FROM '{dst.as_posix()}'").fetchone()[0],
        "rejected_lines_whole_file": con.execute("SELECT count(*) FROM reject_errors").fetchone()[0],
    }
    return stats


# --------------------------------------------------------------------------- clean
def _norm_brand_sql(expr: str) -> str:
    return f"trim(regexp_replace(replace(lower({expr}), '-', ' '), '\\s+', ' ', 'g'))"


def clean(src: Path = RAW_PATH, out_dir: Path = PROCESSED_DIR) -> list[tuple]:
    """Apply filters F1-F7 and transformations C1-C12; write table, log and metadata."""
    con = duckdb.connect()
    log: list[tuple] = []

    def step(rule: str, description: str, sql: str) -> None:
        before = con.execute("SELECT count(*) FROM cur").fetchone()[0]
        con.execute(f"CREATE OR REPLACE TABLE nxt AS {sql}")
        con.execute("DROP TABLE cur; ALTER TABLE nxt RENAME TO cur")
        after = con.execute("SELECT count(*) FROM cur").fetchone()[0]
        log.append((rule, description, before, before - after, after))

    num = lambda c: f'try_cast("{c}" AS DOUBLE)'  # noqa: E731
    text = lambda c: f"nullif(trim(regexp_replace({c}, '\\s+', ' ', 'g')), '')"  # noqa: E731
    tags = lambda c: f"list_filter(string_split(nullif({c}, ''), ','), lambda s: s <> '')"  # noqa: E731

    # C1-C5: types, text, codes, energy. Nothing is removed here.
    con.execute(f"""CREATE TABLE cur AS
        WITH typed AS (
            SELECT
                code AS code_raw,
                CASE WHEN length(code) = 12 THEN '0' || code
                     WHEN length(code) = 14 AND code[1] = '0' THEN code[2:]
                     ELSE code END AS code,
                {text('product_name')} AS product_name,
                {text('generic_name')} AS generic_name,
                {text('brands')} AS brands,
                {text('quantity')} AS quantity,
                {num('product_quantity')} AS product_quantity,
                {text('stores')} AS stores,
                {tags('categories_tags')} AS categories_tags,
                nullif(main_category, '') AS main_category,
                nullif(nullif(pnns_groups_1, ''), 'unknown') AS pnns_group_1,
                nullif(nullif(pnns_groups_2, ''), 'unknown') AS pnns_group_2,
                {tags('labels_tags')} AS labels_tags,
                {tags('origins_tags')} AS origins_tags,
                {tags('manufacturing_places_tags')} AS manufacturing_places_tags,
                {tags('countries_tags')} AS countries_tags,
                CASE WHEN nutriscore_grade IN ('a','b','c','d','e') THEN nutriscore_grade END
                    AS nutriscore_grade,
                CASE WHEN nutriscore_grade IN ('a','b','c','d','e')
                     THEN try_cast(nutriscore_score AS INTEGER) END AS nutriscore_score,
                CASE WHEN nova_group IN ('1','2','3','4') THEN nova_group::INTEGER END AS nova_group,
                coalesce({num('energy-kj_100g')}, {num('energy-kcal_100g')} * 4.184) AS energy_kj,
                {num('energy-kj_100g')} AS energy_kj_declared,
                {num('energy-kcal_100g')} AS energy_kcal_declared,
                {num('fat_100g')} AS fat,
                {num('saturated-fat_100g')} AS saturated_fat,
                {num('carbohydrates_100g')} AS carbohydrates,
                {num('sugars_100g')} AS sugars,
                {num('fiber_100g')} AS fiber,
                {num('proteins_100g')} AS proteins,
                {num('salt_100g')} AS salt,
                {num('fruits-vegetables-legumes_100g')} AS fruits_vegetables_legumes,
                {num('completeness')} AS completeness,
                try_cast(unique_scans_n AS INTEGER) AS unique_scans_n,
                make_timestamp(try_cast(created_t AS BIGINT) * 1000000) AS created_at,        -- UTC
                make_timestamp(try_cast(last_modified_t AS BIGINT) * 1000000) AS last_modified_at
            FROM '{src.as_posix()}'
        )
        SELECT * FROM typed""")

    # F1: identifier must be a GS1 code (EAN-8 / EAN-13 after normalisation) with a valid check digit.
    checksum = ("(10 - list_sum(list_transform(range(1, length(code)), lambda i: "
                "cast(substring(code, length(code) - i, 1) AS INTEGER) * "
                "(CASE WHEN i % 2 = 1 THEN 3 ELSE 1 END))) % 10) % 10")
    step("F1", "Code is not a valid EAN-8/EAN-13 (wrong length or check digit)",
         f"""SELECT * FROM cur WHERE regexp_full_match(code, '[0-9]+') AND length(code) IN (8, 13)
             AND {checksum} = cast(right(code, 1) AS INTEGER)""")

    # F2: one row per code, keep the most recently edited entry.
    step("F2", "Duplicate code (kept the most recently modified entry)",
         """SELECT * EXCLUDE (rn) FROM (
                SELECT *, row_number() OVER (PARTITION BY code
                                             ORDER BY last_modified_at DESC NULLS LAST) AS rn
                FROM cur) WHERE rn = 1""")

    # F3-F5: out-of-scope categories.
    has_cat = lambda pattern: f"len(list_filter(categories_tags, lambda s: regexp_matches(s, '{pattern}'))) > 0"  # noqa: E731
    step("F3", "Alcoholic beverage",
         f"SELECT * FROM cur WHERE NOT coalesce({has_cat('^en:alcoholic-beverages$')}, false)")
    step("F4", "Baby / infant food",
         f"""SELECT * FROM cur WHERE NOT coalesce({has_cat('^en:baby-foods?$|^en:baby-milks$|^en:infant')}, false)
             AND coalesce(pnns_group_1, '') <> 'Baby foods'""")
    step("F5", "Non-food item (pet food, cosmetics, household)",
         f"""SELECT * FROM cur WHERE NOT coalesce({has_cat('^en:non-food|pet-food|^en:cosmetics|^en:dog-food|^en:cat-food')}, false)""")

    # F6: core nutrition table must be complete.
    step("F6", "Missing at least one core nutrient (energy, fat, saturated fat, sugars, proteins, salt)",
         "SELECT * FROM cur WHERE " + " AND ".join(f"{c} IS NOT NULL" for c in CORE_NUTRIENTS))

    # F7: physically impossible / internally inconsistent nutrition tables.
    grams = ["fat", "saturated_fat", "carbohydrates", "sugars", "fiber", "proteins", "salt"]
    in_range = " AND ".join(f"({c} IS NULL OR {c} BETWEEN 0 AND 100)" for c in grams)
    step("F7a", "Nutrient outside 0-100 g per 100 g", f"SELECT * FROM cur WHERE {in_range}")
    step("F7b", "Energy outside 0-3800 kJ per 100 g",
         "SELECT * FROM cur WHERE energy_kj BETWEEN 0 AND 3800")
    step("F7c", "Saturated fat > fat or sugars > carbohydrates (0.5 g tolerance)",
         """SELECT * FROM cur WHERE saturated_fat <= fat + 0.5
             AND (carbohydrates IS NULL OR sugars <= carbohydrates + 0.5)""")
    step("F7d", "Fat + carbohydrates + fiber + proteins + salt > 105 g",
         """SELECT * FROM cur WHERE fat + coalesce(carbohydrates, sugars) + coalesce(fiber, 0)
             + proteins + salt <= 105""")
    # kJ and kcal can disagree; the row is kept if kJ matches the energy implied by the
    # macronutrients (fat 37, carbs 17, protein 17, fiber 8 kJ/g) within 20 %.
    macro_kj = "(37 * fat + 17 * coalesce(carbohydrates, sugars) + 17 * proteins + 8 * coalesce(fiber, 0))"
    step("F7e", "kJ and kcal disagree AND kJ does not match energy computed from macros (+-20 %)",
         f"""SELECT * FROM cur WHERE energy_kj_declared IS NULL OR energy_kcal_declared IS NULL
             OR energy_kcal_declared <= 40
             OR energy_kj_declared / energy_kcal_declared BETWEEN 3.6 AND 4.8
             OR abs(energy_kj - {macro_kj}) <= 0.2 * {macro_kj}""")

    # C6-C12: derived columns. Nothing is removed here.
    brand_list = f"list_transform(string_split(coalesce(brands, ''), ','), lambda b: {_norm_brand_sql('b')})"
    store_list = "list_transform(string_split(lower(coalesce(stores, '')), ','), lambda s: trim(s))"
    retailer_cols = []
    for r in STORE_PATTERNS:
        store_hit = f"len(list_filter({store_list}, lambda s: regexp_matches(s, '{STORE_PATTERNS[r]}'))) > 0"
        brands_sql = ", ".join("'" + b.replace("'", "''") + "'" for b in OWN_BRANDS.get(r, []))
        brand_hit = f"len(list_intersect({brand_list}, [{brands_sql}])) > 0" if brands_sql else "false"
        retailer_cols += [f"{store_hit} AS store_{r}", f"{brand_hit} AS own_brand_{r}",
                          f"({store_hit}) OR ({brand_hit}) AS at_{r}"]

    organic = ("len(list_filter(labels_tags, lambda l: l IN ('en:organic', 'en:eu-organic', 'en:bio-suisse') "
               "OR regexp_matches(l, '^en:[a-z]{2}-bio-[0-9]+$'))) > 0")
    con.execute(f"""CREATE OR REPLACE TABLE cur AS SELECT
            * EXCLUDE (energy_kj_declared, energy_kcal_declared, product_quantity),
            -- C6 package size
            CASE WHEN product_quantity > 0 AND product_quantity <= 10000 THEN product_quantity END
                AS product_quantity,
            CASE WHEN product_quantity > 0 AND product_quantity <= 10000 THEN
                CASE WHEN regexp_matches(lower(coalesce(quantity, '')), '[0-9]\\s*(ml|cl|dl|l|ltr|liter|litre)\\b')
                     THEN 'ml' ELSE 'g' END END AS product_quantity_unit,
            -- C7 brand
            nullif({_norm_brand_sql("split_part(brands, ',', 1)")}, '') AS brand_main,
            -- C8 code type
            code[1] = '2' AND length(code) = 13 AS code_is_internal,
            -- C9 retailers
            {", ".join(retailer_cols)},
            -- C10 organic
            coalesce({organic}, false) AS is_organic,
            -- C11 origin
            CASE WHEN origins_tags IS NULL OR len(origins_tags) = 0 THEN NULL
                 WHEN list_bool_and(list_transform(origins_tags, lambda o: o = 'en:switzerland')) THEN 'domestic'
                 WHEN list_contains(origins_tags, 'en:switzerland') THEN 'mixed'
                 ELSE 'imported' END AS origin_status,
            -- C12 nutriscore availability
            nutriscore_grade IS NOT NULL AS has_nutriscore
        FROM cur""")

    order = """code, code_raw, code_is_internal, product_name, generic_name, brands, brand_main,
        quantity, product_quantity, product_quantity_unit, stores,
        at_migros, at_coop, at_denner, at_aldi, at_lidl, at_volg,
        store_migros, own_brand_migros, store_coop, own_brand_coop, store_denner, own_brand_denner,
        store_aldi, own_brand_aldi, store_lidl, own_brand_lidl, store_volg, own_brand_volg,
        main_category, pnns_group_1, pnns_group_2, categories_tags,
        has_nutriscore, nutriscore_grade, nutriscore_score, nova_group,
        energy_kj, fat, saturated_fat, carbohydrates, sugars, fiber, proteins, salt,
        fruits_vegetables_legumes, is_organic, labels_tags, origin_status, origins_tags,
        manufacturing_places_tags, countries_tags, completeness, unique_scans_n,
        created_at, last_modified_at"""
    out_dir.mkdir(parents=True, exist_ok=True)
    clean_path, csv_path = out_dir / CLEAN_PATH.name, out_dir / CLEAN_CSV_PATH.name
    con.execute(f"COPY (SELECT {order} FROM cur ORDER BY code) TO '{clean_path.as_posix()}' (FORMAT parquet)")
    # CSV copy for spreadsheets: lists joined with "|" so they survive the comma delimiter.
    list_cols = ["categories_tags", "labels_tags", "origins_tags", "manufacturing_places_tags", "countries_tags"]
    replace = ", ".join(f"array_to_string({c}, '|') AS {c}" for c in list_cols)
    con.execute(f"""COPY (SELECT * REPLACE ({replace}) FROM '{clean_path.as_posix()}')
                    TO '{csv_path.as_posix()}' (HEADER, DELIMITER ',')""")

    with open(out_dir / LOG_PATH.name, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["rule", "description", "rows_before", "rows_removed", "rows_after"])
        w.writerows(log)
    return log


def write_metadata(extract_stats: dict | None, log: list[tuple]) -> None:
    meta = json.loads(META_PATH.read_text(encoding="utf-8")) if META_PATH.exists() else {}
    if CSV_PATH.exists():
        meta["source_url"] = DUMP_URL
        meta["source_file_bytes"] = CSV_PATH.stat().st_size
        meta["source_downloaded_at"] = datetime.fromtimestamp(
            CSV_PATH.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
    if extract_stats:
        meta["extract"] = extract_stats
        h = hashlib.sha256(RAW_PATH.read_bytes()).hexdigest()
        meta["raw_parquet_sha256"] = h
    meta["cleaned_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta["rows_raw"] = log[0][2]
    meta["rows_clean"] = log[-1][4]
    meta["licence"] = "Open Database License (ODbL) — https://world.openfoodfacts.org/terms-of-use"
    META_PATH.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["download", "extract", "clean", "all"])
    stage = parser.parse_args().stage

    if stage in ("download", "all"):
        print(f"Downloading {DUMP_URL} ...")
        download()
    stats = None
    if stage in ("extract", "all"):
        stats = extract_swiss()
        print(f"Swiss products: {stats['swiss_rows']}  (unparseable lines in whole dump: "
              f"{stats['rejected_lines_whole_file']})")
    if stage in ("clean", "extract", "all"):
        log = clean()
        write_metadata(stats, log)
        width = max(len(r[1]) for r in log)
        for rule, desc, before, removed, after in log:
            print(f"{rule:<4} {desc:<{width}}  -{removed:>6}  -> {after}")


if __name__ == "__main__":
    main()
