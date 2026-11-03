# Matching tiendas ↔ Open Food Facts: decisiones

Script: [`src/matching.py`](../src/matching.py) · Resultados en
`data/processed/matches.parquet` (mejor candidato OFF por producto, con score) y
`data/processed/products_matched.parquet` (un registro por producto: precio + nutrición).
Muestra de revisión manual: `data/processed/match_review_sample.csv`.

Los identificadores (M1…M8) aparecen como comentarios en el código.

## Resumen

| | Aldi | Volgshop |
|---|---:|---:|
| Productos limpios | 1 577 | 445 |
| Emparejados con OFF | **103** (6.5 %) | **122** (27 %) |
| Con nutrición (tienda u OFF) | 103 | 395 |
| con nutrición de la tienda | 0 | 381 |
| con nutrición de OFF | 103 | 14 |
| Con Nutri-Score (de OFF) | 79 | 100 |
| Con origen | 12 | 427 |

**Validación**
- *Contra la nutrición de Volgshop:* de los 108 matches aceptados de Volgshop que también
  tienen tabla propia completa, 95 (88 %) coinciden con OFF. Criterio de coincidencia:
  energía ±12 % (mín. 40 kJ); grasa, azúcares y proteína ±20 % (mín. 1.5 g). Los 13 que
  no coinciden tienen todos el mismo nombre en ambas fuentes, y la diferencia viene de un
  error de datos (pasta Bschüssig con 361 "kJ" en Volg, que son kcal; Magerquark de Emmi
  con 98 kJ en OFF) o de una receta distinta (Balisto, Stimorol). El 88 % es entonces una
  cota inferior de la precisión.
- *Revisión manual:* en una muestra aleatoria de 50 matches aceptados por tienda (semilla
  42), los 100 son el mismo producto (revisión hecha por Claude Code, ver
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

**M5. Desempate entre candidatos:** score, después tamaño coincidente, después producto
etiquetado con la tienda en OFF, después número de escaneos en OFF (`unique_scans_n`).

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

## Limitaciones

**L1. La cobertura de Aldi es muy baja (6.5 %).** Las marcas propias con más productos
casi no están en OFF con productos suizos: Saveurs Suisses (117 productos, 0 matches),
Panetteria (62, 0), Bio (104, 2), Le Gusto (85, 5). Muchos productos de marca Aldi
en OFF son de Aldi Süd o Hofer (Alemania y Austria) y no están etiquetados como vendidos
en Suiza. El resultado está sesgado hacia marcas de fabricante (Alpina, Knorr, Barilla,
Ferrero), así que para H2 (diferencias entre tiendas) los 103 productos de Aldi
no representan el surtido de Aldi.

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
