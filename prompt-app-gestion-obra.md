# Prompt — Aplicación de Gestión de Obra (avance real, estados de pago y programación semanal)

> Copiar y pegar íntegro como prompt de construcción. Está derivado de la plantilla real
> `plantilla/PPTO_RCR_Conservacion_Escuela_Juan_Sandoval_Carrasco.xlsx` (presupuesto de conservación,
> Constructora RCR SpA), cuya estructura se describe en detalle en el §2 y en
> `docs/analisis-plantilla-presupuesto.md`.

---

## 1. Rol y objetivo

Actúa como arquitecto y desarrollador full-stack especializado en software de control de obras
civiles en Chile (licitaciones públicas, itemizado, APU, estados de pago).

Construye una **aplicación de gestión de obra** que reemplace el flujo actual en Excel. La
aplicación se alimenta de una **plantilla de obra** (presupuesto itemizado + análisis de precios
unitarios) y, a partir de ella, permite cargar **avance real por partida**, generar **estados de
pago** y producir **reportes de avance físico y financiero contrastados contra la programación,
medidos en semanas laborales hábiles**.

Regla de oro: **la plantilla es la fuente de verdad de precios y cantidades**. Ningún avance,
reporte ni estado de pago puede inventar precios: todo monto se deriva de las cantidades del
itemizado, los precios unitarios del presupuesto y los análisis de precios unitarios (APU).

---

## 2. La plantilla de obra (estructura real a soportar)

El archivo de referencia tiene 4 hojas. La aplicación debe importarlo tal cual y modelarlo.

### 2.1. Hojas `avance real` y `avance proyectado 20%` — itemizado + medición

Son **la misma tabla en dos cortes de fecha distintos** (03-03-2025 y 17-03-2025). Cada corte es,
en la práctica, un **estado de pago**. Encabezado:

| Celda/columna | Contenido |
|---|---|
| A1 | `PRESUPUESTO OBRAS CIVILES` |
| A2 / A3 | `Licitación:` … / `Ubicación:` … |
| E2 / E3 | `Fecha:` (fecha de corte) / `Versión:` |
| G2 / H2 | `% Avance` / `=J152/F152` (avance financiero global) |
| A4:J4 | `Ítem · Descripción · Unidad · Cantidad · P. Unitario ($) · P. Total ($) · Cant avance · unidad · avance % · monto avance` |

Fórmulas por fila de partida (fila 7 como ejemplo):

```
F7 = D7 * E7                  ' P. Total = Cantidad × P. Unitario
I7 = G7 * 100% / D7           ' avance % = Cant avance / Cantidad
J7 = F7 * I7                  ' monto avance = P. Total × avance %
```

Cierre del presupuesto (filas 147–152), con columna F = contrato y columna J = avance del corte:

```
COSTO DIRECTO NETO      F147 = Σ partidas                  J147 = Σ monto avance
GASTOS GENERALES 15%    F148 = F147 × 0,15                 J148 = J147 × 0,15
UTILIDADES 20%          F149 = F147 × 0,20                 J149 = J147 × 0,20
SUBTOTAL                F150 = ROUND(F147+F148+F149,0)     J150 = J147+J148+J149
IVA 19%                 F151 = ROUND(F150 × 0,19,0)        J151 = J150 × 0,19
TOTAL                   F152 = ROUND(F150+F151,0)          J152 = J150+J151
% Avance                H152 = J152 / F152
```

Cifras del contrato de referencia (deben reproducirse exactamente tras la importación):

| Concepto | Contrato | Corte 03-03-2025 | Corte 17-03-2025 |
|---|---:|---:|---:|
| Costo directo neto | 502.933.585 | 33.545.325 | 102.573.561 |
| Gastos generales 15% | 75.440.038 | 5.031.799 | 15.386.034 |
| Utilidades 20% | 100.586.717 | 6.709.065 | 20.514.712 |
| Subtotal | 678.960.340 | 45.286.189 | 138.474.307 |
| IVA 19% | 129.002.465 | 8.604.376 | 26.310.118 |
| **Total** | **807.962.805** | **53.890.565** | **164.784.425** |
| % avance | 100% | 6,6699% | 20,3951% |

Características estructurales a respetar:

- **Jerarquía por código de ítem** de profundidad variable: `1` → `1.3` → `1.3.1`; `2.1.1.1`
  llega a 4 niveles. 23 filas son títulos/agrupadores (sin cantidad ni precio) y **116 son
  partidas medibles**.
- **Partidas sin precio** marcadas `INCLUIDO EN GASTOS GENERALES` (5 filas de instalación de
  faena): no aportan monto y **no deben ponderar** en el avance.
