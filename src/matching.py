"""Matching of retailer products (Aldi, Volgshop) to Open Food Facts entries.

    data/processed/aldi_clean.parquet  ─┐
    data/processed/volg_clean.parquet  ─┼─>  data/processed/matches.parquet (+ .csv)
    data/processed/off_ch_clean.parquet ┘      best OFF candidate per retailer product, with score
                                         data/processed/products_matched.parquet (+ .csv)
                                               one row per retailer product: price + nutrition
                                         data/processed/match_review_sample.csv
                                               random sample of accepted matches for manual review

Usage:
    python src/matching.py

Neither shop publishes EANs, so matching is by brand and name (README, pass 2). Rules
M1-M13 are justified in docs/matching_decisions.md. products_matched also carries the
Migros/Coop/Lidl/Denner prices from Open Prices (M11, joined on EAN by openprices.py)
and a Nutri-Score computed from the nutrition table where OFF has none (M12, nutriscore.py),
and a common PNNS category for every product (M13, categories.py).
"""
from __future__ import annotations

import collections
import random
import re
import unicodedata
from pathlib import Path

import duckdb
from rapidfuzz import fuzz

from categories import add_category
from nutriscore import add_nutriscore
from scraping import _write_parquet

ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = ROOT / "data" / "processed"
OFF_PATH = PROCESSED_DIR / "off_ch_clean.parquet"
OFF_EXT_PATH = PROCESSED_DIR / "off_aldi_ext_clean.parquet"      # E6: DE/AT, Aldi brands
INGREDIENTS_PATH = ROOT / "data" / "raw" / "off_ingredients.parquet"
ALDI_DETAILS_PATH = ROOT / "data" / "raw" / "aldi_details_raw.parquet"
OPENPRICES_PATH = PROCESSED_DIR / "openprices_clean.parquet"
RETAIL_META_PATH = PROCESSED_DIR / "retail_metadata.json"
# M11: chains whose prices come from Open Prices. Aldi is left out: its scraped
# catalogue is complete and dated, the 14 Open Prices entries add nothing.
OPENPRICES_CHAINS = ("migros", "coop", "lidl", "denner")

NUTRIENTS = ["energy_kj", "fat", "saturated_fat", "carbohydrates", "sugars", "fiber", "proteins", "salt"]
OFF_COLUMNS = ["code", "product_name", "brands", "product_quantity", "product_quantity_unit",
               "store_aldi", "own_brand_aldi", "store_volg", "own_brand_volg", "main_category",
               "pnns_group_1", "pnns_group_2", "nutriscore_grade", "nutriscore_score", "nova_group",
               "origin_status", "is_organic", "unique_scans_n", *NUTRIENTS]

# M4 acceptance thresholds.
ACCEPT_SCORE = 90           # name similarity alone
ACCEPT_SCORE_WITH_SIZE = 75  # name similarity when the package size also agrees
SIZE_TOLERANCE = 0.10
# Brands that are labels, not manufacturers: on their own they do not identify a product line.
GENERIC_BRANDS = {"bio", "no brand", "sans marque", "ohne marke",
                  # common words used as brand names by several unrelated companies
                  "american", "bbq", "halloween", "gourmet", "premium"}

# M9 ingredient similarity thresholds (calibrated in docs/matching_decisions.md).
ING_ACCEPT = 70       # confirms a match
ING_REJECT = 30       # contradicts a match
ING_RESCUE_NAME = 60  # minimum name score for a match accepted on ingredients
ING_STOPWORDS = {"zutaten", "und", "mit", "aus", "von", "enthalt", "enthalten", "kann", "spuren",
                 "davon", "anteil", "insgesamt", "mind", "mindestens", "sowie", "oder", "der",
                 "die", "das", "den", "dem", "des", "ein", "eine", "einer", "zum", "zur",
                 "verschiedenen", "anderen", "erzeugnisse", "erzeugnissen", "hergestellt",
                 "biologischer", "landwirtschaft", "kontrolliert", "naturlich", "naturliches"}

# Words that carry no product identity in names (M2).
STOPWORDS = {"mit", "und", "de", "la", "le", "les", "du", "des", "et", "aux", "au", "a", "al", "di",
             "con", "in", "im", "nach", "art", "the", "of", "bio", "classic", "original"}


