"""Common product category across retailers: the 9 PNNS groups (level 1) of OFF.

Products matched to OFF keep OFF's PNNS group. The others (mostly Volgshop) get one from
keyword rules on the product name (German, French, Italian), and else from the shop's
own sub-category. matching.py calls add_category() when it builds products_matched.

    python src/categories.py validate   # rules vs OFF's PNNS group

Rules (K1, K2, ...) are justified in docs/category_decisions.md.
"""
from __future__ import annotations

import argparse
import collections
import re
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = ROOT / "data" / "processed"

BEV, CER, COMP, FAT, FME, FV, DAIRY, SALTY, SUGARY = (
    "Beverages", "Cereals and potatoes", "Composite foods", "Fat and sauces", "Fish Meat Eggs",
    "Fruits and vegetables", "Milk and dairy products", "Salty snacks", "Sugary snacks")
PNNS_GROUPS = {BEV, CER, COMP, FAT, FME, FV, DAIRY, SALTY, SUGARY}

# K2: shop sub-categories whose products all share one PNNS group. They decide before
# the name: in "Softdrinks", "Orange, Zero" is a soft drink, not a fruit.
SHOP_STRONG: dict[str, str] = {
    "Softdrinks": BEV, "Funktionsgetränke & Energydrinks": BEV, "Mineralwasser": BEV,
    "Kaffee": BEV, "Tee": BEV, "Säfte & Sirup": BEV, "Alkoholfreie Getränke": BEV,
    "Käse": DAIRY, "Käse & Frischkäse": DAIRY, "Glace & Sorbets": DAIRY,
    "Fertiggerichte & Pizza": COMP, "Dressings, Öle & Saucen": FAT,
    "Schokolade": SUGARY, "Riegel": SUGARY, "Gebäck & Guetzli": SUGARY, "Biscuits": SUGARY,
    "Schokolade & Süssigkeiten": SUGARY,
    "Müesli & Flakes": CER, "Müesli & Cerealien": CER, "Porridge & Haferflocken": CER,
    "Toast & abgepacktes Brot": CER, "Frische Backwaren (Panetteria)": CER, "Aufbackwaren": CER,
    "Brote, Kleinbrote & Süssgebäck": CER,
    "Charcuterie & Wurstwaren": FME, "Wurstwaren & Charcuterie": FME, "Geflügel": FME,
    "Rind & Kalb": FME, "Schwein": FME, "Lamm & Wild": FME, "Frischer Fisch & Meeresfrüchte": FME,
    "Fisch und Fleisch": FME,
    "Früchte & Gemüse": FV, "Gemüse": FV, "Salat": FV, "Früchte": FV,
}

