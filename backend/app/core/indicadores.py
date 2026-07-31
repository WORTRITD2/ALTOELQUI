"""Indicadores económicos oficiales: UF, UTM, UTA, IPC, dólar observado (§4.4).

Diseño offline-first. Nunca se inventa un valor: si ninguna fuente responde se
usa el último conocido, se marca PROVISIONAL y la advertencia viaja hasta el
PDF del estado de pago.

Prioridad de fuentes:
  1. Banco Central de Chile (oficial, requiere credenciales gratuitas)
  2. SII — contraste de UF/UTM/UTA
  3. mindicador.cl — respaldo, marcado como NO OFICIAL
  4. Carga manual con rol autorizado
"""
from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import IndicadorValor, SincronizacionIndicador

# Códigos de serie del BCCh: configurables, nunca incrustados en la lógica.
SERIES_BCCH = {
    "UF": os.getenv("BCCH_SERIE_UF", "F073.UFF.PRE.Z.D"),
    "UTM": os.getenv("BCCH_SERIE_UTM", "F073.UTR.PRE.Z.M"),
    "IPC": os.getenv("BCCH_SERIE_IPC", "F074.IPC.VAR.Z.EP23.C.M"),
    "USD_OBS": os.getenv("BCCH_SERIE_USD", "F073.TCO.PRE.Z.D"),
}
SERIES_MINDICADOR = {"UF": "uf", "UTM": "utm", "IPC": "ipc", "USD_OBS": "dolar"}

FRECUENCIA = {"UF": "DIARIA", "UTM": "MENSUAL", "UTA": "ANUAL", "IPC": "MENSUAL", "USD_OBS": "DIARIA"}

# Rangos de cordura (§4.4): fuera de esto se marca para revisión humana.
RANGOS = {
    "UF": (Decimal("20000"), Decimal("200000")),
    "UTM": (Decimal("30000"), Decimal("300000")),
    "USD_OBS": (Decimal("300"), Decimal("3000")),
}
VARIACION_DIARIA_MAX_UF = Decimal("0.005")  # 0,5%


@dataclass
class Lectura:
    codigo: str
    fecha: dt.date
    valor: Decimal | None
    fuente: str | None
    estado: str  # CONFIRMADO | PROVISIONAL | SIN_DATO
    advertencia: str | None = None
    obtenido_en: dt.datetime | None = None
    url_origen: str | None = None

    def as_dict(self) -> dict:
        return {
            "codigo": self.codigo,
            "fecha": self.fecha.isoformat(),
            "valor": str(self.valor) if self.valor is not None else None,
            "fuente": self.fuente,
            "estado": self.estado,
            "advertencia": self.advertencia,
            "obtenido_en": self.obtenido_en.isoformat() if self.obtenido_en else None,
            "url_origen": self.url_origen,
        }

    def leyenda(self) -> str:
        """Lo que se imprime al pie del EP."""
        if self.valor is None:
            return f"{self.codigo} al {self.fecha:%d-%m-%Y}: SIN DATO"
        cuando = f", consultado el {self.obtenido_en:%d-%m-%Y %H:%M}" if self.obtenido_en else ""
        prov = " [PROVISIONAL]" if self.estado == "PROVISIONAL" else ""
        return f"{self.codigo} al {self.fecha:%d-%m-%Y} = {self.valor} ({self.fuente}{cuando}){prov}"


class Proveedor:
    nombre = "BASE"
    oficial = True

    def disponible(self) -> bool:
        return False

    def obtener(self, codigo: str, desde: dt.date, hasta: dt.date) -> list[tuple[dt.date, Decimal]]:
        raise NotImplementedError


