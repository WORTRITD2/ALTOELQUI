"""API REST."""
from __future__ import annotations

import datetime as dt
import os
import shutil
import tempfile
from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import export_excel, panel, reportes
from .core import parametros as P
from .core import programacion as PR
from .core.calculo import (
    EstadoPagoError,
    aprobar_estado_pago,
    calcular_avance,
    generar_estado_pago,
)
from .core.calendario import CalendarioObra, sembrar_feriados
from .core.indicadores import ServicioIndicadores
from .db import get_session
from .importador import importar_plantilla, leer_mediciones
from .models import (
    AvanceSemanal,
    EstadoPago,
    Feriado,
    IndicadorValor,
    Obra,
    Organizacion,
    Partida,
    PlantillaParametros,
    PlantillaParametroValor,
    Presupuesto,
    Programacion,
    ValidacionImportacion,
)

router = APIRouter(prefix="/api")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _obra(db: Session, obra_id: int) -> Obra:
    obra = db.get(Obra, obra_id)
    if obra is None:
        raise HTTPException(404, f"Obra {obra_id} no encontrada")
    return obra


def _presupuesto(db: Session, obra_id: int, presupuesto_id: int | None = None) -> Presupuesto:
    if presupuesto_id:
        pres = db.get(Presupuesto, presupuesto_id)
        if pres is None:
            raise HTTPException(404, "Presupuesto no encontrado")
        return pres
    pres = db.scalars(
        select(Presupuesto)
        .where(Presupuesto.obra_id == obra_id)
        .order_by(Presupuesto.version.desc())
    ).first()
    if pres is None:
        raise HTTPException(404, "La obra no tiene presupuesto importado")
    return pres


def _fecha(valor: str | None) -> dt.date:
    return dt.date.fromisoformat(valor) if valor else dt.date.today()


# --------------------------------------------------------------------------
# Obras
# --------------------------------------------------------------------------
class ObraNueva(BaseModel):
    nombre: str
    organizacion_id: int | None = None
    licitacion_id: str | None = None
    mandante: str | None = None
    contratista: str | None = None
    ubicacion: str | None = None
    fecha_inicio: dt.date | None = None
    plazo_dias: int | None = None
    plantilla_parametros_id: int | None = None
    parametros: dict[str, str] = Field(default_factory=dict)


@router.get("/obras")
def listar_obras(db: Session = Depends(get_session)):
    return [
        {
            "id": o.id,
            "nombre": o.nombre,
            "contratista": o.contratista,
            "mandante": o.mandante,
            "ubicacion": o.ubicacion,
            "fecha_inicio": o.fecha_inicio.isoformat() if o.fecha_inicio else None,
            "plazo_dias": o.plazo_dias,
            "estado": o.estado,
            "presupuestos": len(o.presupuestos),
        }
        for o in db.scalars(select(Obra).order_by(Obra.id)).all()
    ]


@router.post("/obras")
def crear_obra(datos: ObraNueva, db: Session = Depends(get_session)):
    org_id = datos.organizacion_id
    if org_id is None:
        org = db.scalars(select(Organizacion).order_by(Organizacion.id)).first()
        if org is None:
            org = Organizacion(razon_social="Organización por defecto")
            db.add(org)
            db.commit()
        org_id = org.id

    obra = Obra(
        organizacion_id=org_id,
        nombre=datos.nombre,
        licitacion_id=datos.licitacion_id,
        mandante=datos.mandante,
        contratista=datos.contratista,
        ubicacion=datos.ubicacion,
        fecha_inicio=datos.fecha_inicio,
        plazo_dias=datos.plazo_dias,
    )
    db.add(obra)
    db.commit()

    desde = datos.fecha_inicio or dt.date.today()
    valores: dict[str, str] = {}
    if datos.plantilla_parametros_id:
        filas = db.scalars(
            select(PlantillaParametroValor).where(
                PlantillaParametroValor.plantilla_id == datos.plantilla_parametros_id
            )
        ).all()
        valores.update({f.clave: f.valor for f in filas})
    valores.update(datos.parametros)
    if valores:
        P.aplicar_plantilla(db, obra.id, valores, desde, usuario="api")
    return {"id": obra.id, "parametros_aplicados": len(valores)}