- Filas `SUBTOTAL` por capítulo (`C15`, `C142`, `D146`).
- Unidades heterogéneas en el original: `m²`, `m2`, `m`, `M. Lineal`, `Ml`, `un`, `Un`, `gl`, `m3`.
- **El `P. Unitario` del itemizado es COSTO DIRECTO**, no precio de venta: GG, utilidad e IVA se
  aplican una sola vez al pie. Verificado contra los APU (p. ej. ítem 2.1.5 Cubierta PV4:
  11.500 materiales + 6.900 MO + 115 equipos = **18.515** = P. Unitario del itemizado).

### 2.2. Hoja `P.U` — análisis de precios unitarios (112 APU, bloques de 44 filas)

Cada bloque:

```
Rendimiento (Un/jornada):  <valor>        Parámetros (editar):
Unidad de pago:            <unidad>       Gastos Generales  0,15
                                          Utilidad          0,20
<código> <descripción de la partida>      IVA               0,19

MATERIALES                       #, Descripción, Unidad, Cantidad, $ Unitario, Subtotal → TOTAL
MANO DE OBRA (rendimiento/jornada)  … → TOTAL + Leyes sociales 50% → TOTAL MO
MAQUINARIA Y HERRAMIENTAS (prorrateo por unidad) … → TOTAL
RESUMEN → Costo Directo · Gastos Generales · Utilidad · Sub-Total Neto · IVA 19% · PRECIO UNITARIO
```

Relación clave: `Costo Directo APU = Materiales + Total MO + Equipos` y ese costo directo es
exactamente el `P. Unitario ($)` del itemizado. Las cantidades de mano de obra y equipos se
expresan como `1 / rendimiento` (jornadas por unidad), lo que permite **derivar HH y jornadas
necesarias por partida** — insumo directo de la programación semanal.

### 2.3. Hoja `Anexo 4` — formato oficial de APU para el mandante

Formato de presentación exigido en la licitación: cabecera con nombre de obra, ID, contratista;
`PARTIDA / ÍTEM / UNIDAD / PRECIO UNITARIO`; secciones `MATERIALES (A)`, `MANO DE OBRA (B)` con
`LEYES SOCIALES`, `EQUIPOS Y HERRAMIENTAS (C)`; y pie de firma del representante legal. La
aplicación debe **regenerar este anexo** para cualquier partida, sin reescritura manual.

---

## 3. Flujo de trabajo a implementar

Implementa este flujo como **máquina de estados explícita**, con roles, transiciones permitidas,
validaciones de salida y registro de auditoría (quién, cuándo, qué cambió).

```
[1] PLANTILLA / PRESUPUESTO
    Seleccionar/crear OBRA → fijar sus parámetros con vigencia (§4) desde la plantilla de la organización
    Importar plantilla → itemizado jerárquico + APU
    Estado: BORRADOR → VALIDADO → CONTRATO VIGENTE (línea base congelada, versionada)
        ↓
[2] PROGRAMACIÓN
    Asignar a cada partida: fecha inicio, fecha término, cuadrilla, rendimiento (del APU)
    El sistema distribuye la cantidad contratada en SEMANAS LABORALES HÁBILES
    Genera: curva S programada (avance % planificado acumulado por semana) = LÍNEA BASE
    Estado: PROGRAMADO (v1, v2… reprogramaciones versionadas, la línea base original nunca se pierde)
        ↓
[3] AVANCE REAL (ciclo semanal)
    Cada semana hábil, el jefe de terreno registra `Cant avance` acumulada por partida
    El sistema calcula avance % y monto avance con las fórmulas del §5
    Adjuntos: fotos, libro de obra, medición en terreno
    Estado: EN TERRENO → REVISADO (ITO/oficina técnica) → APROBADO
        ↓
[4] ESTADO DE PAGO
    Corte a una fecha (fin de semana hábil): congela el avance acumulado aprobado
    EP n = acumulado a la fecha − acumulado del EP n−1 (siempre incremental, nunca negativo salvo nota de ajuste explícita)
    Aplica GG, utilidad, IVA; descuenta anticipo y retención si el contrato los define
    Estado: BORRADOR → PRESENTADO → OBSERVADO → APROBADO → PAGADO
        ↓
[5] REPORTES  (§6)
    Avance real vs presupuesto · Avance real vs programación semanal · Estado de pago
        ↓
[6] CIERRE
    Avance 100%, entrega final, liberación de retenciones, informe de cierre
```

Reglas del flujo:

- **Un corte de avance no aprobado no puede entrar a un estado de pago.**
- Un EP `APROBADO` es **inmutable**: correcciones se hacen en el EP siguiente o por nota de ajuste
  trazable.
- Modificaciones de contrato (obras extraordinarias, aumentos/disminuciones de cantidad) crean una
  **nueva versión del presupuesto** con su propio itemizado; los reportes deben poder mostrar
  contrato original vs contrato vigente.
