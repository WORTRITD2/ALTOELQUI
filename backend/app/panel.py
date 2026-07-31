"""Panel de control de gerencia.

Vista de cartera (todas las obras) y vista de una obra con filtros. Pensado
para supervisión: pocos números, bien elegidos, y la posibilidad de acotar por
capítulo, semana, estado o semáforo sin tener que leer el itemizado completo.

Los filtros se aplican en el servidor: el móvil recibe solo lo que va a mostrar.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import reportes
from .core import parametros as P
from .core import programacion as PR
from .core.calculo import calcular_avance, cierre_economico, redondear, resumen_por_capitulo
from .models import EstadoPago, Obra, Presupuesto, Programacion

CERO = Decimal("0")


@dataclass
class Filtros:
    capitulo: str | None = None       # prefijo de código: "2" o "2.1"
    semaforo: str | None = None       # VERDE | AMARILLO | ROJO | SIN_PROGRAMA
    estado: str | None = None         # SIN_INICIAR | EN_CURSO | TERMINADA
    texto: str | None = None
    incidencia_min: float = 0.0
    orden: str = "incidencia"         # incidencia | atraso | avance | codigo
    limite: int = 200
    desplazamiento: int = 0


def _presupuesto_vigente(db: Session, obra_id: int) -> Presupuesto | None:
    return db.scalars(
        select(Presupuesto)
        .where(Presupuesto.obra_id == obra_id)
        .order_by(Presupuesto.version.desc())
    ).first()


def _semaforo(real: Decimal, programado: Decimal) -> str:
    if programado <= 0:
        return "SIN_PROGRAMA"
    ratio = real / programado
    if ratio >= 1:
        return "VERDE"
    if ratio >= Decimal("0.8"):
        return "AMARILLO"
    return "ROJO"


def _estado_partida(pct: Decimal) -> str:
    if pct <= 0:
        return "SIN_INICIAR"
    if pct >= 1:
        return "TERMINADA"
    return "EN_CURSO"


# --------------------------------------------------------------------------
# Cartera: todas las obras de un vistazo
# --------------------------------------------------------------------------
def cartera(db: Session, fecha: dt.date, solo_aprobados: bool = True) -> dict:
    filas = []
    total_contrato = total_ejecutado = total_facturado = CERO

    for obra in db.scalars(select(Obra).order_by(Obra.nombre)).all():
        pres = _presupuesto_vigente(db, obra.id)
        if pres is None:
            filas.append(
                {
                    "id": obra.id,
                    "nombre": obra.nombre,
                    "mandante": obra.mandante,
                    "sin_presupuesto": True,
                    "alertas": ["Sin presupuesto importado"],
                }
            )
            continue

        res = calcular_avance(db, pres, fecha, solo_aprobados)
        cierre = cierre_economico(db, obra.id, fecha, res.avance_cd)
        contrato = pres.total_contrato or redondear(
            cierre_economico(db, obra.id, fecha, res.contrato_cd).total
        )
        eps = list(
            db.scalars(
                select(EstadoPago).where(EstadoPago.obra_id == obra.id).order_by(EstadoPago.numero)
            ).all()
        )
        facturado = sum((e.total for e in eps if e.estado in ("APROBADO", "PAGADO")), CERO)

        prog = db.scalars(
            select(Programacion)
            .where(Programacion.presupuesto_id == pres.id)
            .order_by(Programacion.es_linea_base.desc(), Programacion.version.desc())
        ).first()
        programado = CERO
        if prog:
            acum = PR.programado_acumulado(db, prog.id, pres.id)
            claves = [k for k in acum if k <= fecha.strftime("%G-W%V")]
            programado = acum[max(claves)] if claves else CERO

        spi = float(res.pct / programado) if programado else None
        alertas = _alertas(obra, res.pct, programado, eps, prog)

        total_contrato += Decimal(str(contrato))
        total_ejecutado += cierre.total
        total_facturado += facturado

        filas.append(
            {
                "id": obra.id,
                "nombre": obra.nombre,
                "mandante": obra.mandante,
                "ubicacion": obra.ubicacion,
                "fecha_inicio": obra.fecha_inicio.isoformat() if obra.fecha_inicio else None,
                "avance_pct": float(res.pct),
                "programado_pct": float(programado),
                "desviacion_pp": float((res.pct - programado) * 100),
                "spi": spi,
                "semaforo": _semaforo(res.pct, programado),
                "contrato": str(contrato),
                "ejecutado": str(redondear(cierre.total)),
                "facturado": str(redondear(facturado)),
                "por_facturar": str(redondear(cierre.total - facturado)),
                "estados_pago": len(eps),
                "ultimo_ep": (
                    {
                        "numero": eps[-1].numero,
                        "estado": eps[-1].estado,
                        "total": str(redondear(eps[-1].total)),
                        "fecha_corte": eps[-1].fecha_corte.isoformat(),
                    }
                    if eps
                    else None
                ),
                "alertas": alertas,
                "sin_presupuesto": False,
            }
        )

    activas = [f for f in filas if not f.get("sin_presupuesto")]
    avance_cartera = (
        float(total_ejecutado / total_contrato) if total_contrato else 0.0
    )
    return {
        "fecha": fecha.isoformat(),
        "totales": {
            "obras": len(filas),
            "contrato": str(redondear(total_contrato)),
            "ejecutado": str(redondear(total_ejecutado)),
            "facturado": str(redondear(total_facturado)),
            "por_facturar": str(redondear(total_ejecutado - total_facturado)),
            "avance_ponderado": avance_cartera,
            "en_rojo": len([f for f in activas if f["semaforo"] == "ROJO"]),
            "con_alertas": len([f for f in activas if f["alertas"]]),
        },
        "obras": filas,
    }


def _alertas(obra, real: Decimal, programado: Decimal, eps, prog) -> list[str]:
    salida = []
    if prog is None:
        salida.append("Sin programación cargada: no hay contra qué comparar")
    elif programado > 0 and real < programado * Decimal("0.8"):
        salida.append(f"Atraso: {float((programado - real) * 100):.1f} puntos bajo el programa")
    borradores = [e for e in eps if e.estado == "BORRADOR"]
    if borradores:
        salida.append(f"EP N°{borradores[-1].numero} sin presentar")
    observados = [e for e in eps if e.estado == "OBSERVADO"]
    if observados:
        salida.append(f"EP N°{observados[-1].numero} observado por el mandante")
    provisionales = [e for e in eps if e.provisional]
    if provisionales:
        salida.append(f"EP N°{provisionales[-1].numero} calculado con indicadores provisionales")
    return salida


# --------------------------------------------------------------------------
# Detalle de una obra, con filtros
# --------------------------------------------------------------------------
def obra_filtrada(
    db: Session,
    obra: Obra,
    presupuesto: Presupuesto,
    fecha: dt.date,
    filtros: Filtros,
    solo_aprobados: bool = True,
) -> dict:
    res = calcular_avance(db, presupuesto, fecha, solo_aprobados)
    cierre = cierre_economico(db, obra.id, fecha, res.avance_cd)
    contrato = presupuesto.total_contrato or redondear(
        cierre_economico(db, obra.id, fecha, res.contrato_cd).total
    )

    prog = db.scalars(
        select(Programacion)
        .where(Programacion.presupuesto_id == presupuesto.id)
        .order_by(Programacion.es_linea_base.desc(), Programacion.version.desc())
    ).first()
    prog_acum_partida = (
        PR.acumulado_programado_por_partida(db, prog.id, fecha.strftime("%G-W%V")) if prog else {}
    )

    partidas = []
    for f in res.filas:
        p = f.partida
        cant_prog = prog_acum_partida.get(p.id, CERO)
        pct_prog = min(cant_prog / p.cantidad, Decimal("1")) if p.cantidad else CERO
        incidencia = (p.p_total or CERO) / res.contrato_cd if res.contrato_cd else CERO
        atraso = max(pct_prog - f.pct, CERO)
        partidas.append(
            {
                "id": p.id,
                "codigo": p.codigo,
                "capitulo": p.codigo.split(".")[0],
                "descripcion": p.descripcion,
                "unidad": p.unidad,
                "cantidad": str(p.cantidad),
                "ejecutado": str(f.cant_acumulada),
                "avance_pct": float(f.pct),
                "programado_pct": float(pct_prog),
                "monto_avance": str(redondear(f.monto)),
                "p_total": str(p.p_total),
                "saldo": str(redondear(f.saldo_monto)),
                "incidencia": float(incidencia),
                "atraso_pp": float(atraso * 100),
                "monto_atraso": str(redondear(atraso * (p.p_total or CERO))),
                "semaforo": _semaforo(f.pct, pct_prog),
                "estado": _estado_partida(f.pct),
                "_orden_atraso": float(atraso * (p.p_total or CERO)),
            }
        )

    filtradas = _aplicar_filtros(partidas, filtros)
    total_filtrado = len(filtradas)
    resumen_filtro = _resumen(filtradas, res.contrato_cd)

    claves = {
        "incidencia": lambda x: -x["incidencia"],
        "atraso": lambda x: -x["_orden_atraso"],
        "avance": lambda x: x["avance_pct"],
        "codigo": lambda x: [int(n) if n.isdigit() else 0 for n in x["codigo"].split(".")],
    }
    filtradas.sort(key=claves.get(filtros.orden, claves["incidencia"]))
    pagina = filtradas[filtros.desplazamiento: filtros.desplazamiento + filtros.limite]
    for x in pagina:
        x.pop("_orden_atraso", None)

    semanal = reportes.reporte_semanal(
        db, obra, presupuesto, obra.fecha_inicio or fecha, fecha, solo_aprobados=solo_aprobados
    )

    return {
        "obra": {
            "id": obra.id,
            "nombre": obra.nombre,
            "mandante": obra.mandante,
            "ubicacion": obra.ubicacion,
            "contratista": obra.contratista,
        },
        "fecha": fecha.isoformat(),
        "kpis": {
            "avance_pct": float(res.pct),
            "programado_pct": semanal["resumen"]["programado_acumulado"],
            "desviacion_pp": semanal["resumen"]["desviacion_pp"],
            "spi": semanal["resumen"]["spi"],
            "atraso_semanas": semanal["resumen"]["atraso_semanas"],
            "proyeccion_termino": semanal["resumen"]["proyeccion_termino"],
            "contrato": str(contrato),
            "ejecutado": str(redondear(cierre.total)),
            "semana": semanal["semanas"][-1]["iso"] if semanal["semanas"] else None,
        },
        "curva_s": semanal["curva_s"],
        "capitulos": resumen_por_capitulo(res, nivel=1),
        "subcapitulos": resumen_por_capitulo(res, nivel=2),
        "partidas": pagina,
        "paginacion": {
            "total": total_filtrado,
            "limite": filtros.limite,
            "desplazamiento": filtros.desplazamiento,
        },
        "resumen_filtro": resumen_filtro,
        "criticas": sorted(
            [p for p in filtradas if p["semaforo"] == "ROJO"],
            key=lambda x: -float(x["monto_atraso"]),
        )[:10],
        "semanas": semanal["semanas"],
    }


def _aplicar_filtros(partidas: list[dict], f: Filtros) -> list[dict]:
    salida = partidas
    if f.capitulo:
        prefijo = f.capitulo if f.capitulo.endswith(".") else f.capitulo + "."
        salida = [p for p in salida if p["codigo"] == f.capitulo or p["codigo"].startswith(prefijo)]
    if f.semaforo:
        salida = [p for p in salida if p["semaforo"] == f.semaforo.upper()]
    if f.estado:
        salida = [p for p in salida if p["estado"] == f.estado.upper()]
    if f.texto:
        q = f.texto.lower()
        salida = [
            p for p in salida if q in p["descripcion"].lower() or q in p["codigo"].lower()
        ]
    if f.incidencia_min:
        salida = [p for p in salida if p["incidencia"] >= f.incidencia_min]
    return list(salida)


def _resumen(partidas: list[dict], contrato_cd: Decimal) -> dict:
    monto = sum(Decimal(p["p_total"]) for p in partidas) if partidas else CERO
    avance = sum(Decimal(p["monto_avance"]) for p in partidas) if partidas else CERO
    return {
        "partidas": len(partidas),
        "monto_contratado": str(redondear(monto)),
        "monto_ejecutado": str(redondear(avance)),
        "avance_pct": float(avance / monto) if monto else 0.0,
        "incidencia": float(monto / contrato_cd) if contrato_cd else 0.0,
        "en_rojo": len([p for p in partidas if p["semaforo"] == "ROJO"]),
        "sin_iniciar": len([p for p in partidas if p["estado"] == "SIN_INICIAR"]),
        "terminadas": len([p for p in partidas if p["estado"] == "TERMINADA"]),
        "monto_atraso": str(
            redondear(sum((Decimal(p["monto_atraso"]) for p in partidas), CERO))
        ),
    }


def capitulos_disponibles(db: Session, presupuesto: Presupuesto) -> list[dict]:
    """Para poblar el filtro sin traer el itemizado completo."""
    from .models import Partida

    filas = db.scalars(
        select(Partida).where(Partida.presupuesto_id == presupuesto.id).order_by(Partida.orden)
    ).all()
    vistos: dict[str, str] = {}
    for p in filas:
        if p.es_agrupador and p.nivel <= 2:
            vistos.setdefault(p.codigo, p.descripcion)
    return [{"codigo": c, "descripcion": d} for c, d in vistos.items()]
