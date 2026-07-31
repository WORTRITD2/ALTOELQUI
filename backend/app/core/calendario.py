"""Semanas laborales hábiles y feriados (§4.4 punto 5, §5).

Las semanas se identifican por ISO-8601 ("2025-W10"). Los días hábiles salen
del parámetro `dias_habiles_semana` de la obra, descontando feriados.

Los feriados de fecha fija están en la semilla; los movibles (Semana Santa) se
calculan. Los trasladables por Ley 19.973, el Día de los Pueblos Indígenas
(solsticio) y los feriados de elecciones NO se inventan: deben venir de la API
oficial o cargarse a mano. `sembrar_feriados` deja constancia de eso.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Feriado

FUENTE_API = "https://apis.digital.gob.cl/fl/feriados"

# Feriados chilenos de fecha fija (estables por ley).
FIJOS: tuple[tuple[int, int, str, bool], ...] = (
    (1, 1, "Año Nuevo", True),
    (5, 1, "Día Nacional del Trabajo", True),
    (5, 21, "Día de las Glorias Navales", False),
    (6, 29, "San Pedro y San Pablo", False),
    (7, 16, "Virgen del Carmen", False),
    (8, 15, "Asunción de la Virgen", False),
    (9, 18, "Independencia Nacional", True),
    (9, 19, "Día de las Glorias del Ejército", True),
    (10, 12, "Encuentro de Dos Mundos", False),
    (10, 31, "Día de las Iglesias Evangélicas y Protestantes", False),
    (11, 1, "Día de Todos los Santos", False),
    (12, 8, "Inmaculada Concepción", False),
    (12, 25, "Navidad", True),
)


def pascua(anio: int) -> dt.date:
    """Domingo de Resurrección (algoritmo de Meeus/Jones/Butcher)."""
    a = anio % 19
    b, c = divmod(anio, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes, dia = divmod(h + l - 7 * m + 114, 31)
    return dt.date(anio, mes, dia + 1)


def feriados_calculados(anio: int) -> list[tuple[dt.date, str, bool]]:
    dom = pascua(anio)
    return [
        (dom - dt.timedelta(days=2), "Viernes Santo", False),
        (dom - dt.timedelta(days=1), "Sábado Santo", False),
    ]


def sembrar_feriados(db: Session, desde_anio: int, hasta_anio: int) -> int:
    """Carga la base mínima verificable. Devuelve cuántos insertó."""
    nuevos = 0
    for anio in range(desde_anio, hasta_anio + 1):
        candidatos = [(dt.date(anio, m, d), n, irr) for m, d, n, irr in FIJOS]
        candidatos += feriados_calculados(anio)
        for fecha, nombre, irrenunciable in candidatos:
            existe = db.scalars(
                select(Feriado).where(Feriado.fecha == fecha, Feriado.obra_id.is_(None))
            ).first()
            if existe:
                continue
            db.add(
                Feriado(
                    fecha=fecha,
                    nombre=nombre,
                    irrenunciable=irrenunciable,
                    fuente="SEMILLA",
                )
            )
            nuevos += 1
    db.commit()
    return nuevos


def feriados_entre(db: Session, obra_id: int | None, desde: dt.date, hasta: dt.date) -> dict[dt.date, str]:
    filas = db.scalars(
        select(Feriado).where(
            Feriado.fecha >= desde,
            Feriado.fecha <= hasta,
            (Feriado.obra_id.is_(None)) | (Feriado.obra_id == obra_id),
        )
    ).all()
    return {f.fecha: f.nombre for f in filas}


def iso_semana(fecha: dt.date) -> str:
    anio, semana, _ = fecha.isocalendar()
    return f"{anio}-W{semana:02d}"


def rango_iso(etiqueta: str) -> tuple[dt.date, dt.date]:
    """Lunes y domingo de una semana ISO."""
    anio, semana = etiqueta.split("-W")
    lunes = dt.date.fromisocalendar(int(anio), int(semana), 1)
    return lunes, lunes + dt.timedelta(days=6)


@dataclass
class Semana:
    iso: str
    inicio: dt.date          # lunes
    fin: dt.date             # domingo
    dias_habiles: int
    horas_habiles: float
    feriados: list[str] = field(default_factory=list)
    primer_habil: dt.date | None = None
    ultimo_habil: dt.date | None = None

    def as_dict(self) -> dict:
        return {
            "iso": self.iso,
            "inicio": self.inicio.isoformat(),
            "fin": self.fin.isoformat(),
            "dias_habiles": self.dias_habiles,
            "horas_habiles": self.horas_habiles,
            "feriados": self.feriados,
            "primer_habil": self.primer_habil.isoformat() if self.primer_habil else None,
            "ultimo_habil": self.ultimo_habil.isoformat() if self.ultimo_habil else None,
        }


class CalendarioObra:
    """Semanas hábiles de una obra, según sus parámetros y los feriados vigentes."""

    def __init__(
        self,
        db: Session,
        obra_id: int,
        dias_habiles: str = "1,2,3,4,5",
        horas_jornada: float = 8.5,
    ) -> None:
        self.db = db
        self.obra_id = obra_id
        self.dias = {int(x) for x in str(dias_habiles).split(",") if x.strip()}
        self.horas_jornada = float(horas_jornada)
        self._feriados: dict[dt.date, str] = {}
        self._cargado: tuple[dt.date, dt.date] | None = None

    def _asegurar(self, desde: dt.date, hasta: dt.date) -> None:
        if self._cargado and self._cargado[0] <= desde and self._cargado[1] >= hasta:
            return
        self._feriados = feriados_entre(self.db, self.obra_id, desde, hasta)
        self._cargado = (desde, hasta)

    def es_habil(self, fecha: dt.date) -> bool:
        self._asegurar(fecha, fecha)
        return fecha.isoweekday() in self.dias and fecha not in self._feriados

    def dias_habiles_entre(self, desde: dt.date, hasta: dt.date) -> int:
        self._asegurar(desde, hasta)
        n, cur = 0, desde
        while cur <= hasta:
            if cur.isoweekday() in self.dias and cur not in self._feriados:
                n += 1
            cur += dt.timedelta(days=1)
        return n

    def semana(self, etiqueta: str) -> Semana:
        inicio, fin = rango_iso(etiqueta)
        self._asegurar(inicio, fin)
        habiles = [
            inicio + dt.timedelta(days=i)
            for i in range(7)
            if (inicio + dt.timedelta(days=i)).isoweekday() in self.dias
            and (inicio + dt.timedelta(days=i)) not in self._feriados
        ]
        nombres = [
            f"{self._feriados[inicio + dt.timedelta(days=i)]} ({(inicio + dt.timedelta(days=i)):%d-%m})"
            for i in range(7)
            if (inicio + dt.timedelta(days=i)) in self._feriados
        ]
        return Semana(
            iso=etiqueta,
            inicio=inicio,
            fin=fin,
            dias_habiles=len(habiles),
            horas_habiles=round(len(habiles) * self.horas_jornada, 2),
            feriados=nombres,
            primer_habil=habiles[0] if habiles else None,
            ultimo_habil=habiles[-1] if habiles else None,
        )

    def semanas(self, desde: dt.date, hasta: dt.date) -> list[Semana]:
        self._asegurar(desde - dt.timedelta(days=7), hasta + dt.timedelta(days=7))
        etiquetas: list[str] = []
        cur = desde - dt.timedelta(days=desde.isoweekday() - 1)
        while cur <= hasta:
            etiquetas.append(iso_semana(cur))
            cur += dt.timedelta(days=7)
        return [self.semana(e) for e in etiquetas]

    def semanas_habiles_necesarias(self, jornadas: float, cuadrillas: float = 1.0) -> float:
        base = 5 * cuadrillas
        return jornadas / base if base else 0.0
