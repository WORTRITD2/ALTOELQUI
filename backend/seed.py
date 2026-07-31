"""Carga la obra de referencia completa: plantilla, mediciones, programación y EP.

    python seed.py [--reset]

Reproduce el escenario real: presupuesto de $807.962.805, corte del 03-03-2025
(6,67%) y corte del 17-03-2025 (20,40%), con sus dos estados de pago.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
from decimal import Decimal

from sqlalchemy import select

from app.core import parametros as P
from app.core import programacion as PR
from app.core.calculo import aprobar_estado_pago, calcular_avance, generar_estado_pago
from app.core.calendario import CalendarioObra, sembrar_feriados
from app.db import Base, SessionLocal, engine
from app.importador import importar_plantilla, leer_mediciones
from app.models import (
    AvanceSemanal,
    EstadoPago,
    Obra,
    Organizacion,
    Partida,
    PlantillaParametros,
    PlantillaParametroValor,
)

RUTA_PLANTILLA = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "plantilla",
    "PPTO_RCR_Conservacion_Escuela_Juan_Sandoval_Carrasco.xlsx",
)

PARAMETROS_RCR = {
    "pct_gg": "0.15",
    "pct_utilidad": "0.20",
    "base_utilidad": "CD",
    "pct_iva": "0.19",
    "pct_leyes_sociales": "0.50",
    "pct_anticipo": "0",
    "pct_retencion": "0",
    "dias_habiles_semana": "1,2,3,4,5",
    "horas_jornada": "8.5",
    "moneda": "CLP",
    "reajuste": "SIN_REAJUSTE",
    "politica_redondeo": "TOTALES",
    "decimales_moneda": "0",
    "plazo_dias": "180",
    "plazo_tipo_dias": "CORRIDOS",
}

CORTES = [
    ("avance real ", dt.date(2025, 3, 3)),
    ("avance proyectado 20%", dt.date(2025, 3, 17)),
]


def cargar_mediciones(db, obra, presupuesto, hoja: str, fecha_esperada: dt.date) -> int:
    fecha, mediciones = leer_mediciones(RUTA_PLANTILLA, hoja)
    fecha = fecha or fecha_esperada
    partidas = {
        p.codigo: p
        for p in db.scalars(select(Partida).where(Partida.presupuesto_id == presupuesto.id)).all()
    }
    iso = fecha.strftime("%G-W%V")
    cargadas = 0
    for codigo, cantidad in mediciones.items():
        p = partidas.get(codigo)
        if p is None or not p.es_medible:
            continue
        fila = db.scalars(
            select(AvanceSemanal).where(
                AvanceSemanal.obra_id == obra.id,
                AvanceSemanal.partida_id == p.id,
                AvanceSemanal.iso_semana == iso,
            )
        ).first()
        if fila is None:
            fila = AvanceSemanal(
                obra_id=obra.id, partida_id=p.id, iso_semana=iso, fecha_medicion=fecha
            )
            db.add(fila)
        fila.fecha_medicion = fecha
        fila.cantidad_acumulada = cantidad
        fila.estado = "APROBADO"
        fila.registrado_por = "jefe_terreno"
        fila.aprobado_por = "ito"
        cargadas += 1
    db.commit()
    return cargadas


def main(reset: bool = False) -> None:
    if reset and engine.url.database and os.path.exists(engine.url.database):
        os.remove(engine.url.database)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    P.sembrar_catalogo(db)
    print(f"Feriados sembrados: {sembrar_feriados(db, 2024, 2027)}")

    org = db.scalars(select(Organizacion)).first()
    if org is None:
        org = Organizacion(razon_social="Constructora RCR SpA", rut="76.000.000-0")
        db.add(org)
        db.commit()

    plantilla = db.scalars(select(PlantillaParametros)).first()
    if plantilla is None:
        plantilla = PlantillaParametros(
            organizacion_id=org.id,
            nombre="Estándar RCR — obras públicas",
            descripcion="GG 15%, utilidad 20% sobre CD, IVA 19%, leyes sociales 50%.",
        )
        db.add(plantilla)
        db.commit()
        for clave, valor in PARAMETROS_RCR.items():
            db.add(PlantillaParametroValor(plantilla_id=plantilla.id, clave=clave, valor=valor))
        db.commit()

    obra = db.scalars(select(Obra).where(Obra.nombre.like("%Sandoval%"))).first()
    if obra is None:
        obra = Obra(
            organizacion_id=org.id,
            nombre="Conservación Escuela Juan Sandoval Carrasco",
            licitacion_id="CONSERVACIÓN ESCUELA JUAN SANDOVAL CARRASCO",
            mandante="Servicio Local de Educación Pública Puerto Cordillera",
            contratista="Constructora RCR SpA",
            ubicacion="Santa Elena N°385, Coquimbo",
            fecha_inicio=dt.date(2025, 2, 17),
            plazo_dias=180,
        )
        db.add(obra)
        db.commit()
        P.aplicar_plantilla(db, obra.id, PARAMETROS_RCR, obra.fecha_inicio, usuario="seed")
        print(f"Obra {obra.id} creada con {len(PARAMETROS_RCR)} parámetros vigentes")

    resultado = importar_plantilla(db, obra, RUTA_PLANTILLA)
    presupuesto = resultado.presupuesto
    if resultado.reutilizado:
        print("Plantilla ya importada (idempotente): se reutiliza el presupuesto existente")
    else:
        r = resultado.resumen()
        print(
            f"Importación: {r['partidas_medibles']} partidas medibles, "
            f"{r['no_medibles']} no medibles, {r['apus']} APU, "
            f"{r['errores']} errores de validación sobre {r['hallazgos']} hallazgos"
        )
        for regla, n in r["por_regla"].items():
            print(f"    {regla}: {n}")

    for hoja, fecha in CORTES:
        n = cargar_mediciones(db, obra, presupuesto, hoja, fecha)
        res = calcular_avance(db, presupuesto, fecha)
        print(f"Corte {fecha:%d-%m-%Y}: {n} mediciones · avance {res.pct * 100:.4f}%")

    cal = CalendarioObra(db, obra.id, "1,2,3,4,5", 8.5)
    prog = PR.generar_linea_base(db, presupuesto, cal, obra.fecha_inicio, 180, Decimal("1"))
    print(f"Programación línea base v{prog.version} generada")

    for numero, (_, fecha) in enumerate(CORTES, start=1):
        ep = generar_estado_pago(db, obra, presupuesto, fecha, numero)
        print(
            f"EP N°{ep.numero} corte {fecha:%d-%m-%Y}: período ${ep.total:,.0f} · "
            f"acumulado ${ep.total_acum:,.0f} ({ep.pct_acum * 100:.2f}%)".replace(",", ".")
        )
    primero = db.scalars(select(EstadoPago).order_by(EstadoPago.numero)).first()
    if primero and primero.estado == "BORRADOR":
        aprobar_estado_pago(db, primero, "oficina_tecnica")
        print(f"EP N°{primero.numero} aprobado con snapshot de parámetros congelado")

    db.close()
    print("\nListo. Levanta la aplicación con:  uvicorn app.main:app --reload")


if __name__ == "__main__":
    main(reset="--reset" in sys.argv)
