# Para Vojta: los datos para la base SQL

*Versión en español de [`For_Vojta.md`](For_Vojta.md).*

Hola Vojta, aquí está todo lo que necesitas saber de los datos para armar la base SQL
(PostgreSQL). Estado al 10 de noviembre de 2026, rama `data/off-acquisition-v1`.

**Versión corta:** todo lo importante está en una sola tabla,
`data/processed/products_matched.parquet` (2 443 filas, una fila = un producto en una
cadena). Para el análisis (H1, H2) sirven **1 045 productos**, los que tienen precio por
100 g/ml, Nutri-Score y categoría común. Las demás tablas son pasos intermedios o datos de
origen.

---

## 1. De dónde vienen los datos

| Fuente | Qué aporta | Cómo se obtuvo |
|---|---|---|
| **Aldi Suisse** (aldi-suisse.ch) | precios, tamaño del paquete, marca, categoría, ingredientes | API JSON pública de la tienda online, 3 de noviembre de 2026 |
| **Volgshop** (volgshop.ch) | precios, tamaño del paquete, tabla nutricional, país de producción, ingredientes | API JSON pública de la tienda online (WooCommerce), 3 de noviembre de 2026 |
| **Open Food Facts (OFF)** | valores nutricionales, Nutri-Score, NOVA, categorías, EAN | export CSV completo (~1.5 GB), 2 y 3 de noviembre de 2026 |
| **Open Prices** | precios de Migros, Coop, Lidl y Denner (por EAN) | API pública, 10 de noviembre de 2026 |

Migros y Coop bloquean el scraping (protección anti-bots), así que sus precios vienen de
Open Prices, un proyecto comunitario de OFF en el que voluntarios fotografían etiquetas de
precio y tickets. Ni Aldi ni Volgshop publican el EAN, así que sus productos se
emparejaron con OFF por **marca y nombre** (matching difuso).

## 2. Archivos

Todas las tablas existen en dos formatos:
- **`.parquet`**: con los tipos de datos correctos. Es el que recomiendo para importar.
- **`.csv`**: UTF-8, separador `,` y listas unidas con `|`.

### Tabla principal (la que necesitas)

| Archivo | Filas | Llave | Contenido |
|---|---:|---|---|
| `data/processed/products_matched.parquet` | 2 443 | (`retailer`, `retailer_id`) | todas las cadenas: precio + nutrición + Nutri-Score + categoría |

### Tablas de apoyo (opcionales)

| Archivo | Filas | Llave | Contenido |
|---|---:|---|---|
| `off_ch_clean.parquet` | 73 738 | `code` (EAN) | productos suizos de OFF ya limpios (para el clustering) |
| `off_aldi_ext_clean.parquet` | 15 162 | `code` | fichas alemanas y austriacas de OFF de las marcas de Aldi |
| `off_openprices_ext_clean.parquet` | 105 | `code` | fichas de OFF de otros países para EAN de Open Prices |
| `aldi_clean.parquet` | 1 577 | `sku` | catálogo de Aldi limpio |
| `volg_clean.parquet` | 445 | `product_id` | catálogo de Volgshop limpio |
| `openprices_clean.parquet` | 435 | (`chain`, `code`) | precios de Open Prices limpios |
| `matches.parquet` | 2 022 | (`retailer`, `retailer_id`) | mejor candidato de OFF para cada producto de Aldi/Volg, con su score |
| `*_cleaning_log.csv` | | | cuántas filas eliminó cada regla |
| `*_metadata.json` | | | procedencia de los datos (URL, fecha, SHA-256) |

Los datos crudos están en `data/raw/`; para la base de datos no hacen falta.

## 3. Columnas de la tabla principal `products_matched`

**Identificación y tienda**

| Columna | Tipo | Valores / nota |
|---|---|---|
| `retailer` | text | `aldi` 1 577, `volg` 445, `migros` 242, `coop` 131, `lidl` 33, `denner` 15 |
| `retailer_id` | text | ID del producto en la tienda (SKU en Aldi, id en Volg, **EAN** en Migros/Coop/Lidl/Denner) |
| `name`, `brand` | text | nombre y marca (en Volg muchas veces sin marca) |
| `category_main`, `category_sub` | text | categoría propia de la tienda (solo Aldi y Volg); **no usar para comparar**, ver `category_common` |
| `is_organic` | bool | producto orgánico |

