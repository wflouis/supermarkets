"""Nutri-Score (2023 algorithm) computed from the nutrition table.

Fills the Nutri-Score for products that have a complete nutrition table but no
Nutri-Score from Open Food Facts (mostly Volgshop, whose own table is used). The
implementation is checked against the grades OFF computed itself.

    python src/nutriscore.py validate    # compare with OFF grades -> data/processed/nutriscore_validation.csv

matching.py calls add_nutriscore() when it builds products_matched. Rules (S1, S2, ...)
are justified in docs/nutriscore_decisions.md.
"""
from __future__ import annotations

import argparse
import collections
import csv
import re
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = ROOT / "data" / "processed"
RAW_DIR = ROOT / "data" / "raw"

# --------------------------------------------------------------------------- algorithm
# S1: thresholds of the 2023 update (general foods, beverages, fats/oils/nuts/seeds).
# A value strictly above the i-th threshold earns i+1 points.
T = {
    "energy": [335 * i for i in range(1, 11)],
    "energy_bev": [30, 90, 150, 210, 240, 270, 300, 330, 360, 390],
    "energy_satfat": [120 * i for i in range(1, 11)],            # fats: kJ from saturated fat
    "sugars": [3.4, 6.8, 10, 14, 17, 20, 24, 27, 31, 34, 37, 41, 44, 48, 51],
    "sugars_bev": [0.5, 2, 3.5, 5, 6, 7, 8, 9, 10, 11],
    "satfat": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    "satfat_ratio": [10, 16, 22, 28, 34, 40, 46, 52, 58, 64],     # fats: % of total fat
    "salt": [round(0.2 * i, 1) for i in range(1, 21)],
    "proteins": [2.4, 4.8, 7.2, 9.6, 12, 14, 17],
    "proteins_bev": [1.2, 1.5, 1.8, 2.1, 2.4, 2.7, 3.0],
    "fiber": [3.0, 4.1, 5.2, 6.3, 7.4],
}
FVL_POINTS = [(80, 5), (60, 2), (40, 1)]
FVL_POINTS_BEV = [(80, 6), (60, 4), (40, 2)]
GRADES = {   # upper bound of each grade A-D; above D is E
    "general": [0, 2, 10, 18],
    "fat": [-6, 2, 10, 18],
    "beverage": [None, 2, 6, 9],   # A is water only
}


def _pts(value: float | None, key: str) -> int:
    if value is None:
        return 0
    return sum(value > t for t in T[key])   # one point per threshold strictly exceeded


def _fvl_pts(fvl: float | None, table) -> int:
    for limit, p in table:
        if fvl is not None and fvl > limit:
            return p
    return 0


def nutriscore(n: dict, kind: str, fvl: float | None = None, sweetener: bool = False) -> tuple[int | None, str | None]:
    """Score and grade for one product. kind: general, cheese, red_meat, fat, beverage, water."""
    if kind == "water":
        return None, "a"
    fiber = _pts(n.get("fiber"), "fiber")
    if kind == "beverage":
        neg = (_pts(n["energy_kj"], "energy_bev") + _pts(n["sugars"], "sugars_bev")
               + _pts(n["saturated_fat"], "satfat") + _pts(n["salt"], "salt") + (4 if sweetener else 0))
        pos = _pts(n["proteins"], "proteins_bev") + fiber + _fvl_pts(fvl, FVL_POINTS_BEV)
        score = neg - pos
        a, b, c, d = GRADES["beverage"]
        grade = "b" if score <= b else "c" if score <= c else "d" if score <= d else "e"
        return score, grade
    fvl_p = _fvl_pts(fvl, FVL_POINTS)
    prot = _pts(n["proteins"], "proteins")
    if kind == "red_meat":
        prot = min(prot, 2)
    if kind == "fat":
        fat, sat = n.get("fat"), n["saturated_fat"]
        ratio = 100 * sat / fat if fat else 0
        neg = (_pts(sat * 37, "energy_satfat") + _pts(n["sugars"], "sugars")
               + _pts(ratio, "satfat_ratio") + _pts(n["salt"], "salt"))
        limit, bounds = 7, GRADES["fat"]
    else:
        neg = (_pts(n["energy_kj"], "energy") + _pts(n["sugars"], "sugars")
               + _pts(n["saturated_fat"], "satfat") + _pts(n["salt"], "salt"))
        limit, bounds = 11, GRADES["general"]
    # S2: above the limit, proteins only count for cheese
    pos = fiber + fvl_p + (prot if neg < limit or kind == "cheese" else 0)
    score = neg - pos
    grade = next((g for g, ub in zip("abcd", bounds) if score <= ub), "e")
    return score, grade