# K3: name keywords (German, French, Italian), first match wins. The order follows PNNS
# conventions that are not obvious: potato crisps are "Cereals and potatoes", nuts,
# olives and pickles "Salty snacks", legumes and tofu "Cereals and potatoes", soups
# "Fruits and vegetables", ice cream and dairy desserts "Milk and dairy products".
NAME_RULES: list[tuple[str, str]] = [
    (COMP, r"pizza|lasagne(?!blätter)|ravioli|sandwich(?!toast)|burger(?! ?(style )?sauce)|quiche|"
           r"wähe|flammkuchen|tarte flambée|fertiggericht|paella|eintopf|fondue|gratin|moussaka|"
           r"cordon bleu|fisch-?stäbchen|fisch-?sticks|bami goreng|nasi goreng|sushi|älplermagronen|"
           r"hachis|taboulé|kartoffeltaschen|baguettes,|fajita|chili con carne|club sandwich|"
           r"pasta &|picco belli"),
    (FV, r"suppe|soupe|zuppa|minestrone|gazpacho"),
    (CER, r"linsen|lentille|kichererbse|pois chiche|bohnen|haricot|tofu|erdnussbutter|"
          r"peanut butter|edamame"),
    (FAT, r"sauce|salsa|sugo|pesto|dressing|vinaigrette|mayonna|mayo\b|ketchup|senf|moutarde|"
          r"senape|mayonai|curry ?past|ajvar|coulis|hollandaise|tartare|aioli|bouillon|brühe|aromat|"
          r"flüssigwürze|würze\b|gemüse-?extrakt"),
    (CER, r"chips|crisps|pringles|kartoffel|pomme(s)? de terre|patate|rösti|frites|stocki"),
    (DAIRY, r"glace|gelato|ice cream|eiscreme|soft ice|pudding|flan\b|dessertcreme|crème dessert|"
            r"mousse|crème (caramel|brûlée)|panna cotta"),
    (SUGARY, r"schokolade|schoko|chocolat|cioccolat|praline|truffe|lindor|kuvertüre|frigor|cailler|"
             r"nougat|riegel|barre|biscuit|biskuit|guetzli|keks|cookie|waffel|gaufre|kuchen|cake|"
             r"torte|tourte|tarte|gipfel|croissant|muffin|brownie|bonbon|caramel|karamell|gummi|"
             r"lakritz|marshmallow|konfitüre|confiture|marmelade|gelee|delicia|honig|miel\b|nutella|"
             r"brotaufstrich|zucker(?! ?zero)|sucre|sorbet|dessert|lebkuchen|meringue|mars\b|twix|"
             r"snickers|kitkat|toblerone|balisto|branches|minor\b|kägi|petit beurre|madeleine|bärli|"
             r"sirup|sirop|crème noisette|choco-cream"),
    (BEV, r"\bwasser\b|mineral|\beau\b|acqua|drink|saft|\bjus\b|juice|succo|limonade|cola\b|"
          r"eistee|ice tea|\btee\b|\bthé\b|infusion|kaffee(?!rahm)|café|caffè|espresso|cappuccino|"
          r"latte macchiato|energy|rivella|schorle|süessmost|\bmost\b|smoothie|nektar|nectar|boisson|"
          r"bevanda|sinalco|elmer|red bull|powerade|capri.?sun|kombucha|ovomaltine|caotina|nesquik|"
          r"kakao|\bzero\b|kokos(nuss)?milch|hafer ?drink|soja ?drink|mandel ?drink|lait de coco|"
          r"meal to go|coffee"),
    (DAIRY, r"käse|fromage|formaggio|jog(h)?urt|yogh?ourt|yaourt|quark|séré|milch\b|vollmilch|"
            r"magermilch|\blait\b|\blatte\b|rahm(?!spinat)|\bcrème\b|creme fra|mozzarella|mascarpone|"
            r"ricotta|gruy[eè]re|emmental|appenzell|camembert|brie\b|feta|gorgonzola|parmesan|"
            r"grana padano|sbrinz|raclette|tilsiter|cottage|hüttenkäse|kefir|buttermilch|skyr|"
            r"petit suisse|babybel|philadelphia|cantadou|aktifit|lc1|actimel|mix-it"),
    (FAT, r"\bbutter\b|beurre|burro|margarine|\böl\b|olivenöl|huile|olio|kokosfett|schmalz|"
          r"bratcreme|bratbutter|kräuterbutter|flora\b|lätta|becel"),
    (SALTY, r"cracker|salzstange|bretzel|brezel|apéro|popcorn|nic nac|\btuc\b|goldfish|"
            r"stickletti|flips|jumpys|grissini|nüsse|noix|mandel|amande|cashew|pistazie|haselnuss|"
            r"baumnuss|erdnuss|erdnüsse|cacahu|arachid|nussmischung|nussmix|cornichon|gurken|"
            r"oliven|olives|tapenade"),
    (FME, r"schinken|jambon|prosciutto|salami|wurst|würstchen|wienerli|cervelat|saucisse|"
          r"salsiccia|speck|lard\b|bacon|poulet|huhn|hähnchen|chicken|pollo|truthahn|trute|dinde|"
          r"rind|boeuf|bœuf|manzo|kalb|veau|schwein|porc|maiale|lamm|agneau|hack|steak|schnitzel|"
          r"filet|plätzli|fleischkäse|leberkäse|thon|thun|tonno|lachs|saumon|salmone|forelle|"
          r"crevette|garnele|shrimp|fisch|poisson|pesce|sardine|makrele|hering|kabeljau|pangasius|"
          r"\beier\b(?! ?(tagliatelle|nudeln|teigwaren|ravioli))|\bei\b|oeufs?|œufs?|uova|"
          r"bündnerfleisch|trockenfleisch|charcuterie|aufschnitt|mortadella|coppa|chorizo|seitan|"
          r"quorn|fleischersatz|planted|nuggets"),
    (CER, r"\bmais\b|maiskörner|sonnenmais|polenta|maizena|maisstärke"),
    (FV, r"apfel|äpfel|birne|banane|orange|zitrone|mandarine|grapefruit|ananas|mango|beeren|"
         r"erdbeer|himbeer|kirsch|aprikose|pfirsich|traube|sultanine|rosine|dattel|feige|früchte|"
         r"fruits?\b|frutta|kompott|compote|apfelmus|gemüse|légumes?|verdur|tomate|karotte|rüebli|"
         r"carotte|zwiebel|oignon|knoblauch|paprika|peperoni|zucchini|aubergine|spinat|épinard|"
         r"brokkoli|blumenkohl|kohl|kraut|lauch|sellerie|randen|kürbis|champignon|pilz|spargel|"
         r"erbsen|salat\b|laitue|avocado|kokos|fruchtcocktail"),
    (CER, r"brot\b|brötchen|\bpain\b|pane\b|toast|zwieback|knäcke|baguette|ciabatta|tortilla|"
          r"wrap|teigwaren|pasta|nudel|noodle|spaghetti|penne|fusilli|hörnli|spiralen|farfalle|"
          r"tagliatelle|tortellini|tortelloni|lasagneblätter|gnocchi|spätzli|reis\b|\briz\b|riso\b|"
          r"risotto|couscous|bulgur|quinoa|mehl|farine|farina|grieß|griess|haferflocken|flocken|"
          r"müesli|muesli|granola|cornflakes|cerealien|porridge|blätterteig|kuchenteig|pizzateig|"
          r"stärke|reiswaffel"),
]
NAME_RX = [(g, re.compile(rx, re.I)) for g, rx in NAME_RULES]