# --------------------------------------------------------------------------- text
def norm(s: str | None) -> str:
    """M2: lower case, no accents, no sizes, no punctuation."""
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c)).replace("ß", "ss").replace("&", " ")
    s = re.sub(r"\b\d+(?:[.,]\d+)?\s*(?:x\s*\d+(?:[.,]\d+)?\s*)?(kg|g|gr|mg|ml|cl|dl|l|stk|stuck)\b",
               " ", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def tokens(name: str | None, brand: str | None = None) -> list[str]:
    brand_toks = set(norm(brand).split())
    return [t for t in norm(name).split() if t not in STOPWORDS and t not in brand_toks and len(t) > 1]


def _coverage(a: list[str], b: list[str]) -> float:
    """Share of tokens in a that have a counterpart in b (fuzzy ratio >= 85).

    Deliberately no substring rule for German compounds: "Magermilch" contains "Milch"
    and "halbscharf" contains "scharf", but the modifier is what tells the products apart.
    """
    if not a:
        return 0.0
    return sum(any(fuzz.ratio(t, u) >= 85 for u in b) for t in a) / len(a)


_LANG_MARKERS = {
    "de": {"und", "mit", "zucker", "salz", "wasser", "milch", "enthalt", "spuren", "kann", "aus",
           "weizenmehl", "pflanzliche", "speisesalz", "saure", "zutaten", "von"},
    "fr": {"et", "de", "du", "des", "sucre", "sel", "eau", "lait", "huile", "peut", "contenir",
           "traces", "farine", "ingredients", "acide"},
    "it": {"di", "e", "zucchero", "sale", "acqua", "latte", "olio", "puo", "contenere", "farina",
           "ingredienti"},
    "en": {"and", "sugar", "salt", "water", "milk", "oil", "may", "contain", "flour", "ingredients"},
}


def is_german(text: str | None) -> bool:
    """M9: the OFF export has no language column; count frequent function words."""
    words = norm(text).split()
    counts = {lang: sum(w in m for w in words) for lang, m in _LANG_MARKERS.items()}
    return counts["de"] >= 2 and counts["de"] > max(v for k, v in counts.items() if k != "de")


def ingredient_tokens(text: str | None) -> list[str] | None:
    """M9: the distinct words of an ingredient list, without numbers and filler words."""
    if not text:
        return None
    toks = [t for t in norm(re.sub(r"\d+(?:[.,]\d+)?\s*%", " ", text)).split()
            if len(t) >= 3 and not t.isdigit() and t not in ING_STOPWORDS]
    return list(dict.fromkeys(toks)) or None


def name_score(a: list[str], b: list[str]) -> float:
    """M3: harmonic mean of the coverage in both directions, 0-100.

    Both names must be covered, so "Müsli-Riegel, Schoko" vs "Schoko Müsli" (the bar
    has a word the muesli lacks) does not score 100 as with token_set_ratio.
    """
    ca, cb = _coverage(a, b), _coverage(b, a)
    return 0.0 if ca + cb == 0 else round(200 * ca * cb / (ca + cb), 1)


# --------------------------------------------------------------------------- data
def _load(path: Path, cols: list[str] | None = None, where: str = "") -> list[dict]:
    sel = ", ".join(cols) if cols else "* EXCLUDE (scraped_at)"
    rel = duckdb.sql(f"SELECT {sel} FROM '{path.as_posix()}' {where}")
    return [dict(zip(rel.columns, r)) for r in rel.fetchall()]


class OffIndex:
    def __init__(self, include_ext: bool = False):
        self.rows = _load(OFF_PATH, OFF_COLUMNS, "WHERE product_name IS NOT NULL")
        for o in self.rows:
            o["scope"] = "ch"
        if include_ext and OFF_EXT_PATH.exists():
            ext = _load(OFF_EXT_PATH, OFF_COLUMNS, "WHERE product_name IS NOT NULL")
            for o in ext:
                o["scope"] = "de_at"
            self.rows += ext
        ingr = {}
        if INGREDIENTS_PATH.exists():
            # Only German lists are compared with Aldi's German ingredients (M9).
            ingr = {c: t for c, t in duckdb.sql(
                f"SELECT code, ingredients_text FROM '{INGREDIENTS_PATH.as_posix()}' "
                "WHERE ingredients_text IS NOT NULL").fetchall() if is_german(t)}
        self.by_brand: dict[str, list[dict]] = collections.defaultdict(list)
        for o in self.rows:
            o["_ingr"] = ingredient_tokens(ingr.get(o["code"]))
            o["_brands"] = {norm(b) for b in (o["brands"] or "").split(",") if norm(b)}
            for b in o["_brands"]:
                self.by_brand[b].append(o)
            o["_tokens"] = tokens(o["product_name"])
        # Brand vocabulary for finding the brand inside Volgshop names (M1).
        self.brand_vocab = {b for b, v in self.by_brand.items() if len(b) >= 3 and len(v) >= 2}

    def store(self, shop: str, brands: set[str]) -> list[dict]:
        """OFF products tagged with the shop whose brand is one the shop sells (M7).
        The store tag alone is not enough: OFF has e.g. Kaufland's K-Classic tagged Aldi."""
        brands = brands | {shop}
        return [o for o in self.rows if (o[f"store_{shop}"] or o[f"own_brand_{shop}"])
                and (o["_brands"] & brands or any(shop in b for b in o["_brands"]))]


def _volg_brand(name: str, vocab: set[str]) -> str | None:
    """M1: longest OFF brand (1-3 words) that the Volgshop name starts with."""
    words = norm(name).split()
    for n in (3, 2, 1):
        cand = " ".join(words[:n])
        if len(words) > n and cand in vocab:
            return cand
    return None


# --------------------------------------------------------------------------- matching
def _size_ratio(r: dict, o: dict) -> float | None:
    if not r["size_value"] or not o["product_quantity"] or r["size_unit"] != o["product_quantity_unit"]:
        return None
    return round(min(r["size_value"], o["product_quantity"]) / max(r["size_value"], o["product_quantity"]), 3)


def _name_ok(s: float, size_ok: bool, retail_cov: float) -> bool:
    return s >= ACCEPT_SCORE or (size_ok and s >= ACCEPT_SCORE_WITH_SIZE and retail_cov == 1)


def _tier(s: float, size_ok: bool, retail_cov: float, ingr: float | None) -> int:
    """2 = accepted, 1 = probable, 0 = rejected.

    M4: below 90 the size must agree AND every word of the shop's name must be found in
    the OFF name; a missing shop word is usually the variant ("Sugarfree", "Waldbeer").
    M9: ingredients below ING_REJECT veto a name match. Ingredients alone (name score
    60-89, ingredients >= ING_ACCEPT) only make a match *probable*: in review they picked
    flavour and "light" variants, which share the ingredient list.
    M10: German/Austrian entries follow the same rule as Swiss ones; same-name pairs
    agree on nutrition as often across countries as within one (cross_country_check).
    The Swiss entry still wins ties (best_match sort key).
    """
    if ingr is not None and ingr < ING_REJECT:
        return 0
    if _name_ok(s, size_ok, retail_cov):
        return 2
    return 1 if ingr is not None and ingr >= ING_ACCEPT and s >= ING_RESCUE_NAME else 0


def best_match(r: dict, cands: list[dict], brand: str | None, shop: str) -> dict:
    """Score every candidate; acceptable ones first, then name score, Swiss entry (the
    recipe actually sold in Switzerland), ingredients, size, store tag and popularity (M5)."""
    toks = tokens(r["name"], brand)
    brand_toks = set(norm(brand).split())
    r_ingr = r.get("_ingr")
    scored = []
    for o in cands:
        otoks = [t for t in o["_tokens"] if t not in brand_toks]
        s = name_score(toks, otoks)
        ratio = _size_ratio(r, o)
        size_ok = ratio is not None and ratio >= 1 - SIZE_TOLERANCE
        ingr = (name_score(r_ingr, o["_ingr"])
                if r_ingr and o["_ingr"] and s >= ING_RESCUE_NAME else None)
        cov = _coverage(toks, otoks)
        tier = _tier(s, size_ok, cov, ingr)
        scored.append({"key": (tier, s, o["scope"] == "ch", ingr or 0, size_ok,
                               bool(o[f"store_{shop}"]), o["unique_scans_n"] or 0),
                       "s": s, "ratio": ratio, "size_ok": size_ok, "cov": cov, "ingr": ingr,
                       "o": o, "tier": tier})
    if not scored:
        return {}
    scored.sort(key=lambda x: x["key"], reverse=True)
    b, o = scored[0], scored[0]["o"]
    return {"off_code": o["code"], "off_name": o["product_name"], "off_brands": o["brands"],
            "off_scope": o["scope"], "score": b["s"], "retail_coverage": round(b["cov"], 3),
            "ingredient_score": b["ingr"], "size_ratio": b["ratio"], "size_match": b["size_ok"],
            "second_score": scored[1]["s"] if len(scored) > 1 else None,
            "accepted": b["tier"] == 2,
            "probable": b["tier"] == 1}   # M9: ingredients agree, name not enough; not used


def match_shop(shop: str, rows: list[dict], off: OffIndex) -> list[dict]:
    if shop == "aldi":
        shop_brands = {norm(r["brand"]) for r in rows if r["brand"]}
    else:
        shop_brands = {b for r in rows if (b := _volg_brand(r["name"], off.brand_vocab))}
    store_cands = off.store(shop, shop_brands - GENERIC_BRANDS)
    out = []
    for r in rows:
        rid = r["sku"] if shop == "aldi" else r["product_id"]
        if shop == "aldi":
            brand = norm(r["brand"]) or None
        else:
            brand = _volg_brand(r["name"], off.brand_vocab | {"volg"})
        rec = {"retailer": shop, "retailer_id": str(rid), "retailer_name": r["name"],
               "brand_used": brand, "method": None}
        # M1/M6: brand blocking; generic labels only within the shop's own OFF products.
        if brand and brand not in GENERIC_BRANDS and off.by_brand.get(brand):
            rec["method"] = "brand"
            rec.update(best_match(r, off.by_brand[brand], brand, shop))
        elif brand in GENERIC_BRANDS:
            cands = [o for o in off.by_brand.get(brand, []) if o[f"store_{shop}"]]
            if cands:
                rec["method"] = "generic_brand_in_store"
                rec.update(best_match(r, cands, brand, shop))
        # M7: no usable brand -> the shop's own products in OFF, name only, strict.
        if rec["method"] is None or not rec.get("accepted"):
            fb = best_match(r, store_cands, brand, shop)
            if fb and fb["accepted"] and fb["score"] >= ACCEPT_SCORE and fb["size_match"]:
                rec.update(fb, method="store_name")
            elif rec["method"] is None and fb:
                rec.update(fb, method="store_name", accepted=False)
        rec.setdefault("accepted", False)
        out.append(rec)
    return out


# --------------------------------------------------------------------------- output
COMMON = ["retailer", "retailer_id", "name", "brand", "category_main", "category_sub",
          "size_value", "size_unit", "price_chf", "price_per_100_chf", "price_per_100_unit",
          "is_organic"]


def combine(aldi: list[dict], volg: list[dict], matches: list[dict], off: OffIndex) -> list[dict]:
    """M8: one row per retailer product with price, matched OFF fields and final nutrition."""
    off_by_code = {o["code"]: o for o in off.rows}
    m_by_id = {(m["retailer"], m["retailer_id"]): m for m in matches}
    scraped = _scrape_dates()
    out = []
    for shop, rows in (("aldi", aldi), ("volg", volg)):
        for r in rows:
            rid = str(r["sku"] if shop == "aldi" else r["product_id"])
            m = m_by_id[(shop, rid)]
            o = off_by_code.get(m.get("off_code")) if m["accepted"] else None
            row = {"retailer": shop, "retailer_id": rid, "name": r["name"],
                   "brand": r.get("brand") or m["brand_used"],
                   **{c: r.get(c) for c in COMMON[4:]},
                   "origin_status_retailer": r.get("origin_status"),
                   "matched": o is not None, "match_score": m.get("score") if o else None,
                   "match_method": m["method"] if o else None,
                   "off_scope": m.get("off_scope") if o else None,
                   "off_code": o and o["code"], "off_name": o and o["product_name"]}
            for c in ["main_category", "pnns_group_1", "pnns_group_2", "nutriscore_grade",
                      "nutriscore_score", "nova_group", "origin_status"]:
                row[f"off_{c}"] = o and o[c]
            # Nutrition: the shop's own complete table first (Volgshop), else OFF.
            if shop == "volg" and r["nutrition_status"] == "complete":
                src = {k: r[k] for k in NUTRIENTS}
                row["nutrition_source"] = "retailer"
            elif o is not None:
                src = {k: o[k] for k in NUTRIENTS}
                row["nutrition_source"] = "off"
            else:
                src, row["nutrition_source"] = {}, None
            row.update({k: src.get(k) for k in NUTRIENTS})
            row.update(price_source="retailer_web", price_date=scraped[shop])
            out.append(row)
    return out + openprices_rows()


def _scrape_dates() -> dict[str, str | None]:
    import json
    meta = json.loads(RETAIL_META_PATH.read_text(encoding="utf-8")) if RETAIL_META_PATH.exists() else {}
    return {shop: (meta.get(shop, {}).get("scraped_at") or "")[:10] or None for shop in ("aldi", "volg")}


def openprices_rows() -> list[dict]:
    """M11: Open Prices products, already joined to OFF on EAN by openprices.py."""
    if not OPENPRICES_PATH.exists():
        return []
    chains = ", ".join(f"'{c}'" for c in OPENPRICES_CHAINS)
    out = []
    rel = duckdb.sql(f"SELECT * FROM '{OPENPRICES_PATH.as_posix()}' WHERE chain IN ({chains})")
    for o in (dict(zip(rel.columns, r)) for r in rel.fetchall()):
        row = {"retailer": o["chain"], "retailer_id": o["code"], "name": o["product_name"],
               "brand": o["brand_main"], "category_main": None, "category_sub": None,
               "size_value": o["size_value"], "size_unit": o["size_unit"],
               "price_chf": o["price_chf"], "price_per_100_chf": o["price_per_100_chf"],
               "price_per_100_unit": o["size_unit"], "is_organic": o["is_organic"],
               "origin_status_retailer": None, "matched": True, "match_score": None,
               "match_method": "ean", "off_scope": o["off_scope"], "off_code": o["code"],
               "off_name": o["product_name"]}
        for c in ["main_category", "pnns_group_1", "pnns_group_2", "nutriscore_grade",
                  "nutriscore_score", "nova_group", "origin_status"]:
            row[f"off_{c}"] = o[c]
        row["nutrition_source"] = "off"
        row.update({k: o[k] for k in NUTRIENTS})
        row.update(price_source="open_prices", price_date=str(o["price_date"]))
        out.append(row)
    return out


def _to_csv(name: str) -> None:
    pq = (PROCESSED_DIR / f"{name}.parquet").as_posix()
    duckdb.sql(f"COPY (SELECT * FROM '{pq}') TO '{(PROCESSED_DIR / f'{name}.csv').as_posix()}' (HEADER)")


def nutrition_agrees(a: dict, b: dict) -> bool | None:
    """Same tolerance as the Volgshop validation: energy +-12 % (min 40 kJ); fat, sugars
    and proteins +-20 % (min 1.5 g)."""
    keys = ["energy_kj", "fat", "sugars", "proteins"]
    if any(a.get(k) is None or b.get(k) is None for k in keys):
        return None
    tol = {"energy_kj": (40, 0.12), "fat": (1.5, 0.2), "sugars": (1.5, 0.2), "proteins": (1.5, 0.2)}
    return all(abs(a[k] - b[k]) <= max(t[0], t[1] * a[k]) for k, t in tol.items())


def cross_country_check(off: OffIndex) -> dict:
    """M10 check: pairs of OFF entries with the same brand, name (score 100) and package
    size, one Swiss and one German/Austrian. Writes cross_country_check.csv."""
    pairs = []
    for brand, rows in off.by_brand.items():
        if brand in GENERIC_BRANDS:
            continue
        ch = [o for o in rows if o["scope"] == "ch"]
        ext = [o for o in rows if o["scope"] == "de_at"]
        for e in ext:
            etoks = [t for t in e["_tokens"] if t not in set(brand.split())]
            for c in ch:
                ctoks = [t for t in c["_tokens"] if t not in set(brand.split())]
                if (name_score(etoks, ctoks) == 100 and e["product_quantity"] and c["product_quantity"]
                        and e["product_quantity_unit"] == c["product_quantity_unit"]
                        and min(e["product_quantity"], c["product_quantity"])
                        / max(e["product_quantity"], c["product_quantity"]) >= 1 - SIZE_TOLERANCE):
                    ingr = name_score(e["_ingr"], c["_ingr"]) if e["_ingr"] and c["_ingr"] else None
                    pairs.append({"brand": brand, "ch_code": c["code"], "ch_name": c["product_name"],
                                  "de_at_code": e["code"], "de_at_name": e["product_name"],
                                  "ingredient_score": ingr, "agree": nutrition_agrees(c, e)})
    pairs = list({(p["ch_code"], p["de_at_code"]): p for p in pairs}.values())
    _write_parquet(pairs or [{"brand": None}], PROCESSED_DIR / "cross_country_check.parquet")
    _to_csv("cross_country_check")
    judged = [p for p in pairs if p["agree"] is not None]
    confirmed = [p for p in judged if (p["ingredient_score"] or 0) >= ING_ACCEPT]
    return {"pairs": len(pairs), "with_nutrition": len(judged),
            "agree": sum(p["agree"] for p in judged),
            "ingredients_confirmed": len(confirmed),
            "agree_when_ingredients_confirmed": sum(p["agree"] for p in confirmed)}


def write_review_sample(matches: list[dict], n_per_shop: int = 50, seed: int = 42) -> None:
    rng = random.Random(seed)
    rows = []
    for shop in ("aldi", "volg"):
        acc = [m for m in matches if m["retailer"] == shop and m["accepted"]]
        rows += rng.sample(acc, min(n_per_shop, len(acc)))
    cols = ["retailer", "retailer_id", "retailer_name", "brand_used", "method", "score", "size_ratio",
            "off_code", "off_name", "off_brands"]
    import csv
    with open(PROCESSED_DIR / "match_review_sample.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols + ["correct", "comment"])
        for m in rows:
            w.writerow([m.get(c) for c in cols] + ["", ""])


def main() -> None:
    off = OffIndex()                          # Volgshop: Swiss entries only
    off_aldi = OffIndex(include_ext=True)     # Aldi: Swiss + DE/AT Aldi-brand entries (M10)
    aldi = _load(PROCESSED_DIR / "aldi_clean.parquet")
    details = {}
    if ALDI_DETAILS_PATH.exists():
        details = dict(duckdb.sql(f"SELECT sku, ingredients FROM '{ALDI_DETAILS_PATH.as_posix()}'")
                       .fetchall())
    for r in aldi:
        text = details.get(r["sku"])
        r["_ingr"] = ingredient_tokens(text) if is_german(text) else None
    volg = _load(PROCESSED_DIR / "volg_clean.parquet")
    for r in aldi:
        r["retailer"] = "aldi"
    for r in volg:
        r["retailer"], r["brand"] = "volg", None
        r["_ingr"] = ingredient_tokens(r["ingredients"]) if is_german(r["ingredients"]) else None
    matches = match_shop("aldi", aldi, off_aldi) + match_shop("volg", volg, off)
    _write_parquet(matches, PROCESSED_DIR / "matches.parquet")
    _to_csv("matches")
    combined = combine(aldi, volg, matches, off_aldi)
    # M12: Nutri-Score computed where OFF has none (nutriscore.py, docs/nutriscore_decisions.md)
    ingredients = {("aldi", str(r["sku"])): details.get(r["sku"]) for r in aldi}
    ingredients |= {("volg", str(r["product_id"])): r["ingredients"] for r in volg}
    add_nutriscore(combined, ingredients)
    add_category(combined)   # M13: common PNNS category (categories.py)
    _write_parquet(combined, PROCESSED_DIR / "products_matched.parquet")
    _to_csv("products_matched")
    write_review_sample(matches)
    if OFF_EXT_PATH.exists():
        print("cross-country check:", cross_country_check(off_aldi))
    for shop in ("aldi", "volg"):
        ms = [m for m in matches if m["retailer"] == shop]
        acc = collections.Counter(m["method"] for m in ms if m["accepted"])
        print(f"{shop}: {len(ms)} products, {sum(acc.values())} matched  {dict(acc)}")
    print("open prices (EAN):", dict(collections.Counter(r["retailer"] for r in openprices_rows())))


if __name__ == "__main__":
    main()