- Roles: `Administrador de obra` (todo), `Jefe de terreno` (registra avance), `Oficina técnica /
  ITO` (revisa y aprueba), `Finanzas` (EP y pagos), `Mandante` (solo lectura de EP y reportes).

---

## 4. Parámetros de obra e indicadores económicos

Ningún porcentaje, tarifa ni valor de moneda puede estar escrito en el código. Todos son
**parámetros seleccionables por obra y versionados en el tiempo**. Los del §2 (15% GG, 20%
utilidad, 19% IVA, 50% leyes sociales) son solo los valores de *esta* obra en *esa* fecha.

### 4.1. Selección de obra como contexto

La aplicación es multi-obra. Al iniciar sesión se **selecciona la obra activa** y todo —
itemizado, programación, avances, EP, reportes — queda circunscrito a ella. La cabecera muestra
siempre obra activa, contrato vigente, semana en curso y último EP.

Jerarquía de valores, de menor a mayor prioridad:

```
1. Valores por defecto del sistema (Chile: IVA 19%, leyes sociales 50%, semana lun–vie)
2. Plantilla de parámetros de la organización (los que la constructora usa habitualmente)
3. Parámetros de la obra          ← se fijan al crear la obra, desde la plantilla o a mano
4. Vigencia específica dentro de la obra (§4.3)
```

Crear una obra nueva debe ser: elegir plantilla de parámetros → ajustar lo que difiera →
importar el presupuesto. Nunca partir de cero.

### 4.2. Parámetros contractuales de la obra

Constantes del contrato, pero **editables con vigencia** porque cambian por ley, por resolución
del mandante o por modificación de contrato.

| Parámetro | Clave | Valor en la obra de referencia | Se aplica sobre |
|---|---|---:|---|
| Gastos generales | `pct_gg` | 15% | Costo directo del corte |
| Utilidad | `pct_utilidad` | 20% | Costo directo del corte (no sobre CD+GG) |
| IVA | `pct_iva` | 19% | Neto |
| Leyes sociales | `pct_leyes_sociales` | 50% | Mano de obra del APU |
| Anticipo | `pct_anticipo` | según bases | Monto del EP (amortización) |
| Retención | `pct_retencion` | según bases | Monto del EP |
| Multa por atraso | `multa_diaria` | en UTM o ‰ del contrato | Días de atraso |
| Plazo contractual | `plazo_dias` | días corridos o hábiles | Programación |
| Jornada semanal | `jornada` | días hábiles y horas/día | Semanas hábiles (§5) |
| Moneda del contrato | `moneda` | CLP o UF | Todo el cálculo |
| Mecanismo de reajuste | `reajuste` | sin reajuste / UF / polinómico / IPC | Monto del EP |
| Base de cálculo de la utilidad | `base_utilidad` | `CD` o `CD+GG` | Cierre económico |
| Redondeo | `politica_redondeo` | pesos, solo en totales | Cierre económico |

`base_utilidad` es un parámetro y no una constante justamente porque otras bases de licitación
calculan la utilidad sobre CD+GG; el sistema debe soportar ambas sin tocar código.

### 4.3. Vigencia temporal: editar sin reescribir el pasado

**Prohibido el `UPDATE` destructivo sobre un parámetro.** Editar un parámetro **cierra la
vigencia anterior y abre una nueva**:

```
ParametroObra(obra_id, clave, valor, vigente_desde, vigente_hasta, motivo,
              documento_respaldo, usuario, creado_en)

valor_vigente(obra, clave, fecha) = registro cuyo intervalo [vigente_desde, vigente_hasta)
                                     contiene fecha        ' vigente_hasta NULL = vigente hoy
```

Reglas:

- Todo cálculo resuelve sus parámetros **con la fecha de corte del período**, nunca con "hoy".
- Al aprobar un estado de pago se **congela un snapshot** de todos los parámetros e indicadores
  usados. Reabrir un EP de hace un año debe mostrar exactamente los mismos números, aunque los
  parámetros hayan cambiado diez veces desde entonces.
- Un cambio de parámetro con vigencia anterior a un EP aprobado **se rechaza**: exige nota de
  ajuste explícita, con motivo y documento de respaldo.
- Toda edición exige `motivo` y admite adjuntar el respaldo (resolución, ley, acta).
- La pantalla de parámetros muestra una **línea de tiempo** por clave, con quién cambió qué,
  cuándo y por qué.
- Antes de confirmar, un **simulador de impacto** muestra cuánto cambiarían los EP futuros con el
  nuevo valor.

### 4.4. Indicadores económicos externos (UF, UTM, IPC y otros)

