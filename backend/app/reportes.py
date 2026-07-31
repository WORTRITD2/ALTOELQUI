"""Reportes (§6 del prompt).

  6.1  Avance real según presupuesto
  6.2  Avance real vs programación por semana laboral hábil
  6.3  Estado de pago
  6.4  Tablero
"""
from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .core import parametros as P
from .core import programacion as PR
from .core.calculo import (
    calcular_avance,
    cierre_economico,
    redondear,
    resumen_por_capitulo,
)
from .core.calendario import CalendarioObra
from .core.indicadores import ServicioIndicadores
from .models import (
    APU,
    EstadoPago,
    Obra,
    Partida,
    Presupuesto,
    Programacion,
)

CERO = Decimal("0")


def _calendario(db: Session, obra: Obra, fecha: dt.date) -> CalendarioObra:
    return CalendarioObra(
        db,
        obra.id,
        dias_habiles=P.valor_vigente(db, obra.id, "dias_habiles_semana", fecha),
        horas_jornada=float(P.valor_vigente(db, obra.id, "horas_jornada", fecha)),
    )


# --------------------------------------------------------------------------
# 6.1 Avance real según presupuesto
# --------------------------------------------------------------------------
def reporte_presupuesto(
    db: Session, obra: Obra, presupuesto: Presupuesto, fecha: dt.date, solo_aprobados: bool = True
) -> dict:
    res = calcular_avance(db, presupuesto, fecha, solo_aprobados)
    cierre_contrato = cierre_economico(db, obra.id, fecha, res.contrato_cd)
    cierre_avance = cierre_economico(db, obra.id, fecha, res.avance_cd)

    # El contrato firmado manda sobre el recálculo: la plantilla redondea cada
    # línea del pie (ROUND), así que re-derivarlo puede diferir en pesos.
    contrato = cierre_contrato.as_dict()
    contrato_recalculado = dict(contrato)
    if presupuesto.total_contrato:
        contrato = {
            "cd": str(presupuesto.total_cd or cierre_contrato.cd),
            "gg": str(presupuesto.total_gg or redondear(cierre_contrato.gg)),
            "utilidad": str(presupuesto.total_utilidad or redondear(cierre_contrato.utilidad)),
            "neto": str(presupuesto.total_neto or redondear(cierre_contrato.neto)),
            "iva": str(presupuesto.total_iva or redondear(cierre_contrato.iva)),
            "total": str(presupuesto.total_contrato),
            "origen": "firmado en la plantilla",
            "parametros": cierre_contrato.parametros,
        }
    diferencia_contrato = (
        Decimal(contrato["total"]) - Decimal(contrato_recalculado["total"])
        if presupuesto.total_contrato
        else CERO
    )

    filas = []
    for f in res.filas:
        p = f.partida
        incidencia = (p.p_total or CERO) / res.contrato_cd if res.contrato_cd else CERO
        filas.append(
            {
                "codigo": p.codigo,
                "descripcion": p.descripcion,
                "unidad": p.unidad,
                "cantidad": str(p.cantidad),
                "p_unitario": str(p.p_unitario),
                "p_total": str(p.p_total),
                "cant_acumulada": str(f.cant_acumulada),
                "avance_pct": float(f.pct),
                "monto_avance": str(redondear(f.monto)),
                "saldo_cantidad": str(f.saldo_cantidad),
                "saldo_monto": str(redondear(f.saldo_monto)),
                "incidencia": float(incidencia),
            }
        )

    top = sorted(filas, key=lambda x: x["incidencia"], reverse=True)[:10]

    return {
        "obra": obra.nombre,
        "fecha_corte": fecha.isoformat(),
        "contrato": contrato,
        "contrato_recalculado": contrato_recalculado,
        "diferencia_contrato": str(diferencia_contrato),
        "avance": cierre_avance.as_dict(),
        "avance_pct": float(res.pct),
        "filas": filas,
        "capitulos": resumen_por_capitulo(res, nivel=1),
        "subcapitulos": resumen_por_capitulo(res, nivel=2),
        "top_incidencia": top,
        "advertencia_ponderacion": (
            "El avance de cada capítulo es ponderado por costo, nunca el promedio simple "
            "de porcentajes. Las partidas incluidas en gastos generales quedan fuera."
        ),
    }


