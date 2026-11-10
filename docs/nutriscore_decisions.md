# Nutri-Score calculado: decisiones

Script: [`src/nutriscore.py`](../src/nutriscore.py) (algoritmo y validación) · Se aplica en
[`src/matching.py`](../src/matching.py) al construir `products_matched` (M12 de
[`matching_decisions.md`](matching_decisions.md)) · Validación reproducible con
`python src/nutriscore.py validate` → `data/processed/nutriscore_validation.csv`

Los identificadores (S1, S2…) son propios de este documento.

## Por qué

OFF solo da Nutri-Score a los productos emparejados que tienen una ficha completa. Volgshop
publica su propia tabla nutricional para 381 productos, pero solo 99 tenían Nutri-Score de
OFF. Calcularlo a partir de la tabla agrega 358 productos al análisis de H1 y H2.

| Cadena | Nutri-Score de OFF | Calculado | Total | No aplicable |
|---|---:|---:|---:|---:|
| Volgshop | 99 | 288 | 387 | 10 |
| Aldi | 214 | 51 | 265 | 42 |
| Migros | 226 | 12 | 238 | 4 |
| Coop | 122 | 5 | 127 | 4 |
| Lidl | 32 | 1 | 33 | 0 |
| Denner | 13 | 1 | 14 | 1 |
| **Total** | **706** | **358** | **1 064** | |

## Columnas nuevas en `products_matched`

| Columna | Qué es |
|---|---|
| `nutriscore_grade`, `nutriscore_score` | **Para el análisis.** El de OFF si existe; si no, el calculado |
| `nutriscore_source` | `off` o `computed` |
| `nutriscore_calc_grade`, `nutriscore_calc_score` | Calculado para **todo** producto con tabla completa, también los que tienen grado de OFF (análisis de sensibilidad) |
| `nutriscore_kind` | Categoría del algoritmo: `general`, `cheese`, `red_meat`, `fat`, `beverage`, `water`, `not_applicable`, `unsupported` |
| `nutriscore_category_source` | De dónde sale la categoría: `off_categories` (ficha OFF emparejada) o `retailer_name` (categoría y nombre de la tienda) |

`off_nutriscore_grade` no cambia.

---

## S. Reglas

**S1. Algoritmo 2023.** Es la versión que usa OFF desde 2024, así que los grados calculados
son comparables con los de OFF. Se implementan las tres tablas de puntos (alimentos
generales, bebidas, y grasas/aceites/frutos secos/semillas) y sus límites de grado.
- *Negativos:* energía, azúcares, grasa saturada y sal. En el grupo de grasas se usan la
  energía de la grasa saturada y la proporción saturada/total. En bebidas suman 4 puntos
  si hay edulcorantes no calóricos.
- *Positivos:* proteína, fibra y FVL (fruta, verdura y legumbres).
- *Agua:* siempre A.

**S2. Regla de la proteína.** Si los puntos negativos llegan a 11 (7 en el grupo de grasas),
la proteína no cuenta, salvo en el queso. En la carne roja la proteína tiene un tope de 2
puntos. Los embutidos se tratan como alimento general: en OFF, ese tope casi nunca cambia
el puntaje de jamones y salchichas.

**S3. Categoría del algoritmo, desde las etiquetas OFF.** La regla se dedujo de los datos:
para cada producto se probó qué categoría reproduce exactamente el puntaje de OFF, y se
vio qué etiquetas lo predicen.
- *Grasas:* `en:fats`, `en:seeds` y `en:nuts`, salvo castañas, mezclas de frutos secos y
  mezclas con fruta seca. **Ojo:** en la taxonomía de OFF, `en:seeds` incluye las legumbres
  secas y los cereales en grano (arroz, maíz). OFF los puntúa con la tabla de grasas, y aquí
  se hace lo mismo para que los grados sean consistentes con los suyos.
- *Bebidas:* `en:beverages`, salvo preparaciones en polvo y jarabes.
- *Queso:* `en:cheeses`. *Agua:* `en:waters` sin sabor.
- *No aplicable:* se respeta el `not-applicable` de OFF (café, té, especias, sal, vinagre,
  chicles, suplementos).

