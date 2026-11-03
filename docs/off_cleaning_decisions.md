# Open Food Facts: decisiones de extracción, filtrado y limpieza

Script: [`src/openfoodfacts.py`](../src/openfoodfacts.py) · Conteos reproducibles en
[`data/processed/off_ch_cleaning_log.csv`](../data/processed/off_ch_cleaning_log.csv) ·
Procedencia del snapshot en [`data/processed/off_ch_metadata.json`](../data/processed/off_ch_metadata.json)

Los identificadores (E1, F1, C1, N1…) aparecen como comentarios en el código, así que
cada regla se puede rastrear hasta la línea que la implementa.

- **E**: extracción, es decir, qué se descarga y qué entra al subconjunto suizo.
- **F**: filtros que **eliminan filas**.
- **C**: limpieza y transformaciones que **no eliminan filas**.
- **N**: cosas que deliberadamente **no** se hicieron.

## Resumen del embudo

Snapshot del export descargado el 2026-11-02.

| Regla | Qué elimina | Eliminadas | Quedan |
|---|---|---:|---:|
| E3 | Productos no etiquetados como vendidos en Suiza | ~4.78 M | 107 342 |
| F1 | Código que no es un EAN-8/EAN-13 válido | 1 775 | 105 567 |
| F2 | Código duplicado | 1 | 105 566 |
| F3 | Bebidas alcohólicas | 1 818 | 103 748 |
| F4 | Alimentos infantiles | 290 | 103 458 |
| F5 | No alimentos | 117 | 103 341 |
| F6 | Tabla nutricional incompleta | 29 025 | 74 316 |
| F7a | Nutriente fuera de 0–100 g | 25 | 74 291 |
| F7b | Energía fuera de 0–3800 kJ | 4 | 74 287 |
| F7c | Grasa saturada > grasa, o azúcares > carbohidratos | 123 | 74 164 |
| F7d | Suma de macronutrientes > 105 g | 230 | 73 934 |
| F7e | Energía inconsistente | 196 | **73 738** |

De los 73 738 productos finales, 42 230 tienen Nutri-Score A–E; 12 534 se pueden
asignar a Migros (7 185 con Nutri-Score) y 9 561 a Coop (5 873 con Nutri-Score).

---

## E. Extracción

**E1. Fuente: el export CSV completo de OFF, no la API ni el parquet de Hugging Face.**
URL: `static.openfoodfacts.org/data/en.openfoodfacts.org.products.csv.gz` (~1.5 GB).
*Justificación:* la API de búsqueda devuelve como máximo 100 productos por página y
limitó nuestras peticiones (503 y luego 401), así que no permite obtener ~100 000 productos.
El parquet de Hugging Face pesa ~8 GB y también limitaba las lecturas parciales. El CSV es
el volcado oficial y completo, se descarga con una sola petición y es lo que OFF recomienda
para uso masivo. La descarga se identifica con un User-Agent que nombra el proyecto, como
pide OFF.

**E2. Solo se conservan 37 de las ~210 columnas.**
Se guardan identificador, nombre, marca, cantidad, tiendas, categorías, Nutri-Score, NOVA,
origen, etiquetas, los nutrientes por 100 g que usa el análisis y metadatos de calidad.
*Justificación:* las demás columnas (imágenes, URLs, aditivos, vitaminas y minerales,
ácidos grasos específicos, alérgenos) no intervienen en ninguna hipótesis. Quitarlas
reduce el archivo de 1.5 GB a 9 MB, lo que permite versionarlo en git.

**E3. Filtro de país: `countries_tags` contiene `en:switzerland`.**
*Justificación:* la pregunta de investigación trata del mercado suizo. Se compara contra
la etiqueta normalizada (`en:switzerland`) y no contra el texto libre `countries`, que
mezcla idiomas ("Suisse", "Schweiz", "Svizzera"). Se usa coincidencia exacta del tag
dentro de la lista, no `LIKE`, para no capturar subcadenas.
*Nota:* 21 248 de los productos finales también están etiquetados en otros países. No se
excluyen, porque un producto vendido en Suiza y en Alemania sigue siendo un producto
suizo para nuestro análisis.

**E4. Todo se lee como texto y el tipado se hace después.**
El CSV usa tabulador como separador y no usa comillas (`quote=''`).
*Justificación:* si DuckDB adivinara los tipos, una sola fila mal formada podría descartar
o corromper una columna entera. Con `quote=''` se evita que una comilla suelta dentro de un
nombre de producto "se trague" las líneas siguientes. Las filas que no se pueden parsear
se registran con `store_rejects`; en este snapshot fueron 0 de 4.89 M líneas.

