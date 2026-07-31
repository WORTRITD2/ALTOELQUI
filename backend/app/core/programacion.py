"""Programación en semanas laborales hábiles (§5).

La cantidad contratada de cada partida se reparte entre las semanas hábiles de
su ventana, usando el rendimiento del APU para estimar jornadas:

    jornadas_necesarias(i) = cantidad(i) / rendimiento_APU(i)

La línea base generada aquí es un punto de partida editable, no un dogma: cada
partida admite fechas y cuadrillas propias.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import APU, Partida, Programacion, ProgramacionPartida, ProgramacionSemanal
from .calendario import CalendarioObra, iso_semana
from .calculo import partidas_medibles

CERO = Decimal("0")
JORNADAS_POR_DEFECTO = Decimal("5")  # si la partida no tiene rendimiento en el APU


@dataclass
class VentanaPartida:
    partida: Partida
    inicio: dt.date
    fin: dt.date
    jornadas: Decimal
    cuadrillas: Decimal


def jornadas_de(db: Session, partida: Partida) -> Decimal:
    apu = db.scalars(select(APU).where(APU.partida_id == partida.id)).first()
    if apu and apu.rendimiento and apu.rendimiento > 0 and partida.cantidad:
        return partida.cantidad / apu.rendimiento
    return JORNADAS_POR_DEFECTO


def generar_linea_base(
    db: Session,
    presupuesto,
    calendario: CalendarioObra,
    fecha_inicio: dt.date,
    plazo_dias: int,
    cuadrillas: Decimal = Decimal("1"),
    nombre: str = "Línea base",
) -> Programacion:
    """Reparte la obra completa en el plazo contractual, ponderando por jornadas."""
    partidas = partidas_medibles(db, presupuesto.id)
    jornadas = {p.id: jornadas_de(db, p) for p in partidas}
    total_jornadas = sum(jornadas.values(), CERO) or Decimal("1")

    fecha_fin = fecha_inicio + dt.timedelta(days=plazo_dias)

    prog = Programacion(
        presupuesto_id=presupuesto.id,
        version=1,
        es_linea_base=True,
        nombre=nombre,
    )
    ultima = db.scalars(
        select(Programacion)
        .where(Programacion.presupuesto_id == presupuesto.id)
        .order_by(Programacion.version.desc())
    ).first()
    if ultima:
        prog.version = ultima.version + 1
        prog.es_linea_base = False
    db.add(prog)
    db.flush()

    dias_totales = max((fecha_fin - fecha_inicio).days, 1)
    acumulado = CERO

    for p in partidas:
        j = jornadas[p.id]
        inicio_frac = acumulado / total_jornadas
        acumulado += j
        fin_frac = acumulado / total_jornadas

        inicio = fecha_inicio + dt.timedelta(days=int(dias_totales * float(inicio_frac)))
        fin = fecha_inicio + dt.timedelta(days=max(int(dias_totales * float(fin_frac)), 1))
        if fin <= inicio:
            fin = inicio + dt.timedelta(days=6)

        db.add(
            ProgramacionPartida(
                programacion_id=prog.id,
                partida_id=p.id,
                fecha_inicio=inicio,
                fecha_fin=fin,
                cuadrillas=cuadrillas,
                rendimiento_asignado=(p.cantidad / j) if j else None,
            )
        )
        for iso, cantidad in _repartir(calendario, p.cantidad or CERO, inicio, fin).items():
            db.add(
                ProgramacionSemanal(
                    programacion_id=prog.id,
                    partida_id=p.id,
                    iso_semana=iso,
                    cantidad_programada=cantidad,
                )
            )
    db.commit()
    return prog


def _repartir(
    calendario: CalendarioObra, cantidad: Decimal, inicio: dt.date, fin: dt.date
) -> dict[str, Decimal]:
    """Distribuye una cantidad entre las semanas de la ventana, a prorrata de días hábiles."""
    if cantidad <= CERO:
        return {}
    dias: list[dt.date] = []
    cur = inicio
    while cur <= fin:
        if calendario.es_habil(cur):
            dias.append(cur)
        cur += dt.timedelta(days=1)
    if not dias:
        return {iso_semana(inicio): cantidad}

    por_semana: dict[str, int] = {}
    for d in dias:
        por_semana[iso_semana(d)] = por_semana.get(iso_semana(d), 0) + 1

    total = Decimal(len(dias))
    salida: dict[str, Decimal] = {}
    repartido = CERO
    claves = list(por_semana)
    for i, iso in enumerate(claves):
        if i == len(claves) - 1:
            salida[iso] = cantidad - repartido  # el resto al final: no se pierde nada
        else:
            parte = (cantidad * Decimal(por_semana[iso]) / total)
            salida[iso] = parte
            repartido += parte
    return salida


def programado_acumulado(
    db: Session, programacion_id: int, presupuesto_id: int
) -> dict[str, Decimal]:
    """Avance financiero programado acumulado por semana ISO (ponderado por costo)."""
    filas = db.scalars(
        select(ProgramacionSemanal).where(ProgramacionSemanal.programacion_id == programacion_id)
    ).all()
    partidas = {p.id: p for p in partidas_medibles(db, presupuesto_id)}
    contrato = sum((p.p_total or CERO for p in partidas.values()), CERO)

    por_semana: dict[str, Decimal] = {}
    for f in filas:
        p = partidas.get(f.partida_id)
        if not p or not p.cantidad:
            continue
        monto = (p.p_total or CERO) * (f.cantidad_programada / p.cantidad)
        por_semana[f.iso_semana] = por_semana.get(f.iso_semana, CERO) + monto

    acumulado = CERO
    salida: dict[str, Decimal] = {}
    for iso in sorted(por_semana):
        acumulado += por_semana[iso]
        salida[iso] = acumulado / contrato if contrato else CERO
    return salida


def programado_por_partida(
    db: Session, programacion_id: int, iso: str
) -> dict[int, Decimal]:
    filas = db.scalars(
        select(ProgramacionSemanal).where(
            ProgramacionSemanal.programacion_id == programacion_id,
            ProgramacionSemanal.iso_semana == iso,
        )
    ).all()
    return {f.partida_id: f.cantidad_programada for f in filas}


def acumulado_programado_por_partida(
    db: Session, programacion_id: int, hasta_iso: str
) -> dict[int, Decimal]:
    filas = db.scalars(
        select(ProgramacionSemanal).where(
            ProgramacionSemanal.programacion_id == programacion_id,
            ProgramacionSemanal.iso_semana <= hasta_iso,
        )
    ).all()
    salida: dict[int, Decimal] = {}
    for f in filas:
        salida[f.partida_id] = salida.get(f.partida_id, CERO) + f.cantidad_programada
    return salida