# --------------------------------------------------------------------------
# 6.2 Avance real vs programación por semana hábil
# --------------------------------------------------------------------------
def reporte_semanal(
    db: Session,
    obra: Obra,
    presupuesto: Presupuesto,
    desde: dt.date,
    hasta: dt.date,
    programacion_id: int | None = None,
    solo_aprobados: bool = True,
) -> dict:
    cal = _calendario(db, obra, hasta)
    semanas = cal.semanas(desde, hasta)

    prog = None
    if programacion_id:
        prog = db.get(Programacion, programacion_id)
    else:
        prog = db.scalars(
            select(Programacion)
            .where(Programacion.presupuesto_id == presupuesto.id)
            .order_by(Programacion.es_linea_base.desc(), Programacion.version.desc())
        ).first()

    programado = (
        PR.programado_acumulado(db, prog.id, presupuesto.id) if prog else {}
    )

    filas = []
    ar_anterior = CERO
    ap_anterior = CERO
    contrato_cd = None

    for s in semanas:
        res = calcular_avance(db, presupuesto, s.fin, solo_aprobados)
        contrato_cd = res.contrato_cd
        ar = res.pct
        ap = _ultimo_programado(programado, s.iso)
        delta = ar - ap
        spi = (ar / ap) if ap else None
        filas.append(
            {
                "iso": s.iso,
                "inicio": s.inicio.isoformat(),
                "fin": s.fin.isoformat(),
                "dias_habiles": s.dias_habiles,
                "horas_habiles": s.horas_habiles,
                "feriados": s.feriados,
                "real_periodo": float(ar - ar_anterior),
                "real_acumulado": float(ar),
                "programado_periodo": float(ap - ap_anterior),
                "programado_acumulado": float(ap),
                "desviacion_pp": float(delta * 100),
                "spi": float(spi) if spi is not None else None,
                "monto_ejecutado_periodo": str(redondear((ar - ar_anterior) * res.contrato_cd)),
                "monto_acumulado": str(redondear(res.avance_cd)),
                "semaforo": _semaforo(ar, ap),
            }
        )
        ar_anterior, ap_anterior = ar, ap

    ultima = filas[-1] if filas else None
    criticas = _partidas_criticas(db, presupuesto, prog, hasta, solo_aprobados)
    recursos = _recursos_semana(db, presupuesto, prog, semanas[-1].iso if semanas else None, hasta,
                                solo_aprobados)

    return {
        "obra": obra.nombre,
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
        "programacion": {"id": prog.id, "nombre": prog.nombre, "version": prog.version} if prog else None,
        "semanas": filas,
        "curva_s": [
            {
                "iso": f["iso"],
                "programado": f["programado_acumulado"],
                "real": f["real_acumulado"],
            }
            for f in filas
        ],
        "resumen": {
            "real_acumulado": ultima["real_acumulado"] if ultima else 0,
            "programado_acumulado": ultima["programado_acumulado"] if ultima else 0,
            "desviacion_pp": ultima["desviacion_pp"] if ultima else 0,
            "spi": ultima["spi"] if ultima else None,
            "atraso_semanas": _atraso_semanas(filas),
            "proyeccion_termino": _proyeccion(filas, semanas),
            "contrato_cd": str(redondear(contrato_cd or CERO)),
        },
        "partidas_criticas": criticas,
        "recursos": recursos,
    }


def _ultimo_programado(programado: dict[str, Decimal], iso: str) -> Decimal:
    claves = [k for k in programado if k <= iso]
    return programado[max(claves)] if claves else CERO


def _semaforo(real: Decimal, programado: Decimal) -> str:
    if programado <= 0:
        return "SIN_PROGRAMA"
    ratio = real / programado
    if ratio >= 1:
        return "VERDE"
    if ratio >= Decimal("0.8"):
        return "AMARILLO"
    return "ROJO"


def _atraso_semanas(filas: list[dict]) -> float:
    """Cuántas semanas atrás quedó el avance real respecto del programa."""
    if not filas:
        return 0.0
    real = filas[-1]["real_acumulado"]
    for i, f in enumerate(filas):
        if f["programado_acumulado"] >= real:
            return round(len(filas) - 1 - i, 1)
    return 0.0


