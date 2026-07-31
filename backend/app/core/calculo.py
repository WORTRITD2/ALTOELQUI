"""Motor de cálculo (§5 del prompt).

Todo porcentaje se resuelve con `valor_vigente(obra, clave, fecha_de_corte)`,
nunca con la fecha actual. El avance financiero es siempre ponderado por costo:
jamás el promedio simple de porcentajes.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    AvanceSemanal,
    EstadoPago,
    EstadoPagoDetalle,
    Obra,
    Partida,
    Presupuesto,
    SnapshotParametros,
)
from . import parametros as P
from .indicadores import ServicioIndicadores

CERO = Decimal("0")


def redondear(valor: Decimal, decimales: int = 0) -> Decimal:
    exp = Decimal(1).scaleb(-decimales)
    return Decimal(valor).quantize(exp, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------
# Avance
# --------------------------------------------------------------------------
@dataclass
class FilaAvance:
    partida: Partida
    cant_acumulada: Decimal
    pct: Decimal
    monto: Decimal

    @property
    def saldo_cantidad(self) -> Decimal:
        return (self.partida.cantidad or CERO) - self.cant_acumulada

    @property
    def saldo_monto(self) -> Decimal:
        return (self.partida.p_total or CERO) - self.monto


@dataclass
class ResultadoAvance:
    fecha: dt.date
    filas: list[FilaAvance]
    contrato_cd: Decimal
    avance_cd: Decimal

    @property
    def pct(self) -> Decimal:
        return self.avance_cd / self.contrato_cd if self.contrato_cd else CERO


def partidas_medibles(db: Session, presupuesto_id: int) -> list[Partida]:
    filas = db.scalars(
        select(Partida).where(Partida.presupuesto_id == presupuesto_id).order_by(Partida.orden)
    ).all()
    return [p for p in filas if p.es_medible]


def acumulados(
    db: Session, obra_id: int, fecha: dt.date, solo_aprobados: bool = True
) -> dict[int, Decimal]:
    """Cantidad acumulada por partida a una fecha de corte."""
    q = select(AvanceSemanal).where(
        AvanceSemanal.obra_id == obra_id, AvanceSemanal.fecha_medicion <= fecha
    )
    if solo_aprobados:
        q = q.where(AvanceSemanal.estado == "APROBADO")
    filas = list(db.scalars(q.order_by(AvanceSemanal.fecha_medicion)).all())
    salida: dict[int, Decimal] = {}
    for f in filas:  # ordenadas: la última medición manda
        salida[f.partida_id] = f.cantidad_acumulada
    return salida


def calcular_avance(
    db: Session, presupuesto: Presupuesto, fecha: dt.date, solo_aprobados: bool = True
) -> ResultadoAvance:
    acum = acumulados(db, presupuesto.obra_id, fecha, solo_aprobados)
    filas: list[FilaAvance] = []
    contrato = CERO
    avance = CERO
    for p in partidas_medibles(db, presupuesto.id):
        contrato += p.p_total or CERO
        cant = acum.get(p.id, CERO)
        cantidad = p.cantidad or CERO
        pct = (cant / cantidad) if cantidad else CERO
        monto = (p.p_total or CERO) * pct
        avance += monto
        filas.append(FilaAvance(partida=p, cant_acumulada=cant, pct=pct, monto=monto))
    return ResultadoAvance(fecha=fecha, filas=filas, contrato_cd=contrato, avance_cd=avance)


# --------------------------------------------------------------------------
# Cierre económico
# --------------------------------------------------------------------------
@dataclass
class Cierre:
    cd: Decimal
    gg: Decimal
    utilidad: Decimal
    neto: Decimal
    iva: Decimal
    total: Decimal
    parametros: dict[str, str] = field(default_factory=dict)

    def as_dict(self, decimales: int = 0) -> dict:
        return {
            "cd": str(redondear(self.cd, decimales)),
            "gg": str(redondear(self.gg, decimales)),
            "utilidad": str(redondear(self.utilidad, decimales)),
            "neto": str(redondear(self.neto, decimales)),
            "iva": str(redondear(self.iva, decimales)),
            "total": str(redondear(self.total, decimales)),
            "cd_exacto": str(self.cd),
            "total_exacto": str(self.total),
            "parametros": self.parametros,
        }


def cierre_economico(db: Session, obra_id: int, fecha: dt.date, cd: Decimal) -> Cierre:
    """CD → GG → utilidad → neto → IVA → total, con los parámetros vigentes a `fecha`.

    La cadena se calcula exacta y se redondea solo al presentar, igual que la
    columna de avance de la plantilla (`J150 = J147+J148+J149`, sin ROUND).
    El total del CONTRATO no se re-deriva: se importa firmado desde la plantilla
    (`Presupuesto.total_contrato`), que sí trae ROUND en cada línea del pie.
    """
    pct_gg = P.pct(db, obra_id, "pct_gg", fecha)
    pct_util = P.pct(db, obra_id, "pct_utilidad", fecha)
    base_util = P.valor_vigente(db, obra_id, "base_utilidad", fecha)
    pct_iva = P.pct(db, obra_id, "pct_iva", fecha)
    gg = cd * pct_gg
    base = cd + gg if base_util == "CD+GG" else cd
    utilidad = base * pct_util
    neto = cd + gg + utilidad
    iva = neto * pct_iva
    total = neto + iva
    return Cierre(
        cd=cd,
        gg=gg,
        utilidad=utilidad,
        neto=neto,
        iva=iva,
        total=total,
        parametros={
            "pct_gg": str(pct_gg),
            "pct_utilidad": str(pct_util),
            "base_utilidad": base_util,
            "pct_iva": str(pct_iva),
        },
    )


# --------------------------------------------------------------------------
# Agregación jerárquica (ponderada por costo)
# --------------------------------------------------------------------------
def raiz_capitulo(codigo: str, nivel: int = 1) -> str:
    return ".".join(str(codigo).split(".")[:nivel])


def resumen_por_capitulo(res: ResultadoAvance, nivel: int = 1) -> list[dict]:
    grupos: dict[str, dict] = {}
    for f in res.filas:
        clave = raiz_capitulo(f.partida.codigo, nivel)
        g = grupos.setdefault(clave, {"capitulo": clave, "contrato": CERO, "avance": CERO, "partidas": 0})
        g["contrato"] += f.partida.p_total or CERO
        g["avance"] += f.monto
        g["partidas"] += 1
    salida = []
    for g in grupos.values():
        pct = g["avance"] / g["contrato"] if g["contrato"] else CERO
        salida.append(
            {
                "capitulo": g["capitulo"],
                "contrato": str(redondear(g["contrato"])),
                "avance": str(redondear(g["avance"])),
                "pct": float(pct),
                "incidencia": float(g["contrato"] / res.contrato_cd) if res.contrato_cd else 0.0,
                "partidas": g["partidas"],
            }
        )
    return sorted(salida, key=lambda x: x["capitulo"])


# --------------------------------------------------------------------------
# Estados de pago
# --------------------------------------------------------------------------
class EstadoPagoError(ValueError):
    pass


def _ep_anterior(db: Session, obra_id: int, numero: int) -> EstadoPago | None:
    return db.scalars(
        select(EstadoPago)
        .where(EstadoPago.obra_id == obra_id, EstadoPago.numero < numero)
        .order_by(EstadoPago.numero.desc())
    ).first()


def generar_estado_pago(
    db: Session,
    obra: Obra,
    presupuesto: Presupuesto,
    fecha_corte: dt.date,
    numero: int | None = None,
    dias_atraso: int = 0,
    solo_aprobados: bool = True,
) -> EstadoPago:
    """EP n = acumulado a la fecha − acumulado del EP n−1. Siempre incremental."""
    if numero is None:
        ultimo = db.scalars(
            select(EstadoPago).where(EstadoPago.obra_id == obra.id).order_by(EstadoPago.numero.desc())
        ).first()
        numero = (ultimo.numero + 1) if ultimo else 1

    existente = db.scalars(
        select(EstadoPago).where(EstadoPago.obra_id == obra.id, EstadoPago.numero == numero)
    ).first()
    if existente and existente.estado in ("APROBADO", "PAGADO"):
        raise EstadoPagoError(f"El EP N°{numero} está {existente.estado} y es inmutable.")
    if existente:
        db.delete(existente)
        db.commit()

    anterior = _ep_anterior(db, obra.id, numero)
    if anterior and fecha_corte <= anterior.fecha_corte:
        raise EstadoPagoError(
            f"La fecha de corte debe ser posterior al EP N°{anterior.numero} "
            f"({anterior.fecha_corte:%d-%m-%Y})."
        )

    actual = calcular_avance(db, presupuesto, fecha_corte, solo_aprobados)
    acum_ant = (
        acumulados(db, obra.id, anterior.fecha_corte, solo_aprobados) if anterior else {}
    )

    decimales = int(P.valor_vigente(db, obra.id, "decimales_moneda", fecha_corte))
    cierre_acum = cierre_economico(db, obra.id, fecha_corte, actual.avance_cd)

    cd_ant = CERO
    detalles: list[EstadoPagoDetalle] = []
    for f in actual.filas:
        cant_ant = acum_ant.get(f.partida.id, CERO)
        cantidad = f.partida.cantidad or CERO
        monto_ant = (f.partida.p_total or CERO) * (cant_ant / cantidad if cantidad else CERO)
        cd_ant += monto_ant
        if f.cant_acumulada == CERO and cant_ant == CERO:
            continue
        detalles.append(
            EstadoPagoDetalle(
                partida_id=f.partida.id,
                cant_anterior=cant_ant,
                cant_periodo=f.cant_acumulada - cant_ant,
                cant_acumulada=f.cant_acumulada,
                pct_acumulado=f.pct,
                monto_periodo=f.monto - monto_ant,
                monto_acumulado=f.monto,
            )
        )

    cierre_ant = cierre_economico(db, obra.id, fecha_corte, cd_ant)
    cd_periodo = actual.avance_cd - cd_ant
    cierre_per = cierre_economico(db, obra.id, fecha_corte, cd_periodo)

    total_periodo = redondear(cierre_acum.total, decimales) - redondear(cierre_ant.total, decimales)

    # Descuentos y recargos, con parámetros vigentes a la fecha de corte
    pct_anticipo = P.pct(db, obra.id, "pct_anticipo", fecha_corte)
    pct_retencion = P.pct(db, obra.id, "pct_retencion", fecha_corte)
    anticipo = total_periodo * pct_anticipo
    retencion = total_periodo * pct_retencion

    advertencias: list[str] = []
    multa = CERO
    if dias_atraso > 0:
        multa_diaria = P.pct(db, obra.id, "multa_diaria", fecha_corte)
        unidad = P.valor_vigente(db, obra.id, "multa_unidad", fecha_corte)
        if unidad == "UTM":
            lectura = ServicioIndicadores(db).valor("UTM", fecha_corte)
            if lectura.valor is None:
                advertencias.append(lectura.advertencia or "UTM sin dato: multa no calculada")
            else:
                multa = multa_diaria * lectura.valor * dias_atraso
                if lectura.estado == "PROVISIONAL":
                    advertencias.append(lectura.advertencia or "UTM provisional")
        elif unidad == "PERMIL_CONTRATO":
            multa = (actual.contrato_cd * multa_diaria / Decimal("1000")) * dias_atraso
        else:
            multa = multa_diaria * dias_atraso

    # Moneda del contrato
    moneda = P.valor_vigente(db, obra.id, "moneda", fecha_corte)
    uf_valor = None
    if moneda == "UF":
        lectura = ServicioIndicadores(db).valor("UF", fecha_corte)
        uf_valor = lectura.valor
        if lectura.valor is None or lectura.estado == "PROVISIONAL":
            advertencias.append(lectura.advertencia or "UF provisional")

    ep = EstadoPago(
        obra_id=obra.id,
        numero=numero,
        fecha_corte=fecha_corte,
        iso_semana_inicio=(
            None
            if anterior is None
            else (anterior.fecha_corte + dt.timedelta(days=1)).strftime("%G-W%V")
        ),
        iso_semana_fin=fecha_corte.strftime("%G-W%V"),
        estado="BORRADOR",
        cd_acum=actual.avance_cd,
        total_acum=cierre_acum.total,
        pct_acum=actual.pct,
        cd=cd_periodo,
        gg=cierre_per.gg,
        utilidad=cierre_per.utilidad,
        neto=cierre_per.neto,
        iva=cierre_per.iva,
        total=total_periodo,
        anticipo=anticipo,
        retencion=retencion,
        multa=multa,
        reajuste=CERO,
        liquido=total_periodo - anticipo - retencion - multa,
        moneda=moneda,
        uf_conversion=uf_valor,
        uf_fecha=fecha_corte if moneda == "UF" else None,
        provisional=bool(advertencias),
        advertencias="\n".join(advertencias) or None,
    )
    ep.detalle = detalles
    db.add(ep)
    db.commit()
    return ep


def aprobar_estado_pago(db: Session, ep: EstadoPago, usuario: str) -> EstadoPago:
    """Congela el snapshot de parámetros e indicadores. Desde aquí el EP es inmutable."""
    if ep.estado in ("APROBADO", "PAGADO"):
        raise EstadoPagoError(f"El EP N°{ep.numero} ya está {ep.estado}.")

    params = P.resolver_todos(db, ep.obra_id, ep.fecha_corte)
    servicio = ServicioIndicadores(db)
    indicadores = {
        codigo: servicio.valor(codigo, ep.fecha_corte).as_dict() for codigo in ("UF", "UTM")
    }
    db.add(
        SnapshotParametros(
            estado_pago_id=ep.id,
            parametros_json=json.dumps(params, ensure_ascii=False, indent=2),
            indicadores_json=json.dumps(indicadores, ensure_ascii=False, indent=2),
        )
    )
    ep.estado = "APROBADO"
    ep.aprobado_por = usuario
    ep.aprobado_en = dt.datetime.now(dt.timezone.utc)
    db.commit()
    return ep