# --------------------------------------------------------------------------- category (S3)
OFF_WATER = {"en:waters", "en:spring-waters", "en:mineral-waters"}
OFF_NOT_WATER = {"en:flavored-waters", "en:flavoured-waters", "en:sweetened-beverages",
                 "en:artificially-sweetened-beverages"}
OFF_BEVERAGE_EXCLUDE = {"en:dehydrated-beverages", "en:beverage-preparations",
                        "en:instant-beverages", "en:syrups"}
# OFF puts everything under en:seeds in this group, which in its taxonomy includes legumes
# and cereal grains (rice): checked empirically in docs/nutriscore_decisions.md (S3).
OFF_FAT = {"en:fats", "en:seeds", "en:nuts", "en:nut-butters"}
OFF_FAT_EXCLUDE = {"en:chestnuts", "en:mixed-nuts", "en:dried-fruits"}
OFF_RED_MEAT = {"en:beef", "en:pork", "en:lamb", "en:veal", "en:horse-meat", "en:mutton",
                "en:goat-meat", "en:game-meat"}


# S4: fruit, vegetable and legume share when the table does not give it. Products that
# are (almost) entirely fruit, vegetables or legumes, including the oils the 2023 update
# counts (olive, rapeseed, walnut).
OFF_FVL_100 = {"en:fruit-juices", "en:vegetable-juices", "en:olive-oils", "en:rapeseed-oils",
               "en:walnut-oils", "en:fruits", "en:vegetables", "en:mushrooms", "en:dates",
               "en:berries"}
OFF_FVL_EXCLUDE = {"en:fruit-nectars", "en:nectars", "en:fruit-juice-drinks"}


def fvl_from_off(tags: list[str] | None) -> float:
    t = set(tags or [])
    return 100.0 if t & OFF_FVL_100 and not t & OFF_FVL_EXCLUDE else 0.0


def kind_from_off(tags: list[str] | None) -> str:
    t = set(tags or [])
    if t & OFF_WATER and not t & OFF_NOT_WATER:
        return "water"
    if "en:beverages" in t and not t & OFF_BEVERAGE_EXCLUDE:
        return "beverage"
    if "en:cheeses" in t:
        return "cheese"
    if t & OFF_FAT and not t & OFF_FAT_EXCLUDE:
        return "fat"
    if t & OFF_RED_MEAT:
        return "red_meat"
    return "general"


SWEETENER = re.compile(
    r"aspartam|acesulfam|sucralos|saccharin|cyclamat|steviol|stevia|neotam|advantam|"
    r"\be ?9(50|51|52|54|55|60|61|62|69)\b", re.I)


def has_sweetener(ingredients: str | None) -> bool:
    return bool(ingredients and SWEETENER.search(ingredients))


# --------------------------------------------------------------------------- category from German names (S5)
# For products without an OFF entry (Volgshop): shop sub-category plus product name.
def _rx(words: str) -> re.Pattern:
    return re.compile(words, re.I)


DE_NOT_APPLICABLE = _rx(r"speisesalz|jodsalz|meersalz|essig|hefe\b|würzmischung|\bgewürze?\b|aromat\b|"
                        r"kaugummi|nescaf|instantkaffee|kaffeebohnen|kräutertee|schwarztee|grüntee\b(?! minze)|"
                        r"nahrungsergänzung")