def _proyeccion(filas: list[dict], semanas) -> str | None:
    """Fecha estimada de término según el ritmo de las últimas 4 semanas hábiles."""
    if len(filas) < 2:
        return None
    ultimas = filas[-4:]
    ritmo = sum(f["real_periodo"] for f in ultimas) / len(ultimas)
    if ritmo <= 0:
        return None
    restante = 1.0 - filas[-1]["real_acumulado"]
    semanas_faltantes = restante / ritmo
    fin = dt.date.fromisoformat(filas[-1]["fin"]) + dt.timedelta(weeks=round(semanas_faltantes))
    return fin.isoformat()


def _partidas_criticas(db, presupuesto, prog, fecha, solo_aprobados) -> list[dict]:
    """Ordenadas por MONTO de atraso, no por porcentaje: ahí está el dinero."""
    if prog is None:
        return []
    res = calcular_avance(db, presupuesto, fecha, solo_aprobados)
    iso = fecha.strftime("%G-W%V")
    prog_acum = PR.acumulado_programado_por_partida(db, prog.id, iso)

    filas = []
    for f in res.filas:
        p = f.partida
        if not p.cantidad:
            continue
        cant_prog = prog_acum.get(p.id, CERO)
        pct_prog = min(cant_prog / p.cantidad, Decimal("1")) if p.cantidad else CERO
        atraso_pct = pct_prog - f.pct
        if atraso_pct <= 0:
            continue
        filas.append(
            {
                "codigo": p.codigo,
                "descripcion": p.descripcion,
                "unidad": p.unidad,
                "cantidad_programada": str(redondear(cant_prog, 2)),
                "cantidad_ejecutada": str(redondear(f.cant_acumulada, 2)),
                "avance_programado": float(pct_prog),
                "avance_real": float(f.pct),
                "atraso_pp": float(atraso_pct * 100),
                "monto_atraso": str(redondear(atraso_pct * (p.p_total or CERO))),
                "_orden": atraso_pct * (p.p_total or CERO),
                "semaforo": _semaforo(f.pct, pct_prog),
            }
        )
    filas.sort(key=lambda x: x["_orden"], reverse=True)
    for f in filas:
        f.pop("_orden")
    return filas[:15]


def _recursos_semana(db, presupuesto, prog, iso, fecha, solo_aprobados) -> dict:
    """HH y jornadas programadas vs reales, derivadas del rendimiento del APU.

    Alerta si el rendimiento real se desvía más de 20% del rendimiento del APU:
    es la señal temprana de que el precio unitario está en riesgo.
    """
    if prog is None or iso is None:
        return {"jornadas_programadas": 0, "jornadas_reales": 0, "alertas": []}

    programado = PR.programado_por_partida(db, prog.id, iso)
    res = calcular_avance(db, presupuesto, fecha, solo_aprobados)
    por_partida = {f.partida.id: f for f in res.filas}

    jornadas_prog = CERO
    jornadas_reales = CERO
    alertas = []
    for partida_id, cant_prog in programado.items():
        apu = db.scalars(select(APU).where(APU.partida_id == partida_id)).first()
        if not apu or not apu.rendimiento or apu.rendimiento <= 0:
            continue
        jornadas_prog += cant_prog / apu.rendimiento
        f = por_partida.get(partida_id)
        if f is None:
            continue
        jornadas_reales += f.cant_acumulada / apu.rendimiento

    return {
        "iso": iso,
        "jornadas_programadas": float(round(jornadas_prog, 2)),
        "jornadas_reales": float(round(jornadas_reales, 2)),
        "alertas": alertas,
        "nota": (
            "Las jornadas salen de cantidad / rendimiento del APU. Registrar jornadas reales "
            "de terreno permite comparar rendimiento real vs APU y anticipar la pérdida de margen."
        ),
    }


