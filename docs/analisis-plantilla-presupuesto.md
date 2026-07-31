# Análisis de la plantilla de obra

Documento de respaldo del prompt `prompt-app-gestion-obra.md`. Recoge lo que efectivamente
contiene `plantilla/PPTO_RCR_Conservacion_Escuela_Juan_Sandoval_Carrasco.xlsx`, leído celda a
celda (fórmulas y valores), para que las reglas del prompt sean verificables y no supuestos.

**Obra**: Servicio de obras de conservación en Escuela Juan Sandoval Carrasco, Servicio Local de
Educación Pública Puerto Cordillera · Santa Elena N°385, Coquimbo · Contratista: Constructora
RCR SpA.

## Hojas del libro

| Hoja | Filas × Col | Rol en el flujo |
|---|---|---|
| `avance real ` | 1000 × 26 (datos hasta fila 152) | Itemizado + medición al 03-03-2025 |
| `avance proyectado 20%` | ídem | Mismo itemizado, corte al 17-03-2025 |
| `P.U` | 4920 × 9 | 112 análisis de precios unitarios, bloques de 44 filas |
| `Anexo 4` | 272 × 26 | Formato oficial de APU para el mandante (con firma) |

Que las dos primeras hojas sean la misma tabla en dos fechas distintas, separadas por dos
semanas, es exactamente el ciclo de estado de pago que la aplicación debe automatizar: hoy se
duplica la hoja a mano en cada corte.

## Estructura del itemizado

Columnas `A:J` — `Ítem · Descripción · Unidad · Cantidad · P. Unitario ($) · P. Total ($) ·
Cant avance · unidad · avance % · monto avance`.

Fórmulas verificadas:

| Celda | Fórmula |
|---|---|
| `F7` | `=D7*E7` |
| `I7` | `=G7*100%/D7` |
| `J7` | `=F7*I7` (en otras filas `=I19*F19`, equivalente) |
| `H2` | `=J152/F152` |
| `F150` | `=ROUND(F147+F148+F149,0)` |
| `F151` | `=ROUND(F150*D151,0)` |
| `F152` | `=ROUND(F150+F151,0)` |
| `J150` | `=J147+J148+J149` |
| `J151` | `=J150*0.19` |
| `J152` | `=J151+J150` |

Conteos: **116 partidas medibles**, **23 filas agrupadoras**, **5 filas** marcadas
`INCLUIDO EN GASTOS GENERALES`, **38 códigos de ítem corrompidos a fecha** por Excel.

Profundidad de códigos: hasta 4 niveles (`2.1.1.1`). Capítulos: `1 OBRAS PREVIAS`,
`2 MEJORAMIENTO` (con 2.1 Cubierta, 2.2 Pavimentos, 2.3 Muros, 2.4 Cielos, 2.6 Ventanas,
2.7 Puertas, 2.8 Artefactos sanitarios, 2.9 Eléctricos, 2.10 Accesibilidad universal,
2.11 Elementos complementarios), `3 OTROS`.

## Cierre económico

| Concepto | % | Contrato | Corte 03-03 | Corte 17-03 |
|---|---:|---:|---:|---:|
| Costo directo neto | — | 502.933.585 | 33.545.325 | 102.573.561 |
| Gastos generales | 15% | 75.440.038 | 5.031.799 | 15.386.034 |
| Utilidades | 20% | 100.586.717 | 6.709.065 | 20.514.712 |
| Subtotal | — | 678.960.340 | 45.286.189 | 138.474.307 |
| IVA | 19% | 129.002.465 | 8.604.376 | 26.310.118 |
| **Total** | | **807.962.805** | **53.890.565** | **164.784.425** |
| % avance | | 100% | 6,6699% | 20,3951% |

Utilidad calculada sobre costo directo (`502.933.585 × 0,20 = 100.586.717`), **no** sobre
CD + GG. Diferencia entre cortes: `164.784.425 − 53.890.565 = 110.893.860` → monto del EP n°2.

## Análisis de precios unitarios

Bloque tipo de la hoja `P.U` (paso constante de 44 filas):