DE_WATER = _rx(r"mineralwasser|valser|henniez|evian|vittel|aproz|passugger|\bwasser\b")
DE_FLAVOURED = _rx(r"aroma|citro|zitrone|limette|minze|tee|active|vitamin|frucht|orange|apfel|himbeer")
DE_MILK_DRINK = _rx(r"milch\b|milchdrink|vollmilch|magermilch|drink|latte|cappuccino|macchiato|"
                    r"energy milk|aktifit|shake")
DE_NOT_DRINK = _rx(r"kondensmilch|rahm|creme|crème|pulver|nachfüll|stick")
DE_FAT = _rx(r"rahm|cr[eè]me ?fra[iî]che|crémefine|\bbutter\b|bratbutter|kräuterbutter|margarine|"
             r"bratcreme|\böl\b|olivenöl|"
             r"sonnenblumenöl|rapsöl|schmalz")
# OFF's seeds group: nuts, seeds, and (in its taxonomy) rice, legumes and corn (S3).
DE_SEEDS = _rx(r"mandel|nüsse|cashew|erdnüss|haselnüss|baumnüss|pistazie|kerne\b|samen\b|kokos|"
               r"\breis\b|langkornreis|risotto|linsen|kichererbsen|bohnen|maiskörner")
DE_NUT_MIX = _rx(r"nussmischung|studentenfutter|nuss-frucht|nussmix|kokosmilch")
DE_SYRUP = _rx(r"sirup")
DE_FVL_100 = _rx(r"orangensaft|apfelsaft|süessmost|\bmost\b|gemüsesaft|tomatensaft|olivenöl|rapsöl|"
                 r"karotte|randen|rotkraut|sauerkraut|salat\b|champignon|spargel|erbsen|ananas|"
                 r"apfelmus|tomatenpur|maiskörner|oliven\b")
DE_POTATO = _rx(r"kartoffel|rösti|pommes")
# Ingredients that count for the FVL share (2023: fruit, vegetables, legumes and olive,
# rapeseed and walnut oil; not potatoes, not nuts, not concentrates used as sweetener).
FVL_WORDS = _rx(r"apfel|äpfel|birne|orange|zitrone|limette|grapefruit|mandarine|ananas|mango|banane|"
                r"erdbeer|himbeer|brombeer|heidelbeer|johannisbeer|kirsch|aprikose|pfirsich|pflaume|"
                r"traube|feige|dattel|frucht|früchte|beeren|tomate|karotte|rüebli|zwiebel|knoblauch|"
                r"paprika|peperoni|gurke|zucchini|aubergine|spinat|kohl|kraut|lauch|sellerie|randen|"
                r"kürbis|champignon|pilz|spargel|mais\b|erbse|bohne|linse|kichererbse|soja|gemüse|"
                r"olive|rapsöl|baumnussöl|salat")
FVL_NOT = _rx(r"kartoffel|zucker|sirup|aroma|extrakt|pulver|stärke|faser|pektin")


def _top_level(text: str) -> list[str]:
    """Split an ingredient list on commas outside brackets."""
    parts, part, depth = [], "", 0
    for ch in text:
        depth += (ch in "([") - (ch in ")]")
        if ch == "," and depth <= 0:
            parts.append(part)
            part = ""
        else:
            part += ch
    return parts + [part]


def fvl_from_ingredients(text: str | None) -> float | None:
    """Sum of the declared percentages of fruit/veg/legume ingredients (top level)."""
    if not text:
        return None
    total, found = 0.0, False
    for piece in _top_level(text):
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", piece)
        head = re.split(r"[(\[]", piece)[0]
        if m and FVL_WORDS.search(head) and not FVL_NOT.search(head):
            total += float(m.group(1).replace(",", "."))
            found = True
    return min(total, 100.0) if found else None


def kind_from_german(name: str, sub: str | None) -> str:
    sub = sub or ""
    if DE_NOT_APPLICABLE.search(name):
        return "not_applicable"
    if DE_SYRUP.search(name):   # OFF scores syrups as diluted; the label gives the concentrate
        return "unsupported"
    if sub =="Alkoholfreie Getränke" or (sub.startswith("Milch") and DE_MILK_DRINK.search(name)
                                           and not DE_NOT_DRINK.search(name)):
        if DE_WATER.search(name) and not DE_FLAVOURED.search(name):
            return "water"
        return "beverage"
    if sub == "Käse & Frischkäse":
        return "cheese"
    if (DE_FAT.search(name) or DE_SEEDS.search(name)) and not DE_NUT_MIX.search(name):
        return "fat"
    return "general"