@router.get("/obras/{obra_id}")
def detalle_obra(obra_id: int, fecha: str | None = None, db: Session = Depends(get_session)):
    obra = _obra(db, obra_id)
    f = _fecha(fecha)
    presupuesto = db.scalars(
        select(Presupuesto).where(Presupuesto.obra_id == obra_id).order_by(Presupuesto.version.desc())
    ).first()
    return {
        "id": obra.id,
        "nombre": obra.nombre,
        "licitacion_id": obra.licitacion_id,
        "mandante": obra.mandante,
        "contratista": obra.contratista,
        "ubicacion": obra.ubicacion,
        "fecha_inicio": obra.fecha_inicio.isoformat() if obra.fecha_inicio else None,
        "plazo_dias": obra.plazo_dias,
        "estado": obra.estado,
        "presupuesto": (
            {"id": presupuesto.id, "version": presupuesto.version, "estado": presupuesto.estado}
            if presupuesto
            else None
        ),
        "parametros_vigentes": P.resolver_todos(db, obra_id, f),
        "fecha_referencia": f.isoformat(),
    }


# --------------------------------------------------------------------------
# Parámetros
# --------------------------------------------------------------------------
class ParametroNuevo(BaseModel):
    clave: str
    valor: str
    vigente_desde: dt.date
    motivo: str | None = None
    usuario: str | None = "api"
    documento_respaldo_url: str | None = None
    permitir_retroactivo: bool = False


@router.get("/parametros/catalogo")
def catalogo():
    return [
        {
            "clave": d.clave,
            "etiqueta": d.etiqueta,
            "tipo": d.tipo,
            "unidad": d.unidad,
            "opciones": list(d.opciones),
            "defecto": d.defecto,
            "descripcion": d.descripcion,
        }
        for d in P.CATALOGO
    ]


@router.get("/obras/{obra_id}/parametros")
def parametros_vigentes(obra_id: int, fecha: str | None = None, db: Session = Depends(get_session)):
    _obra(db, obra_id)
    return P.resolver_todos(db, obra_id, _fecha(fecha))


@router.get("/obras/{obra_id}/parametros/historial")
def parametros_historial(obra_id: int, clave: str | None = None, db: Session = Depends(get_session)):
    _obra(db, obra_id)
    return [
        {
            "clave": p.clave,
            "valor": p.valor,
            "vigente_desde": p.vigente_desde.isoformat(),
            "vigente_hasta": p.vigente_hasta.isoformat() if p.vigente_hasta else None,
            "motivo": p.motivo,
            "usuario": p.usuario,
            "documento": p.documento_respaldo_url,
            "creado_en": p.creado_en.isoformat(),
        }
        for p in P.historial(db, obra_id, clave)
    ]


@router.post("/obras/{obra_id}/parametros")
def fijar_parametro(obra_id: int, datos: ParametroNuevo, db: Session = Depends(get_session)):
    _obra(db, obra_id)
    try:
        p = P.fijar(
            db, obra_id, datos.clave, datos.valor, datos.vigente_desde,
            motivo=datos.motivo, usuario=datos.usuario,
            documento_respaldo_url=datos.documento_respaldo_url,
            permitir_retroactivo=datos.permitir_retroactivo,
        )
    except P.ParametroError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"clave": p.clave, "valor": p.valor, "vigente_desde": p.vigente_desde.isoformat()}


@router.post("/obras/{obra_id}/parametros/simular")
def simular_parametro(
    obra_id: int, datos: ParametroNuevo, db: Session = Depends(get_session)
):
    """Impacto de un cambio antes de confirmarlo, sin escribir nada."""
    obra = _obra(db, obra_id)
    pres = _presupuesto(db, obra_id)
    fecha = datos.vigente_desde
    antes = reportes.reporte_presupuesto(db, obra, pres, fecha)

    original = P.valor_vigente(db, obra_id, datos.clave, fecha)
    savepoint = db.begin_nested()
    try:
        P.fijar(db, obra_id, datos.clave, datos.valor, fecha, motivo="simulación",
                usuario="simulador", permitir_retroactivo=True)
        despues = reportes.reporte_presupuesto(db, obra, pres, fecha)
    finally:
        savepoint.rollback()

    return {
        "clave": datos.clave,
        "valor_actual": original,
        "valor_simulado": datos.valor,
        "fecha": fecha.isoformat(),
        "contrato_antes": antes["contrato"]["total"],
        "contrato_despues": despues["contrato"]["total"],
        "avance_antes": antes["avance"]["total"],
        "avance_despues": despues["avance"]["total"],
        "delta_contrato": str(
            Decimal(despues["contrato"]["total"]) - Decimal(antes["contrato"]["total"])
        ),
    }