Series temporales obtenidas de fuentes oficiales chilenas, no digitadas a mano.

| Indicador | Frecuencia | Uso en obra |
|---|---|---|
| **UF** | Diaria | Contratos y EP expresados en UF; reajuste |
| **UTM** | Mensual | Multas, garantías, topes legales |
| **UTA** | Anual (= UTM × 12) | Topes tributarios |
| **IPC** | Mensual (INE) | Reajuste polinómico, fórmulas de las bases |
| **Dólar observado** | Días hábiles | Insumos importados |
| **Ingreso mínimo mensual** | Por ley | Validación de tarifas de mano de obra del APU |
| **Índices de costos de la construcción** | Mensual | Reajuste polinómico por familia de insumos |

**Fuentes oficiales, en orden de prioridad** (implementar con proveedor conmutable):

1. **Banco Central de Chile — Base de Datos Estadísticos** (fuente oficial de UF, UTM, dólar
   observado, IPC). Servicio web REST/SOAP con credenciales gratuitas previa inscripción;
   `https://si3.bcentral.cl/SieteRestWS/SieteRestWS.ashx` con `function=GetSeries` y el código de
   serie (p. ej. UF diaria `F073.UFF.PRE.Z.D`, UTM mensual `F073.UTR.PRE.Z.M`). **Verificar el
   código exacto de cada serie en el catálogo del BCCh antes de codificar** y dejarlo como
   configuración, no incrustado.
2. **SII — «Valores y fechas»** (`sii.cl`): tablas oficiales de UF, UTM y UTA. Usar como
   **contraste**: si el valor del SII y el del BCCh difieren, alertar en vez de elegir en silencio.
3. **INE**: IPC e índices de costos de la construcción.
4. **`mindicador.cl`**: API JSON pública y gratuita, sin credenciales
   (`https://mindicador.cl/api/uf/dd-mm-aaaa`). Útil como respaldo y para desarrollo, **marcada
   siempre como fuente no oficial** en el registro.
5. **Feriados legales** (determinan la semana hábil del §5): API de feriados del gobierno
   (`apis.digital.gob.cl/fl/feriados/<año>`), con carga manual de respaldo y edición por obra
   para feriados regionales, días de paralización o cierres de faena. Un cambio en el calendario
   **no debe recalcular semanas ya cerradas en un EP aprobado**.

**Reglas de sincronización y de uso:**

```
IndicadorValor(codigo, fecha, valor, fuente, url_origen, obtenido_en,
               estado[CONFIRMADO|PROVISIONAL], usuario_si_manual)
```

- Job diario (p. ej. 09:00 hora de Chile) que consulta y persiste; reintentos con backoff y
  **backfill automático de huecos** al detectar fechas faltantes.
- **La UF se publica con desfase**: el valor rige del día 10 de un mes al día 9 del siguiente, en
  función del IPC del mes anterior. El sistema debe distinguir valor **publicado** de valor
  **proyectado**, y marcar como `PROVISIONAL` todo cálculo que use un valor aún no publicado.
- Si la fuente no responde: usar el último valor disponible, marcar el cálculo como provisional y
  **mostrar la advertencia en pantalla y en el PDF**. Jamás fallar en silencio ni improvisar un
  valor.
- Un valor ya usado en un EP aprobado **no se sobrescribe** aunque la fuente lo corrija: se
  registra la corrección como un valor nuevo y se avisa qué EP quedaron afectados.
- Validaciones de cordura: variación diaria de UF > 0,5%, UTM que no cambia al inicio de mes, o
  valor fuera de un rango razonable ⇒ marcar para revisión humana.
- Carga manual permitida solo con rol autorizado, quedando registrada como `fuente = MANUAL` con
  usuario y motivo.

### 4.5. Uso de los indicadores en el cálculo

- **Contrato en UF**: el itemizado se almacena en UF y cada EP se convierte a pesos con la UF de
  la fecha que definan las bases (fecha de corte, de presentación o de pago — parámetro
  `fecha_conversion_uf`, no un supuesto del programador).
- **Reajuste polinómico**: fórmula configurable por obra, del tipo
  `R = Σ (peso_k × Índice_k(t) / Índice_k(t₀))`, con los pesos y los índices definidos en las
  bases. El reporte debe mostrar el desglose del reajuste, no solo el resultado.
- **Multas en UTM**: se calculan con la UTM del mes del atraso.
- El PDF de cada EP debe imprimir, al pie, **los valores exactos usados y su fuente**: p. ej.
  `UF al 17-03-2025 = $38.264,41 (Banco Central de Chile, consultado el 18-03-2025 09:02)`.

### 4.6. Precios de insumos de los APU, también con vigencia