**Precio**

| Columna | Tipo | Valores / nota |
|---|---|---|
| `price_chf` | double | precio regular (no de promoción) en CHF |
| `size_value`, `size_unit` | double, text | tamaño del paquete en `g` o `ml` |
| `price_per_100_chf` | double | **variable dependiente**: precio por 100 g o 100 ml |
| `price_per_100_unit` | text | `g` (2 091) o `ml` (352); g y ml **no se deben mezclar** sin distinguirlos |
| `price_source` | text | `retailer_web` (Aldi, Volg) u `open_prices` |
| `price_date` | date | fecha del precio (3 de noviembre de 2026 para Aldi/Volg; 2024–2026 para Open Prices) |

**Emparejamiento con OFF**

| Columna | Tipo | Valores / nota |
|---|---|---|
| `matched` | bool | el producto tiene ficha en OFF |
| `match_method` | text | `ean` (Open Prices), `brand`, `store_name`, `generic_brand_in_store`; NULL = sin emparejar |
| `match_score` | double | similitud de nombres 0–100 (solo Aldi/Volg) |
| `off_code` | text | EAN de la ficha OFF → llave foránea a las tablas de OFF |
| `off_scope` | text | `ch` (ficha suiza), `de_at` (alemana/austriaca), `openprices_ext` (otro país) |
| `off_name`, `off_main_category`, `off_pnns_group_1/2`, `off_nova_group`, `off_origin_status` | | datos copiados de OFF |
| `off_nutriscore_grade`, `off_nutriscore_score` | | Nutri-Score directo de OFF (sin completar) |

**Nutrición (por 100 g/ml)**

| Columna | Tipo | Valores / nota |
|---|---|---|
| `energy_kj`, `fat`, `saturated_fat`, `carbohydrates`, `sugars`, `fiber`, `proteins`, `salt` | double | gramos por 100 g/ml (energía en kJ); `fiber` falta a menudo |
| `nutrition_source` | text | `retailer` (tabla propia de Volg, 381), `off` (708), NULL = sin nutrición (1 354) |

**Nutri-Score (usar estas columnas)**

| Columna | Tipo | Valores / nota |
|---|---|---|
| `nutriscore_grade` | text | **`a`–`e`, para el análisis.** El de OFF y, si falta, el calculado |
| `nutriscore_score` | double | puntaje numérico (más bajo = más sano) |
| `nutriscore_source` | text | `off` (706) o `computed` (358) |
| `nutriscore_calc_grade`, `nutriscore_calc_score` | | nuestro cálculo para todos los productos con nutrición (para el análisis de sensibilidad) |
| `nutriscore_kind` | text | tipo de algoritmo: `general`, `beverage`, `fat`, `cheese`, `water`, `red_meat`, `not_applicable`, `unsupported` |
| `nutriscore_category_source` | text | de dónde sale `nutriscore_kind`: `off_categories` o `retailer_name` |

**Categoría común (usar para comparar entre tiendas)**

| Columna | Tipo | Valores / nota |
|---|---|---|
| `category_common` | text | 9 grupos PNNS: Beverages, Cereals and potatoes, Composite foods, Fat and sauces, Fish Meat Eggs, Fruits and vegetables, Milk and dairy products, Salty snacks, Sugary snacks |
| `category_common_source` | text | `off`, `shop_category`, `name` (regla por nombre) |
| `category_rules` | text | la categoría según nuestras reglas (para control) |

**Origen (para H3)**

| Columna | Valores / nota |
|---|---|
| `origin_status_retailer` | `domestic` / `imported`: solo Volg, **país de fabricación** (426 productos) |
| `off_origin_status` | `domestic` / `imported` / `mixed`: de OFF, **origen de los ingredientes** (179 productos) |

Ojo, son dos conceptos distintos. Un chocolate fabricado en Suiza con cacao de Ghana es
`domestic` en Volg e `imported` en OFF.

## 4. Propuesta de esquema (PostgreSQL)

Sigue el plan del README (products, nutrition 1:1, categories n:1, retailers n:1), más una
tabla de productos de OFF. Es solo una propuesta; ajústala como te sirva.

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