# --------------------------------------------------------------------------
# Importación
# --------------------------------------------------------------------------
@router.post("/obras/{obra_id}/importar")
async def importar(
    obra_id: int,
    archivo: UploadFile = File(...),
    hoja_presupuesto: str | None = None,
    hoja_pu: str = "P.U",
    db: Session = Depends(get_session),
):
    obra = _obra(db, obra_id)
    destino = os.path.join(tempfile.gettempdir(), archivo.filename or "plantilla.xlsx")
    with open(destino, "wb") as fh:
        shutil.copyfileobj(archivo.file, fh)
    resultado = importar_plantilla(db, obra, destino, hoja_presupuesto, hoja_pu)
    return resultado.resumen()


@router.get("/presupuestos/{presupuesto_id}/validaciones")
def validaciones(presupuesto_id: int, severidad: str | None = None, db: Session = Depends(get_session)):
    q = select(ValidacionImportacion).where(
        ValidacionImportacion.presupuesto_id == presupuesto_id
    )
    if severidad:
        q = q.where(ValidacionImportacion.severidad == severidad.upper())
    filas = db.scalars(q.order_by(ValidacionImportacion.severidad, ValidacionImportacion.id)).all()
    return [
        {
            "regla": v.regla,
            "severidad": v.severidad,
            "ubicacion": v.ubicacion,
            "mensaje": v.mensaje,
            "valor_original": v.valor_original,
            "valor_corregido": v.valor_corregido,
        }
        for v in filas
    ]


@router.get("/presupuestos/{presupuesto_id}/partidas")
def listar_partidas(presupuesto_id: int, db: Session = Depends(get_session)):
    filas = db.scalars(
        select(Partida).where(Partida.presupuesto_id == presupuesto_id).order_by(Partida.orden)
    ).all()
    return [
        {
            "id": p.id,
            "codigo": p.codigo,
            "nivel": p.nivel,
            "descripcion": p.descripcion,
            "unidad": p.unidad,
            "cantidad": str(p.cantidad) if p.cantidad is not None else None,
            "p_unitario": str(p.p_unitario) if p.p_unitario is not None else None,
            "p_total": str(p.p_total) if p.p_total is not None else None,
            "es_agrupador": p.es_agrupador,
            "es_incluida_en_gg": p.es_incluida_en_gg,
            "tiene_apu": p.apu is not None,
        }
        for p in filas
    ]


# --------------------------------------------------------------------------
# Calendario y programación
# --------------------------------------------------------------------------
@router.post("/feriados/sembrar")
def sembrar(desde: int = 2024, hasta: int = 2027, db: Session = Depends(get_session)):
    return {"insertados": sembrar_feriados(db, desde, hasta)}


@router.get("/obras/{obra_id}/semanas")
def semanas(obra_id: int, desde: str, hasta: str, db: Session = Depends(get_session)):
    obra = _obra(db, obra_id)
    f = _fecha(hasta)
    cal = CalendarioObra(
        db, obra_id,
        P.valor_vigente(db, obra_id, "dias_habiles_semana", f),
        float(P.valor_vigente(db, obra_id, "horas_jornada", f)),
    )
    return [s.as_dict() for s in cal.semanas(_fecha(desde), f)]


class ProgramacionNueva(BaseModel):
    fecha_inicio: dt.date | None = None
    plazo_dias: int | None = None
    cuadrillas: float = 1.0
    nombre: str = "Línea base"


@router.post("/obras/{obra_id}/programacion")
def crear_programacion(obra_id: int, datos: ProgramacionNueva, db: Session = Depends(get_session)):
    obra = _obra(db, obra_id)
    pres = _presupuesto(db, obra_id)
    inicio = datos.fecha_inicio or obra.fecha_inicio or dt.date.today()
    plazo = datos.plazo_dias or obra.plazo_dias or 180
    cal = CalendarioObra(
        db, obra_id,
        P.valor_vigente(db, obra_id, "dias_habiles_semana", inicio),
        float(P.valor_vigente(db, obra_id, "horas_jornada", inicio)),
    )
    prog = PR.generar_linea_base(
        db, pres, cal, inicio, plazo, Decimal(str(datos.cuadrillas)), datos.nombre
    )
    return {"id": prog.id, "version": prog.version, "es_linea_base": prog.es_linea_base}


