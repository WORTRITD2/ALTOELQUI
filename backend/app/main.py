"""Punto de entrada de la aplicación de gestión de obra.

Un solo servicio sirve la API y la interfaz. En Render (o cualquier host con
Docker) eso basta: la dirección que entrega el host abre la aplicación completa,
con HTTPS, que es lo que la PWA necesita para instalarse en Android.

Publicar el frontend aparte en Netlify sigue siendo válido; en ese caso este
servicio responde solo la API y la raíz muestra una página de estado.
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, select

from .api import router
from .core.parametros import sembrar_catalogo
from .db import Base, SessionLocal, engine

RAIZ_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _ubicar_frontend() -> str | None:
    """El frontend puede venir junto a la API (Docker) o al lado (desarrollo)."""
    candidatos = [
        os.getenv("FRONTEND_DIR"),
        os.path.join(RAIZ_REPO, "frontend"),
        "/frontend",
    ]
    for ruta in candidatos:
        if ruta and os.path.isfile(os.path.join(ruta, "index.html")):
            return ruta
    return None


FRONTEND = _ubicar_frontend()

app = FastAPI(
    title="Gestión de Obra",
    description=(
        "Avance real por partida, estados de pago y control contra la programación "
        "en semanas laborales hábiles. Parámetros por obra con vigencia temporal."
    ),
    version="1.0.0",
)

# Con el frontend servido desde aquí no hay cruce de dominios. ORIGENES_PERMITIDOS
# solo hace falta si la interfaz se publica aparte (Netlify).
ORIGENES = [o.strip() for o in os.getenv("ORIGENES_PERMITIDOS", "*").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGENES,
    allow_credentials="*" not in ORIGENES,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


def _sembrar_si_esta_vacia() -> str:
    """Carga la obra de referencia la primera vez, si hay plantilla disponible.

    Los hosts gratuitos no siempre dan consola, así que la primera carga tiene
    que poder ocurrir sola. Solo actúa con la base recién creada: nunca toca
    datos existentes.
    """
    from .models import Obra

    db = SessionLocal()
    try:
        if db.scalars(select(Obra)).first() is not None:
            return "la base ya tiene obras: no se siembra"
    finally:
        db.close()

    if os.getenv("SEMBRAR_AL_ARRANCAR", "1") != "1":
        return "siembra desactivada (SEMBRAR_AL_ARRANCAR=0)"

    import seed

    if not os.path.isfile(seed.RUTA_PLANTILLA):
        return f"sin plantilla en {seed.RUTA_PLANTILLA}: base vacía"
    try:
        seed.main(reset=False)
        return "obra de referencia cargada desde la plantilla"
    except Exception as exc:  # noqa: BLE001 — arrancar igual, con el aviso
        return f"no se pudo sembrar: {type(exc).__name__} {exc}"


ESTADO_ARRANQUE: dict[str, str] = {}


@app.on_event("startup")
def inicializar() -> None:
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        sembrar_catalogo(db)
    finally:
        db.close()
    ESTADO_ARRANQUE["siembra"] = _sembrar_si_esta_vacia()
    ESTADO_ARRANQUE["frontend"] = FRONTEND or "no incluido"


@app.get("/salud")
def salud() -> dict:
    from .models import Obra

    db = SessionLocal()
    try:
        obras = len(list(db.scalars(select(Obra)).all()))
    except Exception:  # noqa: BLE001
        obras = -1
    finally:
        db.close()
    return {
        "estado": "ok",
        "obras": obras,
        "frontend": bool(FRONTEND),
        "motor": engine.url.get_backend_name(),
        "tablas": len(inspect(engine).get_table_names()),
        "arranque": ESTADO_ARRANQUE,
    }


# La interfaz se sirve en la raíz para que la PWA (service worker, manifest e
# iconos) tenga el alcance correcto. Se monta al final: las rutas de la API ya
# están registradas y tienen prioridad.
if FRONTEND:
    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
else:

    @app.get("/", response_class=HTMLResponse)
    def portada() -> str:
        """Sin interfaz empaquetada, la raíz explica qué es esto en vez de dar 404."""
        return """<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>API de Gestión de Obra</title>
<style>body{font-family:system-ui,Arial,sans-serif;max-width:38rem;margin:3rem auto;
padding:0 1.2rem;color:#16202c;line-height:1.5} code{background:#eef1f5;padding:.1rem .35rem;
border-radius:4px} a{color:#1f3864} .ok{color:#1a7f4b;font-weight:600}</style></head><body>
<h1>API de Gestión de Obra</h1>
<p class="ok">El servicio está funcionando.</p>
<p>Esta dirección responde <strong>solo la API</strong>: la interfaz no viene empaquetada en
esta imagen, así que la raíz no tiene una página que mostrar.</p>
<ul>
  <li><a href="/salud">/salud</a> — estado del servicio y cuántas obras hay cargadas</li>
  <li><a href="/docs">/docs</a> — documentación interactiva de la API</li>
  <li><a href="/api/obras">/api/obras</a> — obras registradas</li>
</ul>
<h2>¿Quieres ver la aplicación aquí mismo?</h2>
<p>Reconstruye la imagen con el contexto en la raíz del repositorio (el
<code>render.yaml</code> incluido ya lo hace) para que la interfaz viaje junto a la API. La
otra opción es publicarla en Netlify apuntando <code>API_URL</code> a esta dirección.</p>
</body></html>"""
