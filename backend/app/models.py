"""Modelo de datos (§8 del prompt).

Regla estructural: los porcentajes NO son columnas de Obra. Viven en
ParametroObra con vigencia temporal, y todo cálculo los resuelve con la fecha
de corte del período.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, Money


def ahora() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# --------------------------------------------------------------------------
# Organización y obra
# --------------------------------------------------------------------------
class Organizacion(Base):
    __tablename__ = "organizacion"
    id: Mapped[int] = mapped_column(primary_key=True)
    razon_social: Mapped[str] = mapped_column(String(200))
    rut: Mapped[str | None] = mapped_column(String(20))
    obras: Mapped[list["Obra"]] = relationship(back_populates="organizacion")


class PlantillaParametros(Base):
    """Los parámetros que la constructora usa habitualmente. Base de obras nuevas."""

    __tablename__ = "plantilla_parametros"
    id: Mapped[int] = mapped_column(primary_key=True)
    organizacion_id: Mapped[int] = mapped_column(ForeignKey("organizacion.id"))
    nombre: Mapped[str] = mapped_column(String(120))
    descripcion: Mapped[str | None] = mapped_column(Text)
    valores: Mapped[list["PlantillaParametroValor"]] = relationship(
        back_populates="plantilla", cascade="all, delete-orphan"
    )


class PlantillaParametroValor(Base):
    __tablename__ = "plantilla_parametro_valor"
    id: Mapped[int] = mapped_column(primary_key=True)
    plantilla_id: Mapped[int] = mapped_column(ForeignKey("plantilla_parametros.id"))
    clave: Mapped[str] = mapped_column(String(60))
    valor: Mapped[str] = mapped_column(String(60))
    plantilla: Mapped[PlantillaParametros] = relationship(back_populates="valores")


class Obra(Base):
    __tablename__ = "obra"
    id: Mapped[int] = mapped_column(primary_key=True)
    organizacion_id: Mapped[int] = mapped_column(ForeignKey("organizacion.id"))
    nombre: Mapped[str] = mapped_column(String(250))
    licitacion_id: Mapped[str | None] = mapped_column(String(120))
    mandante: Mapped[str | None] = mapped_column(String(200))
    contratista: Mapped[str | None] = mapped_column(String(200))
    ubicacion: Mapped[str | None] = mapped_column(String(250))
    fecha_inicio: Mapped[dt.date | None] = mapped_column(Date)
    plazo_dias: Mapped[int | None] = mapped_column(Integer)
    estado: Mapped[str] = mapped_column(String(30), default="EN_EJECUCION")
    creada_en: Mapped[dt.datetime] = mapped_column(DateTime, default=ahora)

    organizacion: Mapped[Organizacion] = relationship(back_populates="obras")
    presupuestos: Mapped[list["Presupuesto"]] = relationship(back_populates="obra")


# --------------------------------------------------------------------------
# Parámetros con vigencia temporal (§4.3)
# --------------------------------------------------------------------------
class ParametroDefinicion(Base):
    """Catálogo: qué parámetros existen, de qué tipo y en qué rango son válidos."""

    __tablename__ = "parametro_definicion"
    clave: Mapped[str] = mapped_column(String(60), primary_key=True)
    etiqueta: Mapped[str] = mapped_column(String(120))
    tipo: Mapped[str] = mapped_column(String(20))  # PORCENTAJE|MONTO|ENTERO|ENUM|BOOLEAN|TEXTO
    unidad: Mapped[str | None] = mapped_column(String(20))
    valor_min: Mapped[Decimal | None] = mapped_column(Money)
    valor_max: Mapped[Decimal | None] = mapped_column(Money)
    opciones: Mapped[str | None] = mapped_column(String(250))  # ENUM: separadas por |
    valor_defecto_sistema: Mapped[str | None] = mapped_column(String(60))
    descripcion: Mapped[str | None] = mapped_column(Text)


class ParametroObra(Base):
    """Un valor vigente en un intervalo. Editar = cerrar vigencia y abrir otra."""

    __tablename__ = "parametro_obra"
    __table_args__ = (UniqueConstraint("obra_id", "clave", "vigente_desde"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    obra_id: Mapped[int] = mapped_column(ForeignKey("obra.id"))
    clave: Mapped[str] = mapped_column(String(60))
    valor: Mapped[str] = mapped_column(String(60))
    vigente_desde: Mapped[dt.date] = mapped_column(Date)
    vigente_hasta: Mapped[dt.date | None] = mapped_column(Date)  # NULL = vigente hoy
    motivo: Mapped[str | None] = mapped_column(Text)
    documento_respaldo_url: Mapped[str | None] = mapped_column(String(400))
    usuario: Mapped[str | None] = mapped_column(String(120))
    creado_en: Mapped[dt.datetime] = mapped_column(DateTime, default=ahora)


# --------------------------------------------------------------------------
# Indicadores económicos externos (§4.4)
# --------------------------------------------------------------------------
class IndicadorValor(Base):
    """Serie histórica. Una corrección de la fuente NO sobrescribe: se registra
    como un valor nuevo, y la lectura toma el más reciente por fuente oficial."""

    __tablename__ = "indicador_valor"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(20))  # UF, UTM, UTA, IPC, USD_OBS, IMM
    fecha: Mapped[dt.date] = mapped_column(Date)
    valor: Mapped[Decimal] = mapped_column(Money)
    fuente: Mapped[str] = mapped_column(String(20))  # BCCH|SII|INE|MINDICADOR|MANUAL
    url_origen: Mapped[str | None] = mapped_column(String(400))
    obtenido_en: Mapped[dt.datetime] = mapped_column(DateTime, default=ahora)
    estado: Mapped[str] = mapped_column(String(15), default="CONFIRMADO")  # |PROVISIONAL
    usuario: Mapped[str | None] = mapped_column(String(120))
    nota: Mapped[str | None] = mapped_column(Text)


class SincronizacionIndicador(Base):
    __tablename__ = "sincronizacion_indicador"
    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(20))
    ejecutada_en: Mapped[dt.datetime] = mapped_column(DateTime, default=ahora)
    rango_desde: Mapped[dt.date | None] = mapped_column(Date)
    rango_hasta: Mapped[dt.date | None] = mapped_column(Date)
    estado: Mapped[str] = mapped_column(String(15))  # OK|PARCIAL|ERROR
    fuente: Mapped[str | None] = mapped_column(String(20))
    valores_nuevos: Mapped[int] = mapped_column(Integer, default=0)
    detalle: Mapped[str | None] = mapped_column(Text)


class Feriado(Base):
    __tablename__ = "feriado"
    __table_args__ = (UniqueConstraint("fecha", "obra_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    fecha: Mapped[dt.date] = mapped_column(Date)
    nombre: Mapped[str] = mapped_column(String(150))
    obra_id: Mapped[int | None] = mapped_column(ForeignKey("obra.id"))  # NULL = nacional
    irrenunciable: Mapped[bool] = mapped_column(Boolean, default=False)
    fuente: Mapped[str] = mapped_column(String(20), default="SEMILLA")


# --------------------------------------------------------------------------
# Presupuesto, partidas y APU
# --------------------------------------------------------------------------
class Presupuesto(Base):
    __tablename__ = "presupuesto"
    id: Mapped[int] = mapped_column(primary_key=True)
    obra_id: Mapped[int] = mapped_column(ForeignKey("obra.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    estado: Mapped[str] = mapped_column(String(20), default="BORRADOR")
    vigente_desde: Mapped[dt.date | None] = mapped_column(Date)
    origen_archivo: Mapped[str | None] = mapped_column(String(300))
    creado_en: Mapped[dt.datetime] = mapped_column(DateTime, default=ahora)

    # Totales del contrato tal como fueron firmados (se importan, no se re-derivan)
    total_cd: Mapped[Decimal | None] = mapped_column(Money)
    total_gg: Mapped[Decimal | None] = mapped_column(Money)
    total_utilidad: Mapped[Decimal | None] = mapped_column(Money)
    total_neto: Mapped[Decimal | None] = mapped_column(Money)
    total_iva: Mapped[Decimal | None] = mapped_column(Money)
    total_contrato: Mapped[Decimal | None] = mapped_column(Money)

    obra: Mapped[Obra] = relationship(back_populates="presupuestos")
    partidas: Mapped[list["Partida"]] = relationship(
        back_populates="presupuesto", cascade="all, delete-orphan"
    )


class Partida(Base):
    __tablename__ = "partida"
    id: Mapped[int] = mapped_column(primary_key=True)
    presupuesto_id: Mapped[int] = mapped_column(ForeignKey("presupuesto.id"))
    codigo: Mapped[str] = mapped_column(String(40))
    codigo_padre: Mapped[str | None] = mapped_column(String(40))
    nivel: Mapped[int] = mapped_column(Integer, default=1)
    descripcion: Mapped[str] = mapped_column(Text)
    unidad: Mapped[str | None] = mapped_column(String(30))
    unidad_original: Mapped[str | None] = mapped_column(String(40))
    cantidad: Mapped[Decimal | None] = mapped_column(Money)
    p_unitario: Mapped[Decimal | None] = mapped_column(Money)  # costo directo
    p_total: Mapped[Decimal | None] = mapped_column(Money)
    es_agrupador: Mapped[bool] = mapped_column(Boolean, default=False)
    es_incluida_en_gg: Mapped[bool] = mapped_column(Boolean, default=False)
    orden: Mapped[int] = mapped_column(Integer, default=0)
    fila_origen: Mapped[int | None] = mapped_column(Integer)

    presupuesto: Mapped[Presupuesto] = relationship(back_populates="partidas")
    apu: Mapped["APU | None"] = relationship(
        back_populates="partida", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def es_medible(self) -> bool:
        return not self.es_agrupador and not self.es_incluida_en_gg and self.p_total is not None


class APU(Base):
    __tablename__ = "apu"
    id: Mapped[int] = mapped_column(primary_key=True)
    partida_id: Mapped[int] = mapped_column(ForeignKey("partida.id"))
    rendimiento: Mapped[Decimal | None] = mapped_column(Money)  # unidades por jornada
    unidad_pago: Mapped[str | None] = mapped_column(String(30))
    fecha_precios: Mapped[dt.date | None] = mapped_column(Date)
    hoja_origen: Mapped[str | None] = mapped_column(String(40))
    fila_origen: Mapped[int | None] = mapped_column(Integer)

    partida: Mapped[Partida] = relationship(back_populates="apu")
    recursos: Mapped[list["APURecurso"]] = relationship(
        back_populates="apu", cascade="all, delete-orphan"
    )

    def costo_directo(self, pct_leyes_sociales: Decimal) -> Decimal:
        total = Decimal("0")
        for r in self.recursos:
            total += r.subtotal or Decimal("0")
            if r.tipo == "MANO_OBRA":
                total += (r.subtotal or Decimal("0")) * pct_leyes_sociales
        return total


class APURecurso(Base):
    __tablename__ = "apu_recurso"
    id: Mapped[int] = mapped_column(primary_key=True)
    apu_id: Mapped[int] = mapped_column(ForeignKey("apu.id"))
    tipo: Mapped[str] = mapped_column(String(15))  # MATERIAL|MANO_OBRA|EQUIPO
    descripcion: Mapped[str] = mapped_column(Text)
    unidad: Mapped[str | None] = mapped_column(String(30))
    cantidad: Mapped[Decimal | None] = mapped_column(Money)
    precio_unitario: Mapped[Decimal | None] = mapped_column(Money)
    subtotal: Mapped[Decimal | None] = mapped_column(Money)
    orden: Mapped[int] = mapped_column(Integer, default=0)

    apu: Mapped[APU] = relationship(back_populates="recursos")


class ListaPrecios(Base):
    __tablename__ = "lista_precios"
    id: Mapped[int] = mapped_column(primary_key=True)
    organizacion_id: Mapped[int] = mapped_column(ForeignKey("organizacion.id"))
    nombre: Mapped[str] = mapped_column(String(150))
    vigente_desde: Mapped[dt.date] = mapped_column(Date)
    vigente_hasta: Mapped[dt.date | None] = mapped_column(Date)
    moneda: Mapped[str] = mapped_column(String(10), default="CLP")


class PrecioInsumo(Base):
    __tablename__ = "precio_insumo"
    id: Mapped[int] = mapped_column(primary_key=True)
    lista_id: Mapped[int] = mapped_column(ForeignKey("lista_precios.id"))
    tipo: Mapped[str] = mapped_column(String(15))
    descripcion: Mapped[str] = mapped_column(Text)
    unidad: Mapped[str | None] = mapped_column(String(30))
    precio: Mapped[Decimal] = mapped_column(Money)
    proveedor: Mapped[str | None] = mapped_column(String(150))


# --------------------------------------------------------------------------
# Programación y avance
# --------------------------------------------------------------------------
class Programacion(Base):
    __tablename__ = "programacion"
    id: Mapped[int] = mapped_column(primary_key=True)
    presupuesto_id: Mapped[int] = mapped_column(ForeignKey("presupuesto.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    es_linea_base: Mapped[bool] = mapped_column(Boolean, default=True)
    nombre: Mapped[str | None] = mapped_column(String(150))
    creada_en: Mapped[dt.datetime] = mapped_column(DateTime, default=ahora)
    creada_por: Mapped[str | None] = mapped_column(String(120))

    detalle: Mapped[list["ProgramacionPartida"]] = relationship(
        back_populates="programacion", cascade="all, delete-orphan"
    )
    semanal: Mapped[list["ProgramacionSemanal"]] = relationship(
        back_populates="programacion", cascade="all, delete-orphan"
    )


class ProgramacionPartida(Base):
    __tablename__ = "programacion_partida"
    id: Mapped[int] = mapped_column(primary_key=True)
    programacion_id: Mapped[int] = mapped_column(ForeignKey("programacion.id"))
    partida_id: Mapped[int] = mapped_column(ForeignKey("partida.id"))
    fecha_inicio: Mapped[dt.date] = mapped_column(Date)
    fecha_fin: Mapped[dt.date] = mapped_column(Date)
    cuadrillas: Mapped[Decimal] = mapped_column(Money, default=Decimal("1"))
    rendimiento_asignado: Mapped[Decimal | None] = mapped_column(Money)

    programacion: Mapped[Programacion] = relationship(back_populates="detalle")


class ProgramacionSemanal(Base):
    __tablename__ = "programacion_semanal"
    __table_args__ = (UniqueConstraint("programacion_id", "partida_id", "iso_semana"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    programacion_id: Mapped[int] = mapped_column(ForeignKey("programacion.id"))
    partida_id: Mapped[int] = mapped_column(ForeignKey("partida.id"))
    iso_semana: Mapped[str] = mapped_column(String(8))  # 2025-W10
    cantidad_programada: Mapped[Decimal] = mapped_column(Money)

    programacion: Mapped[Programacion] = relationship(back_populates="semanal")


class AvanceSemanal(Base):
    """Medición en terreno. Se registra CANTIDAD ejecutada, jamás un porcentaje."""

    __tablename__ = "avance_semanal"
    __table_args__ = (UniqueConstraint("obra_id", "partida_id", "iso_semana"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    obra_id: Mapped[int] = mapped_column(ForeignKey("obra.id"))
    partida_id: Mapped[int] = mapped_column(ForeignKey("partida.id"))
    iso_semana: Mapped[str] = mapped_column(String(8))
    fecha_medicion: Mapped[dt.date] = mapped_column(Date)
    cantidad_periodo: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    cantidad_acumulada: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    observaciones: Mapped[str | None] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(String(15), default="EN_TERRENO")
    registrado_por: Mapped[str | None] = mapped_column(String(120))
    aprobado_por: Mapped[str | None] = mapped_column(String(120))
    aprobado_en: Mapped[dt.datetime | None] = mapped_column(DateTime)


class Adjunto(Base):
    __tablename__ = "adjunto"
    id: Mapped[int] = mapped_column(primary_key=True)
    avance_id: Mapped[int] = mapped_column(ForeignKey("avance_semanal.id"))
    tipo: Mapped[str] = mapped_column(String(20), default="FOTO")
    url: Mapped[str] = mapped_column(String(500))
    tomado_en: Mapped[dt.datetime | None] = mapped_column(DateTime)
    geolocalizacion: Mapped[str | None] = mapped_column(String(80))


# --------------------------------------------------------------------------
# Estados de pago
# --------------------------------------------------------------------------
class EstadoPago(Base):
    __tablename__ = "estado_pago"
    __table_args__ = (UniqueConstraint("obra_id", "numero"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    obra_id: Mapped[int] = mapped_column(ForeignKey("obra.id"))
    numero: Mapped[int] = mapped_column(Integer)
    iso_semana_inicio: Mapped[str | None] = mapped_column(String(8))
    iso_semana_fin: Mapped[str | None] = mapped_column(String(8))
    fecha_corte: Mapped[dt.date] = mapped_column(Date)
    estado: Mapped[str] = mapped_column(String(15), default="BORRADOR")

    # acumulado a la fecha de corte
    cd_acum: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    total_acum: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    pct_acum: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    # del período
    cd: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    gg: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    utilidad: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    neto: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    iva: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    reajuste: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    anticipo: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    retencion: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    multa: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    liquido: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))

    moneda: Mapped[str] = mapped_column(String(10), default="CLP")
    uf_conversion: Mapped[Decimal | None] = mapped_column(Money)
    uf_fecha: Mapped[dt.date | None] = mapped_column(Date)
    provisional: Mapped[bool] = mapped_column(Boolean, default=False)
    advertencias: Mapped[str | None] = mapped_column(Text)

    creado_en: Mapped[dt.datetime] = mapped_column(DateTime, default=ahora)
    aprobado_en: Mapped[dt.datetime | None] = mapped_column(DateTime)
    aprobado_por: Mapped[str | None] = mapped_column(String(120))

    detalle: Mapped[list["EstadoPagoDetalle"]] = relationship(
        back_populates="estado_pago", cascade="all, delete-orphan"
    )
    snapshot: Mapped["SnapshotParametros | None"] = relationship(
        back_populates="estado_pago", uselist=False, cascade="all, delete-orphan"
    )


class EstadoPagoDetalle(Base):
    __tablename__ = "estado_pago_detalle"
    id: Mapped[int] = mapped_column(primary_key=True)
    estado_pago_id: Mapped[int] = mapped_column(ForeignKey("estado_pago.id"))
    partida_id: Mapped[int] = mapped_column(ForeignKey("partida.id"))
    cant_anterior: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    cant_periodo: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    cant_acumulada: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    pct_acumulado: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    monto_periodo: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    monto_acumulado: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))

    estado_pago: Mapped[EstadoPago] = relationship(back_populates="detalle")


class SnapshotParametros(Base):
    """Fotografía inmutable de lo usado para calcular un EP aprobado."""

    __tablename__ = "snapshot_parametros"
    id: Mapped[int] = mapped_column(primary_key=True)
    estado_pago_id: Mapped[int] = mapped_column(ForeignKey("estado_pago.id"))
    parametros_json: Mapped[str] = mapped_column(Text)
    indicadores_json: Mapped[str] = mapped_column(Text, default="{}")
    congelado_en: Mapped[dt.datetime] = mapped_column(DateTime, default=ahora)

    estado_pago: Mapped[EstadoPago] = relationship(back_populates="snapshot")


class ModificacionContrato(Base):
    __tablename__ = "modificacion_contrato"
    id: Mapped[int] = mapped_column(primary_key=True)
    obra_id: Mapped[int] = mapped_column(ForeignKey("obra.id"))
    tipo: Mapped[str] = mapped_column(String(20))  # EXTRAORDINARIA|AUMENTO|DISMINUCION
    resolucion: Mapped[str | None] = mapped_column(String(150))
    fecha: Mapped[dt.date] = mapped_column(Date)
    monto: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    presupuesto_version_resultante: Mapped[int | None] = mapped_column(Integer)


class ValidacionImportacion(Base):
    """Informe del importador (§7). Nada se silencia."""

    __tablename__ = "validacion_importacion"
    id: Mapped[int] = mapped_column(primary_key=True)
    presupuesto_id: Mapped[int] = mapped_column(ForeignKey("presupuesto.id"))
    regla: Mapped[str] = mapped_column(String(60))
    severidad: Mapped[str] = mapped_column(String(15))  # INFO|ADVERTENCIA|ERROR
    ubicacion: Mapped[str | None] = mapped_column(String(60))
    mensaje: Mapped[str] = mapped_column(Text)
    valor_original: Mapped[str | None] = mapped_column(String(200))
    valor_corregido: Mapped[str | None] = mapped_column(String(200))


class Auditoria(Base):
    __tablename__ = "auditoria"
    id: Mapped[int] = mapped_column(primary_key=True)
    entidad: Mapped[str] = mapped_column(String(60))
    entidad_id: Mapped[str] = mapped_column(String(40))
    accion: Mapped[str] = mapped_column(String(40))
    usuario: Mapped[str | None] = mapped_column(String(120))
    timestamp: Mapped[dt.datetime] = mapped_column(DateTime, default=ahora)
    datos_antes: Mapped[str | None] = mapped_column(Text)
    datos_despues: Mapped[str | None] = mapped_column(Text)
