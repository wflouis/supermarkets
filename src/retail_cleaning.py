"""Cleaning of the scraped retailer catalogues (Aldi Suisse, Volgshop).

    data/raw/aldi_raw.parquet  ->  data/processed/aldi_clean.parquet (+ .csv)
    data/raw/volg_raw.parquet  ->  data/processed/volg_clean.parquet (+ .csv)
                                   data/processed/retail_cleaning_log.csv   rows removed per filter
                                   data/processed/retail_metadata.json      snapshot provenance

Usage:
    python src/retail_cleaning.py            # both shops
    python src/retail_cleaning.py aldi

Every rule is justified in docs/retail_cleaning_decisions.md. The rule ids in the
comments (C1, F1, ...) refer to that document. C rules transform and never remove
rows; F rules remove rows and are logged with before/after counts.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from scraping import _write_parquet, parse_volg_nutrition

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
LOG_PATH = PROCESSED_DIR / "retail_cleaning_log.csv"
META_PATH = PROCESSED_DIR / "retail_metadata.json"

CORE_NUTRIENTS = ["energy_kj", "fat", "saturated_fat", "sugars", "proteins", "salt"]


# --------------------------------------------------------------------------- shared
_UNITS = {"mg": ("g", 0.001), "g": ("g", 1), "kg": ("g", 1000),
          "ml": ("ml", 1), "cl": ("ml", 10), "dl": ("ml", 100), "l": ("ml", 1000)}
_U = r"(kg|mg|g|ml|cl|dl|l)"
_N = r"(\d+(?:\.\d+)?)"


def parse_size(text: str | None) -> dict | None:
    """Package size in g or ml from strings like "500 g", "6x50cl", "Packung à 250 g",
    "ungefähr 0.2 kg/Stück" (C2).

    Returns None for count-based sizes ("20 Stück", "54 Waschgänge") and for weight
    ranges ("ca. 200g - 400g"), which have no single size to divide the price by.
    For multipacks both the total and the single-unit size are returned.
    """
    if not text:
        return None
    t = text.lower().replace(",", ".").replace("×", "x").replace("–", "-")
    t = re.sub(r"(\d)\s*grs?\b", r"\1g", t)
    t = re.sub(r"\b(ltr|liter)\b", "l", t)
    approx = bool(re.search(r"\bca\.|ungefähr|~", t))
    if re.search(rf"{_N}\s*{_U}?\s*-\s*{_N}\s*{_U}\b", t):
        return None
    t = re.sub(rf"{_N}\s*{_U}\s*\+", " ", t)   # "Eier 53g+": minimum weight per egg, not a size
    m = re.search(rf"{_N}\s*x\s*(?:ca\.\s*)?{_N}\s*{_U}\b", t)
    if m:
        unit, f = _UNITS[m.group(3)]
        single = float(m.group(2)) * f
        return {"value": float(m.group(1)) * single, "unit": unit, "single": single,
                "approx": approx}
    m = re.search(rf"{_N}\s*{_U}\b", t)
    if m:
        unit, f = _UNITS[m.group(2)]
        return {"value": float(m.group(1)) * f, "unit": unit, "single": None, "approx": approx}
    return None


def _fix_kg_typo(size: dict | None) -> bool:
    """C3: '750 kg' muesli at CHF 3.29 is a g/kg mix-up. >= 50 kg is read as g."""
    if size and size["unit"] == "g" and size["value"] >= 50_000:
        size["value"] /= 1000
        if size["single"]:
            size["single"] /= 1000
        return True
    return False


def _per_100(price: float | None, size_value: float | None) -> float | None:
    if price is None or not size_value:
        return None
    return round(price / size_value * 100, 4)


class Pipeline:
    """Row filters with a before/after log, like the OFF cleaning."""

    def __init__(self, shop: str, rows: list[dict]):
        self.shop, self.rows, self.log = shop, rows, []

    def step(self, rule: str, description: str, keep) -> None:
        before = len(self.rows)
        self.rows = [r for r in self.rows if keep(r)]
        self.log.append((self.shop, rule, description, before, before - len(self.rows), len(self.rows)))


def _load(path: Path) -> list[dict]:
    # scraped_at is TIMESTAMPTZ; read as text so fetching does not need pytz.
    rel = duckdb.sql(f"SELECT * REPLACE (strftime(timezone('UTC', scraped_at), '%Y-%m-%dT%H:%M:%SZ') AS scraped_at) "
                     f"FROM '{path.as_posix()}'")
    cols = rel.columns
    return [dict(zip(cols, r)) for r in rel.fetchall()]


def _write(rows: list[dict], columns: list[str], name: str, sort_key: str) -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out = [{c: r.get(c) for c in columns} for r in sorted(rows, key=lambda r: str(r[sort_key]))]
    for r in out:   # timestamps are not JSON-serialisable; keep ISO strings
        for k, v in r.items():
            if isinstance(v, datetime):
                r[k] = v.isoformat()
    pq = PROCESSED_DIR / f"{name}.parquet"
    _write_parquet(out, pq)
    con = duckdb.connect()
    types = dict(con.execute(f"SELECT column_name, column_type FROM "
                             f"(DESCRIBE SELECT * FROM '{pq.as_posix()}')").fetchall())
    list_cols = [c for c, t in types.items() if t.endswith("[]")]
    replace = ", ".join(f"array_to_string({c}, '|') AS {c}" for c in list_cols)
    select = f"* REPLACE ({replace})" if replace else "*"
    # CSV copy for spreadsheets: lists joined with "|" so they survive the delimiter.
    con.execute(f"""COPY (SELECT {select} FROM '{pq.as_posix()}')
                    TO '{(PROCESSED_DIR / f"{name}.csv").as_posix()}' (HEADER, DELIMITER ',')""")


# --------------------------------------------------------------------------- aldi
# Crawl categories that are campaigns or themes, not product types (C4).
ALDI_THEMES = {"Aktionen", "Tiefpreisversprechen", "Grillen", "Weihnachten", "Ostern", "Gourmet",
               "Saveurs Suisses", "Retour aux sources (Bio)", "Testsieger", "Vegetarisch & Vegan"}
# F2: non-food. Top categories, "Aktionen" sub-categories, and brands of non-food items
# that only appear under the generic "Aktionen" or theme categories.
# Top-level product categories (the shop's assortment tree without the themes).
ALDI_PRODUCT_TOPS = {"Alkoholfreie Getränke", "Alkohol & Tabakwaren", "Brot & Backwaren", "Fisch",
                     "Fleisch", "Früchte & Gemüse", "Frühstück", "Gekühlte Produkte",
                     "Gesundheit, Körperpflege & Baby", "Haushalt & Wohnen", "Milchprodukte & Eier",
                     "Süssigkeiten & Snacks", "Tiefgekühlte Produkte", "Vorräte"}
ALDI_NONFOOD_TOP = {"Gesundheit, Körperpflege & Baby", "Haushalt & Wohnen"}
ALDI_NONFOOD_SUB = {
    "Auto, Töff & Velo", "Batterien & Akkus", "Bekleidung & Accessoires", "Beleuchtung",
    "Bücher, Zeitungen & Zeitschriften", "Büroartikel", "Damenbekleidung", "Deko-Artikel",
    "Elektronik", "Garten", "Gesundheit, Körperpflege & Baby", "Haushalt", "Heimtextilien",
    "Herrenbekleidung", "Kinderbekleidung", "Küche", "Outdoor, Sport & Freizeit",
    "Pflanzen & Blumen", "Putz- & Reinigungsmittel", "Spielwaren", "Tierbedarf", "Tiernahrung",
    "Waschmittel & Textilpflege", "Halloween",
}
ALDI_NONFOOD_BRANDS = {"WHISKAS", "SHEBA", "PURINA FELIX", "CATSAN", "DOMESTOS", "POWER FORCE",
                       "SUN", "PANTENE PRO-V", "LACURA", "AMBIANO", "GARDENLINE", "VARTA", "TEMPO"}
ALDI_BABY_BRANDS = {"APTAMIL", "MAMIA", "MAMIA BIO"}
# F3: alcohol under the generic "Aktionen" category, recognised by name. Only applied
# there: elsewhere the same words are flavours ("Rotwein Sauce", "Rum-Traube").
ALDI_ALCOHOL_NAME = re.compile(
    r"\b(aoc|doc|docg|igt|vdf)\b|\bvino\b|\bwein\b|bier|\blager\b|vodka|chenin|sauvignon|"
    r"pinot|syrah|merlot|negroamaro|frizzante|prosecco", re.I)


def _aldi_categories(r: dict) -> tuple[str | None, str | None]:
    """C4: product-type category. The product's own category path if it is not a theme,
    else the first non-theme crawl category, else the theme path's second level if that
    is itself a product category ("Vegetarisch & Vegan > Vorräte"). Otherwise NULL."""
    path = (r["category_path"] or "").split(" > ")
    if path[0] and path[0] not in ALDI_THEMES:
        return path[0], path[1] if len(path) > 1 else None
    for c in r["crawl_categories"] or []:
        if c not in ALDI_THEMES:
            return c, None
    if len(path) > 1 and path[1] in ALDI_PRODUCT_TOPS:
        return path[1], None
    return None, None


def _chf(display: str | None) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)", (display or "").replace("'", ""))
    return float(m.group(1)) if m else None


def clean_aldi() -> list[tuple]:
    rows = _load(RAW_DIR / "aldi_raw.parquet")
    for r in rows:
        path = (r["category_path"] or "").split(" > ")
        r["category_main"], r["category_sub"] = _aldi_categories(r)
        r["category_theme_only"] = r["category_main"] is None or not any(
            c not in ALDI_THEMES for c in r["crawl_categories"] or [])
        r["_top"], r["_sub"] = path[0] or None, path[1] if len(path) > 1 else None
        # C1 prices: the regular price is the analysis price; the promotion is kept apart.
        regular = _chf(r["regular_price_display"])
        r["on_promotion"] = regular is not None
        r["price_promo_chf"] = r["price_chf"] if regular is not None else None
        r["price_chf"] = regular if regular is not None else r["price_chf"]
        # C2/C3 size and unit price
        size = parse_size(r["selling_size"])
        r["size_corrected"] = _fix_kg_typo(size)
        r["size_value"] = size and size["value"]
        r["size_unit"] = size and size["unit"]
        r["size_is_approx"] = bool(size and size["approx"])
        r["price_per_100_chf"] = _per_100(r["price_chf"], r["size_value"])
        r["price_per_100_unit"] = r["size_unit"]
        r["comparison_published_chf"] = r.pop("comparison_price_chf")
        # C5 labels
        badges = r["badges"] or []
        text = f"{r['brand'] or ''} {r['name']}"
        r["is_organic"] = bool(re.search(r"\bbio\b", text, re.I)) or \
            "Retour aux sources (Bio)" in (r["crawl_categories"] or [])
        r["is_vegan"] = "Vegan" in badges
        r["is_vegetarian"] = "Vegan" in badges or "Vegetarisch" in badges
        r["storage"] = ("frozen" if "Tiefgekühlt" in badges else
                        "chilled" if "Gekühlt" in badges else "ambient")

    p = Pipeline("aldi", rows)
    p.step("F1", "Duplicate SKU", _first_seen("sku"))
    p.step("F2", "Non-food (category, Aktionen sub-category or non-food brand)",
           lambda r: r["_top"] not in ALDI_NONFOOD_TOP and r["_sub"] not in ALDI_NONFOOD_SUB
           and (r["brand"] or "") not in ALDI_NONFOOD_BRANDS)
    p.step("F3", "Alcohol or tobacco",
           lambda r: r["_top"] != "Alkohol & Tabakwaren" and not (
               r["category_path"] == "Aktionen" and ALDI_ALCOHOL_NAME.search(r["name"])
               and "alkoholfrei" not in r["name"].lower())
           and not (r["brand"] == "FELDSCHLÖSSCHEN" and "alkoholfrei" not in r["name"].lower()))
    p.step("F4", "Baby food",
           lambda r: r["_sub"] != "Baby & Kinderartikel" and (r["brand"] or "") not in ALDI_BABY_BRANDS)
    p.step("F5", "No price per 100 g/ml (size missing, count-based or a weight range)",
           lambda r: r["price_per_100_chf"] is not None)
    p.step("F6", "Price per 100 g/ml outside CHF 0.01-50",
           lambda r: 0.01 <= r["price_per_100_chf"] <= 50)

    columns = ["sku", "name", "brand", "category_main", "category_sub", "category_path",
               "crawl_categories", "category_theme_only", "selling_size", "size_value", "size_unit",
               "size_is_approx", "size_corrected", "price_chf", "on_promotion", "price_promo_chf",
               "price_per_100_chf", "price_per_100_unit", "comparison_published_chf",
               "comparison_basis", "is_organic", "is_vegan", "is_vegetarian", "storage", "badges",
               "url", "scraped_at"]
    _write(p.rows, columns, "aldi_clean", "sku")
    return p.log


def _first_seen(key: str):
    seen: set = set()

    def keep(r: dict) -> bool:
        if r[key] in seen:
            return False
        seen.add(r[key])
        return True
    return keep


# --------------------------------------------------------------------------- volg
VOLG_EXCLUDE = {   # F2/F3: category slug -> reason
    "koerperpflege-reinigung-haushalt-tierbedarf": "nonfood",
    "jugendschutz": "alcohol_tobacco",   # Volg's 18+ category: all alcohol and tobacco
    "tabakwaren": "alcohol_tobacco",
}
VOLG_DOMESTIC = {"schweiz", "liechtenstein", "lichtenstein"}
VOLG_UNKNOWN_ORIGIN = {"diverse", "europa", "eu", "europäische union", "made in eu"}


def _volg_paths(r: dict) -> list[str]:
    return [re.sub(r"^.*/produkt-kategorie/|/$", "", link) for link in r["category_links"] or []]


def _volg_categories(r: dict, name_of: dict[str, str]) -> tuple[str | None, str | None, str | None]:
    """C4: names along the deepest category path (main, sub, full path).

    name_of maps category slug paths to display names across all products, because a
    product does not always list every ancestor of its deepest category."""
    paths = _volg_paths(r)
    if not paths:
        return None, None, None
    deepest = max(paths, key=lambda s: s.count("/"))
    parts = deepest.split("/")
    names = [name_of.get("/".join(parts[:i + 1]), parts[i]) for i in range(len(parts))]
    return names[0], names[1] if len(names) > 1 else None, " > ".join(names)


def _volg_unit_price(text: str | None) -> tuple[float | None, float | None]:
    """Published unit price, e.g. '100g=2,555' -> (2.555, 100). Count bases ('1 Stk.') -> None."""
    m = re.match(r"\s*(\d+)\s*(g|gr|ml|l)?\s*=\s*(?:fr[.,]?|chf)?\s*(\d+(?:[.,]\d+)?)",
                 (text or "").lower())
    if not m:
        return None, None
    basis = float(m.group(1)) * (1000 if m.group(2) == "l" else 1)
    return float(m.group(3).replace(",", ".")), basis


def _volg_size(r: dict) -> dict:
    """C2: package size for Volgshop.

    Candidates: the 'Mengeneinheit' attribute and the size in the product name, each as
    total and (for multipacks) single unit. If the published unit price exists, the
    candidate that reproduces it best is used (within 25 %). Without a usable unit price
    the attribute total is used, unless attribute and name disagree, which leaves the
    size unresolved.
    """
    attr, name = parse_size(r["quantity"]), parse_size(r["name"])
    for s in (attr, name):
        _fix_kg_typo(s)
    cands = []
    for src, s in (("attribute", attr), ("name", name)):
        if s:
            cands.append((src, s["value"], s["unit"], s["approx"]))
            if s["single"]:
                cands.append((f"{src}_single_unit", s["single"], s["unit"], s["approx"]))
    out = {"size_value": None, "size_unit": None, "size_source": None, "size_is_approx": False,
           "unit_price_published_chf": None, "unit_price_mismatch": None}
    if not cands:
        return out
    published, basis = _volg_unit_price(r["unit_price_text"])
    if published:
        out["unit_price_published_chf"] = round(published / basis * 100, 4)
    totals = [c for c in cands if not c[0].endswith("single_unit")]
    conflict = len({round(c[1], 1) for c in totals}) > 1
    chosen = None
    if published and r["price_chf"]:
        target = published / basis * 100
        err = lambda c: abs(r["price_chf"] / c[1] * 100 - target) / target  # noqa: E731
        best = min(cands, key=err)
        if err(best) <= 0.25:
            chosen = best
        elif not conflict:
            chosen = totals[0]
        if chosen:
            out["unit_price_mismatch"] = err(chosen) > 0.02
    elif not conflict:
        chosen = totals[0]
    if chosen:
        out.update(size_source=chosen[0], size_value=chosen[1], size_unit=chosen[2],
                   size_is_approx=chosen[3])
    return out


def _volg_nutrition(r: dict) -> None:
    """C6: nutrition table checks, same thresholds as OFF F7 (see the decisions doc).

    Products are not removed for bad nutrition: their price is still valid and the
    nutrition can come from Open Food Facts at matching. The values are set to NULL
    and nutrition_status records why.
    """
    nutrients = ["energy_kj", "energy_kcal", "fat", "saturated_fat", "carbohydrates", "sugars",
                 "fiber", "proteins", "salt"]
    kj_decl, kcal_decl = r["energy_kj"], r["energy_kcal"]
    r["energy_kj"] = kj_decl if kj_decl is not None else (
        round(kcal_decl * 4.184, 1) if kcal_decl is not None else None)
    g = {k: r[k] for k in ["fat", "saturated_fat", "carbohydrates", "sugars", "fiber", "proteins", "salt"]}
    status = None
    if all(r[k] is None for k in nutrients):
        status = "missing"
    elif r["nutrition_basis"] not in (None, "100g", "100ml"):
        status = "not_per_100"
    elif any(v is not None and not 0 <= v <= 100 for v in g.values()):
        status = "implausible"
    elif r["energy_kj"] is not None and not 0 <= r["energy_kj"] <= 3800:
        status = "implausible"
    elif (g["saturated_fat"] is not None and g["fat"] is not None and g["saturated_fat"] > g["fat"] + 0.5) or \
         (g["sugars"] is not None and g["carbohydrates"] is not None and g["sugars"] > g["carbohydrates"] + 0.5):
        status = "implausible"
    elif all(g[k] is not None for k in ("fat", "proteins", "salt")) and \
            g["fat"] + (g["carbohydrates"] if g["carbohydrates"] is not None else g["sugars"] or 0) \
            + (g["fiber"] or 0) + g["proteins"] + g["salt"] > 105:
        status = "implausible"
    elif kj_decl and kcal_decl and kcal_decl > 40 and not 3.6 <= kj_decl / kcal_decl <= 4.8:
        carbs = g["carbohydrates"] if g["carbohydrates"] is not None else g["sugars"]
        if None in (g["fat"], carbs, g["proteins"]):
            status = "implausible"
        else:
            macro = 37 * g["fat"] + 17 * carbs + 17 * g["proteins"] + 8 * (g["fiber"] or 0)
            if abs(r["energy_kj"] - macro) > 0.2 * macro:
                status = "implausible"
    if status in ("not_per_100", "implausible"):
        for k in nutrients:
            r[k] = None
    elif status is None:
        status = "complete" if all(r[k] is not None for k in CORE_NUTRIENTS) else "incomplete"
    r["nutrition_status"] = status


def clean_volg() -> list[tuple]:
    rows = _load(RAW_DIR / "volg_raw.parquet")
    name_of = {p: n for r in rows for p, n in zip(_volg_paths(r), r["categories"])}
    for r in rows:
        r["_tops"] = {p.split("/")[0] for p in _volg_paths(r)}
        r["category_main"], r["category_sub"], r["category_path"] = _volg_categories(r, name_of)
        r.update(_volg_size(r))                                   # C2
        r["price_per_100_chf"] = _per_100(r["price_chf"], r["size_value"])
        r["price_per_100_unit"] = r["size_unit"]
        country = (r["production_country"] or "").strip().lower()  # C7
        r["origin_status"] = (None if not country or country in VOLG_UNKNOWN_ORIGIN else
                              "domestic" if country in VOLG_DOMESTIC else "imported")
        r["own_brand_volg"] = r["name"].lower().startswith("volg ")
        r["is_organic"] = bool(re.search(r"\bbio\b", f"{r['labels'] or ''} {r['name']}", re.I))
        r.update(parse_volg_nutrition(r["nutrition_text"]))       # C6: re-parse, current parser
        _volg_nutrition(r)

    p = Pipeline("volg", rows)
    p.step("F1", "Duplicate product id", _first_seen("product_id"))
    p.step("F2", "Non-food (Körperpflege, Reinigung, Haushalt, Tierbedarf)",
           lambda r: not any(VOLG_EXCLUDE.get(t) == "nonfood" for t in r["_tops"]))
    p.step("F3", "Alcohol or tobacco (Jugendschutz, Tabakwaren)",
           lambda r: not any(VOLG_EXCLUDE.get(t) == "alcohol_tobacco" for t in r["_tops"]))
    p.step("F4", "Baby food", lambda r: not re.search(r"\b(baby|säugling)", r["name"], re.I)
           or "babybel" in r["name"].lower())
    p.step("F5", "No price per 100 g/ml (size missing, count-based, a weight range or unresolved)",
           lambda r: r["price_per_100_chf"] is not None)
    p.step("F6", "Price per 100 g/ml outside CHF 0.01-50",
           lambda r: 0.01 <= r["price_per_100_chf"] <= 50)

    columns = ["product_id", "sku", "name", "own_brand_volg", "category_main", "category_sub",
               "category_path", "quantity", "size_value", "size_unit", "size_source",
               "size_is_approx", "price_chf", "price_per_100_chf", "price_per_100_unit",
               "unit_price_published_chf", "unit_price_mismatch", "production_country",
               "origin_status", "labels", "is_organic", "nutrition_status", "energy_kj",
               "energy_kcal", "fat", "saturated_fat", "carbohydrates", "sugars", "fiber",
               "proteins", "salt", "nutrition_has_lt", "nutrition_text", "ingredients", "url",
               "scraped_at"]
    _write(p.rows, columns, "volg_clean", "product_id")
    return p.log


# --------------------------------------------------------------------------- cli
def _write_log_and_meta(logs: list[tuple]) -> None:
    old = []
    if LOG_PATH.exists():   # keep the other shop's rows when only one shop is re-run
        shops = {l[0] for l in logs}
        with open(LOG_PATH, encoding="utf-8") as fh:
            old = [tuple(r) for r in list(csv.reader(fh))[1:] if r[0] not in shops]
    with open(LOG_PATH, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["shop", "rule", "description", "rows_before", "rows_removed", "rows_after"])
        w.writerows(sorted(old + logs, key=lambda l: (l[0], l[1])))
    meta = json.loads(META_PATH.read_text(encoding="utf-8")) if META_PATH.exists() else {}
    for shop in {l[0] for l in logs}:
        raw = RAW_DIR / f"{shop}_raw.parquet"
        scraped = duckdb.sql(f"SELECT strftime(timezone('UTC', min(scraped_at)), '%Y-%m-%dT%H:%M:%SZ') FROM '{raw.as_posix()}'").fetchall()[0][0]
        shop_log = [l for l in logs if l[0] == shop]
        meta[shop] = {"raw_parquet_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
                      "scraped_at": scraped,
                      "cleaned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "rows_raw": shop_log[0][3], "rows_clean": shop_log[-1][5]}
    META_PATH.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("shop", nargs="?", default="all", choices=["aldi", "volg", "all"])
    shop = ap.parse_args().shop
    logs = []
    if shop in ("aldi", "all"):
        logs += clean_aldi()
    if shop in ("volg", "all"):
        logs += clean_volg()
    _write_log_and_meta(logs)
    width = max(len(l[2]) for l in logs)
    for s, rule, desc, before, removed, after in logs:
        print(f"{s:<5} {rule:<3} {desc:<{width}}  -{removed:>5}  -> {after}")


if __name__ == "__main__":
    main()
