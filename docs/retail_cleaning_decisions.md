# Aldi y Volgshop: decisiones de limpieza

Scripts: [`src/scraping.py`](../src/scraping.py) (descarga) y
[`src/retail_cleaning.py`](../src/retail_cleaning.py) (limpieza) · Conteos reproducibles en
[`data/processed/retail_cleaning_log.csv`](../data/processed/retail_cleaning_log.csv) ·
Procedencia de los snapshots en [`data/processed/retail_metadata.json`](../data/processed/retail_metadata.json)

Los identificadores (F1, C1, N1…) aparecen como comentarios en el código. Son propios de
este documento y no coinciden con los de [`off_cleaning_decisions.md`](off_cleaning_decisions.md).

- **F**: filtros que **eliminan filas**.
- **C**: limpieza y transformaciones que **no eliminan filas**.
- **N**: cosas que deliberadamente **no** se hicieron.

## Resumen del embudo

Snapshots descargados el 2026-11-03 de las APIs JSON públicas de cada tienda.

| Regla | Qué elimina | Aldi | Quedan | Volgshop | Quedan |
|---|---|---:|---:|---:|---:|
| — | Productos descargados | | 2 406 | | 696 |
| F1 | Identificador duplicado | 0 | 2 406 | 0 | 696 |
| F2 | No alimentos | 377 | 2 029 | 114 | 582 |
| F3 | Alcohol y tabaco | 140 | 1 889 | 103 | 479 |
| F4 | Alimentos infantiles | 9 | 1 880 | 0 | 479 |
| F5 | Sin precio por 100 g/ml calculable | 297 | 1 583 | 34 | 445 |
| F6 | Precio por 100 g/ml fuera de CHF 0.01–50 | 6 | **1 577** | 0 | **445** |

De los 445 productos de Volgshop, 381 tienen tabla nutricional completa (C6). Aldi no
publica valores nutricionales: su nutrición tiene que venir de Open Food Facts en el
matching (N1).

---

## F. Filtros (eliminan filas)

**F1. Identificador duplicado** (SKU en Aldi, id de producto en Volgshop).
No hubo casos. El scraper de Aldi ya deduplica por SKU, porque un producto aparece en
varias categorías del crawl. *Justificación:* el identificador es la llave primaria en la
base de datos.

**F2. Se excluyen los no alimentos.**
- *Aldi* (377): las categorías superiores "Gesundheit, Körperpflege & Baby" y "Haushalt &
  Wohnen"; las subcategorías no alimentarias de "Aktionen" (ropa, decoración, juguetes,
  limpieza, comida para mascotas, plantas…; la lista está en `ALDI_NONFOOD_SUB`); y 13
  marcas de no alimentos que aparecen sin subcategoría bajo "Aktionen" (Whiskas, Sheba,
  Domestos, Pantene, Varta…; `ALDI_NONFOOD_BRANDS`). La lista de marcas se armó revisando
  a mano los 332 productos de categorías genéricas o temáticas con tamaño en g/ml.
- *Volgshop* (114): la categoría "Körperpflege, Reinigung, Haushalt & Tierbedarf".

*Justificación:* están fuera del alcance del estudio, y su precio "por 100 g" no tiene
sentido nutricional. Es el mismo criterio que F5 de OFF.

**F3. Se excluyen alcohol y tabaco.**
- *Aldi* (140): la categoría "Alkohol & Tabakwaren"; los vinos, cervezas y licores en
  promoción, que aparecen solo bajo "Aktionen" y se reconocen por el nombre (AOC, DOC,
  IGT, vino, Bier, Vodka, variedades de uva…); y la marca Feldschlösschen salvo
  "alkoholfrei". La regla por nombre se aplica **solo** a la categoría genérica
  "Aktionen": en las demás, las mismas palabras son sabores ("Rotwein Sauce",
  "Edelmarzipan, Rum-Traube") y la regla las habría eliminado por error.