@router.get("/obras/{obra_id}/programaciones")
def listar_programaciones(obra_id: int, db: Session = Depends(get_session)):
    pres = _presupuesto(db, obra_id)
    filas = db.scalars(
        select(Programacion).where(Programacion.presupuesto_id == pres.id)
    ).all()
    return [
        {"id": p.id, "version": p.version, "nombre": p.nombre, "es_linea_base": p.es_linea_base}
        for p in filas
    ]


# --------------------------------------------------------------------------
# Avance
# --------------------------------------------------------------------------
class AvanceNuevo(BaseModel):
    partida_id: int
    iso_semana: str
    fecha_medicion: dt.date
    cantidad_acumulada: Decimal
    observaciones: str | None = None
    registrado_por: str | None = "terreno"
    aprobar: bool = False


@router.post("/obras/{obra_id}/avances")
def registrar_avance(obra_id: int, datos: AvanceNuevo, db: Session = Depends(get_session)):
    _obra(db, obra_id)
    partida = db.get(Partida, datos.partida_id)
    if partida is None:
        raise HTTPException(404, "Partida no encontrada")
    if partida.cantidad and datos.cantidad_acumulada > partida.cantidad:
        raise HTTPException(
            409,
            f"La cantidad acumulada {datos.cantidad_acumulada} supera la contratada "
            f"{partida.cantidad}. Requiere modificación de contrato.",
        )

    previo = db.scalars(
        select(AvanceSemanal)
        .where(
            AvanceSemanal.obra_id == obra_id,
            AvanceSemanal.partida_id == datos.partida_id,
            AvanceSemanal.fecha_medicion < datos.fecha_medicion,
        )
        .order_by(AvanceSemanal.fecha_medicion.desc())
    ).first()
    anterior = previo.cantidad_acumulada if previo else Decimal("0")

    fila = db.scalars(
        select(AvanceSemanal).where(
            AvanceSemanal.obra_id == obra_id,
            AvanceSemanal.partida_id == datos.partida_id,
            AvanceSemanal.iso_semana == datos.iso_semana,
        )
    ).first()
    if fila is None:
        fila = AvanceSemanal(
            obra_id=obra_id,
            partida_id=datos.partida_id,
            iso_semana=datos.iso_semana,
            fecha_medicion=datos.fecha_medicion,
        )
        db.add(fila)
    if fila.estado == "APROBADO":
        raise HTTPException(409, "El avance de esa semana ya está aprobado.")

    fila.fecha_medicion = datos.fecha_medicion
    fila.cantidad_acumulada = datos.cantidad_acumulada
    fila.cantidad_periodo = datos.cantidad_acumulada - anterior
    fila.observaciones = datos.observaciones
    fila.registrado_por = datos.registrado_por
    if datos.aprobar:
        fila.estado = "APROBADO"
        fila.aprobado_por = datos.registrado_por
        fila.aprobado_en = dt.datetime.now(dt.timezone.utc)
    db.commit()
    return {"id": fila.id, "estado": fila.estado, "cantidad_periodo": str(fila.cantidad_periodo)}


@router.post("/avances/{avance_id}/aprobar")
def aprobar_avance(avance_id: int, usuario: str = "ito", db: Session = Depends(get_session)):
    fila = db.get(AvanceSemanal, avance_id)
    if fila is None:
        raise HTTPException(404, "Avance no encontrado")
    fila.estado = "APROBADO"
    fila.aprobado_por = usuario
    fila.aprobado_en = dt.datetime.now(dt.timezone.utc)
    db.commit()
    return {"id": fila.id, "estado": fila.estado}


@router.get("/obras/{obra_id}/avances")
def listar_avances(obra_id: int, iso: str | None = None, db: Session = Depends(get_session)):
    q = select(AvanceSemanal).where(AvanceSemanal.obra_id == obra_id)
    if iso:
        q = q.where(AvanceSemanal.iso_semana == iso)
    filas = db.scalars(q.order_by(AvanceSemanal.iso_semana, AvanceSemanal.partida_id)).all()
    salida = []
    for f in filas:
        p = db.get(Partida, f.partida_id)
        salida.append(
            {
                "id": f.id,
                "partida": p.codigo,
                "descripcion": p.descripcion,
                "iso_semana": f.iso_semana,
                "fecha_medicion": f.fecha_medicion.isoformat(),
                "cantidad_periodo": str(f.cantidad_periodo),
                "cantidad_acumulada": str(f.cantidad_acumulada),
                "estado": f.estado,
            }
        )
    return salida


