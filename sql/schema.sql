DROP TABLE IF EXISTS nutrition CASCADE;
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS off_products CASCADE;
DROP TABLE IF EXISTS retailers CASCADE;

CREATE TABLE retailers (
    retailer_id   TEXT PRIMARY KEY,          -- 'aldi', 'volg', 'migros', 'coop', 'lidl', 'denner'
    price_source  TEXT NOT NULL CHECK (price_source IN ('retailer_web', 'open_prices'))   -- 'retailer_web' | 'open_prices'
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
    origin_status     TEXT,
    -- + nutrients, for clustering on all 88 988 products in SQL
    is_organic        BOOLEAN,
    energy_kj         DOUBLE PRECISION,
    fat               DOUBLE PRECISION,
    saturated_fat     DOUBLE PRECISION,
    carbohydrates     DOUBLE PRECISION,
    sugars            DOUBLE PRECISION,
    fiber             DOUBLE PRECISION,
    proteins          DOUBLE PRECISION,
    salt              DOUBLE PRECISION
);

CREATE TABLE products (
    product_id          INTEGER PRIMARY KEY,
    retailer_id         TEXT NOT NULL REFERENCES retailers,
    retailer_product_id TEXT NOT NULL,       -- products_matched.retailer_id
    name                TEXT NOT NULL,
    brand               TEXT,
    shop_category_main  TEXT,
    shop_category_sub   TEXT,
    --category_id         INTEGER REFERENCES categories,   -- from category_common
    category_common  TEXT CHECK (category_common IN (
        'Beverages', 'Cereals and potatoes', 'Composite foods',
        'Fat and sauces', 'Fish Meat Eggs', 'Fruits and vegetables',
        'Milk and dairy products', 'Salty snacks', 'Sugary snacks')),
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