- *Volgshop* (103): las categorías "Jugendschutz" (la categoría +18 de Volg, que agrupa
  todo el alcohol y el tabaco) y "Tabakwaren".

Las bebidas sin alcohol (cerveza, vino y espumoso "alkoholfrei") **se conservan**.
*Justificación:* igual que F3 de OFF. El Nutri-Score no se calcula para el alcohol y su
precio en Suiza depende sobre todo del impuesto, no de la calidad nutricional.

**F4. Se excluyen los alimentos infantiles.**
- *Aldi* (9): la subcategoría "Baby & Kinderartikel" y las marcas Aptamil y Mamia
  (purés de fruta para bebés).
- *Volgshop* (0): el catálogo online no tiene alimentos infantiles. La regla busca "Baby"
  o "Säugling" en el nombre y excluye "Babybel".

*Justificación:* igual que F4 de OFF. Tienen su propia regulación y no reciben Nutri-Score.

**F5. Se exige poder calcular el precio por 100 g o 100 ml** (C2).
Esta variable es la variable dependiente del análisis, así que un producto sin ella no
aporta nada. Se eliminan:
- **Sin tamaño** (Aldi 227 de los 297): 526 productos de Aldi no traen `sellingSize`, y la
  ficha de detalle tampoco lo tiene. 299 de ellos ya habían salido en F2–F4 (no
  alimentos, alcohol). Los 227 restantes son alimentos sin tamaño publicado, como
  "Glasnudeln", "Sbrinz" o "Tomatoketchup, mild".
- **Tamaño en unidades** y no en peso o volumen (Aldi 70, y la mayoría de los 34 de
  Volgshop): cápsulas de café, bolsitas de té, huevos, fruta y verdura por pieza
  ("Avocado Stk."), sacarina en tabletas.
- **Rangos de peso** ("Lauch Stück ca. 200g – 400g"): no hay un único peso por el que
  dividir el precio.
- **Tamaño sin resolver en Volgshop** (C2): el atributo y el nombre no coinciden y el
  precio por unidad publicado no permite decidir. Solo pasó con "Kinder Milchschnitte".

*Sesgo conocido:* los 227 alimentos de Aldi sin tamaño se pierden aunque tengan precio.
El café en cápsulas y el té en bolsitas salen por completo. Su precio
por gramo es muy alto, pero son productos sin aporte nutricional relevante, así que el
efecto sobre la pregunta de investigación es pequeño. Se menciona como limitación.

**F6. Precio por 100 g/ml fuera de CHF 0.01–50.**
Se eliminan 6 productos de Aldi:
- Un error de datos: "Schweinssteaks vom Hals 0.5 g" a CHF 7.85, casi seguro 0.5 kg.
  No se corrige porque no hay forma de confirmarlo.
- Cinco productos legítimos pero de pocos gramos: una vaina de vainilla (4 g) y
  decoraciones de repostería (2–5 g), con precios de CHF 52–86 por 100 g.

*Justificación:* el precio máximo después del filtro es CHF 28.6 por 100 ml (aromas de
repostería). Por encima de CHF 50 solo quedan productos que se usan en cantidades de
gramos, cuyo "precio por 100 g" sería un outlier extremo en la regresión sin decir nada
sobre la prima de salud.

## C. Limpieza y transformaciones (no eliminan filas)

**C1. Precio: se usa el precio regular, no el de promoción** (Aldi).
Cuando Aldi muestra un precio anterior tachado (`wasPriceDisplay`), ese es el precio
regular (`price_chf`), y el precio rebajado se guarda aparte en `price_promo_chf` con
`on_promotion = true`. Son 64 productos.
*Justificación:* las promociones duran una semana y dependen de la fecha del scraping.
El precio regular es el que se compara entre tiendas. Volgshop no tenía ninguna promoción
(`on_sale` siempre falso).

