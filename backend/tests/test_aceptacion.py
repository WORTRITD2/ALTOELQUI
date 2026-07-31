"""Criterios de aceptación del §10 del prompt, con los números reales del contrato."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import reportes
from app.core import parametros as P
from app.core.calculo import (
    calcular_avance,
    cierre_economico,
    generar_estado_pago,
    redondear,
    resumen_por_capitulo,
)
from app.core.calendario import CalendarioObra
from app.core.indicadores import Proveedor, ServicioIndicadores
from app.models import EstadoPago, Obra, Organizacion, Partida, ValidacionImportacion

CORTE_1 = dt.date(2025, 3, 3)
CORTE_2 = dt.date(2025, 3, 17)


# 1 -------------------------------------------------------------------------
def test_importacion_reproduce_la_plantilla(db, obra, presupuesto):
    partidas = db.scalars(
        select(Partida).where(Partida.presupuesto_id == presupuesto.id)
    ).all()
    medibles = [p for p in partidas if p.es_medible]
    no_medibles = [p for p in partidas if not p.es_medible]
    con_apu = [p for p in partidas if p.apu is not None]

    assert len(medibles) == 116
    assert len(no_medibles) == 23
    assert len(con_apu) == 112

    res = calcular_avance(db, presupuesto, CORTE_2)
    assert res.contrato_cd == Decimal("502933585")

    # El contrato firmado se importa tal cual (la plantilla redondea cada línea del pie)
    assert presupuesto.total_cd == Decimal("502933585")
    assert presupuesto.total_gg == Decimal("75440038")
    assert presupuesto.total_utilidad == Decimal("100586717")
    assert presupuesto.total_neto == Decimal("678960340")
    assert presupuesto.total_iva == Decimal("129002465")
    assert presupuesto.total_contrato == Decimal("807962805")

    reporte = reportes.reporte_presupuesto(db, obra, presupuesto, CORTE_2)
    assert reporte["contrato"]["total"] == "807962805"
    assert reporte["contrato"]["origen"] == "firmado en la plantilla"
    # El recálculo exacto difiere en menos de un peso por el redondeo de la plantilla
    assert abs(Decimal(reporte["diferencia_contrato"])) <= Decimal("1")


# 2 -------------------------------------------------------------------------
@pytest.mark.parametrize(
    "fecha,pct_esperado,total_esperado",
    [(CORTE_1, "0.0667", "53890565"), (CORTE_2, "0.2040", "164784425")],
)
def test_cortes_reproducen_avance_y_monto(db, obra, presupuesto, fecha, pct_esperado, total_esperado):
    res = calcular_avance(db, presupuesto, fecha)
    assert round(res.pct, 4) == Decimal(pct_esperado)
    cierre = cierre_economico(db, obra.id, fecha, res.avance_cd)
    assert redondear(cierre.total) == Decimal(total_esperado)


# 3 -------------------------------------------------------------------------
def test_ep2_es_el_diferencial_entre_cortes(db, obra):
    ep1, ep2 = db.scalars(
        select(EstadoPago).where(EstadoPago.obra_id == obra.id).order_by(EstadoPago.numero)
    ).all()[:2]
    assert redondear(ep1.total) == Decimal("53890565")
    assert redondear(ep2.total) == Decimal("110893860")
    assert redondear(ep2.total_acum) == Decimal("164784425")
    assert redondear(ep2.total) == redondear(ep2.total_acum) - redondear(ep1.total_acum)


# 4 -------------------------------------------------------------------------
def test_avance_por_capitulo_es_ponderado_por_costo(db, presupuesto):
    res = calcular_avance(db, presupuesto, CORTE_2)
    capitulos = resumen_por_capitulo(res, nivel=1)

    suma_contrato = sum(Decimal(c["contrato"]) for c in capitulos)
    suma_avance = sum(Decimal(c["avance"]) for c in capitulos)
    assert abs(suma_contrato - res.contrato_cd) <= Decimal("1")
    assert abs(suma_avance - res.avance_cd) <= Decimal("1")

    global_ponderado = suma_avance / suma_contrato
    assert abs(global_ponderado - res.pct) < Decimal("0.0001")

    # El promedio simple de porcentajes NO coincide: por eso está prohibido.
    promedio_simple = sum(Decimal(str(c["pct"])) for c in capitulos) / len(capitulos)
    assert abs(promedio_simple - res.pct) > Decimal("0.001")


# 5 -------------------------------------------------------------------------
def test_reporte_semanal_y_dias_habiles_con_feriados(db, obra, presupuesto):
    rep = reportes.reporte_semanal(db, obra, presupuesto, dt.date(2025, 2, 17), CORTE_2)
    assert rep["semanas"], "debe haber semanas ISO en el rango"
    for s in rep["semanas"]:
        assert s["iso"].startswith("2025-W")
        assert "programado_acumulado" in s and "real_acumulado" in s
    assert rep["resumen"]["spi"] is not None
    assert rep["semanas"][-1]["iso"] == "2025-W12"

    cal = CalendarioObra(db, obra.id, "1,2,3,4,5", 8.5)
    # 18 y 19 de septiembre de 2025 caen jueves y viernes: esa semana tiene 3 días hábiles
    semana_18 = cal.semana("2025-W38")
    assert semana_18.dias_habiles == 3
    assert any("Independencia" in f for f in semana_18.feriados)
    # Semana sin feriados: 5 días hábiles
    assert cal.semana("2025-W10").dias_habiles == 5


# 6 -------------------------------------------------------------------------
def test_anexo4_de_cubierta_pv4(db, obra, presupuesto):
    partida = db.scalars(
        select(Partida).where(
            Partida.presupuesto_id == presupuesto.id, Partida.codigo == "2.1.5"
        )
    ).first()
    anexo = reportes.anexo_4(db, obra, partida, CORTE_2)
    assert Decimal(anexo["materiales"]["total"]) == Decimal("11500")
    assert Decimal(anexo["mano_obra"]["total"]) == Decimal("6900")
    assert anexo["mano_obra"]["pct_leyes_sociales"] == 0.5
    assert Decimal(anexo["equipos"]["total"]) == Decimal("115")
    assert Decimal(anexo["precio_unitario"]) == Decimal("18515")
    assert anexo["cuadra"] is True


# 7 -------------------------------------------------------------------------
def test_modificacion_de_contrato_no_altera_ep_aprobado(db, obra, presupuesto):
    ep1 = db.scalars(
        select(EstadoPago).where(EstadoPago.obra_id == obra.id, EstadoPago.numero == 1)
    ).first()
    assert ep1.estado == "APROBADO"
    total_antes = ep1.total

    partida = db.scalars(
        select(Partida).where(
            Partida.presupuesto_id == presupuesto.id, Partida.codigo == "1.2"
        )
    ).first()
    cantidad_original, ptotal_original = partida.cantidad, partida.p_total
    partida.cantidad = cantidad_original * 2
    partida.p_total = partida.cantidad * partida.p_unitario
    db.commit()
    try:
        db.refresh(ep1)
        assert ep1.total == total_antes, "el EP aprobado guarda sus montos, no los recalcula"
        with pytest.raises(Exception):
            from app.core.calculo import EstadoPagoError  # noqa: F401

            generar_estado_pago(db, obra, presupuesto, CORTE_1, numero=1)
    finally:
        partida.cantidad, partida.p_total = cantidad_original, ptotal_original
        db.commit()


# 8 -------------------------------------------------------------------------
def test_informe_de_validaciones_del_importador(db, presupuesto):
    filas = db.scalars(
        select(ValidacionImportacion).where(
            ValidacionImportacion.presupuesto_id == presupuesto.id
        )
    ).all()
    reglas = {f.regla for f in filas}
    for esperada in (
        "CODIGO_FECHA",            # 1. códigos convertidos a fecha
        "UNIDAD_NO_NORMALIZADA",   # 2. unidades heterogéneas
        "INCLUIDA_EN_GG",          # 3. incluido en gastos generales
        "SUBTOTAL_SIN_FORMULA",    # 4. subtotales sin valor
        "APU_IVA_INCONSISTENTE",   # 5. IVA mal calculado en el resumen del APU
        "CELDA_HUERFANA",          # 6. valores fuera de tabla
        "APU_NO_CUADRA",           # 7. APU vs P. Unitario
        "TOTALES_CUADRAN",         # 8. cuadratura de totales
    ):
        assert esperada in reglas, f"falta la validación {esperada}"

    codigos = [f for f in filas if f.regla == "CODIGO_FECHA"]
    assert len(codigos) == 38
    reconstruido = {f.valor_corregido for f in codigos}
    assert "2.6.10" in reconstruido and "2.11.16" in reconstruido


# 9 -------------------------------------------------------------------------
def test_segunda_obra_con_otros_parametros(db):
    org = db.scalars(select(Organizacion)).first()
    otra = Obra(
        organizacion_id=org.id,
        nombre="Obra con bases distintas",
        fecha_inicio=dt.date(2025, 1, 6),
    )
    db.add(otra)
    db.commit()
    P.aplicar_plantilla(
        db,
        otra.id,
        {"pct_gg": "0.12", "pct_utilidad": "0.15", "base_utilidad": "CD+GG", "pct_iva": "0.19"},
        dt.date(2025, 1, 6),
    )

    cd = Decimal("100000000")
    cierre = cierre_economico(db, otra.id, dt.date(2025, 6, 1), cd)
    assert cierre.gg == Decimal("12000000")
    assert cierre.utilidad == Decimal("16800000")  # 15% sobre CD+GG, no sobre CD
    assert cierre.neto == Decimal("128800000")
    assert redondear(cierre.total) == Decimal("153272000")

    # La primera obra no se ve afectada
    obra_ref = db.scalars(select(Obra).order_by(Obra.id)).first()
    original = cierre_economico(db, obra_ref.id, dt.date(2025, 6, 1), cd)
    assert original.gg == Decimal("15000000")
    assert original.utilidad == Decimal("20000000")


# 10 ------------------------------------------------------------------------
def test_vigencia_temporal_no_reescribe_el_pasado(db, obra, presupuesto):
    ep1 = db.scalars(
        select(EstadoPago).where(EstadoPago.obra_id == obra.id, EstadoPago.numero == 1)
    ).first()
    total_ep1 = redondear(ep1.total)

    P.fijar(db, obra.id, "pct_gg", "0.12", dt.date(2025, 6, 1),
            motivo="Resolución de prueba", usuario="tests")

    assert P.pct(db, obra.id, "pct_gg", CORTE_1) == Decimal("0.15")
    assert P.pct(db, obra.id, "pct_gg", dt.date(2025, 5, 31)) == Decimal("0.15")
    assert P.pct(db, obra.id, "pct_gg", dt.date(2025, 6, 1)) == Decimal("0.12")

    res = calcular_avance(db, presupuesto, CORTE_1)
    cierre = cierre_economico(db, obra.id, CORTE_1, res.avance_cd)
    assert redondear(cierre.total) == total_ep1

    with pytest.raises(P.ParametroError) as exc:
        P.fijar(db, obra.id, "pct_gg", "0.10", dt.date(2025, 2, 1), motivo="retroactivo")
    assert "nota de ajuste" in str(exc.value)


def test_parametro_fuera_de_rango_se_rechaza(db, obra):
    with pytest.raises(P.ParametroError):
        P.fijar(db, obra.id, "pct_iva", "1.5", dt.date(2026, 1, 1))
    with pytest.raises(P.ParametroError):
        P.fijar(db, obra.id, "base_utilidad", "CD+GG+IVA", dt.date(2026, 1, 1))


# 11 ------------------------------------------------------------------------
def test_indicador_queda_congelado_en_el_snapshot(db, obra, presupuesto):
    servicio = ServicioIndicadores(db, proveedores=[])
    servicio.cargar_manual("UF", CORTE_2, Decimal("38264.41"), usuario="tests",
                           nota="Valor de prueba")
    lectura = servicio.valor("UF", CORTE_2)
    assert lectura.valor == Decimal("38264.41")
    assert lectura.estado == "CONFIRMADO"
    assert "UF al 17-03-2025" in lectura.leyenda()

    ep2 = db.scalars(
        select(EstadoPago).where(EstadoPago.obra_id == obra.id, EstadoPago.numero == 2)
    ).first()
    from app.core.calculo import aprobar_estado_pago

    if ep2.estado == "BORRADOR":
        aprobar_estado_pago(db, ep2, "tests")
    reporte = reportes.reporte_estado_pago(db, ep2)
    assert reporte["indicadores"]["UF"]["valor"] == "38264.41"
    assert reporte["origen_parametros"].startswith("snapshot")

    # Una corrección posterior de la fuente no altera el EP ya aprobado
    servicio.cargar_manual("UF", CORTE_2, Decimal("99999"), usuario="tests", nota="corrección")
    assert reportes.reporte_estado_pago(db, ep2)["indicadores"]["UF"]["valor"] == "38264.41"


# 12 ------------------------------------------------------------------------
def test_degradacion_sin_red_marca_provisional(db):
    class ProveedorCaido(Proveedor):
        nombre = "BCCH"

        def disponible(self):
            return True

        def obtener(self, codigo, desde, hasta):
            raise ConnectionError("sin red")

    servicio = ServicioIndicadores(db, proveedores=[ProveedorCaido()])
    sync = servicio.sincronizar("UTM", dt.date(2025, 3, 1), dt.date(2025, 3, 31))
    assert sync.estado == "ERROR"
    assert "ConnectionError" in (sync.detalle or "")

    servicio.cargar_manual("UTM", dt.date(2025, 3, 1), Decimal("67429"), usuario="tests")
    lectura = servicio.valor("UTM", dt.date(2025, 5, 20))
    assert lectura.estado == "PROVISIONAL"
    assert lectura.valor == Decimal("67429")
    assert "último conocido" in lectura.advertencia

    sin_dato = servicio.valor("IPC", dt.date(2025, 5, 20))
    assert sin_dato.estado == "SIN_DATO" and sin_dato.valor is None


# 13 ------------------------------------------------------------------------
def test_pie_de_trazabilidad_del_estado_de_pago(db, obra):
    ep1 = db.scalars(
        select(EstadoPago).where(EstadoPago.obra_id == obra.id, EstadoPago.numero == 1)
    ).first()
    reporte = reportes.reporte_estado_pago(db, ep1)
    pie = " ".join(reporte["pie_trazabilidad"])
    assert "GG 15.00%" in pie
    assert "Utilidad 20.00% sobre CD" in pie
    assert "IVA 19.00%" in pie
    assert reporte["parametros"]["pct_gg"] == "0.15"


# Extras ------------------------------------------------------------------
def test_avance_no_puede_superar_lo_contratado(db, obra, presupuesto):
    from fastapi.testclient import TestClient

    from app.main import app

    partida = db.scalars(
        select(Partida).where(
            Partida.presupuesto_id == presupuesto.id, Partida.codigo == "1.1"
        )
    ).first()
    cliente = TestClient(app)
    r = cliente.post(
        f"/api/obras/{obra.id}/avances",
        json={
            "partida_id": partida.id,
            "iso_semana": "2025-W20",
            "fecha_medicion": "2025-05-12",
            "cantidad_acumulada": "99",
        },
    )
    assert r.status_code == 409
    assert "modificación de contrato" in r.json()["detail"]


def test_importacion_es_idempotente(db, obra):
    from app.importador import importar_plantilla
    from seed import RUTA_PLANTILLA

    resultado = importar_plantilla(db, obra, RUTA_PLANTILLA)
    assert resultado.reutilizado is True