# --------------------------------------------------------------------------
# Estados de pago
# --------------------------------------------------------------------------
class EstadoPagoNuevo(BaseModel):
    fecha_corte: dt.date
    numero: int | None = None
    dias_atraso: int = 0
    solo_aprobados: bool = True


@router.post("/obras/{obra_id}/estados-pago")
def crear_ep(obra_id: int, datos: EstadoPagoNuevo, db: Session = Depends(get_session)):
    obra = _obra(db, obra_id)
    pres = _presupuesto(db, obra_id)
    try:
        ep = generar_estado_pago(
            db, obra, pres, datos.fecha_corte, datos.numero, datos.dias_atraso, datos.solo_aprobados
        )
    except EstadoPagoError as exc:
        raise HTTPException(409, str(exc)) from exc
    return reportes.reporte_estado_pago(db, ep)


@router.post("/estados-pago/{ep_id}/aprobar")
def aprobar_ep(ep_id: int, usuario: str = "oficina_tecnica", db: Session = Depends(get_session)):
    ep = db.get(EstadoPago, ep_id)
    if ep is None:
        raise HTTPException(404, "Estado de pago no encontrado")
    try:
        aprobar_estado_pago(db, ep, usuario)
    except EstadoPagoError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"numero": ep.numero, "estado": ep.estado, "aprobado_por": ep.aprobado_por}


@router.get("/obras/{obra_id}/estados-pago")
def listar_eps(obra_id: int, db: Session = Depends(get_session)):
    filas = db.scalars(
        select(EstadoPago).where(EstadoPago.obra_id == obra_id).order_by(EstadoPago.numero)
    ).all()
    return [
        {
            "id": e.id,
            "numero": e.numero,
            "fecha_corte": e.fecha_corte.isoformat(),
            "estado": e.estado,
            "total": str(e.total),
            "liquido": str(e.liquido),
            "pct_acumulado": float(e.pct_acum),
            "provisional": e.provisional,
        }
        for e in filas
    ]


@router.get("/estados-pago/{ep_id}")
def detalle_ep(ep_id: int, db: Session = Depends(get_session)):
    ep = db.get(EstadoPago, ep_id)
    if ep is None:
        raise HTTPException(404, "Estado de pago no encontrado")
    return reportes.reporte_estado_pago(db, ep)


# --------------------------------------------------------------------------
# Reportes
# --------------------------------------------------------------------------
@router.get("/obras/{obra_id}/reportes/presupuesto")
def rep_presupuesto(
    obra_id: int,
    fecha: str | None = None,
    solo_aprobados: bool = True,
    db: Session = Depends(get_session),
):
    obra = _obra(db, obra_id)
    return reportes.reporte_presupuesto(
        db, obra, _presupuesto(db, obra_id), _fecha(fecha), solo_aprobados
    )


@router.get("/obras/{obra_id}/reportes/semanal")
def rep_semanal(
    obra_id: int,
    desde: str | None = None,
    hasta: str | None = None,
    programacion_id: int | None = None,
    solo_aprobados: bool = True,
    db: Session = Depends(get_session),
):
    obra = _obra(db, obra_id)
    inicio = _fecha(desde) if desde else (obra.fecha_inicio or dt.date.today())
    return reportes.reporte_semanal(
        db, obra, _presupuesto(db, obra_id), inicio, _fecha(hasta), programacion_id, solo_aprobados
    )


@router.get("/obras/{obra_id}/reportes/tablero")
def rep_tablero(
    obra_id: int, fecha: str | None = None, solo_aprobados: bool = True,
    db: Session = Depends(get_session)
):
    obra = _obra(db, obra_id)
    return reportes.tablero(db, obra, _presupuesto(db, obra_id), _fecha(fecha), solo_aprobados)


@router.get("/partidas/{partida_id}/anexo4")
def rep_anexo4(partida_id: int, fecha: str | None = None, db: Session = Depends(get_session)):
    partida = db.get(Partida, partida_id)
    if partida is None:
        raise HTTPException(404, "Partida no encontrada")
    pres = db.get(Presupuesto, partida.presupuesto_id)
    obra = db.get(Obra, pres.obra_id)
    return reportes.anexo_4(db, obra, partida, _fecha(fecha))


