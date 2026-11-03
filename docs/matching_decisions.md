# Matching tiendas ↔ Open Food Facts: decisiones

Script: [`src/matching.py`](../src/matching.py) · Resultados en
`data/processed/matches.parquet` (mejor candidato OFF por producto, con score) y
`data/processed/products_matched.parquet` (un registro por producto: precio + nutrición).
Muestra de revisión manual: `data/processed/match_review_sample.csv`.

Los identificadores (M1…M10) aparecen como comentarios en el código. Los candidatos OFF
son el subconjunto suizo limpio y, solo para Aldi, las fichas alemanas y austriacas de
las marcas que vende Aldi (E6 de [`off_cleaning_decisions.md`](off_cleaning_decisions.md)).

## Resumen

| | Aldi | Volgshop |
|---|---:|---:|
| Productos limpios | 1 577 | 445 |
| Emparejados con OFF | **273** (17.3 %) | **122** (27 %) |
| con ficha suiza | 100 | 122 |
| con ficha DE/AT (M10) | 173 | — |
| Con nutrición (tienda u OFF) | 273 | 395 |
| con nutrición de la tienda | 0 | 381 |
| con nutrición de OFF | 273 | 14 |
| Con Nutri-Score (de OFF) | 214 | 99 |
| Con origen | 24 | 427 |
| Matches "probables", no usados (M9) | 38 | 4 |

Antes de M9 y M10, Aldi tenía 103 matches (6.5 %).

**Validación**
- *Contra la nutrición de Volgshop:* de los 108 matches aceptados de Volgshop que también
  tienen tabla propia completa, 97 (90 %) coinciden con OFF. Criterio de coincidencia:
  energía ±12 % (mín. 40 kJ); grasa, azúcares y proteína ±20 % (mín. 1.5 g). Los 11 que
  no coinciden tienen todos el mismo nombre en ambas fuentes, y la diferencia viene de un
  error de datos (pasta Bschüssig con 361 "kJ" en Volg, que son kcal; Magerquark de Emmi
  con 98 kJ en OFF) o de una receta distinta (Balisto, Stimorol). El 90 % es entonces una
  cota inferior de la precisión.
- *Revisión manual:* en una muestra aleatoria de 50 matches aceptados por tienda (semilla
  42), los 100 son el mismo producto. En una segunda muestra de 50 matches nuevos de Aldi
  (fichas DE/AT y rescates por ingredientes), los 36 matches por nombre contra fichas DE/AT
  son correctos, y solo 6 de los 10 rescatados por ingredientes lo son. Por eso los
  rescates no se usan (M9). Ambas revisiones las hizo Claude Code (ver
  `docs/ai_usage.md`). El archivo `match_review_sample.csv` tiene las columnas `correct` y
  `comment` vacías para que el equipo haga su propia revisión.

---

**M1. Bloqueo por marca.** Solo se comparan productos de la misma marca.
- *Aldi* publica la marca por separado.
- *Volgshop* no la publica, así que se toma la marca OFF más larga (1–3 palabras) con la
  que empieza el nombre ("Hilcona Pizza Prosciutto…" → "hilcona"). Para eso solo cuentan
  las marcas OFF de 3 letras o más y con al menos 2 productos.
- Una marca OFF cuenta si aparece en cualquier posición del campo `brands`, no solo en la
  primera.

*Justificación:* sin EAN, la marca es lo que más reduce los falsos positivos, y deja unos
cientos de candidatos por producto en vez de 73 000. De los 1 532 productos de Aldi con
marca, 1 375 tienen esa marca en OFF.

**M2. Normalización del nombre.** Minúsculas, sin acentos (ü → u, ß → ss), sin tamaños
("500g", "6x50cl"), sin puntuación y sin la propia marca. Se quitan palabras sin valor
identificador ("mit", "und", "de", "bio", "classic", "original"…).

