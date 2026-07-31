# ALTOELQUI — Gestión de obra

Especificación para una aplicación de gestión de obra construida sobre la plantilla de
presupuesto (itemizado + análisis de precios unitarios) que hoy se opera en Excel.

| Archivo | Contenido |
|---|---|
| [`prompt-app-gestion-obra.md`](prompt-app-gestion-obra.md) | **Prompt de construcción** de la aplicación: flujo de trabajo, modelo de datos, fórmulas, reportes y criterios de aceptación |
| [`docs/analisis-plantilla-presupuesto.md`](docs/analisis-plantilla-presupuesto.md) | Análisis celda a celda de la plantilla de referencia: estructura, fórmulas, cuadraturas y defectos detectados |
| `plantilla/PPTO_RCR_Conservacion_Escuela_Juan_Sandoval_Carrasco.xlsx` | Plantilla real de referencia (Conservación Escuela Juan Sandoval Carrasco) |

## Alcance en una línea

Importar la plantilla → programar las partidas en semanas laborales hábiles → registrar avance
real en terreno → emitir estados de pago → reportar avance real contra presupuesto y contra
programa, con los precios del presupuesto y los APU como única fuente de verdad.
