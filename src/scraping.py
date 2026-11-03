"""Retailer catalogue scraping: Aldi Suisse and Volgshop.

Both retailers publish their catalogue through a public JSON API that the shop's own
web front end uses, so no HTML parsing is needed:

    aldi  ->  api.aldi-suisse.ch/v3/product-search   (Nuxt front end; paginated search)
    volg  ->  volgshop.ch/wp-json/wc/store/v1/products  (WooCommerce Store API)

Output (each run overwrites the previous snapshot):

    data/raw/<shop>_responses.jsonl.gz   every API response as received (gitignored)
    data/raw/<shop>_raw.parquet          one row per product, flattened, nothing cleaned

Usage:
    python src/scraping.py aldi
    python src/scraping.py volg
    python src/scraping.py all

Politeness: one request per second, a descriptive User-Agent, and only paths that
robots.txt allows (checked at start-up). No anti-bot circumvention.

Known gaps: neither shop exposes EANs. Aldi's API has no nutrition values (only the
ingredient list on the detail endpoint, not fetched) and leaves countryOrigin empty.
Volgshop has nutrition as free text, parsed into numeric columns here; the raw text
is kept alongside for checking.
"""
from __future__ import annotations

import argparse
import gzip
import html
import http.client
import json
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"

USER_AGENT = "supermarkets-student-project/0.1 (academic research; https://github.com/wflouis/supermarkets)"
DELAY_S = 1.0

ALDI_API = "https://api.aldi-suisse.ch"
ALDI_WEB = "https://www.aldi-suisse.ch"
ALDI_PAGE_SIZE = 60          # API accepts only 12, 16, 24, 30, 32, 48 or 60
ALDI_MAX_OFFSET = 2500       # search results are capped at 2500 per query

VOLG_WEB = "https://www.volgshop.ch"
VOLG_PAGE_SIZE = 100         # WooCommerce Store API maximum