def fvl_from_german(name: str, sub: str | None, ingredients: str | None) -> float:
    v = fvl_from_ingredients(ingredients)
    if v is not None:
        return v
    if DE_POTATO.search(name):
        return 0.0
    if (sub or "") in ("Gemüse", "Salat") or DE_FVL_100.search(name):
        return 100.0
    return 0.0


# --------------------------------------------------------------------------- products_matched
NEEDED = ["energy_kj", "saturated_fat", "sugars", "salt", "proteins"]
OFF_TABLES = [("off_ch_clean.parquet", "off_ch_raw.parquet"),
              ("off_aldi_ext_clean.parquet", "off_aldi_ext_raw.parquet"),
              ("off_openprices_ext_clean.parquet", "off_openprices_ext_raw.parquet")]


def _off_info() -> dict[str, dict]:
    """Categories, FVL share and raw grade (to keep OFF's not-applicable) by EAN."""
    info: dict[str, dict] = {}
    for clean, raw in OFF_TABLES:
        c, r = PROCESSED_DIR / clean, RAW_DIR / raw
        if not c.exists():
            continue
        rel = duckdb.sql(f"""
            SELECT o.code, o.categories_tags, o.fruits_vegetables_legumes, r.nutriscore_grade
            FROM '{c.as_posix()}' o LEFT JOIN '{r.as_posix()}' r ON r.code = o.code_raw""")
        for code, tags, fvl, raw_grade in rel.fetchall():
            info.setdefault(code, {"tags": tags, "fvl": fvl, "raw_grade": raw_grade})
    return info


def add_nutriscore(rows: list[dict], ingredients: dict[tuple[str, str], str | None]) -> None:
    """S6: adds the nutriscore_* columns in place. Final grade = OFF's, else computed."""
    off = _off_info()
    for r in rows:
        ingr = ingredients.get((r["retailer"], r["retailer_id"]))
        o = off.get(r["off_code"]) if r.get("off_code") else None
        if o is not None:
            kind = "not_applicable" if o["raw_grade"] == "not-applicable" else kind_from_off(o["tags"])
            fvl = o["fvl"] if o["fvl"] is not None else fvl_from_off(o["tags"])
            r["nutriscore_category_source"] = "off_categories"
        else:
            kind = kind_from_german(r["name"], r.get("category_sub"))
            fvl = fvl_from_german(r["name"], r.get("category_sub"), ingr)
            r["nutriscore_category_source"] = "retailer_name"
        r["nutriscore_kind"] = kind
        r["nutriscore_calc_score"] = r["nutriscore_calc_grade"] = None
        if kind not in ("not_applicable", "unsupported") and all(r.get(k) is not None for k in NEEDED):
            r["nutriscore_calc_score"], r["nutriscore_calc_grade"] = nutriscore(r, kind, fvl, has_sweetener(ingr))
        if r.get("off_nutriscore_grade"):
            r["nutriscore_grade"], r["nutriscore_score"] = r["off_nutriscore_grade"], r["off_nutriscore_score"]
            r["nutriscore_source"] = "off"
        elif r["nutriscore_calc_grade"]:
            r["nutriscore_grade"], r["nutriscore_score"] = r["nutriscore_calc_grade"], r["nutriscore_calc_score"]
            r["nutriscore_source"] = "computed"
        else:
            r["nutriscore_grade"] = r["nutriscore_score"] = r["nutriscore_source"] = None


# --------------------------------------------------------------------------- validation
NUTR = ["energy_kj", "fat", "saturated_fat", "sugars", "fiber", "proteins", "salt"]