Los materiales, tarifas de mano de obra y equipos de los APU (`$ Unitario`) son precios de una
fecha. Mantener **listas de precios versionadas** por fecha de vigencia y proveedor, de modo que
se pueda:

- recalcular un APU a precios de hoy sin alterar el APU contractual congelado;
- comparar **precio contractual vs precio actual de mercado** por partida, que es la alerta
  temprana de pérdida de margen (complementa la comparación de rendimientos del §6.2);
- reutilizar la lista de precios como base para presupuestar la obra siguiente.

---

## 5. Reglas de cálculo (implementar exactamente)

Sea `i` una partida medible, `t` una fecha de corte, `s` una semana laboral hábil.

**Avance físico de partida**
```
avance_pct(i,t) = cant_avance_acum(i,t) / cantidad_contratada(i)     ∈ [0, 1]
monto_avance(i,t) = P_total(i) × avance_pct(i,t)
P_total(i) = cantidad(i) × P_unitario(i)          ' P_unitario = costo directo
```
Prohibido `avance_pct > 1` sin una modificación de contrato que aumente la cantidad.

**Avance financiero (ponderado por costo, el único válido para EP)**
```
avance_financiero(t) = Σ_i monto_avance(i,t) / Σ_i P_total(i)
```
El avance de un capítulo o subcapítulo es el mismo cociente restringido a sus hijos: **jamás el
promedio simple de porcentajes**. Las partidas `INCLUIDO EN GASTOS GENERALES` quedan fuera del
numerador y del denominador.

**Cierre económico de un corte**

Todo porcentaje se resuelve con `valor_vigente(obra, clave, t)` del §4.3 — **con la fecha de
corte `t`, nunca con la fecha actual**:

```
CD(t)        = Σ_i monto_avance(i,t)
GG(t)        = CD(t) × pct_gg(t)
base_util(t) = CD(t)  ó  CD(t) + GG(t)            ' según parámetro base_utilidad
Utilidad(t)  = base_util(t) × pct_utilidad(t)     ' en la obra de referencia: sobre CD
Neto(t)      = CD(t) + GG(t) + Utilidad(t)
IVA(t)       = Neto(t) × pct_iva(t)
Total(t)     = Neto(t) + IVA(t)
```

**Estado de pago n**
```
EP_n = Total(t_n) − Total(t_{n−1})
Reajuste_n              = EP_n × (R(t_n) − 1)     ' según mecanismo del §4.5, 0 si no aplica
Amortización anticipo_n = EP_n × pct_anticipo(t_n)
Retención_n             = EP_n × pct_retencion(t_n)
Multa_n                 = días_atraso × multa_diaria(t_n)   ' convertida con la UTM del mes
Líquido a pagar_n       = EP_n + Reajuste_n − amortización − retención − multa
```
Si el contrato está en UF: `Total(t)` se calcula en UF y se convierte con
`UF(fecha_conversion_uf)`, registrando el valor y su fuente en el snapshot del EP.

**Programación semanal**
```
Semana laboral hábil: lunes–viernes (jornada configurable, p. ej. lun–jue 8,5 h + vie 6 h),
excluyendo feriados legales chilenos (calendario cargable y editable por obra).
Semanas identificadas por norma ISO-8601: "2025-W10".

cantidad_programada(i,s) distribuida por rendimiento del APU:
    jornadas_necesarias(i) = cantidad(i) / rendimiento_APU(i)
    duración_semanas(i)    = jornadas_necesarias(i) / (cuadrillas × días hábiles de la semana)
avance_programado_acum(s) = Σ_i (cant_programada_acum(i,s) × P_unitario(i)) / Σ_i P_total(i)
```

**Indicadores de desempeño** (mostrar en todo reporte semanal)
```
Avance real acumulado      AR(s)
Avance programado acum.    AP(s)
Desviación                 Δ(s) = AR(s) − AP(s)          (puntos porcentuales)
SPI (índice de desempeño del programa) = AR(s) / AP(s)   ' <1 = atrasado
Valor ganado del período   EV(s) = (AR(s) − AR(s−1)) × Monto contrato
Atraso en semanas          semanas entre AR(s) y la semana en que el programa alcanzaba ese %
Proyección de término      fecha estimada = f(ritmo real de las últimas 4 semanas hábiles)
```

**Redondeo y moneda**: pesos chilenos sin decimales; redondear solo en los totales del pie
(`ROUND(...,0)`, como la plantilla), nunca en los cálculos intermedios por partida. Formato
`$ 807.962.805`. Porcentajes con 2 decimales (`20,40%`); internamente almacenar la fracción.

---

## 6. Reportes exigidos

Todos: filtrables por capítulo/subcapítulo/partida y por rango de semanas; exportables a
**PDF y Excel** con el formato de la plantilla; con fecha de corte, número de EP y semana ISO
visibles en la carátula.

