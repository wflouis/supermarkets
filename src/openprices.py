"""Open Prices (prices.openfoodfacts.org): crowdsourced shelf and receipt prices.

Adds prices for Migros and Coop, which block scraping, by joining community-reported
prices to the Swiss Open Food Facts table on EAN.

    download  ->  data/raw/openprices_responses.jsonl.gz   every API response (gitignored)
                  data/raw/openprices_raw.parquet          one row per price in CHF, flattened
    clean     ->  data/processed/openprices_clean.parquet (+ .csv)
                      one row per (chain, EAN): latest regular price + OFF nutrition
                  data/processed/openprices_cleaning_log.csv   rows removed per filter
                  data/processed/openprices_metadata.json      snapshot provenance

Usage:
    python src/openprices.py all
    python src/openprices.py clean      # re-run cleaning from openprices_raw.parquet

Rules (F1, C1, ...) are justified in docs/openprices_decisions.md.
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

from scraping import Client, _now, _write_parquet

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"

API = "https://prices.openfoodfacts.org/api/v1/prices"
PAGE_SIZE = 100
RAW_PATH = RAW_DIR / "openprices_raw.parquet"
LOG_JSONL = RAW_DIR / "openprices_responses.jsonl.gz"
CLEAN_PATH = PROCESSED_DIR / "openprices_clean.parquet"
LOG_PATH = PROCESSED_DIR / "openprices_cleaning_log.csv"
META_PATH = PROCESSED_DIR / "openprices_metadata.json"
OFF_PATH = PROCESSED_DIR / "off_ch_clean.parquet"
OFF_EXT_PATH = PROCESSED_DIR / "off_openprices_ext_clean.parquet"   # E8 of the OFF decision log

# F3: chain from the OSM brand, else the OSM name. Formats with their own price list
# (franchised convenience stores, pharmacies, restaurants) are not the chain.
CHAIN_PATTERN = re.compile(r"^(migros|coop|denner|lidl|aldi|volg)\b", re.I)
OTHER_FORMAT = re.compile(r"pronto|vitality|restaurant|online|express|migrolino", re.I)
SHOP_TAGS = {"supermarket", "convenience", "department_store", "mall", "kiosk", "general"}
# Shopping centres whose OSM entry names the centre, not the shop. Assigned from the
# own brands bought there (Naturaplan/Coop vs M-Budget/M-Classic), see F3.
LOCATION_CHAIN = {4413: "coop",     # La Maladière centre, Neuchâtel
                  6482: "migros"}   # Métropole Centre, La Chaux-de-Fonds

PRICE_MIN, PRICE_MAX = 0.01, 50.0   # per 100 g/ml, same bounds as the retailer cleaning (F6)


# --------------------------------------------------------------------------- download
def _row(p: dict) -> dict:
    loc = p.get("location") or {}
    prod = p.get("product") or {}
    proof = p.get("proof") or {}
    return {
        "price_id": p["id"], "type": p.get("type"), "product_code": p.get("product_code"),
        "price": p.get("price"), "price_is_discounted": p.get("price_is_discounted"),
        "price_without_discount": p.get("price_without_discount"), "price_per": p.get("price_per"),
        "currency": p.get("currency"), "date": p.get("date"), "receipt_quantity": p.get("receipt_quantity"),
        "proof_type": proof.get("type"), "owner": p.get("owner"), "created": p.get("created"),
        "location_id": p.get("location_id"), "osm_brand": loc.get("osm_brand"),
        "osm_name": loc.get("osm_name"), "osm_tag_value": loc.get("osm_tag_value"),
        "osm_city": loc.get("osm_address_city"), "osm_postcode": loc.get("osm_address_postcode"),
        "osm_country_code": loc.get("osm_address_country_code"),
        "op_product_name": prod.get("product_name"), "op_product_quantity": prod.get("product_quantity"),
        "op_product_quantity_unit": prod.get("product_quantity_unit"),
    }


def download() -> dict:
    """All prices reported in CHF (Switzerland and Liechtenstein; F2 keeps Switzerland)."""
    client = Client(LOG_JSONL, "https://prices.openfoodfacts.org/robots.txt")
    rows, page, pages = [], 1, 1
    try:
        while page <= pages:
            body, _ = client.get(f"{API}?currency=CHF&size={PAGE_SIZE}&page={page}&order_by=id")
            rows += [_row(p) for p in body["items"]]
            pages = body["pages"]
            page += 1
    finally:
        client.close()
    for r in rows:
        r["downloaded_at"] = _now()
    n = _write_parquet(rows, RAW_PATH)
    return {"rows": n, "api_total": body["total"], "requests": client.n_requests}


# --------------------------------------------------------------------------- clean
def chain_of(r: dict) -> str | None:
    if r["location_id"] in LOCATION_CHAIN:
        return LOCATION_CHAIN[r["location_id"]]
    names = [n.strip() for n in (r["osm_brand"], r["osm_name"]) if n]
    if r["osm_tag_value"] not in SHOP_TAGS or any(OTHER_FORMAT.search(n) for n in names):
        return None
    for name in names:
        if m := CHAIN_PATTERN.match(name):
            return m.group(1).lower()
    return None


def clean() -> list[tuple]:
    con = duckdb.connect()
    # Timestamps as text: fetching TIMESTAMPTZ would need pytz.
    rel = con.sql(f"SELECT * REPLACE (created::VARCHAR AS created, downloaded_at::VARCHAR AS downloaded_at, "
                  f"date::VARCHAR AS date) FROM '{RAW_PATH.as_posix()}'")
    rows = [dict(zip(rel.columns, r)) for r in rel.fetchall()]
    log: list[tuple] = []

    def step(rule: str, description: str, keep) -> None:
        nonlocal rows
        before = len(rows)
        rows = [r for r in rows if keep(r)]
        log.append((rule, description, before, before - len(rows), len(rows)))

    log.append(("—", "prices downloaded (currency CHF)", None, None, len(rows)))
    step("F1", "price of a product with EAN (not a loose-produce category price)",
         lambda r: r["type"] == "PRODUCT" and r["product_code"])
    step("F2", "shop in Switzerland", lambda r: r["osm_country_code"] == "CH")
    for r in rows:
        r["chain"] = chain_of(r)
    step("F3", "shop belongs to a Swiss grocery chain", lambda r: r["chain"] is not None)
    step("F4", "regular price, not a promotion", lambda r: not r["price_is_discounted"])
    step("F5", "price per item, not per kg of loose goods", lambda r: r["price_per"] is None)

    # C1: one price per (chain, EAN): the most recent date, median if several that day.
    tmp = PROCESSED_DIR / "_openprices_filtered.parquet"
    _write_parquet(rows, tmp)
    try:
        out, n_prices = _aggregate(tmp.as_posix())
    finally:
        tmp.unlink()
    log.append(("C1", "one price per (chain, EAN): latest date", n_prices, n_prices - len(out), len(out)))
    for rule, desc, keep in [
            ("F6", "EAN in the cleaned OFF tables (nutrition available)",
             lambda r: r["product_name"] is not None),
            ("F7", "package size in g or ml known in OFF",
             lambda r: bool(r["size_value"]) and r["size_unit"] in ("g", "ml")),
            ("F8", f"price per 100 g/ml within CHF {PRICE_MIN}-{PRICE_MAX}",
             lambda r: PRICE_MIN <= r["price_per_100_chf"] <= PRICE_MAX)]:
        before = len(out)
        out = [r for r in out if keep(r)]
        log.append((rule, desc, before, before - len(out), len(out)))
    for r in out:
        r["price_per_100_unit"] = r["size_unit"]

    _write_parquet(out, CLEAN_PATH)
    duckdb.sql(f"COPY (SELECT * FROM '{CLEAN_PATH.as_posix()}' ORDER BY chain, code) TO "
               f"'{CLEAN_PATH.with_suffix('.csv').as_posix()}' (HEADER)")
    with open(LOG_PATH, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["rule", "description", "rows_before", "rows_removed", "rows_after"])
        w.writerows(log)
    return log


def _aggregate(filtered: str) -> tuple[list[dict], int]:
    con = duckdb.connect()
    con.execute(f"CREATE VIEW p AS SELECT *, date::DATE AS d FROM '{filtered}'")
    # C2: nutrition from the Swiss OFF table, else from the non-Swiss entry of the same EAN.
    off = f"SELECT *, 'ch' AS off_scope FROM '{OFF_PATH.as_posix()}'"
    if OFF_EXT_PATH.exists():
        off += (f" UNION ALL BY NAME SELECT *, 'openprices_ext' AS off_scope FROM '{OFF_EXT_PATH.as_posix()}'"
                f" WHERE code NOT IN (SELECT code FROM '{OFF_PATH.as_posix()}')")
    con.execute(f"CREATE VIEW off AS {off}")
    rel = con.sql(f"""
        WITH latest AS (SELECT chain, product_code, max(d) AS d FROM p GROUP BY ALL),
        agg AS (
            SELECT p.chain, p.product_code AS code, p.d AS price_date,
                   median(p.price) AS price_chf, count(*) AS price_n_obs_latest_date
            FROM p JOIN latest USING (chain, product_code, d) GROUP BY ALL),
        hist AS (
            SELECT chain, product_code AS code, count(*) AS price_n_obs,
                   count(DISTINCT location_id) AS price_n_shops, min(d) AS price_first_date
            FROM p GROUP BY ALL)
        SELECT a.chain, a.code, strftime(a.price_date, '%Y-%m-%d') AS price_date,
               strftime(h.price_first_date, '%Y-%m-%d') AS price_first_date,
               h.price_n_obs, h.price_n_shops, a.price_n_obs_latest_date, a.price_chf,
               o.product_name, o.brand_main, o.brands, o.product_quantity AS size_value,
               o.product_quantity_unit AS size_unit,
               round(a.price_chf / o.product_quantity * 100, 4) AS price_per_100_chf,
               o.is_organic, o.main_category, o.pnns_group_1, o.pnns_group_2,
               o.nutriscore_grade, o.nutriscore_score, o.nova_group, o.origin_status,
               o.energy_kj, o.fat, o.saturated_fat, o.carbohydrates, o.sugars, o.fiber,
               o.proteins, o.salt, o.off_scope
        FROM agg a JOIN hist h USING (chain, code)
        LEFT JOIN off o ON o.code = a.code
        ORDER BY a.chain, a.code""")
    out = [dict(zip(rel.columns, r)) for r in rel.fetchall()]
    n_prices = con.execute("SELECT count(*) FROM p").fetchone()[0]
    return out, n_prices


def write_metadata(download_stats: dict | None, log: list[tuple]) -> None:
    meta = json.loads(META_PATH.read_text(encoding="utf-8")) if META_PATH.exists() else {}
    con = duckdb.connect()
    dl_at, d_min, d_max = con.execute(
        f"SELECT min(downloaded_at)::VARCHAR, min(date)::VARCHAR, max(date)::VARCHAR FROM '{RAW_PATH.as_posix()}'").fetchone()
    meta.update({
        "source_url": API + "?currency=CHF",
        "licence": "Open Database License (ODbL) — https://prices.openfoodfacts.org",
        "downloaded_at": dl_at,
        "price_dates": [str(d_min), str(d_max)],
        "raw_parquet_sha256": hashlib.sha256(RAW_PATH.read_bytes()).hexdigest(),
        "rows_raw": log[0][4], "rows_clean": log[-1][4],
        "cleaned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    if download_stats:
        meta["download"] = download_stats
    META_PATH.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["download", "clean", "all"])
    args = ap.parse_args()
    stats = None
    if args.step in ("download", "all"):
        stats = download()
        print("download:", stats)
    if args.step in ("clean", "all"):
        log = clean()
        for row in log:
            print(row)
        write_metadata(stats, log)


if __name__ == "__main__":
    main()
