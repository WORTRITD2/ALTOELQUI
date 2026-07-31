# Lo que el importador encontró en la plantilla real

Resultado de procesar `plantilla/PPTO_RCR_Conservacion_Escuela_Juan_Sandoval_Carrasco.xlsx` con
el importador (`backend/app/importador.py`). Son **102 hallazgos**, de los cuales 22 son errores.
Ninguno se corrige en silencio: todos quedan en la tabla `validacion_importacion` y se ven en la
pestaña «Validaciones».

| Regla | Casos | Severidad | Qué significa |
|---|---:|---|---|
| `CODIGO_FECHA` | 38 | Advertencia | Excel convirtió `2.6.10` en `2010-02-06`. Se reconstruye a `m.d.aa` y se pide confirmación |
| `UNIDAD_NO_NORMALIZADA` | 28 | Info | `m²`/`m2`, `M. Lineal`/`Ml`/`m`, `Un`/`un` unificadas a un catálogo, conservando el texto original |
| `APU_NO_CUADRA` | 21 | **Error** | El costo directo del APU no coincide con el P. Unitario del itemizado |
| `PARTIDA_SIN_APU` | 4 | Info | Partidas medibles sin análisis de precio en la hoja `P.U` |
| `INCLUIDA_EN_GG` | 5 | Info | Instalación de faena marcada «incluido en gastos generales»: no pondera en el avance |
| `SUBTOTAL_SIN_FORMULA` | 2 | Advertencia | Filas rotuladas SUBTOTAL sin valor; se recalculan |
| `APU_IVA_INCONSISTENTE` | 1 | **Error** | En el APU 2.1.1.1 el IVA dice 275 donde corresponde 1.859 |
| `APU_CODIGO_INFERIDO` | 1 | Advertencia | Un bloque de APU sin código legible, inferido como 2.1.8 por su posición |
| `CELDA_HUERFANA` | 1 | Advertencia | `M134` con el valor 10.983.425 fuera de toda tabla |
| `TOTALES_CUADRAN` | 1 | Info | El costo directo calculado coincide exactamente con el del archivo: $502.933.585 |

## El hallazgo que importa: 21 APU que no cuadran

La validación compara, partida por partida, el costo directo del análisis de precios
(`materiales + mano de obra × 1,5 + equipos`) contra el `P. Unitario` con que esa partida entró
al presupuesto. En 21 partidas no coinciden — 20 de ellas del capítulo 2.6 (ventanas) más el
letrero de obra.

**Exposición neta: −$27.413.642** sobre el costo directo del contrato. El signo neto es
favorable, pero está compuesto por diferencias en ambos sentidos que conviene revisar por
separado.

Partidas donde **el APU cuesta más de lo presupuestado** (se pierde plata al ejecutarlas):

| Ítem | Descripción | Diferencia |
|---|---|---:|
| 2.6.9 | Ventana V7 0,60x1,50 | $286.592 |
| 2.6.8 | Ventana V6 1,35x0,50 | $155.820 |
| 2.6.3 | Ventana V1 2,85x1,50 | $154.360 |
| 2.6.13 | Ventana V11 0,60x1,20 | $118.722 |
| 2.6.14 | Ventana V12 1,40x0,60 | $107.868 |

Partidas donde **el presupuesto quedó por sobre el APU** (holgura, o bien un APU incompleto):

| Ítem | Descripción | Diferencia |
|---|---|---:|
| 2.6.12 | Ventana V10 4,35x1,50 | −$7.960.056 |
| 2.6.11 | Ventana V9 3,25x1,50 | −$6.082.224 |
| 2.11.9 | Letrero tipo | −$5.766.400 |
| 2.6.17 | Ventana V15 1,60x1,60 | −$2.976.285 |
| 2.6.10 | Ventana V8 1,60x1,50 | −$2.379.174 |

Ejemplo verificable a mano — partida **2.6.3, Ventana V1**, bloque de la hoja `P.U` en la fila
1277: materiales 528.365 + mano de obra 115.575 (77.050 + 50% de leyes sociales) + equipos
30.150 = **674.090**, que es exactamente el «Costo Directo» que declara el propio resumen del
APU. El itemizado, en cambio, cobra **635.500** por esa ventana: faltan $38.590 por unidad, y son
4 unidades.

Dos lecturas posibles, y la aplicación no elige por nadie:

1. El APU está sobredimensionado (por ejemplo, 4,28 m² de ventana PVC a $120.000/m² para una
   ventana de 2,85 × 1,50 = 4,28 m², sin descuento por volumen).
2. El itemizado se cotizó con un precio de proveedor que el APU no refleja.

En cualquier caso es una diferencia que hoy no se ve en la planilla y que la aplicación bloquea
como error de importación hasta que alguien la resuelva.

## Reproducirlo

```bash
cd backend && python seed.py --reset
curl "http://127.0.0.1:8000/api/presupuestos/1/validaciones?severidad=ERROR"
```

o abrir la pestaña «Validaciones» en la interfaz.