### 5.1. Reporte de avance real según presupuesto

Réplica navegable de la hoja `avance real`, más totales:

`Ítem · Descripción · Unidad · Cantidad contratada · P. Unitario · P. Total · Cant. avance
acumulada · Avance % · Monto avance · Saldo por ejecutar (cantidad y $) · Incidencia % de la
partida en el contrato`

Con: cierre CD / GG / Utilidad / Neto / IVA / Total; subtotales por capítulo con su propio % de
avance ponderado; y **ranking de partidas por incidencia** (dónde está el dinero: las 10 partidas
que concentran el mayor porcentaje del contrato, con su avance).

### 5.2. Reporte de avance real vs programación por semana laboral hábil

Eje temporal en semanas ISO con sus fechas hábiles (`2025-W10 · lun 03-03 a vie 07-03 · 5 días
hábiles`). Contenido:

- **Curva S**: programado acumulado vs real acumulado vs proyección, en % y en $.
- **Tabla semanal**: por semana → avance programado del período, avance real del período,
  acumulados, Δ en puntos porcentuales, SPI, monto ejecutado.
- **Detalle por partida de la semana**: cantidad programada vs ejecutada, con semáforo
  (verde ≥ 100% del programa, amarillo 80–99%, rojo < 80%).
- **Partidas críticas**: las que más aportan al atraso, ordenadas por `(AP−AR) × P_total`, es
  decir por monto de atraso, no por porcentaje.
- **Recursos**: HH y jornadas programadas vs reales de la semana, derivadas de los rendimientos
  del APU; alerta cuando el rendimiento real se desvía > 20% del rendimiento del APU (señal de
  que el precio unitario está en riesgo).

### 5.3. Reporte de estado de pago

Documento formal por EP `n`:

- Carátula: obra, licitación, ubicación, contratista, mandante, EP n°, período (semana ISO inicio
  a semana ISO término), fecha de corte, monto contrato.
- Cuadro por partida: cantidad contratada · acumulado anterior · ejecutado del período · acumulado
  actual · % acumulado · monto del período · monto acumulado · saldo.
- Cierre económico del período y acumulado: CD, GG 15%, utilidad 20%, neto, IVA 19%, total,
  anticipo amortizado, retención, líquido a pagar.
- Resumen histórico: tabla de todos los EP anteriores con sus montos y % acumulados.
- Anexos regenerados: APU (`Anexo 4`) de las partidas involucradas, respaldo fotográfico,
  detalle de cubicaciones.
- Pie de trazabilidad: parámetros vigentes usados (GG, utilidad, IVA, anticipo, retención) e
  indicadores (UF/UTM) con su valor, fuente y fecha de consulta.

### 5.4. Tablero (dashboard)

Avance físico y financiero global, semana en curso, SPI, Δ acumulada, monto facturado vs por
facturar, próximo EP, partidas en rojo, y proyección de término.

---

## 7. Importador de la plantilla y validaciones

El importador debe leer el `.xlsx` de referencia sin adaptación manual previa y **reportar, no
silenciar, cada anomalía**. Defectos reales presentes en la plantilla que hay que detectar:

1. **Códigos de ítem convertidos a fecha por Excel**: 38 filas donde `2.6.10` quedó almacenado
   como `2010-02-06`, `2.11.16` como `2016-02-11`, etc. Reconstruir el código correcto a partir
   del contexto jerárquico (capítulo padre y orden de fila) y pedir confirmación.
2. **Unidades no normalizadas**: mapear `m²`/`m2`, `m`/`M. Lineal`/`Ml`, `un`/`Un` a un catálogo
   único, conservando el texto original.
3. **Filas `INCLUIDO EN GASTOS GENERALES`**: importar como partidas informativas sin monto.
4. **Filas `SUBTOTAL` sin fórmula** (p. ej. `D146`): recalcular, no confiar en el valor cacheado.
5. **IVA inconsistente en el resumen de algunos APU de la hoja `P.U`**: en el bloque 2.1.1.1 el
   sub-total neto es 9.782 y el IVA aparece como 275 en vez de 1.858. Marcar como error de
   validación y recalcular desde los parámetros, no arrastrar el valor.
6. **Celdas sueltas fuera de tabla** (p. ej. `M134` con un valor huérfano): ignorar con aviso.
7. **Cuadratura obligatoria**: para cada partida, `costo directo del APU == P. Unitario del
   itemizado`; si difieren, bloquear la importación de esa partida y listar la diferencia.
8. **Cuadratura de totales**: los seis totales del pie deben coincidir con los del archivo dentro
   de ±1 peso por redondeo; si no, abortar y mostrar el detalle.