```
A1  Rendimiento (Un/jornada)     E2:F4  GG 0,15 · Utilidad 0,20 · IVA 0,19
A2  Unidad de pago
B4  <código> <descripción>
A5  MATERIALES                   → TOTAL
A12 MANO DE OBRA                 → TOTAL + Leyes sociales 50% → TOTAL MO
A20 MAQUINARIA Y HERRAMIENTAS    → TOTAL
A26 RESUMEN → Costo Directo · GG · Utilidad · Sub-Total Neto · IVA · PRECIO UNITARIO
```

Comprobaciones de cuadratura:

| Partida | Materiales | MO (c/ leyes 50%) | Equipos | Suma | P. Unitario itemizado |
|---|---:|---:|---:|---:|---:|
| 2.1.1.1 Retiro cubierta zinc | 197 | 5.175 | 1.874 | **7.246** | 7.246 ✓ |
| 2.1.1.2 Retiro asbesto cemento | 15.019 | 6.900 | 2.253 | **24.172** | 24.172 ✓ |
| 2.1.2 Lana de vidrio | 2.160 | 1.725 | 0 | **3.885** | 3.885 ✓ |
| 2.1.5 Cubierta PV4 (Anexo 4) | 11.500 | 6.900 | 115 | **18.515** | 18.515 ✓ |

Conclusión: **el precio unitario del itemizado es costo directo**; GG, utilidad e IVA se aplican
una sola vez al pie del presupuesto. El bloque `RESUMEN` de cada APU calcula además un precio de
venta unitario que **no** se usa en el itemizado — es informativo, y es donde está el error del
punto 5 más abajo.

El campo `Rendimiento (Un/jornada)` (56 m²/jornada en 2.1.1.1, 40 en 2.1.1.2, 70 en 2.1.2, …) es
el puente hacia la programación: `jornadas = cantidad / rendimiento`.

## Defectos detectados en la plantilla

Cada uno se traduce en una validación del importador (§6 del prompt).

1. **Códigos de ítem convertidos a fecha** — 38 casos. `2.6.10` → `2010-02-06`, `2.7.10` →
   `2010-02-07`, `2.11.16` → `2016-02-11`. Excel interpretó `n.m.dd` como fecha.
2. **Unidades sin normalizar** — conviven `m²` y `m2`, `m` y `M. Lineal` y `Ml`, `un` y `Un`,
   más `gl` y `m3`. La columna `H` (unidad del avance) usa un vocabulario distinto de la
   columna `C` (unidad del contrato) para la misma partida.
3. **`INCLUIDO EN GASTOS GENERALES`** en la columna de unidad de 5 partidas de instalación de
   faena: texto donde debería haber unidad, sin cantidad ni precio.
4. **Filas SUBTOTAL vacías o descuadradas** — `C15` y `D146` rotulan un subtotal sin valor;
   `C142`/`F142` sí lo tiene (498.518.585).
5. **IVA erróneo en el resumen del APU 2.1.1.1** — sub-total neto 9.782, IVA declarado **275**
   cuando `9.782 × 0,19 = 1.858`; el precio unitario resultante (10.057) queda mal. No afecta el
   presupuesto (que usa el costo directo), pero contamina cualquier reporte que tome ese valor.
6. **Celda huérfana `M134`** con el valor 10.983.425 fuera de toda tabla.
7. **Nombre de hoja con espacio final** (`'avance real '`), que rompe referencias escritas a mano.
8. **Etiqueta mal puesta** en `E48` de `P.U`: dice `Utilidad` donde corresponde `iva`.

## Qué se pierde hoy por trabajar en Excel

- No hay eje de tiempo: los cortes son hojas duplicadas, sin semana ISO ni días hábiles, así que
  no existe forma de contrastar avance real contra programa.
- No hay acumulado por estado de pago: el monto del EP se obtiene restando a mano dos hojas.
- No hay trazabilidad de quién midió qué ni respaldo fotográfico asociado a la medición.
- El rendimiento de los APU no se compara nunca con el rendimiento real, que es la señal
  temprana de que un precio unitario se está perdiendo.