**E5. El subconjunto suizo crudo (`data/raw/off_ch_raw.parquet`) se versiona en git.
El CSV de 1.5 GB no.**
*Justificación:* OFF se edita a diario, así que volver a descargar no reproduce los mismos
datos. Versionar el extracto congela el snapshot que usamos. El CSV completo supera el
límite de 100 MB de GitHub. El SHA-256 del extracto queda guardado en el JSON de metadatos.

## F. Filtros (eliminan filas)

**F1. El código debe ser un EAN-8 o EAN-13 válido, con dígito verificador correcto.**
Antes de validar se normaliza: UPC-A de 12 dígitos → se antepone `0`; GTIN-14 que empieza
con `0` → se quita ese `0` (ver C3).
- Se eliminan 889 códigos de longitud no estándar. La mayoría son de 24 dígitos, como
  `2776108499298…000260`: son etiquetas de báscula de Coop/Migros que llevan el precio o
  el peso codificado, así que el mismo producto genera un código distinto en cada paquete.
- Se eliminan 886 códigos con dígito verificador inválido, lo que indica errores de
  captura o de lectura del escáner.

*Justificación:* el EAN es la llave principal para unir OFF con los datos de las tiendas
(paso 1 del matching). Un código inválido no puede unirse por EAN y probablemente
identifica mal al producto.

**F2. Códigos duplicados: se conserva la entrada modificada más recientemente.**
Solo había 1 caso (`7613269480952`, "Croquets").
*Justificación:* el código debe ser llave primaria en la base de datos. La versión más
reciente refleja las correcciones de la comunidad.

**F3. Se excluyen las bebidas alcohólicas (`en:alcoholic-beverages`).**
*Justificación:* el Nutri-Score no se calcula para el alcohol, y su precio en Suiza depende
sobre todo de impuestos especiales (Alkoholsteuer), no de su calidad nutricional. Incluirlas
mezclaría un efecto fiscal con la "prima de salud" que queremos medir.

**F4. Se excluyen los alimentos infantiles** (categorías `en:baby-foods`, `en:baby-milks`,
`en:infant…` o grupo PNNS "Baby foods").
*Justificación:* tienen su propia regulación de composición, no reciben Nutri-Score, y su
perfil nutricional responde a necesidades de bebés, no de adultos.

**F5. Se excluyen los no alimentos** (comida para mascotas, cosméticos, productos de hogar
que se colaron en OFF).
*Justificación:* están fuera del alcance del estudio y sus valores nutricionales no tienen
sentido.

**F6. Se exigen los 6 nutrientes principales por 100 g: energía, grasa, grasa saturada,
azúcares, proteína y sal.** Es el filtro que más filas elimina (29 025).
*Justificación:* son las variables del clustering (k-means) y de la regresión, y los
insumos del Nutri-Score. Un producto sin ellos no aporta nada a la pregunta de
investigación. No se imputan (ver N2).
- La fibra **no** se exige, porque falta en el 46 % de los productos que quedan (en la UE
  no es obligatoria en la etiqueta). Exigirla eliminaría la mitad de la muestra.
- Los carbohidratos tampoco se exigen; solo faltan en 20 filas.
- *Efecto secundario:* este filtro también elimina casi todas las entradas no editadas
  desde 2025 o antes, que en el export no traen nutrientes (son fichas viejas incompletas).
  Por eso el dataset final es, en la práctica, de entradas revisadas en 2024–2026.

**F7. Se eliminan tablas nutricionales físicamente imposibles o internamente
inconsistentes.**
Se elimina la fila completa y no solo el valor: el Nutri-Score de OFF se calcula con esos
mismos números, así que si la tabla está mal, la calificación también.
- **F7a** (25 filas): cualquier nutriente en gramos < 0 o > 100 g por 100 g. Es imposible
  por definición. Ejemplos reales: grasa = 2800, sal = 97 500, que son errores de unidad.
- **F7b** (4 filas): energía > 3800 kJ/100 g. La grasa pura aporta ~3700 kJ, que es el
  máximo físico de un alimento; se deja un 3 % de margen.
- **F7c** (123 filas): grasa saturada > grasa o azúcares > carbohidratos. Una parte no
  puede ser mayor que el total. Se tolera 0.5 g por el redondeo de las etiquetas.
- **F7d** (230 filas): grasa + carbohidratos + fibra + proteína + sal > 105 g. Más de
  100 g de componentes en 100 g de producto es imposible; el margen de 5 g es el mismo
  umbral que usa OFF en su propia verificación de calidad.
