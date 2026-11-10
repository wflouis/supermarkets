# Categoría común entre tiendas: decisiones

Script: [`src/categories.py`](../src/categories.py) · Se aplica en
[`src/matching.py`](../src/matching.py) al construir `products_matched` (M13 de
[`matching_decisions.md`](matching_decisions.md)) · Validación: `python src/categories.py validate`

Los identificadores (K1, K2…) son propios de este documento.

## Por qué

H1 controla por categoría y H2 compara el sobreprecio entre cadenas dentro de cada
categoría. Para eso cada producto necesita una categoría con el mismo significado en todas
las tiendas. Las categorías propias no sirven para esto:
- Aldi agrupa por sección de la tienda ("Vorräte", "Tiefgekühlte Produkte").
- Volgshop mezcla tipos de alimento ("Milchprodukte, Eier & frische Fertiggerichte").
- Migros, Coop, Lidl y Denner no tienen categoría propia (Open Prices no la trae).

La categoría PNNS de OFF sí es común a todas, pero solo existe para los productos
emparejados: solo 95 de los 387 productos de Volgshop con Nutri-Score la tenían.

## Resultado

Entre los 1 064 productos con Nutri-Score, 1 045 (98 %) tienen categoría común: 666 de OFF,
181 por la categoría de la tienda y 198 por el nombre.

| Categoría (PNNS grupo 1) | Aldi | Volg | Migros | Coop | Lidl | Denner | Total |
|---|---:|---:|---:|---:|---:|---:|---:|
| Sugary snacks | 40 | 84 | 68 | 13 | 2 | 4 | 211 |
| Cereals and potatoes | 43 | 58 | 43 | 28 | 7 | 1 | 180 |
| Milk and dairy products | 18 | 63 | 38 | 15 | 7 | 3 | 144 |
| Beverages | 21 | 64 | 21 | 16 | 3 | 0 | 125 |
| Fat and sauces | 35 | 28 | 19 | 19 | 10 | 1 | 112 |
| Fish Meat Eggs | 29 | 36 | 9 | 6 | 2 | 3 | 85 |
| Fruits and vegetables | 29 | 23 | 14 | 7 | 0 | 0 | 73 |
| Salty snacks | 20 | 17 | 9 | 10 | 1 | 1 | 58 |
| Composite foods | 22 | 13 | 12 | 9 | 1 | 0 | 57 |
| Sin categoría | 8 | 1 | 5 | 4 | 0 | 1 | 19 |

Columnas nuevas en `products_matched`:
- `category_common`: la categoría para el análisis.
- `category_common_source`: de dónde sale (`off`, `shop_category` o `name`).
- `category_rules`: la categoría que dan las reglas, para todos los productos (sirve para
  validar y para un análisis de sensibilidad).

---

## K. Reglas

**K1. Prioridad y nivel.** Si el producto tiene PNNS de OFF, se usa ese. Si no, se aplican
las reglas K2–K4. Se usa el **grupo 1** (9 categorías) y no el grupo 2 (unas 40), para que
cada celda cadena × categoría tenga productos suficientes.

**K2. Subcategorías homogéneas de la tienda deciden primero.** Por ejemplo "Softdrinks",
"Käse", "Schokolade", "Müesli & Flakes", las de carne y las de fruta y verdura.
*Justificación:* en la validación, todos sus productos emparejados tienen el mismo grupo
PNNS. Además, el nombre engaña: en "Softdrinks", "Orange, Zero" es un refresco, no una
fruta.

**K3. Palabras clave en el nombre** (alemán, francés e italiano, porque los nombres de OFF
de Migros y Coop suelen estar en francés). Gana la primera regla que coincide. El orden
sigue convenciones de PNNS que no son obvias, y que salieron de los errores de la primera
versión:
- Platos compuestos primero (pizza, lasaña, sándwich, fondue), porque contienen palabras
  de todos los demás grupos.
- Las sopas son "Fruits and vegetables".
- Las legumbres y el tofu son "Cereals and potatoes", igual que las papas fritas de bolsa
  (chips).
- Las salsas, pestos, caldos y condimentos son "Fat and sauces", antes de las palabras de
  verdura o carne que contienen ("Tomatensauce", "Burger sauce").
- Los helados y los postres lácteos son "Milk and dairy products". El chocolate con leche es
  "Sugary snacks", así que la regla de dulces va antes que la de lácteos.
- Los frutos secos, las aceitunas y los pepinillos son "Salty snacks".
- El maíz es "Cereals and potatoes".

**K4. Cualquier otra subcategoría mapeada de la tienda**, si ninguna palabra clave coincide.
Las subcategorías mixtas ("Konserven", "Backzutaten") no se mapean.

## V. Validación

**V1. Contra el PNNS de OFF**, en los productos que tienen ambos:

| Cadena | Productos | Con categoría por reglas | Mismo grupo que OFF |
|---|---:|---:|---:|
| Volg (tienda + nombre) | 97 | 99 % | 93 % |
| Aldi (tienda + nombre) | 202 | 93 % | 88 % |
| Migros (solo nombre) | 217 | 71 % | 88 % |
| Coop (solo nombre) | 119 | 77 % | 90 % |
| Lidl (solo nombre) | 32 | 66 % | 86 % |
| Todas las fichas suizas de OFF (solo nombre) | 39 791 | 67 % | 75 % |

**Ojo:** las reglas se ajustaron mirando los errores de las primeras cinco filas, así que
esas cifras son optimistas. La última fila no se usó para ajustar y es la estimación más
honesta para las reglas de nombre solas. Tiene nombres de todos los idiomas, muchos
genéricos ("Classic", "Bio"). Las reglas de nombre solas solo se usan en 24 productos de
Migros, Coop, Lidl y Denner. Los 289 de Volgshop también usan la subcategoría de la tienda.

## Limitaciones

- **Celdas pequeñas.** Fuera de Aldi, Volgshop, Migros y Coop las celdas son demasiado
  pequeñas para comparar categorías, y algunas de Coop también (Fish Meat Eggs 6, Fruits
  and vegetables 7). H2 por categoría tendría que limitarse a las cuatro cadenas grandes, o
  agrupar categorías.
- **PNNS es la convención de OFF, no la única posible.** Que las papas fritas de bolsa estén
  en "Cereals and potatoes" se ve raro, pero es lo que hace OFF con los 666 productos que
  ya tienen PNNS, y mezclar convenciones sería peor.
- **19 productos quedan sin categoría:** especias, vinagre y nombres de marca sin contexto
  ("bueno", "Pancroc"). Quedan fuera de los modelos que controlan por categoría.
