import os
import tempfile

import pytest

BD = os.path.join(tempfile.gettempdir(), "obra_tests.db")
os.environ["DATABASE_URL"] = f"sqlite:///{BD}"

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import Obra, Presupuesto  # noqa: E402
from sqlalchemy import select  # noqa: E402
import seed  # noqa: E402


@pytest.fixture(scope="session")
def escenario():
    """La obra de referencia completa, cargada una sola vez."""
    if os.path.exists(BD):
        os.remove(BD)
    Base.metadata.create_all(engine)
    seed.main(reset=False)
    db = SessionLocal()
    obra = db.scalars(select(Obra)).first()
    presupuesto = db.scalars(select(Presupuesto)).first()
    yield db, obra, presupuesto
    db.close()


@pytest.fixture
def db(escenario):
    return escenario[0]


@pytest.fixture
def obra(escenario):
    return escenario[1]


@pytest.fixture
def presupuesto(escenario):
    return escenario[2]