**M3. Score de nombre: cobertura en ambas direcciones.**
`score = media armónica de (fracción de palabras de la tienda presentes en OFF, fracción de
palabras de OFF presentes en la tienda)`, de 0 a 100. Dos palabras coinciden si su
similitud de caracteres (`rapidfuzz.fuzz.ratio`) es de al menos 85, lo que absorbe
plurales y erratas ("Pangasiusfilet" ↔ "Pangasiusfilets", "Muesli" ↔ "Müsli").
- *Por qué no `token_set_ratio`:* da 100 cuando un nombre está contenido en el otro, por
  ejemplo "Müsli-Riegel, Schoko" → "Schoko Müsli".
- *Por qué no se acepta la contención de palabras compuestas:* la primera versión aceptaba
  que una palabra contuviera a la otra, para compuestos alemanes como "Knuspermüesli" ↔
  "Müesli". La revisión manual mostró que justo eso oculta el modificador que distingue
  los productos: "Magermilch" → "Milch 3,5 %", "Senf halbscharf" → "Senf scharf",
  "Eierravioli" → "Ravioli". Se eliminó, a costa de algunos aciertos.

**M4. Aceptación.** Un match se acepta si:
- el score es ≥ 90, **o**
- el score es ≥ 75, el tamaño del paquete coincide (±10 %) **y** todas las palabras del
  nombre de la tienda están en OFF.

*Justificación de la tercera condición:* con score 80, lo que falta suele ser justo la
variante del lado de la tienda ("Red Bull **Sugarfree**" → "Red Bull Energy Drink",
"Mix-it **Waldbeer**" → "Mix it"), y la nutrición no coincide. Exigir cobertura completa
del lado de la tienda subió la coincidencia nutricional de 86 % (95/111) a 88 % (95/108)
y eliminó esos casos, pero también descarta matches correctos en los que la tienda añade una palabra
genérica ("Ziegenkäse **Scheiben**, Bockshornklee", "**Instantkaffee** Gold Finesse").
Se prefirió la precisión: un match falso mete una nutrición equivocada en la regresión;
un match perdido solo reduce la muestra.

**M5. Desempate entre candidatos:** primero los aceptados, luego score, ficha suiza antes
que DE/AT (es la receta que se vende en Suiza), similitud de ingredientes, tamaño
coincidente, producto etiquetado con la tienda en OFF y número de escaneos en OFF
(`unique_scans_n`).

**M6. Marcas genéricas.** "Bio", "No brand" y marcas que son palabras comunes usadas por
varias empresas ("American", "BBQ", "Halloween", "Gourmet", "Premium") no bastan como
bloqueo. Para ellas solo se consideran productos OFF etiquetados con la propia tienda.
*Caso real:* "AMERICAN Sandwichtoast" de Aldi casaba con "American Toast" de Jowa (Migros).

**M7. Sin marca utilizable: solo productos OFF de la tienda, regla estricta.** Si el
producto no tiene marca, o su marca no está en OFF, se compara con los productos OFF
etiquetados con esa tienda (`store_aldi`/`store_volg` o marca propia) cuya marca también
vende la tienda. Se exige score ≥ 90 **y** tamaño coincidente.
*Caso real:* sin la condición de marca, "Schwarzwälder Schinken" de Aldi casaba con un
producto K-Classic (Kaufland) que en OFF estaba mal etiquetado como de Aldi.

**M8. Tabla combinada (`products_matched`).**
- Nutrición: la tabla propia de Volgshop si está completa (C6 de
  `retail_cleaning_decisions.md`); si no, la de OFF; si tampoco, NULL. La columna
  `nutrition_source` indica de dónde sale.
- Del producto OFF se copian Nutri-Score, NOVA, categoría (`main_category`, PNNS) y origen.
  La categoría PNNS (`off_pnns_group_1/2`) es la candidata a categoría común entre tiendas
  (N3 de la limpieza).
- Precio, tamaño y categoría vienen siempre de la tienda.
- `off_scope` dice si la ficha OFF es suiza (`ch`) o alemana/austriaca (`de_at`).

**M9. Ingredientes: sirven para vetar un match, no para crearlo.**
Aldi publica la lista de ingredientes en su ficha de detalle (`scraping.py aldi-details`:
903 de 1 575 productos), y Volgshop en el atributo "Zutaten". OFF tiene la suya
(`off_ingredients.parquet`, E7). La similitud se calcula igual que el score de nombre
(M3), sobre las palabras de la lista sin números ni palabras de relleno. Solo se comparan
listas en alemán: el export de OFF no indica el idioma, así que se detecta contando
palabras frecuentes de cada idioma; también hay listas de Aldi en italiano.