# --------------------------------------------------------------------------
# Exportaciones
# --------------------------------------------------------------------------
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _adjunto(contenido: bytes, nombre: str) -> Response:
    return Response(
        contenido, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{nombre}"'}
    )


@router.get("/obras/{obra_id}/reportes/presupuesto.xlsx")
def exp_presupuesto(obra_id: int, fecha: str | None = None, db: Session = Depends(get_session)):
    obra = _obra(db, obra_id)
    rep = reportes.reporte_presupuesto(db, obra, _presupuesto(db, obra_id), _fecha(fecha))
    datos = export_excel.exportar_presupuesto(
        rep,
        {"nombre": obra.nombre, "licitacion": obra.licitacion_id, "ubicacion": obra.ubicacion,
         "contratista": obra.contratista},
    )
    return _adjunto(datos, f"avance-presupuesto-{_fecha(fecha)}.xlsx")


@router.get("/obras/{obra_id}/reportes/semanal.xlsx")
def exp_semanal(
    obra_id: int, desde: str | None = None, hasta: str | None = None,
    db: Session = Depends(get_session)
):
    obra = _obra(db, obra_id)
    inicio = _fecha(desde) if desde else (obra.fecha_inicio or dt.date.today())
    rep = reportes.reporte_semanal(db, obra, _presupuesto(db, obra_id), inicio, _fecha(hasta))
    return _adjunto(export_excel.exportar_semanal(rep), f"avance-semanal-{_fecha(hasta)}.xlsx")


@router.get("/estados-pago/{ep_id}/xlsx")
def exp_ep(ep_id: int, db: Session = Depends(get_session)):
    ep = db.get(EstadoPago, ep_id)
    if ep is None:
        raise HTTPException(404, "Estado de pago no encontrado")
    rep = reportes.reporte_estado_pago(db, ep)
    return _adjunto(export_excel.exportar_estado_pago(rep), f"estado-pago-{ep.numero}.xlsx")


@router.get("/partidas/{partida_id}/anexo4.xlsx")
def exp_anexo4(partida_id: int, fecha: str | None = None, db: Session = Depends(get_session)):
    partida = db.get(Partida, partida_id)
    if partida is None:
        raise HTTPException(404, "Partida no encontrada")
    pres = db.get(Presupuesto, partida.presupuesto_id)
    obra = db.get(Obra, pres.obra_id)
    anexo = reportes.anexo_4(db, obra, partida, _fecha(fecha))
    if "error" in anexo:
        raise HTTPException(409, anexo["error"])
    return _adjunto(export_excel.exportar_anexo4(anexo), f"anexo4-{partida.codigo}.xlsx")