def validate(use_off_fvl: bool = True) -> dict:
    con = duckdb.connect()
    ingr = PROCESSED_DIR.parent / "raw" / "off_ingredients.parquet"
    rel = con.sql(f"""
        SELECT o.code, o.categories_tags, o.fruits_vegetables_legumes AS fvl, o.nutriscore_grade,
               o.nutriscore_score, i.ingredients_text, {', '.join('o.' + c for c in NUTR)}
        FROM '{(PROCESSED_DIR / 'off_ch_clean.parquet').as_posix()}' o
        LEFT JOIN '{ingr.as_posix()}' i USING (code)
        WHERE o.nutriscore_grade IS NOT NULL""")
    rows = [dict(zip(rel.columns, r)) for r in rel.fetchall()]
    out, stats = [], collections.Counter()
    for r in rows:
        kind = kind_from_off(r["categories_tags"])
        fvl = r["fvl"] if use_off_fvl and r["fvl"] is not None else fvl_from_off(r["categories_tags"])
        score, grade = nutriscore(r, kind, fvl, has_sweetener(r["ingredients_text"]))
        out.append({"code": r["code"], "kind": kind, "off_grade": r["nutriscore_grade"],
                    "off_score": r["nutriscore_score"], "calc_grade": grade, "calc_score": score})
        stats[(kind, grade == r["nutriscore_grade"])] += 1
    return out, stats


def validate_volg() -> dict:
    """S7: the path used for Volgshop products without an OFF entry (shop category and
    name, FVL from ingredients), applied to the Volgshop products that do have an OFF
    grade. Run once with Volgshop's own table and once with OFF's table of the same
    product, to separate classification errors from differences between the tables."""
    nutr = ", ".join(f"o.{c} AS off_{c}" for c in NUTR)
    rel = duckdb.sql(f"""
        SELECT m.*, v.ingredients, {nutr}
        FROM '{(PROCESSED_DIR / 'products_matched.parquet').as_posix()}' m
        JOIN '{(PROCESSED_DIR / 'volg_clean.parquet').as_posix()}' v ON v.product_id::VARCHAR = m.retailer_id
        JOIN '{(PROCESSED_DIR / 'off_ch_clean.parquet').as_posix()}' o ON o.code = m.off_code
        WHERE m.retailer = 'volg' AND m.off_nutriscore_grade IS NOT NULL AND m.nutrition_source = 'retailer'""")
    rows = [dict(zip(rel.columns, r)) for r in rel.fetchall()]
    res = collections.Counter()
    for r in rows:
        kind = kind_from_german(r["name"], r["category_sub"])
        if kind in ("not_applicable", "unsupported"):
            res["skipped"] += 1
            continue
        fvl, sw = fvl_from_german(r["name"], r["category_sub"], r["ingredients"]), has_sweetener(r["ingredients"])
        off_n = {c: r[f"off_{c}"] for c in NUTR}
        for label, n in (("volg_table", r), ("off_table", off_n)):
            g = nutriscore(n, kind, fvl, sw)[1]
            res[f"{label}_n"] += 1
            res[f"{label}_same"] += g == r["off_nutriscore_grade"]
            res[f"{label}_within1"] += abs(ord(g) - ord(r["off_nutriscore_grade"])) <= 1
    return dict(res)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["validate"])
    ap.add_argument("--no-off-fvl", action="store_true", help="ignore OFF's fruit/veg share (as for Volgshop)")
    args = ap.parse_args()
    v = validate_volg()
    for label in ("volg_table", "off_table"):
        n = v[f"{label}_n"]
        print(f"Volgshop path, {label}: {n} products, same grade {v[f'{label}_same'] / n:.0%}, "
              f"within one grade {v[f'{label}_within1'] / n:.0%}")
    out, stats = validate(not args.no_off_fvl)
    kinds = sorted({k for k, _ in stats})
    for k in kinds:
        ok, bad = stats[(k, True)], stats[(k, False)]
        print(f"{k:<10} {ok + bad:>6}  grade agrees {ok / (ok + bad):.1%}")
    ok = sum(v for (k, a), v in stats.items() if a)
    print(f"all        {len(out):>6}  grade agrees {ok / len(out):.1%}")
    with open(PROCESSED_DIR / "nutriscore_validation.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)


if __name__ == "__main__":
    main()
