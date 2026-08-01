"""Conexión a base de datos y tipos base.

Por defecto SQLite (sin servidor, portable). Con DATABASE_URL apuntando a
PostgreSQL funciona igual: los montos se guardan como texto exacto para no
perder precisión en ningún motor.
"""
from __future__ import annotations

import os
from decimal import Decimal

from sqlalchemy import String, TypeDecorator, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./obra.db")

# Render, Heroku y otros entregan la URL como "postgres://…", que SQLAlchemy 2
# no reconoce. Se normaliza aquí para que el despliegue no falle al arrancar.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Money(TypeDecorator):
    """Decimal exacto. Nunca punto flotante binario para dinero ni cantidades."""

    impl = String(40)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return str(Decimal(str(value)))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return Decimal(value)


def get_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