# K4: shop sub-category (or main category) when no name rule matches. Only categories
# whose products mostly share one PNNS group; mixed ones ("Konserven") are left out.
SHOP_RULES: dict[str, str] = {
    # Aldi sub-categories
    "Softdrinks": BEV, "Funktionsgetränke & Energydrinks": BEV, "Mineralwasser": BEV,
    "Kaffee": BEV, "Tee": BEV, "Säfte & Sirup": BEV, "Kakao, Schokolade & Ovomaltine": BEV,
    "Alkoholfreie Getränke": BEV,
    "Frische Backwaren (Panetteria)": CER, "Toast & abgepacktes Brot": CER, "Aufbackwaren": CER,
    "Knäckebrot & Zwieback": CER, "Kuchen & Gebäck": SUGARY,
    "Frischer Fisch & Meeresfrüchte": FME, "Fischspezialitäten": FME,
    "Charcuterie & Wurstwaren": FME, "Geflügel": FME, "Rind & Kalb": FME, "Schwein": FME,
    "Lamm & Wild": FME, "Fleisch": FME, "Fisch": FME, "Fisch & Meeresfrüchte": FME,
    "Müesli & Flakes": CER, "Porridge & Haferflocken": CER, "Brotaufstriche & Konfitüren": SUGARY,
    "Honig": SUGARY, "Fertiggerichte": COMP, "Sandwiches & Snacks": COMP, "Desserts": SUGARY,
    "Aufstriche, Dips & Saucen": FAT, "Käse": DAIRY, "Joghurts, Quark & Desserts": DAIRY,
    "Butter, Milch & Rahm": DAIRY, "Eier": FME, "Milchprodukte & Eier": DAIRY,
    "Chips & Snacks": SALTY, "Schokolade": SUGARY, "Riegel": SUGARY,
    "Weitere Süssigkeiten": SUGARY, "Gebäck & Guetzli": SUGARY,
    "Früchte & Gemüse": FV, "Fertiggerichte & Pizza": COMP, "Glace & Sorbets": SUGARY,
    "Desserts, Torten & Kuchen": SUGARY, "Brot, Apérogebäck & Snacks": SALTY,
    "Grundnahrungsmittel": CER, "Dressings, Öle & Saucen": FAT, "Bouillons & Suppen": COMP,
    "Tiefgekühlte Produkte": COMP, "Süssigkeiten & Snacks": SUGARY,
    # Volgshop sub-categories
    "Brote, Kleinbrote & Süssgebäck": CER, "Haltbare Backwaren": CER, "Müesli & Cerealien": CER,
    "Brotaufstriche": SUGARY, "Wurstwaren & Charcuterie": FME, "Fisch und Fleisch": FME,
    "Fleischalternativen": FME, "Gemüse": FV, "Salat": FV, "Früchte": FV, "Salatsaucen": FAT,
    "Kaffee, Tee, Heissgetränke": BEV, "Käse & Frischkäse": DAIRY,
    "Milch, Rahm & Milchmischgetränke": DAIRY, "Frische Fertiggerichte": COMP,
    "Jogurt, Quark & Desserts": DAIRY, "Schokolade & Süssigkeiten": SUGARY, "Biscuits": SUGARY,
    "Snacks & Chips": SALTY, "Gewürze, Saucen, Suppen & Bouillons": FAT,
    "Teigwaren, Reis & Fertiggerichte": CER, "Öl, Essig & Fett": FAT,
}