class ProveedorBCCh(Proveedor):
    """Base de Datos Estadísticos del Banco Central. Fuente oficial."""

    nombre = "BCCH"
    oficial = True
    URL = "https://si3.bcentral.cl/SieteRestWS/SieteRestWS.ashx"

    def __init__(self) -> None:
        self.user = os.getenv("BCCH_USER")
        self.password = os.getenv("BCCH_PASS")

    def disponible(self) -> bool:
        return bool(self.user and self.password)

    def obtener(self, codigo, desde, hasta):
        import httpx

        serie = SERIES_BCCH.get(codigo)
        if not serie:
            return []
        params = {
            "user": self.user,
            "pass": self.password,
            "function": "GetSeries",
            "timeseries": serie,
            "firstdate": desde.isoformat(),
            "lastdate": hasta.isoformat(),
        }
        r = httpx.get(self.URL, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        salida: list[tuple[dt.date, Decimal]] = []
        for serie_obj in (data.get("Series") or {}).get("Obs", []) or []:
            fecha_txt, valor_txt = serie_obj.get("indexDateString"), serie_obj.get("value")
            if not fecha_txt or valor_txt in (None, "", "NaN"):
                continue
            fecha = dt.datetime.strptime(fecha_txt, "%d-%m-%Y").date()
            salida.append((fecha, Decimal(str(valor_txt))))
        return salida


class ProveedorMindicador(Proveedor):
    """API pública gratuita. Respaldo: se registra como fuente NO OFICIAL."""

    nombre = "MINDICADOR"
    oficial = False
    URL = "https://mindicador.cl/api"

    def disponible(self) -> bool:
        return os.getenv("INDICADORES_PERMITIR_NO_OFICIAL", "1") == "1"

    def obtener(self, codigo, desde, hasta):
        import httpx

        serie = SERIES_MINDICADOR.get(codigo)
        if not serie:
            return []
        salida: list[tuple[dt.date, Decimal]] = []
        anios = range(desde.year, hasta.year + 1)
        for anio in anios:
            r = httpx.get(f"{self.URL}/{serie}/{anio}", timeout=20)
            r.raise_for_status()
            for obs in r.json().get("serie", []):
                fecha = dt.datetime.fromisoformat(obs["fecha"].replace("Z", "+00:00")).date()
                if desde <= fecha <= hasta:
                    salida.append((fecha, Decimal(str(obs["valor"]))))
        return salida


class ServicioIndicadores:
    def __init__(self, db: Session, proveedores: list[Proveedor] | None = None) -> None:
        self.db = db
        self.proveedores = proveedores if proveedores is not None else [
            ProveedorBCCh(),
            ProveedorMindicador(),
        ]

    # -- sincronización ---------------------------------------------------
    def sincronizar(self, codigo: str, desde: dt.date, hasta: dt.date) -> SincronizacionIndicador:
        errores: list[str] = []
        for prov in self.proveedores:
            if not prov.disponible():
                errores.append(f"{prov.nombre}: no configurado")
                continue
            try:
                obs = prov.obtener(codigo, desde, hasta)
            except Exception as exc:  # noqa: BLE001 — la red falla, no la app
                errores.append(f"{prov.nombre}: {type(exc).__name__} {exc}")
                continue
            nuevos = self._guardar(codigo, obs, prov)
            sync = SincronizacionIndicador(
                codigo=codigo,
                rango_desde=desde,
                rango_hasta=hasta,
                estado="OK" if obs else "PARCIAL",
                fuente=prov.nombre,
                valores_nuevos=nuevos,
                detalle="; ".join(errores) or None,
            )
            self.db.add(sync)
            self.db.commit()
            return sync

        sync = SincronizacionIndicador(
            codigo=codigo,
            rango_desde=desde,
            rango_hasta=hasta,
            estado="ERROR",
            valores_nuevos=0,
            detalle="; ".join(errores) or "sin proveedores disponibles",
        )
        self.db.add(sync)
        self.db.commit()
        return sync

    def _guardar(self, codigo, observaciones, proveedor) -> int:
        nuevos = 0
        for fecha, valor in observaciones:
            ya = self.db.scalars(
                select(IndicadorValor)
                .where(
                    IndicadorValor.codigo == codigo,
                    IndicadorValor.fecha == fecha,
                    IndicadorValor.fuente == proveedor.nombre,
                )
                .order_by(IndicadorValor.obtenido_en.desc())
            ).first()
            if ya and ya.valor == valor:
                continue  # ya registrado, idéntico
            nota = None if proveedor.oficial else "Fuente NO OFICIAL (agregador)"
            alerta = self._cordura(codigo, fecha, valor)
            if alerta:
                nota = f"{nota + ' · ' if nota else ''}{alerta}"
            self.db.add(
                IndicadorValor(
                    codigo=codigo,
                    fecha=fecha,
                    valor=valor,
                    fuente=proveedor.nombre,
                    url_origen=getattr(proveedor, "URL", None),
                    estado="CONFIRMADO",
                    nota=nota,
                )
            )
            nuevos += 1
        self.db.commit()
        return nuevos

    def _cordura(self, codigo: str, fecha: dt.date, valor: Decimal) -> str | None:
        rango = RANGOS.get(codigo)
        if rango and not (rango[0] <= valor <= rango[1]):
            return f"Fuera de rango razonable {rango}: revisar"
        if codigo == "UF":
            previo = self.db.scalars(
                select(IndicadorValor)
                .where(IndicadorValor.codigo == "UF", IndicadorValor.fecha < fecha)
                .order_by(IndicadorValor.fecha.desc())
            ).first()
            if previo and previo.valor:
                var = abs(valor - previo.valor) / previo.valor
                if var > VARIACION_DIARIA_MAX_UF:
                    return f"Variación diaria {var:.3%} sobre el máximo esperado: revisar"
        return None

    # -- carga manual -----------------------------------------------------
    def cargar_manual(
        self, codigo: str, fecha: dt.date, valor: Decimal, usuario: str, nota: str | None = None
    ) -> IndicadorValor:
        """Inserta un valor nuevo. Si corrige uno ya usado en un EP aprobado, no lo
        sobrescribe: avisa qué estados de pago quedaron afectados."""
        fila = IndicadorValor(
            codigo=codigo,
            fecha=fecha,
            valor=Decimal(str(valor)),
            fuente="MANUAL",
            estado="CONFIRMADO",
            usuario=usuario,
            nota=nota or "Carga manual autorizada",
        )
        self.db.add(fila)
        self.db.commit()
        return fila

    def estados_pago_afectados(self, codigo: str, fecha: dt.date) -> list[int]:
        """EP aprobados cuyo snapshot congeló este indicador para esa fecha."""
        from ..models import EstadoPago

        filas = self.db.scalars(
            select(EstadoPago).where(
                EstadoPago.estado.in_(("APROBADO", "PAGADO")), EstadoPago.fecha_corte == fecha
            )
        ).all()
        return [e.numero for e in filas]

    # -- lectura ----------------------------------------------------------
    def valor(self, codigo: str, fecha: dt.date, sincronizar_si_falta: bool = False) -> Lectura:
        exacto = self._buscar(codigo, fecha, exacto=True)
        if exacto:
            return Lectura(codigo, fecha, exacto.valor, exacto.fuente, "CONFIRMADO",
                           obtenido_en=exacto.obtenido_en, url_origen=exacto.url_origen)

        if sincronizar_si_falta:
            self.sincronizar(codigo, fecha - dt.timedelta(days=40), fecha)
            exacto = self._buscar(codigo, fecha, exacto=True)
            if exacto:
                return Lectura(codigo, fecha, exacto.valor, exacto.fuente, "CONFIRMADO",
                               obtenido_en=exacto.obtenido_en, url_origen=exacto.url_origen)

        previo = self._buscar(codigo, fecha, exacto=False)
        if previo:
            dias = (fecha - previo.fecha).days
            return Lectura(
                codigo, fecha, previo.valor, previo.fuente, "PROVISIONAL",
                advertencia=(
                    f"Sin valor publicado de {codigo} al {fecha:%d-%m-%Y}. "
                    f"Se usa el último conocido ({previo.fecha:%d-%m-%Y}, {dias} días atrás)."
                ),
                obtenido_en=previo.obtenido_en, url_origen=previo.url_origen,
            )
        return Lectura(
            codigo, fecha, None, None, "SIN_DATO",
            advertencia=f"No hay ningún valor de {codigo} en la base. Sincronice o cargue manualmente.",
        )

    def _buscar(self, codigo: str, fecha: dt.date, exacto: bool) -> IndicadorValor | None:
        q = select(IndicadorValor).where(IndicadorValor.codigo == codigo)
        q = q.where(IndicadorValor.fecha == fecha) if exacto else q.where(IndicadorValor.fecha <= fecha)
        # oficial primero, luego el más reciente
        filas = list(
            self.db.scalars(
                q.order_by(IndicadorValor.fecha.desc(), IndicadorValor.obtenido_en.desc())
            ).all()
        )
        if not filas:
            return None
        oficiales = [f for f in filas if f.fuente in ("BCCH", "SII", "INE", "MANUAL")]
        return (oficiales or filas)[0]

    def contrastar(self, codigo: str, fecha: dt.date) -> dict:
        """Si dos fuentes difieren para la misma fecha, se alerta en vez de elegir en silencio."""
        filas = list(
            self.db.scalars(
                select(IndicadorValor).where(
                    IndicadorValor.codigo == codigo, IndicadorValor.fecha == fecha
                )
            ).all()
        )
        valores = {f.fuente: f.valor for f in filas}
        discrepa = len({str(v) for v in valores.values()}) > 1
        return {
            "codigo": codigo,
            "fecha": fecha.isoformat(),
            "valores": {k: str(v) for k, v in valores.items()},
            "discrepancia": discrepa,
        }
