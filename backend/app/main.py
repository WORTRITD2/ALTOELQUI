"""Punto de entrada de la aplicación de gestión de obra."""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .core.parametros import sembrar_catalogo
from .db import Base, SessionLocal, engine

FRONTEND = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend")

app = FastAPI(
    title="Gestión de Obra",
    description=(
        "Avance real por partida, estados de pago y control contra la programación "
        "en semanas laborales hábiles. Parámetros por obra con vigencia temporal."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.on_event("startup")
def inicializar() -> None:
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        sembrar_catalogo(db)
    finally:
        db.close()


@app.get("/salud")
def salud() -> dict:
    return {"estado": "ok"}


if os.path.isdir(FRONTEND):
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

    @app.get("/")
    def inicio() -> FileResponse:
        return FileResponse(os.path.join(FRONTEND, "index.html"))