**S4. FVL cuando la ficha no lo da.** Se usa 100 % para jugos de fruta y verdura, aceites de
oliva, colza y nuez, fruta y verdura fresca, setas, dátiles y bayas. En el resto se usa 0 %.
También salió de los datos: las conservas, los congelados, las compotas y la fruta seca
reproducen el puntaje de OFF unas veces con 0 % y otras con 100 %, así que no se les
asigna 100 %.

**S5. Productos sin ficha OFF (Volgshop): categoría desde la tienda y el nombre.**
- *Bebida:* subcategoría "Alkoholfreie Getränke", o bebidas lácteas de la subcategoría de
  leche (desde 2023 la leche cuenta como bebida). No cuentan la crema, la leche condensada
  ni los polvos (Caotina, Ovomaltine).
- *Agua:* nombres de aguas minerales sin sabor.
- *Queso:* subcategoría "Käse & Frischkäse".
- *Grasas:* mantequilla, margarina, crema, aceites, frutos secos y semillas. Siguiendo S3,
  también arroz, lentejas, garbanzos, judías y maíz.
- *No aplicable:* sal, vinagre, levadura, mezclas de especias, Aromat, café soluble, té y
  chicles. *Sin calcular (`unsupported`):* jarabes, porque OFF los puntúa ya diluidos y la
  etiqueta da el concentrado.
- *FVL:* la suma de los porcentajes declarados en la lista de ingredientes de las frutas,
  verduras y legumbres (las papas no cuentan). Si la lista no da porcentajes, 100 % para
  verduras, ensaladas, jugos y conservas vegetales según el nombre, y 0 % para el resto.
- *Edulcorantes:* detectados en la lista de ingredientes (aspartamo, acesulfamo,
  sucralosa, esteviol, E950–E969).

**S6. Prioridad.** El grado de OFF tiene prioridad sobre el calculado. Para un producto de
Volgshop emparejado, la categoría sale de su ficha OFF (S3) y la nutrición de la tabla de
Volgshop (M8).

## V. Validación

**V1. Implementación contra OFF** (42 232 productos suizos con grado de OFF):

| Categoría | Productos | Grado igual (con FVL de OFF) | Grado igual (sin FVL de OFF) |
|---|---:|---:|---:|
| General | 32 485 | 98.0 % | 94.9 % |
| Bebidas | 3 779 | 98.3 % | 92.3 % |
| Grasas, frutos secos, semillas | 2 720 | 92.1 % | 92.2 % |
| Queso | 2 588 | 99.6 % | 99.4 % |
| Carne roja | 468 | 100 % | 100 % |
| Agua | 192 | 83.9 % | 83.9 % |
| **Total** | 42 232 | **97.7 %** | **94.8 %** |

"Sin FVL de OFF" usa solo la regla S4, como para un producto del que no se conoce el FVL.
La diferencia viene de productos en los que OFF estimó el FVL a partir de los ingredientes
(bebidas de soja, platos de verdura).

**V2. Ruta de Volgshop contra OFF.** Se aplican las reglas S5 a los 86 productos de
Volgshop que tienen grado de OFF y tabla propia, y se compara con ese grado:

| Tabla nutricional usada | Grado igual | A un grado o menos |
|---|---:|---:|
| La de Volgshop | 86 % | 97 % |
| La de OFF para el mismo producto | 91 % | 100 % |

Las reglas S5 explican unos 9 puntos de error. Los otros 5 vienen de que la tabla de
Volgshop y la de OFF no coinciden para el mismo producto (Zwieback, Camembert), lo cual no
es un error del cálculo.

Errores que quedan con las reglas S5: jugos con FVL dudoso en OFF (Ramseier Süessmost
tiene E en OFF; con 90 % de jugo el algoritmo da C), algunos snacks de frutos secos
(Nic Nac's) y el jugo de limón (OFF lo trata como bebida).

## Limitaciones

- **El grado calculado es una estimación.** Para el análisis principal,
  `nutriscore_source` permite comparar los resultados con y sin los grados calculados
  (análisis de sensibilidad).
- **El FVL es el componente más incierto.** Una estimación errónea mueve como mucho 5
  puntos (6 en bebidas), lo que suele ser un grado.
- **Productos sin categoría en OFF.** Los 51 de Aldi y los 19 de Migros, Coop, Lidl y Denner
  que se calcularon tienen ficha OFF sin grado. Casi siempre la ficha no tiene categoría, y
  entonces se tratan como alimento general.