Notas para el import:
- **En `nutrition` van solo las filas con `nutrition_source IS NOT NULL`** (1 089 filas). Los
  demás productos (sobre todo los de Aldi sin emparejar) no tienen nutrición.
- Todo producto con Nutri-Score tiene también tabla nutricional, así que `nutrition` incluye
  los 1 064 productos con calificación.
- `nutriscore_kind` está lleno en todas las filas, pero solo tiene sentido donde existe
  `nutriscore_calc_grade`.
- Varios productos pueden apuntar al mismo `off_code` (el mismo producto en varias tiendas):
  816 referencias a 790 EAN distintos. La relación es n:1.
- El parquet se lee directo con DuckDB (`SELECT * FROM 'file.parquet'`) o con pandas
  (`pd.read_parquet`). Por ahora `requirements.txt` solo tiene `duckdb` y `rapidfuzz`; para
  PostgreSQL habrá que agregar `sqlalchemy` y `psycopg`.

Consulta de control útil después del import (debería dar 1 045):

```sql
SELECT count(*)
FROM products p JOIN nutrition n USING (product_id)
WHERE n.nutriscore_grade IS NOT NULL AND p.category_id IS NOT NULL;
```

## 5. Cómo regenerar los datos

```bash
python src/openfoodfacts.py all             # OFF: download, Swiss extract, cleaning
python src/scraping.py all                  # Aldi and Volgshop
python src/retail_cleaning.py               # shop catalogue cleaning
python src/openfoodfacts.py aldi-ext        # German/Austrian OFF entries for Aldi
python src/scraping.py aldi-details         # Aldi ingredient lists
python src/openprices.py all                # Migros/Coop/Lidl/Denner prices
python src/openfoodfacts.py openprices-ext  # OFF entries for Open Prices EANs
python src/matching.py                      # matching + products_matched (Nutri-Score, category)
```

Ojo: OFF cambia todos los días, así que una descarga nueva no da exactamente los mismos
números. Los snapshots que usamos están guardados en git (`data/raw/*.parquet`).

---

## 6. Decisiones de limpieza (resumen)

El detalle y la justificación de cada decisión están en `docs/*_decisions.md` (en inglés).
Aquí va lo más importante.

### Open Food Facts (107 342 → 73 738 productos)

- **Solo productos marcados como vendidos en Suiza.**
- **Se eliminan:**
  - EAN inválidos (1 775, sobre todo códigos de báscula con el precio adentro);
  - alcohol (su precio lo define el impuesto especial, no la nutrición);
  - alimentos infantiles;
  - productos que no son alimentos.
- **Se exigen los 6 nutrientes básicos:** energía, grasa, grasa saturada, azúcares, proteína y
  sal (se eliminan 29 025). La fibra no se exige porque falta en el 46 % de los productos.
- **Se eliminan los valores físicamente imposibles** (578 filas en total):
  - un nutriente > 100 g por 100 g;
  - energía > 3800 kJ;
  - grasa saturada > grasa;
  - suma de macronutrientes > 105 g;
  - kJ y kcal que no cuadran.
- **No se imputa nada** ni se eliminan outliers estadísticos: un aceite con 90 g de grasa es
  extremo, pero real.
- **Unidades:** energía en kJ y sal en lugar de sodio.
- **Cadena** (`at_migros`, `at_coop`…): se deduce del campo "tiendas" y de las marcas propias
  (M-Classic → Migros, Naturaplan → Coop). `false` significa "no sabemos", no "no se vende
  ahí".

### Aldi y Volgshop (2 406 → 1 577 y 696 → 445 productos)

- **Se eliminan:** productos que no son alimentos, alcohol y tabaco (la cerveza y el vino sin
  alcohol se quedan) y alimentos infantiles.
- **Tiene que poder calcularse el precio por 100 g/ml.** Se eliminan los productos sin tamaño
  de paquete, los que se venden por pieza (cápsulas, huevos, fruta por unidad) y los que traen
  un rango de peso.
- **Se elimina el precio por 100 g fuera de 0.01–50 CHF:** 6 productos (especias y decoraciones
  de pocos gramos, y un error de datos).
- **Siempre el precio regular, no el de promoción.** En Aldi hay 64 productos en promoción, y
  el precio rebajado se guarda aparte.
