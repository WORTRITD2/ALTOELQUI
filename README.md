# ALTOELQUI — Gestión de obra

Aplicación de gestión de obra construida sobre la plantilla de presupuesto (itemizado + análisis
de precios unitarios) que hoy se opera en Excel: importa la plantilla, programa las partidas en
semanas laborales hábiles, registra avance real en terreno, emite estados de pago y reporta el
avance contra presupuesto y contra programa.

## Puesta en marcha

```bash
cd backend
pip install -r requirements.txt
python seed.py --reset          # carga la obra de referencia completa
uvicorn app.main:app --reload   # http://127.0.0.1:8000
```

`seed.py` importa `plantilla/PPTO_RCR_Conservacion_Escuela_Juan_Sandoval_Carrasco.xlsx`, carga los
dos cortes de avance que trae el archivo, genera la programación línea base y emite los dos
estados de pago. Su salida debe ser exactamente:

```
Importación: 116 partidas medibles, 23 no medibles, 112 APU
Corte 03-03-2025: avance 6.6699%
Corte 17-03-2025: avance 20.3951%
EP N°1: período $53.890.565 · acumulado $53.890.565 (6.67%)
EP N°2: período $110.893.860 · acumulado $164.784.425 (20.40%)
```

Pruebas de los criterios de aceptación (17 casos, con los números reales del contrato):

```bash
cd backend && python -m pytest tests -q
```

Base de datos: SQLite por defecto (`backend/obra.db`, sin servidor). Para PostgreSQL basta
`export DATABASE_URL=postgresql+psycopg://usuario:clave@host/base`.

## Qué hace

| Módulo | Qué resuelve |
|---|---|
| **Importador** | Lee el `.xlsx` sin adaptación previa y reporta cada anomalía: códigos de ítem que Excel convirtió en fechas, unidades sin normalizar, subtotales sin fórmula, IVA mal calculado en un APU, celdas huérfanas, y la cuadratura APU ↔ P. Unitario y de totales |
| **Parámetros** | GG, utilidad, base de cálculo, IVA, leyes sociales, anticipo, retención, multas, jornada, moneda y reajuste, **por obra y con vigencia temporal**: editar abre una vigencia nueva, nunca sobrescribe |
| **Indicadores** | UF, UTM, IPC y dólar observado desde el Banco Central (oficial), SII (contraste) o mindicador.cl (respaldo). Sin red: usa el último valor y marca el cálculo `PROVISIONAL` |
| **Programación** | Reparte cada partida en semanas ISO usando el rendimiento del APU (`jornadas = cantidad / rendimiento`), descontando feriados |
| **Avance** | Se registra **cantidad ejecutada**, nunca un porcentaje. Flujo `EN_TERRENO → REVISADO → APROBADO` |
| **Estados de pago** | `EP n = acumulado − acumulado anterior`, con GG, utilidad, IVA, anticipo, retención y multas. Al aprobar congela un snapshot de parámetros e indicadores: el EP queda inmutable |
| **Reportes** | Avance vs presupuesto · avance vs programa por semana hábil (curva S, Δ, SPI, partidas críticas por monto) · estado de pago · tablero. Exportables a Excel; el EP tiene vista de impresión con pie de trazabilidad |
| **Anexo 4** | Regenera el formato oficial de APU para el mandante desde los datos, sin reescritura manual |

## Estructura

```
backend/
  app/
    models.py            modelo de datos
    importador.py        lectura de la plantilla + 8 validaciones
    reportes.py          los cuatro reportes + Anexo 4
    export_excel.py      exportación con el formato de la plantilla
    api.py  main.py      API REST y arranque
    core/
      parametros.py      catálogo y resolución temporal de parámetros
      indicadores.py     UF/UTM/IPC con proveedores conmutables
      calendario.py      semanas hábiles ISO y feriados
      programacion.py    línea base y curva S programada
      calculo.py         avance, cierre económico y estados de pago
  tests/                 criterios de aceptación
  seed.py                carga la obra de referencia
frontend/                interfaz (HTML + JS sin build, servida por el backend)
plantilla/               archivo de referencia
docs/                    análisis de la plantilla
prompt-app-gestion-obra.md   especificación de la que nace todo esto
```

## Reglas de cálculo que la aplicación no negocia

- **El avance financiero es ponderado por costo**, nunca el promedio simple de porcentajes.
  El avance de un capítulo es `Σ monto avance / Σ P. total` de sus hijos.
- **Los parámetros se resuelven con la fecha de corte del período**, jamás con la fecha actual.
- **El `P. Unitario` del itemizado es costo directo**: GG, utilidad e IVA se aplican una sola vez
  al pie del presupuesto.
- **El total del contrato no se re-deriva**: se importa firmado desde la plantilla, que redondea
  cada línea del pie. Recalcularlo desde cero da un peso de diferencia.
- **Un avance por sobre la cantidad contratada se rechaza** hasta que exista una modificación de
  contrato.
- **Un estado de pago aprobado es inmutable**, y un parámetro con vigencia anterior a un EP
  aprobado se rechaza pidiendo nota de ajuste.

## Documentos

| Archivo | Contenido |
|---|---|
| [`prompt-app-gestion-obra.md`](prompt-app-gestion-obra.md) | Especificación completa: flujo, modelo de datos, fórmulas, reportes y criterios de aceptación |
| [`docs/analisis-plantilla-presupuesto.md`](docs/analisis-plantilla-presupuesto.md) | Análisis celda a celda de la plantilla y defectos detectados |
| [`docs/hallazgos-plantilla-real.md`](docs/hallazgos-plantilla-real.md) | Lo que el importador encontró al procesar la plantilla real |

## Pendiente

- Migraciones con Alembic (hoy el esquema se crea con `create_all`; cambiar el modelo exige
  recrear la base de desarrollo).
- Autenticación y roles: el flujo de estados está implementado, pero los endpoints aún no exigen
  identidad.
- Captura de fotos y sincronización offline de la vista de terreno.
- Exportación a PDF por servidor (hoy el EP se imprime desde el navegador).