- **F7e** (196 filas): energía inconsistente. Cuando los kJ y las kcal declarados no
  cuadran (kJ/kcal fuera de 3.6–4.8 en productos con más de 40 kcal), se compara el kJ
  con la energía calculada a partir de los macronutrientes (grasa 37, carbohidratos 17,
  proteína 17 y fibra 8 kJ/g). La fila solo se elimina si el kJ también falla por más
  del 20 %.
  *Justificación:* de 3 742 casos con kJ/kcal discordantes, en el 93 % el kJ coincide con
  los macros y lo que está mal son las kcal (típicamente kcal capturadas como kJ, ratio
  ≈ 1.0). Eliminarlos todos habría tirado 2 900 productos válidos. Como usamos los kJ
  (C5), basta con que los kJ sean confiables. El umbral de 40 kcal evita falsos
  positivos por redondeo en productos casi sin energía, como bebidas light o especias.

## C. Limpieza y transformaciones (no eliminan filas)

**C1. Tipado.** Los nutrientes, la cantidad, la completitud y los escaneos pasan a número
con `try_cast`, que convierte en NULL lo que no sea numérico en lugar de fallar. Las
fechas pasan de epoch a `TIMESTAMP` en UTC.
*Justificación:* cuando un valor no es numérico es mejor perder ese valor que perder el
proceso completo.

**C2. Texto:** se recortan los espacios, se colapsan los espacios múltiples y una cadena
vacía se convierte en NULL (nombre, nombre genérico, marcas, cantidad, tiendas).
*Justificación:* así el matching por nombre (paso 2) no falla por espacios invisibles, y
"vacío" y "desconocido" significan lo mismo.

**C3. Normalización de códigos a EAN-13/EAN-8.** El valor original se conserva en
`code_raw`.
*Justificación:* las tiendas suelen publicar EAN-13. Sin normalizar, un UPC de 12 dígitos
no uniría con su equivalente de 13.

**C4. Nutri-Score y NOVA:** solo se aceptan `a`–`e` y `1`–`4`. "unknown" y
"not-applicable" se convierten en NULL. `nutriscore_score` se pone en NULL cuando no hay
calificación válida. Se agrega `has_nutriscore` para filtrar fácilmente.
*Justificación:* los valores centinela como cadena se colarían como una categoría más en
un `GROUP BY` o en una prueba chi-cuadrada.

**C5. Energía en kJ.** Se usa el kJ declarado y, si falta, kcal × 4.184. Las columnas de
energía declarada se descartan después de F7e.
*Justificación:* el Nutri-Score usa kJ y es la unidad de la etiqueta en Suiza y la UE.
Una sola columna de energía evita colinealidad en la regresión.
- Se usa **sal** y no sodio: en OFF uno se calcula a partir del otro (sal = sodio × 2.5),
  así que el sodio es redundante.

**C6. Tamaño del envase (`product_quantity`).** Se pone en NULL si es ≤ 0 g o > 10 kg, y
se agrega `product_quantity_unit` (`ml` si el texto de cantidad indica ml/cl/dl/l; `g` en
los demás casos).
*Justificación:* hay 197 valores de 0, que vienen de textos como "1pcs" o "25 sachets", y
17 mayores a 10 kg ("1000 kg", "100 x 550 g"), que son formatos mayoristas y no de
supermercado. Se pone NULL en lugar de eliminar la fila porque el tamaño puede venir de
la tienda al hacer el matching. La unidad importa porque "por 100 g" y "por 100 ml" no
son comparables sin densidad. OFF ya convierte litros a ml y kg a g en
`product_quantity` (verificado: "1.5L" → 1500, "150 cl" → 1500).

**C7. Marca principal (`brand_main`):** la primera marca de la lista, en minúsculas, con
guiones convertidos a espacios. `brands` se conserva completo.
*Justificación:* sirve para el matching difuso (marca + nombre) y unifica variantes como
"M-Classic", "M Classic" y "m-classic".

**C8. `code_is_internal`:** EAN-13 que empieza con `2` (rango GS1 de circulación
restringida). Son 9 707 productos y **no se eliminan**.
*Justificación:* son códigos internos de tienda (Migros los usa en productos frescos y de
panadería, con prefijo 21). No son únicos a nivel global, pero sí dentro de la cadena que
los emite, así que todavía pueden unirse con los datos de esa cadena. La bandera permite
excluirlos si el matching produce colisiones.

**C9. Cadena minorista (`at_migros`, `at_coop`, `at_denner`, `at_aldi`, `at_lidl`,
`at_volg`).** Hay dos fuentes de evidencia y se guardan por separado (`store_*` y
`own_brand_*`); `at_*` es la unión de ambas.
1. **Campo `stores`** (texto libre): se usan patrones explícitos por cadena. Se incluyen
   los formatos del mismo grupo (migrolino, Coop Pronto, Coop City) y se excluyen
   "Aldi Süd"/"Aldi Nord" (Alemania), "Biocoop" (cadena francesa) y "coopérative".
2. **Marca propia exclusiva**: M-Classic, M-Budget, Migros Bio, Migros Sélection,
   Anna's Best, V-Love, TerraSuisse y Optigal → Migros. Naturaplan, Prix Garantie,
   Qualité & Prix, Karma, Betty Bossi, Fine Food y Naturafarm → Coop. Denner → Denner.
   Volg → Volg.