Además: importación idempotente y versionada (reimportar la misma plantilla no duplica), soporte
para plantillas de otras obras con la misma estructura, y una **plantilla en blanco descargable**
que sirva de estándar para obras nuevas.

---

## 8. Modelo de datos (mínimo)

Los porcentajes **no son columnas de `Obra`**: viven en `ParametroObra` con vigencia (§4.3).

```
Organizacion(id, razon_social, rut, plantilla_parametros_id)
PlantillaParametros(id, organizacion_id, nombre, descripcion)
PlantillaParametroValor(id, plantilla_id, clave, valor)

Obra(id, organizacion_id, nombre, licitacion_id, mandante, contratista, ubicacion,
     fecha_inicio, plazo_dias, moneda, calendario_id, estado)

ParametroDefinicion(clave, etiqueta, tipo[PORCENTAJE|MONTO|ENTERO|ENUM|BOOLEAN],
                    unidad, valor_min, valor_max, valor_defecto_sistema, descripcion)
ParametroObra(id, obra_id, clave, valor, vigente_desde, vigente_hasta, motivo,
              documento_respaldo_url, usuario_id, creado_en)
  ' UNIQUE (obra_id, clave, vigente_desde); sin solapes de intervalo; vigente_hasta NULL = vigente

IndicadorSerie(codigo[UF|UTM|UTA|IPC|USD_OBS|IMM|ICC_*], nombre, frecuencia, decimales,
               fuente_primaria, codigo_serie_fuente, activo)
IndicadorValor(id, codigo, fecha, valor, fuente[BCCH|SII|INE|MINDICADOR|MANUAL], url_origen,
               obtenido_en, estado[CONFIRMADO|PROVISIONAL], usuario_id, nota)
  ' UNIQUE (codigo, fecha, fuente)
SincronizacionIndicador(id, codigo, ejecutada_en, rango_desde, rango_hasta,
                        estado[OK|PARCIAL|ERROR], detalle, valores_nuevos, huecos_detectados)

ListaPrecios(id, organizacion_id, nombre, vigente_desde, vigente_hasta, moneda)
PrecioInsumo(id, lista_id, tipo[MATERIAL|MANO_OBRA|EQUIPO], codigo, descripcion, unidad,
             precio, proveedor, fuente)

SnapshotParametros(id, estado_pago_id, parametros_json, indicadores_json, congelado_en)
  ' fotografía inmutable de todo lo usado para calcular ese EP

Presupuesto(id, obra_id, version, estado, vigente_desde, total_cd, total_contrato)
Partida(id, presupuesto_id, codigo, codigo_padre, nivel, descripcion, unidad, cantidad,
        p_unitario, p_total, es_agrupador, es_incluida_en_gg, orden)
APU(id, partida_id, rendimiento, unidad_pago, lista_precios_id, fecha_precios)
  ' los %gg/%utilidad/%iva del APU NO se guardan aquí: se resuelven vía ParametroObra a fecha_precios
APURecurso(id, apu_id, tipo[MATERIAL|MANO_OBRA|EQUIPO], descripcion, unidad, cantidad,
           precio_unitario, subtotal)
Calendario(id, nombre, dias_habiles[], jornada_horas_por_dia)
Feriado(id, calendario_id, fecha, descripcion)
SemanaHabil(id, obra_id, iso_semana, fecha_inicio, fecha_fin, dias_habiles, horas_habiles)
Programacion(id, presupuesto_id, version, es_linea_base, creada_por, creada_en)
ProgramacionPartida(id, programacion_id, partida_id, fecha_inicio, fecha_fin, cuadrillas,
                    rendimiento_asignado)
ProgramacionSemanal(id, programacion_id, partida_id, semana_id, cantidad_programada)
AvanceSemanal(id, obra_id, partida_id, semana_id, cantidad_periodo, cantidad_acumulada,
              observaciones, estado[EN_TERRENO|REVISADO|APROBADO], registrado_por, aprobado_por)
Adjunto(id, avance_id, tipo, url, tomado_en, geolocalizacion)
EstadoPago(id, obra_id, numero, semana_inicio_id, semana_fin_id, fecha_corte,
           estado[BORRADOR|PRESENTADO|OBSERVADO|APROBADO|PAGADO],
           cd, gg, utilidad, neto, iva, total, anticipo, retencion, multa, reajuste, liquido,
           snapshot_parametros_id, uf_conversion, uf_fecha)
EstadoPagoDetalle(id, estado_pago_id, partida_id, cant_anterior, cant_periodo, cant_acumulada,
                  pct_acumulado, monto_periodo, monto_acumulado)
ModificacionContrato(id, obra_id, tipo[EXTRAORDINARIA|AUMENTO|DISMINUCION], resolucion,
                     monto, presupuesto_version_resultante)
Auditoria(id, entidad, entidad_id, accion, usuario, timestamp, datos_antes, datos_despues)
```