**C2. Tamaño del paquete y precio por 100 g/ml.**
El tamaño se convierte a g o ml (kg ×1000, dl ×100, cl ×10, l ×1000). Soporta
multipacks ("6x50cl" → 3000 ml), "Packung à 250 g" y pesos aproximados ("ungefähr 0.25
kg/Stück", `size_is_approx`). `price_per_100_chf = precio / tamaño × 100`, con
`price_per_100_unit` igual a `g` o `ml`. Sólidos y líquidos se mantienen separados y no se
convierte ml a g, porque OFF también reporta los nutrientes por 100 ml en bebidas.
"53g+" (peso mínimo por huevo) no se lee como tamaño.

*Validación en Aldi:* en los 1 701 productos sin promoción en los que Aldi publica precio
por unidad, el precio calculado coincide con el publicado en el 100 % de los casos
(±2 %).

*Volgshop: conciliación del tamaño.* La cantidad viene en el atributo "Mengeneinheit" y
casi siempre también en el nombre. Coinciden en 563 productos y difieren en 8. Algunas
veces el error está en el atributo ("Haus Sauce 250ml" con atributo "50ml") y otras en el
nombre ("Mini-Pic 90g" con atributo "5x90g"). Hay además packs que se venden por unidad:
la cerveza sin alcohol "6x50cl" cuesta CHF 1.30 por lata. Regla: se generan candidatos
(total y unidad individual, del atributo y del nombre), y se elige el que reproduce mejor
el precio por unidad publicado por Volg, con tolerancia del 25 %. Sin precio publicado se
usa el total del atributo, salvo que atributo y nombre difieran; entonces el tamaño
queda sin resolver (F5). `size_source` dice de dónde salió: atributo 438, nombre 6,
unidad individual 1.

*El precio por unidad publicado de Volg no se usa como precio* (`unit_price_published_chf`
se guarda solo como referencia). En 41 de 429 productos difiere más de un 2 % del precio
actual, en general entre 5 y 20 %. Parece desactualizado: no se recalcula cuando cambia el
precio. `unit_price_mismatch` marca esos casos.

**C3. Corrección de "kg" en lugar de "g"** (Aldi, 6 productos).
"Müsli 750 kg" a CHF 3.29, "M&M's Cookie Dough 675 kg", "Surimi-Sticks 200 kg". Un tamaño
de 50 kg o más se interpreta como gramos y se marca con `size_corrected`.
*Justificación:* ningún producto de supermercado pesa 50 kg. El propio precio por unidad
de Aldi para esos productos es absurdo (CHF 0.01/kg), lo que confirma el error de origen.

**C4. Categoría de producto.**
- *Aldi:* el crawl recorre las categorías superiores, pero 10 de ellas son campañas o temas
  y no tipos de producto ("Aktionen", "Weihnachten", "Grillen", "Gourmet", "Saveurs
  Suisses"…; `ALDI_THEMES`). `category_main` es la ruta propia del producto si no es un
  tema; si lo es, la primera categoría no temática en la que apareció el producto; si
  tampoco hay, el segundo nivel de la ruta temática cuando ese nivel es una categoría de
  producto ("Vegetarisch & Vegan > Vorräte" → "Vorräte"). Si no se cumple nada, queda
  NULL: 213 productos, casi todos dulces de Navidad y artículos en promoción.
  `category_theme_only` los marca.
- *Volgshop:* los nombres a lo largo de la ruta más profunda del árbol de categorías
  (`category_main`, `category_sub`, `category_path`).

Las categorías de las dos tiendas **no** se armonizan aquí (N3).

**C5. Etiquetas.**
- `is_organic`: "Bio" como palabra en la marca, el nombre o las etiquetas de Volg, o la
  categoría "Retour aux sources (Bio)" de Aldi. Aldi 152, Volgshop 12.
- Aldi, a partir de los badges de la tienda: `is_vegan` (223), `is_vegetarian` y
  `storage` (frozen, chilled o ambient).
- Volgshop: `own_brand_volg` cuando el nombre empieza por "Volg " (51).

**C6. Tabla nutricional de Volgshop.**
El texto libre se vuelve a parsear en la limpieza con la versión actual del parser
(`scraping.parse_volg_nutrition`), así que una corrección del parser no obliga a volver
a hacer scraping. La base de referencia es 100 g/ml cuando el texto menciona "100 g".
Esto incluye las tablas de dos columnas (100 g y porción), donde el primer valor
corresponde a los 100 g. Luego se aplican los mismos controles que en F7 de OFF:
nutrientes entre 0 y 100 g, energía entre 0 y 3800 kJ, grasa saturada ≤ grasa y
azúcares ≤ carbohidratos, suma de macros ≤ 105 g, y la verificación de kJ/kcal contra la
energía calculada a partir de los macros.

**A diferencia de OFF, el producto no se elimina** si su tabla falla: los valores pasan
a NULL y `nutrition_status` dice por qué.

| `nutrition_status` | Productos |
|---|---:|
| complete (los 6 nutrientes principales) | 381 |
| incomplete | 32 |
| missing (sin tabla, o el campo tiene ingredientes o minerales del agua) | 28 |
| implausible | 4 |

*Justificación:* en OFF la tabla nutricional es lo único que aporta el producto. Aquí
el precio sigue siendo válido y la nutrición puede venir de OFF en el matching. Los 4
`implausible` son errores de la tienda: kJ y kcal intercambiados (Linzertörtli, almendras
molidas, curry) y un aceite de colza con 54 g de carbohidratos.
Si no hay kJ, `energy_kj` se calcula a partir de las kcal (×4.184), como en C5 de OFF.

**C7. Origen (Volgshop).**
`origin_status` sale del atributo "Produktionsland": Schweiz → `domestic`; Liechtenstein
(también escrito "Lichtenstein", 8 productos) → `domestic`, porque está en la unión
aduanera suiza y no paga arancel de importación; "diverse", "Europa", "EU" o vacío → NULL;
cualquier otro país → `imported`. Resultado: 332 domestic, 94 imported, 19 NULL.
*Ojo:* "Produktionsland" es el país de **fabricación**, no el de origen de los
ingredientes, que es lo que usa `origin_status` en OFF (`origins_tags`). Al comparar H3
entre fuentes hay que tenerlo en cuenta.

## N. Lo que deliberadamente no se hizo

**N1. No se buscó nutrición ni origen para Aldi.** La API no tiene valores nutricionales
(la ficha de detalle solo trae la lista de ingredientes) y deja `countryOrigin` vacío.
Ambos datos tienen que venir del matching con OFF. No se infiere el origen a partir de la
marca "Saveurs Suisses" ni de "Schweizer" en el nombre.

**N2. No hay EAN en ninguna de las dos tiendas.** El matching con OFF tendrá que ser
por marca y nombre (paso 2 del README). Volgshop además no separa la marca del nombre
("ALNATURA FETA 180G"), así que no se extrae una marca en la limpieza.

**N3. No se armonizan las categorías entre tiendas.** Aldi y Volg usan árboles distintos,
y OFF usa su propia taxonomía (PNNS, categories_tags). Una categoría común hace falta
para controlar por categoría en H1, pero se decide en la integración, idealmente a partir
de la categoría OFF de cada producto emparejado.

**N4. No se imputan tamaños ni nutrientes.** Un producto sin tamaño en peso o volumen
sale (F5). Un nutriente que falta queda NULL.

**N5. No se usa el precio por unidad publicado por Volg** como precio (C2): está
desactualizado en ~10 % de los productos.

**N6. Las marcas propias de Aldi no se marcan.** La mayoría de las marcas de Aldi
(Milsani, Le Gusto, Monarc…) son exclusivas, pero no hay una lista oficial, y armarla a
mano sería adivinar. Se deja para el matching, donde la falta de coincidencia en OFF
también lo revela.
