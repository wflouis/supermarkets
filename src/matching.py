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
M1-M8 are justified in docs/matching_decisions.md.
"""
from __future__ import annotations

import collections
import random
import re
import unicodedata
from pathlib import Path

import duckdb
from rapidfuzz import fuzz

from scraping import _write_parquet

ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = ROOT / "data" / "processed"
OFF_PATH = PROCESSED_DIR / "off_ch_clean.parquet"

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
    def __init__(self):
        self.rows = _load(OFF_PATH, OFF_COLUMNS, "WHERE product_name IS NOT NULL")
        self.by_brand: dict[str, list[dict]] = collections.defaultdict(list)
        for o in self.rows:
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


def best_match(r: dict, cands: list[dict], brand: str | None, shop: str) -> dict:
    """Score every candidate; tie-break by size, store tag and popularity (M5)."""
    toks = tokens(r["name"], brand)
    scored = []
    for o in cands:
        otoks = [t for t in o["_tokens"] if t not in set(norm(brand).split())]
        s = name_score(toks, otoks)
        ratio = _size_ratio(r, o)
        size_ok = ratio is not None and ratio >= 1 - SIZE_TOLERANCE
        scored.append((s, size_ok, bool(o[f"store_{shop}"]), o["unique_scans_n"] or 0, ratio, o,
                       _coverage(toks, otoks)))
    scored.sort(key=lambda x: x[:4], reverse=True)
    if not scored:
        return {}
    s, size_ok, _, _, ratio, o, retail_cov = scored[0]
    # M4: below 90 the size must agree AND every word of the shop's name must be found
    # in the OFF name; a missing shop word is usually the variant ("Sugarfree", "Waldbeer").
    accepted = s >= ACCEPT_SCORE or (size_ok and s >= ACCEPT_SCORE_WITH_SIZE and retail_cov == 1)
    return {"off_code": o["code"], "off_name": o["product_name"], "off_brands": o["brands"],
            "score": s, "retail_coverage": round(retail_cov, 3), "size_ratio": ratio,
            "size_match": size_ok, "second_score": scored[1][0] if len(scored) > 1 else None,
            "accepted": accepted}


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
            if fb and fb["score"] >= ACCEPT_SCORE and fb["size_match"]:
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
            out.append(row)
    return out


def _to_csv(name: str) -> None:
    pq = (PROCESSED_DIR / f"{name}.parquet").as_posix()
    duckdb.sql(f"COPY (SELECT * FROM '{pq}') TO '{(PROCESSED_DIR / f'{name}.csv').as_posix()}' (HEADER)")


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
    off = OffIndex()
    aldi = _load(PROCESSED_DIR / "aldi_clean.parquet")
    volg = _load(PROCESSED_DIR / "volg_clean.parquet")
    for r in aldi:
        r["retailer"] = "aldi"
    for r in volg:
        r["retailer"], r["brand"] = "volg", None
    matches = match_shop("aldi", aldi, off) + match_shop("volg", volg, off)
    _write_parquet(matches, PROCESSED_DIR / "matches.parquet")
    _to_csv("matches")
    _write_parquet(combine(aldi, volg, matches, off), PROCESSED_DIR / "products_matched.parquet")
    _to_csv("products_matched")
    write_review_sample(matches)
    for shop in ("aldi", "volg"):
        ms = [m for m in matches if m["retailer"] == shop]
        acc = collections.Counter(m["method"] for m in ms if m["accepted"])
        print(f"{shop}: {len(ms)} products, {sum(acc.values())} matched  {dict(acc)}")


if __name__ == "__main__":
    main()