---

## 9. Stack y requisitos no funcionales

- **Backend**: TypeScript (NestJS) o Python (FastAPI) + PostgreSQL. Cálculos monetarios en enteros
  o `numeric`, nunca en punto flotante binario.
- **Frontend**: React + TypeScript, tabla jerárquica expandible tipo árbol para el itemizado,
  carta Gantt semanal, curvas S. Interfaz **en español (Chile)**, formato `$ 1.234.567` y
  `dd-mm-aaaa`.
- **Carga de avance optimizada para terreno**: vista móvil, funcionamiento offline con
  sincronización posterior, captura de fotos, ingreso por cantidad ejecutada (no por porcentaje).
- Importación/exportación Excel (`openpyxl`/`exceljs`) y PDF.
- **Integración de indicadores**: capa `ProveedorIndicadores` con implementaciones conmutables
  (BCCh, SII, INE, mindicador) tras una interfaz común, para cambiar de fuente por configuración.
  Job programado con reintentos, backfill, caché local persistente y **modo sin red**: la
  aplicación debe seguir operando con los últimos valores conocidos, marcando lo provisional.
  Credenciales de fuentes en variables de entorno o gestor de secretos, nunca en el código.
- Autenticación con roles del §3, auditoría completa, respaldos.
- Pruebas automatizadas de todas las fórmulas del §5, con los números reales del §2.1 como caso
  de referencia, más pruebas de la resolución temporal de parámetros (§4.3) con fechas límite.

---

## 10. Criterios de aceptación

1. Al importar la plantilla de referencia, el sistema reproduce **116 partidas medibles**, 23
   agrupadores, 112 APU, y un contrato de **$807.962.805** con costo directo **$502.933.585**.
2. Cargando las cantidades de avance del corte 03-03-2025 se obtiene **6,67%** y
   **$53.890.565**; con las del corte 17-03-2025, **20,40%** y **$164.784.425**.
3. El EP n°2 generado a partir de ambos cortes arroja un monto de período de
   **$110.893.860** (164.784.425 − 53.890.565).
4. El avance por capítulo es ponderado por costo y la suma de los capítulos reproduce el avance
   global sin discrepancia.
5. El reporte semanal muestra, para cualquier semana ISO, avance programado, real, Δ y SPI, y
   excluye correctamente feriados legales del conteo de días hábiles.
6. El `Anexo 4` exportado de la partida 2.1.5 (Cubierta PV4) reproduce materiales 11.500, mano de
   obra 6.900 (incluye leyes sociales 50%), equipos 115 y precio unitario **18.515**.
7. Un cambio de cantidad contratada por modificación de contrato no altera retroactivamente los
   EP ya aprobados.
8. Las validaciones del §7 se ejecutan en la importación y quedan listadas en un informe.
9. **Parámetros por obra**: crear una segunda obra con GG 12%, utilidad 15% y utilidad calculada
   sobre CD+GG produce cierres económicos correctos sin tocar código ni afectar a la primera obra.
10. **Vigencia temporal**: cambiar `pct_gg` de 15% a 12% con vigencia 01-06-2025 deja intactos los
    EP con fecha de corte anterior, y el nuevo valor solo aplica a cortes posteriores. Intentar
    fijar una vigencia anterior a un EP aprobado es rechazado con un mensaje explícito.
11. **Indicadores**: la UF del 17-03-2025 se obtiene de la fuente oficial y queda registrada con
    valor, fuente, URL y fecha de consulta. Reabrir ese EP un año después muestra el mismo valor
    aunque la serie se haya corregido.
12. **Degradación sin red**: con la fuente caída, el sistema calcula con el último valor conocido,
    marca el EP como `PROVISIONAL` y la advertencia aparece en pantalla y en el PDF exportado.
13. **Trazabilidad**: el PDF de cualquier EP imprime al pie los parámetros y los indicadores
    usados, con su fuente y fecha de consulta.

---

## 11. Fuera de alcance (versión 1)

Contabilidad y facturación electrónica (SII), remuneraciones, control de bodega e inventario,
adquisiciones y órdenes de compra, prevención de riesgos. Dejar puntos de integración previstos,
pero no implementarlos.

---

## 12. Entregables

1. Modelo de datos y migraciones.
2. Importador de plantilla con informe de validación.
3. Módulos: presupuesto/APU, programación semanal, carga de avance, estados de pago, reportes.
4. Los cuatro reportes del §6 con exportación PDF/Excel.
5. Suite de pruebas cubriendo los criterios del §10.
6. Manual breve de uso por rol y guía para preparar la plantilla de una obra nueva.