@router.get("/estados-pago/{ep_id}/imprimir", response_class=HTMLResponse)
def imprimir_ep(ep_id: int, db: Session = Depends(get_session)):
    """Vista de impresión: el navegador la exporta a PDF con el pie de trazabilidad."""
    ep = db.get(EstadoPago, ep_id)
    if ep is None:
        raise HTTPException(404, "Estado de pago no encontrado")
    r = reportes.reporte_estado_pago(db, ep)
    filas = "".join(
        f"<tr><td>{d['codigo']}</td><td>{d['descripcion']}</td><td>{d['unidad'] or ''}</td>"
        f"<td class='n'>{d['cantidad_contratada']}</td><td class='n'>{d['cant_periodo']}</td>"
        f"<td class='n'>{d['cant_acumulada']}</td><td class='n'>{d['pct_acumulado']*100:.2f}%</td>"
        f"<td class='n'>${int(float(d['monto_periodo'])):,}</td>"
        f"<td class='n'>${int(float(d['monto_acumulado'])):,}</td></tr>".replace(",", ".")
        for d in r["detalle"]
    )
    pe = r["periodo_economico"]
    cierre = "".join(
        f"<tr><th>{k}</th><td class='n'>${int(float(v)):,}</td></tr>".replace(",", ".")
        for k, v in (
            ("Costo directo", pe["cd"]), ("Gastos generales", pe["gg"]),
            ("Utilidad", pe["utilidad"]), ("Neto", pe["neto"]), ("IVA", pe["iva"]),
            ("Total del período", pe["total"]), ("Anticipo", pe["anticipo"]),
            ("Retención", pe["retencion"]), ("Multa", pe["multa"]), ("Líquido a pagar", pe["liquido"]),
        )
    )
    advertencias = "".join(f"<p class='adv'>⚠ {a}</p>" for a in r["advertencias"] if a)
    pie = "<br>".join(r["pie_trazabilidad"])
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Estado de pago N°{r['numero']} — {r['obra']['nombre']}</title>
<style>
 body{{font-family:Arial,Helvetica,sans-serif;font-size:11px;color:#111;margin:24px}}
 h1{{font-size:16px;margin:0 0 4px}} h2{{font-size:12px;margin:18px 0 6px}}
 table{{border-collapse:collapse;width:100%}} td,th{{border:1px solid #bbb;padding:3px 5px}}
 th{{background:#1f3864;color:#fff;text-align:left}} .n{{text-align:right}}
 .cierre{{width:340px;margin-left:auto}} .cierre th{{background:#eee;color:#111}}
 .adv{{color:#c00;font-weight:bold}} footer{{margin-top:18px;font-size:10px;color:#555}}
 @media print{{body{{margin:8mm}}}}
</style></head><body>
<h1>Estado de pago N°{r['numero']} — {r['estado']}</h1>
<p>{r['obra']['nombre']}<br>Licitación: {r['obra']['licitacion'] or '—'} · {r['obra']['ubicacion'] or ''}<br>
Contratista: {r['obra']['contratista'] or '—'} · Mandante: {r['obra']['mandante'] or '—'}<br>
Fecha de corte: {r['fecha_corte']} · Período: {r['periodo']['desde'] or '—'} a {r['periodo']['hasta']}<br>
Avance acumulado: {r['acumulado']['pct']*100:.2f}%</p>
{advertencias}
<h2>Detalle por partida</h2>
<table><tr><th>Ítem</th><th>Descripción</th><th>Un.</th><th>Cant. contratada</th>
<th>Del período</th><th>Acumulada</th><th>% acum.</th><th>Monto período</th><th>Monto acum.</th></tr>
{filas}</table>
<h2>Cierre económico del período</h2>
<table class="cierre">{cierre}</table>
<footer>Parámetros e indicadores usados ({r['origen_parametros']}):<br>{pie}</footer>
</body></html>"""


# --------------------------------------------------------------------------
# Panel de control de gerencia
# --------------------------------------------------------------------------
@router.get("/panel/cartera")
def panel_cartera(
    fecha: str | None = None, solo_aprobados: bool = True, db: Session = Depends(get_session)
):
    """Todas las obras de un vistazo, con semáforo y alertas."""
    return panel.cartera(db, _fecha(fecha), solo_aprobados)


@router.get("/panel/obras/{obra_id}")
def panel_obra(
    obra_id: int,
    fecha: str | None = None,
    capitulo: str | None = None,
    semaforo: str | None = None,
    estado: str | None = None,
    texto: str | None = None,
    incidencia_min: float = 0.0,
    orden: str = "incidencia",
    limite: int = 200,
    desplazamiento: int = 0,
    solo_aprobados: bool = True,
    db: Session = Depends(get_session),
):
    """Detalle de una obra con los filtros aplicados en el servidor."""
    obra = _obra(db, obra_id)
    pres = _presupuesto(db, obra_id)
    filtros = panel.Filtros(
        capitulo=capitulo,
        semaforo=semaforo,
        estado=estado,
        texto=texto,
        incidencia_min=incidencia_min,
        orden=orden,
        limite=min(limite, 500),
        desplazamiento=desplazamiento,
    )
    return panel.obra_filtrada(db, obra, pres, _fecha(fecha), filtros, solo_aprobados)


@router.get("/panel/obras/{obra_id}/capitulos")
def panel_capitulos(obra_id: int, db: Session = Depends(get_session)):
    _obra(db, obra_id)
    return panel.capitulos_disponibles(db, _presupuesto(db, obra_id))


# --------------------------------------------------------------------------
# Indicadores
# --------------------------------------------------------------------------
class IndicadorManual(BaseModel):
    codigo: str
    fecha: dt.date
    valor: Decimal
    usuario: str = "finanzas"
    nota: str | None = None


@router.post("/indicadores/sincronizar")
def sincronizar_indicador(
    codigo: str, desde: str, hasta: str, db: Session = Depends(get_session)
):
    sync = ServicioIndicadores(db).sincronizar(codigo.upper(), _fecha(desde), _fecha(hasta))
    return {
        "codigo": sync.codigo,
        "estado": sync.estado,
        "fuente": sync.fuente,
        "valores_nuevos": sync.valores_nuevos,
        "detalle": sync.detalle,
    }


@router.post("/indicadores/manual")
def indicador_manual(datos: IndicadorManual, db: Session = Depends(get_session)):
    fila = ServicioIndicadores(db).cargar_manual(
        datos.codigo.upper(), datos.fecha, datos.valor, datos.usuario, datos.nota
    )
    return {"codigo": fila.codigo, "fecha": fila.fecha.isoformat(), "valor": str(fila.valor)}


@router.get("/indicadores/{codigo}")
def leer_indicador(
    codigo: str, fecha: str | None = None, sincronizar: bool = False,
    db: Session = Depends(get_session)
):
    return ServicioIndicadores(db).valor(codigo.upper(), _fecha(fecha), sincronizar).as_dict()


@router.get("/indicadores/{codigo}/serie")
def serie_indicador(codigo: str, limite: int = 60, db: Session = Depends(get_session)):
    filas = db.scalars(
        select(IndicadorValor)
        .where(IndicadorValor.codigo == codigo.upper())
        .order_by(IndicadorValor.fecha.desc())
        .limit(limite)
    ).all()
    return [
        {
            "fecha": f.fecha.isoformat(),
            "valor": str(f.valor),
            "fuente": f.fuente,
            "estado": f.estado,
            "nota": f.nota,
        }
        for f in filas
    ]


@router.get("/feriados")
def listar_feriados(desde: str, hasta: str, obra_id: int | None = None, db: Session = Depends(get_session)):
    filas = db.scalars(
        select(Feriado)
        .where(Feriado.fecha >= _fecha(desde), Feriado.fecha <= _fecha(hasta))
        .order_by(Feriado.fecha)
    ).all()
    return [
        {"fecha": f.fecha.isoformat(), "nombre": f.nombre, "fuente": f.fuente,
         "obra_id": f.obra_id, "irrenunciable": f.irrenunciable}
        for f in filas
    ]


# --------------------------------------------------------------------------
# Carga de mediciones desde una hoja de corte de la plantilla
# --------------------------------------------------------------------------
@router.post("/obras/{obra_id}/mediciones/importar")
async def importar_mediciones(
    obra_id: int,
    hoja: str,
    archivo: UploadFile = File(...),
    aprobar: bool = False,
    db: Session = Depends(get_session),
):
    obra = _obra(db, obra_id)
    pres = _presupuesto(db, obra_id)
    destino = os.path.join(tempfile.gettempdir(), archivo.filename or "corte.xlsx")
    with open(destino, "wb") as fh:
        shutil.copyfileobj(archivo.file, fh)

    fecha, mediciones = leer_mediciones(destino, hoja)
    if fecha is None:
        raise HTTPException(409, "La hoja no declara fecha de corte en la cabecera.")

    partidas = {
        p.codigo: p
        for p in db.scalars(select(Partida).where(Partida.presupuesto_id == pres.id)).all()
    }
    cargadas = 0
    for codigo, cantidad in mediciones.items():
        p = partidas.get(codigo)
        if p is None or not p.es_medible:
            continue
        iso = fecha.strftime("%G-W%V")
        fila = db.scalars(
            select(AvanceSemanal).where(
                AvanceSemanal.obra_id == obra_id,
                AvanceSemanal.partida_id == p.id,
                AvanceSemanal.iso_semana == iso,
            )
        ).first()
        if fila is None:
            fila = AvanceSemanal(obra_id=obra_id, partida_id=p.id, iso_semana=iso,
                                 fecha_medicion=fecha)
            db.add(fila)
        fila.fecha_medicion = fecha
        fila.cantidad_acumulada = cantidad
        fila.estado = "APROBADO" if aprobar else "EN_TERRENO"
        cargadas += 1
    db.commit()

    res = calcular_avance(db, pres, fecha, solo_aprobados=aprobar)
    return {
        "fecha_corte": fecha.isoformat(),
        "mediciones_cargadas": cargadas,
        "avance_pct": float(res.pct),
    }