def category_from_rules(name: str | None, sub: str | None, main: str | None) -> tuple[str | None, str | None]:
    """(PNNS group, rule used): homogeneous shop category (K2), name keyword (K3), then
    any mapped shop category (K4)."""
    if sub in SHOP_STRONG:
        return SHOP_STRONG[sub], "shop_category"
    for group, rx in NAME_RX:
        if name and rx.search(name):
            return group, "name"
    for cat in (sub, main):
        if cat in SHOP_RULES:
            return SHOP_RULES[cat], "shop_category"
    return None, None


def add_category(rows: list[dict]) -> None:
    """K1: category_common = OFF's PNNS group if known, else the rules (K2-K4)."""
    for r in rows:
        off = r.get("off_pnns_group_1")
        rule, how = category_from_rules(r.get("name"), r.get("category_sub"), r.get("category_main"))
        r["category_rules"] = rule
        if off in PNNS_GROUPS:
            r["category_common"], r["category_common_source"] = off, "off"
        elif rule:
            r["category_common"], r["category_common_source"] = rule, how
        else:
            r["category_common"] = r["category_common_source"] = None


# --------------------------------------------------------------------------- validation
def validate() -> None:
    """V1: rules vs OFF's PNNS group on products that have both.
    a) products in products_matched (shop category + name);
    b) all Swiss OFF entries, name only (as for Migros/Coop products without PNNS)."""
    pm = (PROCESSED_DIR / "products_matched.parquet").as_posix()
    rel = duckdb.sql(f"SELECT retailer, name, category_sub, category_main, off_pnns_group_1 FROM '{pm}' "
                     f"WHERE off_pnns_group_1 IN ({', '.join(repr(g) for g in PNNS_GROUPS)})")
    by = collections.Counter()
    confusion = collections.Counter()
    for retailer, name, sub, main, off in rel.fetchall():
        rule, how = category_from_rules(name, sub, main)
        by[(retailer, "n")] += 1
        by[(retailer, "covered")] += rule is not None
        by[(retailer, "same")] += rule == off
        if rule and rule != off:
            confusion[(off, rule)] += 1
    print("a) products_matched, shop category + name")
    for retailer in sorted({k for k, _ in by}):
        n, cov, same = by[(retailer, "n")], by[(retailer, "covered")], by[(retailer, "same")]
        print(f"   {retailer:<7} n={n:>4}  assigned {cov / n:.0%}  same group {same / max(cov, 1):.0%} of assigned")
    off = (PROCESSED_DIR / "off_ch_clean.parquet").as_posix()
    rel = duckdb.sql(f"SELECT product_name, pnns_group_1 FROM '{off}' WHERE product_name IS NOT NULL "
                     f"AND pnns_group_1 IN ({', '.join(repr(g) for g in PNNS_GROUPS)})")
    n = cov = same = 0
    for name, g in rel.fetchall():
        rule, _ = category_from_rules(name, None, None)
        n += 1
        cov += rule is not None
        same += rule == g
    print(f"b) OFF Swiss, name only: n={n}  assigned {cov / n:.0%}  same group {same / cov:.0%} of assigned")
    print("most frequent confusions in a) (OFF -> rules):", confusion.most_common(8))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["validate"])
    ap.parse_args()
    validate()


if __name__ == "__main__":
    main()