- **Errores corregidos:** "kg en lugar de g" (por ejemplo "Müsli 750 kg").
- **Volgshop, tabla nutricional:** se parsea del texto y se revisa con las mismas reglas que
  OFF. Si está mal, el producto se queda, pero sin nutrición.
- **Volgshop, país de producción:** Suiza y Liechtenstein = `domestic`.

### Emparejamiento de Aldi/Volg con OFF (Aldi 273 de 1 577, Volg 122 de 445)

- **Sin EAN:** solo se comparan productos de la misma marca, y luego la similitud de nombres
  (0–100). Se acepta un score ≥ 90, o ≥ 75 si además coincide el tamaño del paquete.
- **Se priorizó la precisión sobre la cantidad,** porque un mal emparejamiento metería
  nutrición equivocada en la regresión.
  - Revisión manual de 100 pares: todos correctos.
  - En Volg, el 90 % de los pares también coincide en los valores nutricionales.
- **Los ingredientes solo sirven para descartar un par,** no para crearlo.
- **Para Aldi también se usan las fichas alemanas y austriacas de OFF** (las mismas marcas que
  Aldi Süd y Hofer). Sin ellas solo se habría emparejado el 6.5 % del surtido.
- **Punto débil:** las marcas propias suizas de Aldi (Saveurs Suisses, Panetteria) no están
  en OFF.

### Open Prices (1 050 precios → 435 productos)

- **Solo tiendas en Suiza** (sin Liechtenstein) y solo las cadenas Migros, Coop, Lidl, Denner,
  Aldi y Volg.
- **Sin formatos con precios propios** (Coop Pronto, Migrolino, Denner Express).
- **Sin precios de promoción.**
- **Para cada producto en cada cadena, el precio más reciente.** Los precios son de 2024–2026;
  la columna `price_date` permite controlarlo.
- **No es una muestra aleatoria:** son 123 voluntarios, sobre todo de la Suiza francófona.

### Nutri-Score calculado (706 → 1 064 productos con calificación)

- **OFF solo califica los productos emparejados.** Para los demás que tienen tabla completa
  (sobre todo Volg) se calcula con el algoritmo 2023, el mismo que usa OFF.
- **Validación:** en 42 232 productos de OFF, nuestro cálculo da la misma calificación en el
  97.7 % de los casos. En Volg coincide exactamente en el 86 %, y en el 97 % con a lo sumo un
  grado de diferencia.
- **Lo más incierto es el porcentaje de fruta, verdura y legumbres.** Volg no lo publica, así
  que se estima a partir de los ingredientes.
- **`nutriscore_source`** permite hacer el análisis solo con las calificaciones de OFF
  (análisis de sensibilidad).

### Categoría común (1 045 de 1 064 productos)

- **Las categorías de las tiendas no son comparables,** así que se usan los 9 grupos PNNS de
  OFF.
- **Los productos sin PNNS** reciben categoría según la subcategoría de la tienda y palabras
  clave del nombre. La coincidencia con OFF es de 88–93 %.
- **PNNS tiene sus convenciones:** las papas fritas de bolsa y las legumbres van en "Cereals
  and potatoes", los frutos secos y las aceitunas en "Salty snacks" y las sopas en "Fruits and
  vegetables".

## 7. Cuidado con

- **El precio por 100 g y el precio por 100 ml no son comparables.** En las consultas y en los
  modelos hay que distinguirlos con `price_per_100_unit`.
- **Los precios de Open Prices son de otras fechas** que los de Aldi y Volg.
- **Lidl (33) y Denner (15) tienen pocos productos** para comparar por categoría. Lo razonable
  es comparar Aldi, Volg, Migros y Coop.
- **Los productos de Aldi sin emparejar** (1 304) tienen precio, pero no nutrición ni
  Nutri-Score. No entran en el análisis de H1/H2, pero puedes tenerlos en la base sin
  problema.
- **El equipo todavía tiene que revisar:**
  - el archivo `match_review_sample.csv`, para la revisión manual de los pares (las columnas
    `correct` y `comment` están vacías);
  - las listas de palabras clave de `src/categories.py` y `src/nutriscore.py`.

  Hasta ahora solo las revisó Claude Code.

Si algo no queda claro, escríbeme.