# --------------------------------------------------------------------------
# 6.3 Estado de pago
# --------------------------------------------------------------------------
def reporte_estado_pago(db: Session, ep: EstadoPago) -> dict:
    obra = db.get(Obra, ep.obra_id)
    decimales = int(P.valor_vigente(db, obra.id, "decimales_moneda", ep.fecha_corte))

    detalle = []
    for d in ep.detalle:
        p = db.get(Partida, d.partida_id)
        detalle.append(
            {
                "codigo": p.codigo,
                "descripcion": p.descripcion,
                "unidad": p.unidad,
                "cantidad_contratada": str(p.cantidad),
                "p_unitario": str(p.p_unitario),
                "cant_anterior": str(d.cant_anterior),
                "cant_periodo": str(d.cant_periodo),
                "cant_acumulada": str(d.cant_acumulada),
                "pct_acumulado": float(d.pct_acumulado),
                "monto_periodo": str(redondear(d.monto_periodo, decimales)),
                "monto_acumulado": str(redondear(d.monto_acumulado, decimales)),
                "saldo": str(redondear((p.p_total or CERO) - d.monto_acumulado, decimales)),
            }
        )
    detalle.sort(key=lambda x: x["codigo"])

    if ep.snapshot:
        parametros = json.loads(ep.snapshot.parametros_json)
        indicadores = json.loads(ep.snapshot.indicadores_json)
        origen_parametros = "snapshot congelado al aprobar"
    else:
        parametros = P.resolver_todos(db, obra.id, ep.fecha_corte)
        servicio = ServicioIndicadores(db)
        indicadores = {c: servicio.valor(c, ep.fecha_corte).as_dict() for c in ("UF", "UTM")}
        origen_parametros = "vigentes a la fecha de corte (EP aún no aprobado)"

    historico = [
        {
            "numero": e.numero,
            "fecha_corte": e.fecha_corte.isoformat(),
            "estado": e.estado,
            "total": str(redondear(e.total, decimales)),
            "pct_acumulado": float(e.pct_acum),
        }
        for e in db.scalars(
            select(EstadoPago).where(EstadoPago.obra_id == obra.id).order_by(EstadoPago.numero)
        ).all()
    ]

    pie = [
        f"GG {Decimal(parametros.get('pct_gg', '0')) * 100:.2f}% · "
        f"Utilidad {Decimal(parametros.get('pct_utilidad', '0')) * 100:.2f}% sobre "
        f"{parametros.get('base_utilidad')} · IVA {Decimal(parametros.get('pct_iva', '0')) * 100:.2f}%"
    ]
    for codigo, datos in indicadores.items():
        if datos.get("valor"):
            pie.append(
                f"{codigo} al {datos['fecha']} = {datos['valor']} ({datos.get('fuente')})"
                + (" [PROVISIONAL]" if datos.get("estado") == "PROVISIONAL" else "")
            )

    return {
        "obra": {
            "nombre": obra.nombre,
            "licitacion": obra.licitacion_id,
            "ubicacion": obra.ubicacion,
            "mandante": obra.mandante,
            "contratista": obra.contratista,
        },
        "numero": ep.numero,
        "estado": ep.estado,
        "fecha_corte": ep.fecha_corte.isoformat(),
        "periodo": {"desde": ep.iso_semana_inicio, "hasta": ep.iso_semana_fin},
        "periodo_economico": {
            "cd": str(redondear(ep.cd, decimales)),
            "gg": str(redondear(ep.gg, decimales)),
            "utilidad": str(redondear(ep.utilidad, decimales)),
            "neto": str(redondear(ep.neto, decimales)),
            "iva": str(redondear(ep.iva, decimales)),
            "total": str(redondear(ep.total, decimales)),
            "reajuste": str(redondear(ep.reajuste, decimales)),
            "anticipo": str(redondear(ep.anticipo, decimales)),
            "retencion": str(redondear(ep.retencion, decimales)),
            "multa": str(redondear(ep.multa, decimales)),
            "liquido": str(redondear(ep.liquido, decimales)),
        },
        "acumulado": {
            "cd": str(redondear(ep.cd_acum, decimales)),
            "total": str(redondear(ep.total_acum, decimales)),
            "pct": float(ep.pct_acum),
        },
        "detalle": detalle,
        "historico": historico,
        "parametros": parametros,
        "indicadores": indicadores,
        "origen_parametros": origen_parametros,
        "provisional": ep.provisional,
        "advertencias": (ep.advertencias or "").splitlines(),
        "pie_trazabilidad": pie,
    }


