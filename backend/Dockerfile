# Imagen única: API + interfaz + plantilla de referencia.
# El contexto de build es la RAÍZ del repositorio (ver render.yaml).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY backend/requirements.txt .
RUN pip install -r requirements.txt

COPY backend/ /app/
COPY frontend/ /frontend/
COPY plantilla/ /plantilla/

ENV FRONTEND_DIR=/frontend \
    PLANTILLA_DIR=/plantilla \
    PORT=8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
