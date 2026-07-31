"""Parámetros de obra con vigencia temporal (§4.2 y §4.3).

Invariantes:
  - Nunca se hace UPDATE destructivo sobre un valor: editar cierra la vigencia
    anterior y abre una nueva.
  - Todo cálculo resuelve con la fecha de corte del período, jamás con "hoy".
  - No se admite abrir una vigencia que caiga antes de un estado de pago
    aprobado: eso exige nota de ajuste explícita.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Auditoria, EstadoPago, ParametroDefinicion, ParametroObra


class ParametroError(ValueError):
    """Cambio de parámetro rechazado."""


@dataclass(frozen=True)
class Definicion:
    clave: str
    etiqueta: str
    tipo: str
    unidad: str | None = None
    valor_min: str | None = None
    valor_max: str | None = None
    opciones: tuple[str, ...] = ()
    defecto: str | None = None
    descripcion: str = ""


# Catálogo del sistema. Los defectos son los de Chile; cada obra los sobreescribe.
CATALOGO: tuple[Definicion, ...] = (
    Definicion("pct_gg", "Gastos generales", "PORCENTAJE", "%", "0", "1", (), "0.15",
               "Se aplica sobre el costo directo del corte."),
    Definicion("pct_utilidad", "Utilidad", "PORCENTAJE", "%", "0", "1", (), "0.20",
               "Se aplica sobre la base definida en base_utilidad."),
    Definicion("base_utilidad", "Base de cálculo de la utilidad", "ENUM", None, None, None,
               ("CD", "CD+GG"), "CD",
               "Otras bases de licitación calculan la utilidad sobre CD+GG."),
    Definicion("pct_iva", "IVA", "PORCENTAJE", "%", "0", "1", (), "0.19",
               "Cambia por ley; por eso es un parámetro con vigencia."),
    Definicion("pct_leyes_sociales", "Leyes sociales", "PORCENTAJE", "%", "0", "2", (), "0.50",
               "Recargo sobre la mano de obra del APU."),
    Definicion("pct_anticipo", "Anticipo", "PORCENTAJE", "%", "0", "1", (), "0",
               "Porcentaje del EP que amortiza el anticipo recibido."),
    Definicion("pct_retencion", "Retención", "PORCENTAJE", "%", "0", "1", (), "0",
               "Porcentaje retenido de cada EP hasta la recepción."),
    Definicion("multa_diaria", "Multa diaria por atraso", "MONTO", "CLP/UTM", "0", None, (), "0",
               "Se convierte con la UTM del mes del atraso si la unidad es UTM."),
    Definicion("multa_unidad", "Unidad de la multa", "ENUM", None, None, None,
               ("CLP", "UTM", "PERMIL_CONTRATO"), "CLP", ""),
    Definicion("plazo_dias", "Plazo contractual", "ENTERO", "días", "0", None, (), "0", ""),
    Definicion("plazo_tipo_dias", "Tipo de días del plazo", "ENUM", None, None, None,
               ("CORRIDOS", "HABILES"), "CORRIDOS", ""),
    Definicion("dias_habiles_semana", "Días hábiles de la semana", "TEXTO", None, None, None, (),
               "1,2,3,4,5", "Días ISO: 1=lunes … 7=domingo."),
    Definicion("horas_jornada", "Horas de jornada diaria", "MONTO", "h", "0", "24", (), "8.5", ""),
    Definicion("moneda", "Moneda del contrato", "ENUM", None, None, None, ("CLP", "UF"), "CLP", ""),
    Definicion("reajuste", "Mecanismo de reajuste", "ENUM", None, None, None,
               ("SIN_REAJUSTE", "UF", "IPC", "POLINOMICO"), "SIN_REAJUSTE", ""),
    Definicion("fecha_conversion_uf", "Fecha de conversión UF", "ENUM", None, None, None,
               ("CORTE", "PRESENTACION", "PAGO"), "CORTE",
               "Qué fecha manda para convertir UF a pesos, según las bases."),
    Definicion("politica_redondeo", "Política de redondeo", "ENUM", None, None, None,
               ("TOTALES", "CADA_PARTIDA", "SIN_REDONDEO"), "TOTALES",
               "La plantilla redondea solo en los totales del pie."),
    Definicion("decimales_moneda", "Decimales de la moneda", "ENTERO", None, "0", "6", (), "0", ""),
)

CATALOGO_POR_CLAVE = {d.clave: d for d in CATALOGO}


def sembrar_catalogo(db: Session) -> None:
    for d in CATALOGO:
        if db.get(ParametroDefinicion, d.clave):
            continue
        db.add(
            ParametroDefinicion(
                clave=d.clave,
                etiqueta=d.etiqueta,
                tipo=d.tipo,
                unidad=d.unidad,
                valor_min=Decimal(d.valor_min) if d.valor_min is not None else None,
                valor_max=Decimal(d.valor_max) if d.valor_max is not None else None,
                opciones="|".join(d.opciones) if d.opciones else None,
                valor_defecto_sistema=d.defecto,
                descripcion=d.descripcion,
            )
        )
    db.commit()


def _validar(clave: str, valor: str) -> str:
    d = CATALOGO_POR_CLAVE.get(clave)
    if d is None:
        raise ParametroError(f"Parámetro desconocido: {clave}")
    if d.tipo in ("PORCENTAJE", "MONTO"):
        try:
            v = Decimal(str(valor))
        except Exception as exc:  # noqa: BLE001
            raise ParametroError(f"{clave}: valor no numérico ({valor})") from exc
        if d.valor_min is not None and v < Decimal(d.valor_min):
            raise ParametroError(f"{clave}: {v} es menor que el mínimo {d.valor_min}")
        if d.valor_max is not None and v > Decimal(d.valor_max):
            raise ParametroError(f"{clave}: {v} supera el máximo {d.valor_max}")
        return str(v)
    if d.tipo == "ENTERO":
        return str(int(Decimal(str(valor))))
    if d.tipo == "ENUM" and str(valor) not in d.opciones:
        raise ParametroError(f"{clave}: '{valor}' no está en {d.opciones}")
    return str(valor)


def fijar(
    db: Session,
    obra_id: int,
    clave: str,
    valor,
    vigente_desde: dt.date,
    motivo: str | None = None,
    usuario: str | None = None,
    documento_respaldo_url: str | None = None,
    permitir_retroactivo: bool = False,
) -> ParametroObra:
    """Abre una vigencia nueva cerrando la anterior. No sobrescribe historia."""
    valor = _validar(clave, valor)

    if not permitir_retroactivo:
        ep = db.scalars(
            select(EstadoPago)
            .where(
                EstadoPago.obra_id == obra_id,
                EstadoPago.estado.in_(("APROBADO", "PAGADO")),
                EstadoPago.fecha_corte >= vigente_desde,
            )
            .order_by(EstadoPago.fecha_corte)
        ).first()
        if ep is not None:
            raise ParametroError(
                f"Vigencia {vigente_desde:%d-%m-%Y} anterior al EP N°{ep.numero} "
                f"(aprobado, corte {ep.fecha_corte:%d-%m-%Y}). Requiere nota de ajuste explícita."
            )

    previos = db.scalars(
        select(ParametroObra)
        .where(ParametroObra.obra_id == obra_id, ParametroObra.clave == clave)
        .order_by(ParametroObra.vigente_desde)
    ).all()

    for p in previos:
        if p.vigente_desde == vigente_desde:
            raise ParametroError(
                f"Ya existe un valor de {clave} con vigencia {vigente_desde:%d-%m-%Y}"
            )
        if p.vigente_desde < vigente_desde and (
            p.vigente_hasta is None or p.vigente_hasta > vigente_desde
        ):
            p.vigente_hasta = vigente_desde

    # si se inserta una vigencia anterior a otras, acotarla al siguiente inicio
    posteriores = [p.vigente_desde for p in previos if p.vigente_desde > vigente_desde]
    hasta = min(posteriores) if posteriores else None

    nuevo = ParametroObra(
        obra_id=obra_id,
        clave=clave,
        valor=valor,
        vigente_desde=vigente_desde,
        vigente_hasta=hasta,
        motivo=motivo,
        usuario=usuario,
        documento_respaldo_url=documento_respaldo_url,
    )
    db.add(nuevo)
    db.add(
        Auditoria(
            entidad="ParametroObra",
            entidad_id=f"{obra_id}:{clave}",
            accion="FIJAR",
            usuario=usuario,
            datos_antes=json.dumps([{"valor": p.valor, "desde": str(p.vigente_desde)} for p in previos]),
            datos_despues=json.dumps({"valor": valor, "desde": str(vigente_desde), "motivo": motivo}),
        )
    )
    db.commit()
    return nuevo


def valor_vigente(db: Session, obra_id: int, clave: str, fecha: dt.date) -> str:
    """El valor cuyo intervalo [vigente_desde, vigente_hasta) contiene `fecha`."""
    fila = db.scalars(
        select(ParametroObra)
        .where(
            ParametroObra.obra_id == obra_id,
            ParametroObra.clave == clave,
            ParametroObra.vigente_desde <= fecha,
        )
        .order_by(ParametroObra.vigente_desde.desc())
    ).first()
    if fila is not None and (fila.vigente_hasta is None or fila.vigente_hasta > fecha):
        return fila.valor
    d = CATALOGO_POR_CLAVE.get(clave)
    if d is None or d.defecto is None:
        raise ParametroError(f"Sin valor para {clave} al {fecha:%d-%m-%Y} y sin defecto de sistema")
    return d.defecto


def pct(db: Session, obra_id: int, clave: str, fecha: dt.date) -> Decimal:
    return Decimal(valor_vigente(db, obra_id, clave, fecha))


def resolver_todos(db: Session, obra_id: int, fecha: dt.date) -> dict[str, str]:
    """Todos los parámetros vigentes a una fecha. Es lo que se congela en el EP."""
    return {d.clave: valor_vigente(db, obra_id, d.clave, fecha) for d in CATALOGO}


def historial(db: Session, obra_id: int, clave: str | None = None) -> list[ParametroObra]:
    q = select(ParametroObra).where(ParametroObra.obra_id == obra_id)
    if clave:
        q = q.where(ParametroObra.clave == clave)
    return list(db.scalars(q.order_by(ParametroObra.clave, ParametroObra.vigente_desde)).all())


def aplicar_plantilla(
    db: Session, obra_id: int, valores: dict[str, str], vigente_desde: dt.date, usuario: str | None = None
) -> None:
    for clave, valor in valores.items():
        fijar(db, obra_id, clave, valor, vigente_desde, motivo="Alta de obra", usuario=usuario)
