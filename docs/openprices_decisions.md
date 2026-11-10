# Open Prices: decisiones

Script: [`src/openprices.py`](../src/openprices.py) · Conteos reproducibles en
[`data/processed/openprices_cleaning_log.csv`](../data/processed/openprices_cleaning_log.csv) ·
Procedencia en [`data/processed/openprices_metadata.json`](../data/processed/openprices_metadata.json)

[Open Prices](https://prices.openfoodfacts.org) es el proyecto hermano de Open Food Facts:
voluntarios registran precios a partir de fotos de etiquetas de estante o de tickets, ligados
al EAN del producto y a la tienda (una ubicación de OpenStreetMap). Licencia ODbL, como OFF.

Se usa para tener precios de **Migros y Coop**, que bloquean el scraping (ver
[`retail_cleaning_decisions.md`](retail_cleaning_decisions.md)). Como cada precio trae el EAN,
la unión con OFF es exacta: no hace falta el matching por nombre de Aldi y Volgshop.

Los identificadores (F1, C1, N1…) son propios de este documento.

## Resumen del embudo

Descarga del 2026-11-10 de todos los precios en CHF (`GET /api/v1/prices?currency=CHF`).

| Regla | Qué elimina | Eliminadas | Quedan |
|---|---|---:|---:|
| — | Precios en CHF | | 1 050 |
| F1 | Precio sin EAN (categoría de producto suelto) | 4 | 1 046 |
| F2 | Tienda fuera de Suiza (Liechtenstein 101, Francia 1) | 102 | 944 |
| F3 | Tienda que no es de una cadena suiza de supermercados | 70 | 874 |
| F4 | Precio de promoción | 70 | 804 |
| F5 | Precio por kg de producto suelto | 0 | 804 |
| C1 | Un precio por (cadena, EAN) | 136 | 668 |
| F6 | EAN sin ficha OFF limpia (sin nutrición completa) | 139 | 529 |
| F7 | Sin tamaño del paquete en g o ml en OFF | 94 | 435 |
| F8 | Precio por 100 g/ml fuera de CHF 0.01–50 | 0 | **435** |

| Cadena | Productos | Con Nutri-Score | Fechas de los precios |
|---|---:|---:|---|
| Migros | 242 | 226 | 2024-04 – 2026-10 |
| Coop | 131 | 122 | 2024-04 – 2026-11 |
| Lidl | 33 | 32 | 2024-06 – 2026-06 |
| Denner | 15 | 13 | 2025-01 – 2026-08 |
| Aldi | 14 | 14 | (no se usa, M11) |

---

## F. Filtros (eliminan filas)

**F1. Solo precios de productos con EAN.** Open Prices también admite precios por categoría
("manzanas, 1 kg") sin código. *Justificación:* sin EAN no hay unión con la nutrición de OFF.

**F2. Solo tiendas en Suiza** (`osm_address_country_code = 'CH'`). La consulta por CHF trae
también Liechtenstein (Coop Schaan: 100 precios). *Justificación:* la pregunta es sobre
Suiza, y Liechtenstein tiene otra fiscalidad.

**F3. La tienda tiene que ser de una cadena suiza de supermercados.** La cadena sale de la
marca OSM de la tienda (`osm_brand`) o, si no hay, de su nombre (`osm_name`), cuando empieza
por Migros, Coop, Denner, Lidl, Aldi o Volg. Se exige además que la ubicación sea una tienda
(`osm_tag_value` en supermarket, convenience, department_store, mall, kiosk, general).
- *Se excluyen los formatos con su propia lista de precios:* Coop Pronto, Migrolino y Denner
  Express (franquicias de conveniencia, con precios más altos), Coop Vitality (farmacia),
  Migros Restaurant y Migros Online.
- *Dos centros comerciales se asignan a mano* (`LOCATION_CHAIN`), porque OSM nombra el
  centro y no la tienda. La asignación sale de las marcas propias compradas ahí: en "La
  Maladière centre" (Neuchâtel, 41 precios) son Coop, Naturaplan y Betty Bossi; en
  "Métropole Centre" (La Chaux-de-Fonds, 39 precios) son Migros, M-Budget y M-Classic.
- *Qué se elimina* (70): otras tiendas (Manor 9, Seelan Market 9, Aligro 5, Sapori d'Italia 5,
  VOI 2…), los formatos excluidos (12) y ubicaciones que no son tiendas (estaciones de
  carsharing, un estadio, la sede de Lidl Suiza).

**F4. Solo precios regulares** (`price_is_discounted = false`). *Justificación:* es la misma
regla que para Aldi (C1 de la limpieza de tiendas). Una promoción mide la estrategia
comercial de una semana, no el precio del producto.

**F5. Solo precios por artículo** (`price_per` vacío). Los precios por kg son de productos
sueltos. No hubo casos tras F1.

**F6. El EAN tiene que estar en una tabla OFF limpia.** Primero la suiza
(`off_ch_clean.parquet`). Si la ficha no está etiquetada en Suiza, se usa la del mismo EAN
de otro país (`off_openprices_ext_clean.parquet`, E8 de
[`off_cleaning_decisions.md`](off_cleaning_decisions.md)): aporta 58 productos. Se
eliminan 139: casi todos tienen ficha OFF, pero la limpieza de OFF la quitó por nutrición
incompleta (F6 de OFF), o el EAN no está en el export.

**F7. Hace falta el tamaño del paquete en g o ml** (`product_quantity` de OFF) para el precio
por 100 g/ml. *Se probó usar el tamaño que trae Open Prices como respaldo:* coincide con OFF
en 496 de 505 casos, pero solo habría recuperado 1 producto, así que no se usa.

**F8. Precio por 100 g/ml entre CHF 0.01 y 50**, igual que F6 de la limpieza de tiendas. No
hubo casos.

## C. Transformaciones

**C1. Un precio por (cadena, EAN): el más reciente.** Si ese día hay varios precios (de
tiendas distintas), se toma la mediana. Se guardan también el número de observaciones
(`price_n_obs`), de tiendas (`price_n_shops`) y la primera fecha (`price_first_date`).
*Justificación:* nuestros precios de Aldi y Volgshop son del 2026-11-03, y el más reciente es
el más cercano. Los precios regulares repetidos del mismo producto varían poco: en los 90
productos con más de una observación, la diferencia entre el máximo y el mínimo tiene una
mediana de 0 % y un percentil 90 de 8 %.

**C2. Nutrición, Nutri-Score, NOVA y categoría PNNS vienen de OFF**, unidos por EAN. La
columna `off_scope` dice si la ficha es suiza (`ch`) o de otro país (`openprices_ext`).

## N. Lo que deliberadamente no se hizo

**N1. No se filtró por fecha.** El 7 al 8 % de los precios de Migros y Coop es de 2024, el
62 % de 2025 y el resto de 2026. La inflación de alimentos en Suiza es baja (alrededor del
1 % anual), y la columna `price_date` permite controlar por fecha o hacer un análisis de
sensibilidad (por ejemplo, solo 2025–2026).

**N2. No se validó contra el scraping de Aldi.** La idea era comparar los precios de Open
Prices con los del catálogo de Aldi para los mismos EAN, pero ninguno de los 14 productos de
Aldi en Open Prices está entre los 273 matches de Aldi con OFF.

**N3. No se corrigió por tienda.** Migros es una federación de cooperativas regionales, y
los precios varían un poco entre regiones. Los precios vienen sobre todo de la Suiza
romanda (Ginebra, Nyon, Neuchâtel).

## Sesgos conocidos

- **No es una muestra aleatoria del surtido.** Son 123 voluntarios, y los 5 más activos
  aportan cerca del 60 % de los precios. Los productos reflejan lo que esa gente compra
  (más snacks dulces y cereales en Migros, pocos frescos en ambas cadenas).
- **Productos envasados.** Por F1 y F7, frutas, verduras, carne y pan a granel casi no
  aparecen, igual que en Aldi y Volgshop tras el matching.
- **Lidl y Denner** tienen muy pocos productos (33 y 15) para compararlos como grupo propio.