*Calibración*, en Aldi con 50 matches casi seguros (score 100 y mismo tamaño) frente a
32 920 pares de la misma marca y productos distintos (score de nombre ≤ 20):

| Similitud ≥ | Matches seguros | Productos distintos |
|---:|---:|---:|
| 30 | 98 % | 26.6 % |
| 40 | 86 % | 14.0 % |
| 70 | 44 % | 1.2 % |

- *Veto:* si la similitud es menor que 30, el match se rechaza aunque el nombre coincida.
  Con 40 se habría perdido el 14 % de los matches correctos, porque Aldi suele abreviar
  sus listas ("Gnocchi" tiene similitud 14 con su propio producto en OFF).
- *Rescate:* un candidato con score de nombre 60–89 y similitud ≥ 70 queda como
  **probable** (`probable = true` en `matches.parquet`) y **no** se usa en
  `products_matched`. En Volgshop, 11 de 13 de esos casos coincidían en nutrición, pero en
  la revisión de Aldi solo 6 de 10 eran el mismo producto. Los errores son variantes que
  comparten la lista de ingredientes en otra proporción ("Weichkäse **Leicht**" → la
  versión normal, "Tortilla Wraps **Weizen**" → "Vollkorn"). Quedan disponibles para un
  análisis de sensibilidad.

**M10. Fichas alemanas y austriacas para Aldi.** Muchas marcas propias de Aldi Suisse
(Golden Bridge, Cucina, Snack Fun, Asia Green Garden, My Vay…) son las mismas de Aldi Süd y
Hofer, y en OFF sus fichas están etiquetadas para Alemania o Austria, no para Suiza. Las
fichas DE/AT siguen la misma regla de aceptación que las suizas.
*Justificación:* `cross_country_check.parquet` compara pares de fichas OFF con la misma
marca, nombre (score 100) y tamaño. Coinciden en nutrición en el 67 % de los pares
suizo–suizo (279/416), el 66 % de los DE/AT–DE/AT (555/843) y el 69 % de los
suizo–DE/AT (263/382). Usar una ficha de otro país no añade desacuerdo. El ~67 % mide el
ruido de emparejar solo por nombre entre fichas OFF con nombres genéricos, no el país, y
es menor que el 90 % de M4 porque aquí no hay control de tamaño ni de cobertura por
tienda. Exigir ingredientes solo a las fichas DE/AT habría sido una regla sin base. Las
fichas suizas tienen prioridad en el desempate (M5). Volgshop no usa fichas DE/AT: casi
todo su surtido es suizo y tiene nutrición propia.

## Limitaciones

**L1. La cobertura de Aldi sigue siendo baja (17.3 %).** Con las fichas DE/AT (M10) pasó de
103 a 273 productos, pero las marcas exclusivamente suizas no tienen fichas en ningún
país: Saveurs Suisses (117 productos, 0 matches) y Panetteria (62, 0). También la marca
"Bio" (104, 8). El resultado sigue sesgado hacia marcas de fabricante y marcas
compartidas con Aldi Süd. Para cubrir las suizas exclusivas hace falta capturar etiquetas
a mano.

**L2. Idioma.** El nombre OFF está en el idioma principal de la ficha, que en Suiza a menudo
es francés ("Soupe de pâtes ABC" frente a "Beutelsuppe, ABC-Suppe"). Esos casos no se
emparejan.

**L3. Variantes de receta.** Un mismo nombre puede tener otra receta en otro país o año
(Balisto, Stimorol en la validación). Para Volgshop pesa poco, porque se usa la tabla
propia.

**L4. El Nutri-Score solo existe para productos emparejados.** Los 381 productos de
Volgshop con tabla propia completa solo tienen Nutri-Score si también se emparejaron
(100). Calcularlo a partir de los nutrientes daría Nutri-Score a todos, pero requiere
datos que Volg no publica (porcentaje de frutas, verduras y legumbres) y la categoría
especial del algoritmo (bebida, queso, grasa).