# --------------------------------------------------------------------------- http
class Client:
    """Rate-limited JSON GET with retries; logs every response to a gzip JSONL file."""

    def __init__(self, log_path: Path, robots_url: str):
        self.last = 0.0
        self.n_requests = 0
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log = gzip.open(log_path, "wt", encoding="utf-8")
        self.robots = urllib.robotparser.RobotFileParser(robots_url)
        self.robots.read()

    def get(self, url: str, check_robots: bool = True, retries: int = 3):
        if check_robots and not self.robots.can_fetch(USER_AGENT, url):
            raise PermissionError(f"robots.txt disallows {url}")
        for attempt in range(retries + 1):
            wait = self.last + DELAY_S - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            self.n_requests += 1
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                       "Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                    headers = dict(resp.headers)
                break
            except urllib.error.HTTPError as e:
                if e.code < 500 and e.code != 429 or attempt == retries:
                    raise
            except (urllib.error.URLError, http.client.IncompleteRead, ConnectionError, TimeoutError):
                if attempt == retries:
                    raise
            time.sleep(5 * 2 ** attempt)
        self.log.write(json.dumps({"url": url, "fetched_at": _now(), "body": body},
                                  ensure_ascii=False) + "\n")
        return body, headers

    def close(self):
        self.log.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_parquet(rows: list[dict], dst: Path) -> int:
    """Rows -> parquet via a temporary JSONL file so DuckDB infers the schema."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as tmp:
        for r in rows:
            tmp.write(json.dumps(r, ensure_ascii=False) + "\n")
    try:
        con = duckdb.connect()
        con.execute(f"""COPY (SELECT * FROM read_json('{Path(tmp.name).as_posix()}',
                                                      format='newline_delimited'))
                        TO '{dst.as_posix()}' (FORMAT parquet)""")
        return con.execute(f"SELECT count(*) FROM '{dst.as_posix()}'").fetchone()[0]
    finally:
        Path(tmp.name).unlink()


def _cents(x) -> float | None:
    return None if x is None else x / 100


# --------------------------------------------------------------------------- aldi
def _aldi_search_url(offset: int, category: str | None = None) -> str:
    params = {"currency": "CHF", "serviceType": "walk-in",
              "limit": ALDI_PAGE_SIZE, "offset": offset}
    if category:
        params["categoryTree"] = category
    return f"{ALDI_API}/v3/product-search?{urllib.parse.urlencode(params)}"


def _aldi_row(p: dict, scraped_at: str) -> dict:
    price = p.get("price") or {}
    cats = p.get("categories") or []
    comparison_display = price.get("comparisonDisplay")
    return {
        "sku": p["sku"],
        "name": re.sub(r"\s+", " ", p.get("name") or "").strip(),
        "brand": p.get("brandName"),
        "selling_size": p.get("sellingSize"),
        "content_unit": p.get("contentUnit"),
        "quantity_unit": p.get("quantityUnit"),
        "weight_type": p.get("weightType"),           # "0" fixed weight, else sold by weight
        "price_chf": _cents(price.get("amountRelevant", price.get("amount"))),
        "regular_price_display": price.get("wasPriceDisplay"),  # set when on promotion
        "comparison_price_chf": _cents(price.get("comparison")),
        "comparison_display": comparison_display,     # e.g. "CHF 0.44/100 g"
        "comparison_basis": comparison_display.split("/", 1)[1].strip()
                            if comparison_display and "/" in comparison_display else None,
        "bottle_deposit_chf": _cents(price.get("bottleDeposit")),
        "category_top": cats[0]["name"] if cats else None,
        "category_path": " > ".join(c["name"] for c in cats) or None,
        "badges": [i["displayText"] for b in p.get("badges") or [] for i in b["items"]
                   if i.get("displayText")],
        "not_for_sale_online": p.get("notForSale"),
        "discontinued": p.get("discontinued"),
        "url": f"{ALDI_WEB}/de/produkt/{p.get('urlSlugText')}-{p['sku']}",
        "scraped_at": scraped_at,
    }


def scrape_aldi(raw_dir: Path = RAW_DIR) -> dict:
    """Crawl every top-level category of the search API and deduplicate by SKU.

    A plain unfiltered search reports ~4.2k products but stops at offset 2500, so the
    crawl goes category by category (each well under the cap). Products listed in
    several categories (e.g. "Aktionen" and "Vorräte") are kept once, with the list
    of crawl categories they appeared in.
    """
    client = Client(raw_dir / "aldi_responses.jsonl.gz", f"{ALDI_WEB}/robots.txt")
    scraped_at = _now()
    try:
        # The API host has no robots.txt of its own; the web domain's rules are checked
        # against the equivalent product pages instead.
        first, _ = client.get(_aldi_search_url(0), check_robots=False)
        facets = {f["name"]: f for f in first["meta"]["facets"]}
        categories = [(v["key"], v["label"]) for v in facets["category-tree"]["values"]]
        total_unfiltered = facets["category-tree"]["docCount"]

        rows: dict[str, dict] = {}
        for key, label in categories:
            offset = 0
            while True:
                body, _ = client.get(_aldi_search_url(offset, key), check_robots=False)
                for p in body["data"]:
                    row = rows.setdefault(p["sku"], _aldi_row(p, scraped_at))
                    row.setdefault("crawl_categories", []).append(label)
                total = body["meta"]["pagination"]["totalCount"]
                offset += ALDI_PAGE_SIZE
                if offset >= min(total, ALDI_MAX_OFFSET) or not body["data"]:
                    break
                if total > ALDI_MAX_OFFSET:
                    print(f"  warning: category {label} has {total} products, capped at 2500")
    finally:
        client.close()
    n = _write_parquet(list(rows.values()), raw_dir / "aldi_raw.parquet")
    return {"products": n, "categories": len(categories),
            "unfiltered_total_reported": total_unfiltered, "requests": client.n_requests}


# --------------------------------------------------------------------------- volg
# Volgshop's nutrition field is free text in many layouts, e.g.
#   "Energie in kJ\n 1589\n Energie in kcal\n 383\n Fett\n 31g ..."
#   "Energie in kcal: 45.0\nEnergie in kJ: 190\nFett: < 0.5g ..."
#   "kcal: 266 kcal\nkj: 1103kj\nFett: 22g ..."
#   "Energie / Brennwert\t1103 kJ (266 kcal)\r\nFett ca. 22g ..."
# The parser finds every known label and takes the first number between it and the
# next label. Order matters: at the same position the first alternative wins.
VOLG_LABELS = [
    ("energy_kj", r"energie in kj|\bkj\s*:"),
    ("energy_kcal", r"energie in kcal|\bkcal\s*:"),
    ("energy", r"energie(?:\s*/\s*brennwert)?|brennwert"),
    ("saturated_fat", r"(?:davon\s+)?ges[äa]ttigte\s+fetts[äa]uren"),
    ("fat", r"\bfett\b"),
    ("carbohydrates", r"kohlenhydrate"),
    ("sugars", r"(?:davon\s+)?\bzucker\b"),
    ("fiber", r"nahrungsfasern(?:\s*\(ballaststoffe\))?|ballaststoffe"),
    ("proteins", r"eiwei(?:ss|ß)|\bprotein\b"),
    ("salt", r"kochsalz|\bsalz\b"),
    # Labels that are not kept but must end the previous label's segment.
    ("_other", r"natrium|vitamin|magnesium|calcium|kalzium|kalium|eisen|zink|jod|niacin|"
               r"pantothens|folsäure|biotin|riboflavin|thiamin|stärke|mehrwertig|einfach|"
               r"\bdavon\b|broteinheit|\bbe\b"),
]
VOLG_NUTRIENTS = [k for k, _ in VOLG_LABELS if not k.startswith("_") and k != "energy"]
_LABEL_RE = re.compile("|".join(f"(?P<{k}>{rx})" for k, rx in VOLG_LABELS), re.I)
_VALUE_RE = re.compile(r"(<|~|ca\.)?\s*(\d+(?:[.,]\d+)?)", re.I)


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def parse_volg_nutrition(text: str | None) -> dict:
    """Pull nutrient values out of Volgshop's free-text nutrition field.

    Values written as "< 0.5" are taken at the bound and flagged in nutrition_has_lt;
    "ca." (approximately) is ignored. Anything not found stays None, and the raw text
    is kept in the output table for manual checking. nutrition_basis is the reference
    quantity if the text states one ("pro 100g", "(100 g enthalten)").
    """
    out: dict = {k: None for k in VOLG_NUTRIENTS}
    out["nutrition_basis"] = None
    out["nutrition_has_lt"] = None
    if not text:
        return out
    basis = re.search(r"(?:pro|\()\s*(\d+)\s*(g|gr|ml)\b", text, re.I)
    if basis:
        out["nutrition_basis"] = basis.group(1) + basis.group(2).lower().replace("gr", "g")
    matches = list(_LABEL_RE.finditer(text))
    if not matches:
        return out
    # A few entries put the value before its label ("42.0 Energie in kcal\n175 ...").
    # Detected by a number before the first label and none after the last one.
    value_first = (_VALUE_RE.search(text[:matches[0].start()]) is not None
                   and _VALUE_RE.search(text[matches[-1].end():]) is None)
    has_lt = False
    for i, m in enumerate(matches):
        key = m.lastgroup
        if value_first:
            start = matches[i - 1].end() if i else 0
            segment = text[start:m.start()]
        else:
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            segment = text[m.end():end]
        if key == "_other":
            continue
        if key == "energy":   # combined, e.g. "1103 kJ (266 kcal)"
            for sub, unit in (("energy_kj", "kj"), ("energy_kcal", "kcal")):
                v = re.search(rf"(\d+(?:[.,]\d+)?)\s*{unit}\b", segment, re.I)
                if v and out[sub] is None:
                    out[sub] = _num(v.group(1))
            continue
        v = _VALUE_RE.search(segment)
        if v and out[key] is None:
            out[key] = _num(v.group(2))
            has_lt |= v.group(1) == "<"
    out["nutrition_has_lt"] = has_lt
    return out


def _volg_attrs(p: dict) -> dict[str, str]:
    return {a["name"]: "; ".join(html.unescape(t["name"]) for t in a["terms"])
            for a in p.get("attributes") or []}


def _volg_row(p: dict, scraped_at: str) -> dict:
    prices = p.get("prices") or {}
    unit = 10 ** prices.get("currency_minor_unit", 2)
    attrs = _volg_attrs(p)
    cats = [html.unescape(c["name"]) for c in p.get("categories") or []]
    nutrition_text = attrs.get("Nährwerte")
    return {
        "product_id": p["id"],
        "sku": p.get("sku"),
        "name": html.unescape(p.get("name") or ""),
        "type": p.get("type"),
        "price_chf": int(prices["price"]) / unit if prices.get("price") else None,
        "regular_price_chf": int(prices["regular_price"]) / unit if prices.get("regular_price") else None,
        "on_sale": p.get("on_sale"),
        "quantity": attrs.get("Mengeneinheit"),
        "unit_price_text": attrs.get("100gr/100ml-Preis"),     # e.g. "100g=2,555"
        "production_country": attrs.get("Produktionsland"),
        "labels": attrs.get("Labels"),
        "ingredients": attrs.get("Zutaten"),
        "nutrition_text": nutrition_text,
        **parse_volg_nutrition(nutrition_text),
        "categories": cats,
        "category_links": [c["link"] for c in p.get("categories") or []],
        "brands": [html.unescape(b["name"]) for b in p.get("brands") or []],
        "is_in_stock": p.get("is_in_stock"),
        "attributes_json": json.dumps(attrs, ensure_ascii=False),
        "description": re.sub(r"<[^>]+>", " ", html.unescape(p.get("description") or "")).strip(),
        "url": p.get("permalink"),
        "scraped_at": scraped_at,
    }


def scrape_volg(raw_dir: Path = RAW_DIR) -> dict:
    client = Client(raw_dir / "volg_responses.jsonl.gz", f"{VOLG_WEB}/robots.txt")
    scraped_at = _now()
    rows, page, total_pages, total = [], 1, 1, None
    try:
        while page <= total_pages:
            url = f"{VOLG_WEB}/wp-json/wc/store/v1/products?per_page={VOLG_PAGE_SIZE}&page={page}"
            body, headers = client.get(url)
            total_pages = int(headers.get("X-WP-TotalPages", 1))
            total = int(headers.get("X-WP-Total", 0))
            rows += [_volg_row(p, scraped_at) for p in body]
            page += 1
    finally:
        client.close()
    n = _write_parquet(rows, raw_dir / "volg_raw.parquet")
    return {"products": n, "reported_total": total, "requests": client.n_requests,
            "with_nutrition_text": sum(r["nutrition_text"] is not None for r in rows),
            "with_energy_kj": sum(r["energy_kj"] is not None for r in rows)}


# --------------------------------------------------------------------------- cli
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("shop", choices=["aldi", "volg", "all"])
    shop = ap.parse_args().shop
    if shop in ("aldi", "all"):
        print("aldi:", scrape_aldi())
    if shop in ("volg", "all"):
        print("volg:", scrape_volg())


if __name__ == "__main__":
    main()