# --------------------------------------------------------------------------
# 6.4 Tablero
# --------------------------------------------------------------------------
def tablero(
    db: Session, obra: Obra, presupuesto: Presupuesto, fecha: dt.date, solo_aprobados: bool = True
) -> dict:
    res = calcular_avance(db, presupuesto, fecha, solo_aprobados)
    contrato = cierre_economico(db, obra.id, fecha, res.contrato_cd)
    avance = cierre_economico(db, obra.id, fecha, res.avance_cd)
    # el contrato firmado manda sobre el recálculo (§ redondeo de la plantilla)
    contrato_total = presupuesto.total_contrato or redondear(contrato.total)
    cal = _calendario(db, obra, fecha)
    semana = cal.semana(fecha.strftime("%G-W%V"))

    eps = list(
        db.scalars(
            select(EstadoPago).where(EstadoPago.obra_id == obra.id).order_by(EstadoPago.numero)
        ).all()
    )
    facturado = sum((e.total for e in eps if e.estado in ("APROBADO", "PAGADO")), CERO)

    inicio = obra.fecha_inicio or fecha
    semanal = reporte_semanal(db, obra, presupuesto, inicio, fecha, solo_aprobados=solo_aprobados)

    return {
        "obra": obra.nombre,
        "fecha": fecha.isoformat(),
        "semana": semana.as_dict(),
        "avance_fisico_pct": float(res.pct),
        "contrato_total": str(contrato_total),
        "avance_total": str(redondear(avance.total)),
        "facturado": str(redondear(facturado)),
        "por_facturar": str(redondear(avance.total - facturado)),
        "estados_pago": [
            {"numero": e.numero, "estado": e.estado, "total": str(redondear(e.total))} for e in eps
        ],
        "proximo_ep": (max((e.numero for e in eps), default=0) + 1),
        "spi": semanal["resumen"]["spi"],
        "desviacion_pp": semanal["resumen"]["desviacion_pp"],
        "atraso_semanas": semanal["resumen"]["atraso_semanas"],
        "proyeccion_termino": semanal["resumen"]["proyeccion_termino"],
        "partidas_criticas": semanal["partidas_criticas"][:5],
        "curva_s": semanal["curva_s"],
    }


# --------------------------------------------------------------------------
# Anexo 4 (formato oficial de APU para el mandante)
# --------------------------------------------------------------------------
def anexo_4(db: Session, obra: Obra, partida: Partida, fecha: dt.date) -> dict:
    apu = db.scalars(select(APU).where(APU.partida_id == partida.id)).first()
    if apu is None:
        return {"error": f"La partida {partida.codigo} no tiene APU asociado."}

    pct_leyes = P.pct(db, obra.id, "pct_leyes_sociales", fecha)
    secciones: dict[str, list] = {"MATERIAL": [], "MANO_OBRA": [], "EQUIPO": []}
    for r in sorted(apu.recursos, key=lambda x: (x.tipo, x.orden)):
        secciones.setdefault(r.tipo, []).append(
            {
                "descripcion": r.descripcion,
                "unidad": r.unidad,
                "cantidad": str(r.cantidad),
                "precio_unitario": str(r.precio_unitario),
                "valor_total": str(r.subtotal),
            }
        )

    total_mat = sum((r.subtotal or CERO for r in apu.recursos if r.tipo == "MATERIAL"), CERO)
    subtotal_mo = sum((r.subtotal or CERO for r in apu.recursos if r.tipo == "MANO_OBRA"), CERO)
    leyes = subtotal_mo * pct_leyes
    total_mo = subtotal_mo + leyes
    total_eq = sum((r.subtotal or CERO for r in apu.recursos if r.tipo == "EQUIPO"), CERO)
    costo_directo = total_mat + total_mo + total_eq

    return {
        "titulo": "Anexo N°4 — ANÁLISIS DE PRECIOS UNITARIOS",
        "obra": obra.nombre,
        "licitacion": obra.licitacion_id,
        "contratista": obra.contratista,
        "partida": {
            "codigo": partida.codigo,
            "descripcion": partida.descripcion,
            "unidad": partida.unidad,
            "rendimiento": str(apu.rendimiento) if apu.rendimiento else None,
        },
        "materiales": {"items": secciones["MATERIAL"], "total": str(redondear(total_mat))},
        "mano_obra": {
            "items": secciones["MANO_OBRA"],
            "subtotal": str(redondear(subtotal_mo)),
            "pct_leyes_sociales": float(pct_leyes),
            "leyes_sociales": str(redondear(leyes)),
            "total": str(redondear(total_mo)),
        },
        "equipos": {"items": secciones["EQUIPO"], "total": str(redondear(total_eq))},
        "precio_unitario": str(redondear(costo_directo)),
        "p_unitario_itemizado": str(partida.p_unitario),
        "cuadra": abs(costo_directo - (partida.p_unitario or CERO)) <= Decimal("1"),
    }