*Justificación:* `stores` solo está lleno en el 14 % de las fichas. Con la marca propia,
Migros pasa de 8 003 a 12 534 productos y Coop de 1 686 a 9 561. Las marcas propias
solo se venden en su cadena, así que la inferencia es casi segura.
*Decisiones conservadoras:*
- **No** se incluyen marcas industriales de Migros (Frey, Jowa, Midor, Bischofszell) porque
  también producen para terceros y se venden en otros canales.
- Para Aldi y Lidl solo se usa `stores`, porque sus marcas (Milbona, Milfina…) se venden
  igual en Alemania y Austria y no prueban que el producto esté en la tienda suiza.
- **Limitación:** `at_* = false` significa "sin evidencia", no "no se vende ahí".

**C10. `is_organic`:** la fila tiene `en:organic`, `en:eu-organic`, `en:bio-suisse` o un
código de certificador bio (`en:xx-bio-NNN`).
*Justificación:* la regresión incluye una variable de producto orgánico (README). OFF
etiqueta lo bio de varias formas y se aceptan todas las que implican una certificación.

**C11. `origin_status`:** `domestic` si todos los orígenes son Suiza, `imported` si
ninguno lo es, `mixed` si hay de ambos y NULL si no hay dato.
*Justificación:* es la variable de H3 (prima por importación).
*Decisiones:*
- Se usa `origins_tags` (origen de los ingredientes) y no `manufacturing_places_tags`
  (lugar de fabricación), porque son conceptos distintos. El lugar de fabricación se
  conserva por si se necesita después.
- **Limitación importante:** solo el 8 % de los productos finales tiene origen. H3
  probablemente necesite el origen que publican las tiendas (Coop y Volg lo muestran).

**C12. Listas como listas.** Categorías, etiquetas, orígenes, lugares de fabricación y
países se guardan como `LIST` en el parquet. En el CSV se unen con `|`.
*Justificación:* así se puede filtrar por tag sin tener que analizar el texto con
expresiones regulares. Se usa `|` y no `,` para no romper el separador del CSV.

## N. Lo que deliberadamente NO se hizo

**N1. No se recalcula el Nutri-Score; se usa el de OFF.**
*Justificación:* OFF lo calcula con el algoritmo oficial vigente (versión 2023), que
incluye la proporción de frutas, verduras y legumbres estimada a partir de los
ingredientes, un dato que no tenemos limpio. Recalcularlo sería menos exacto.

**N2. No se imputan nutrientes faltantes.**
*Justificación:* imputar la variable que se quiere explicar o agrupar inventaría señal.
La fibra (46 % faltante) se deja en NULL; si el modelo la necesita, la decisión se toma
y documenta en el notebook de modelado.

**N3. No se filtra por antigüedad de la ficha.**
*Justificación:* el 88 % del extracto suizo tiene fecha de modificación de 2026 por
ediciones masivas automáticas de OFF, así que la fecha no indica qué tan reciente es la
información de la etiqueta. En la práctica, F6 ya elimina las fichas viejas vacías.

**N4. No se eliminan productos sin cadena asignada.**
*Justificación:* forman el universo para hacer matching por nombre con los productos
scrapeados de Aldi y Volg, que no publican EAN. Restringir a productos con cadena
conocida antes del matching perdería esos candidatos.

**N5. No se eliminan productos sin Nutri-Score si tienen los nutrientes completos**
(31 508 filas).
*Justificación:* sirven para el clustering, que usa los nutrientes y no la calificación.
H1 y H2 filtran con `has_nutriscore`.

**N6. No se deduplica por nombre o marca.**
*Justificación:* un mismo producto en distintos tamaños tiene EAN y precio por 100 g
distintos. Son SKUs diferentes y el precio por tamaño es parte de lo que se mide.

**N7. No se eliminan valores atípicos estadísticos** (por ejemplo, con z-score).
*Justificación:* F7 elimina solo lo físicamente imposible. Un producto con 90 g de grasa
(aceite) o 99 g de azúcar (azúcar de mesa) es extremo pero real, y esos extremos son
justamente los productos que el Nutri-Score castiga.

## Sesgos conocidos que estas decisiones no corrigen

- OFF lo alimenta una comunidad: las marcas grandes y las marcas propias de Migros/Coop
  están mejor cubiertas que los productos frescos, a granel o de cadenas pequeñas.
- La cobertura por cadena es muy desigual: Migros 12.5 k y Coop 9.6 k, contra Aldi 331,
  Lidl 299 y Volg 181. Para estas cadenas los productos deben venir de nuestro scraping.
- La asignación por cadena (C9) tiene falsos negativos por construcción.
