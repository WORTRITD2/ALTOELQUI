@echo off
REM Levanta la aplicacion completa en este computador (Windows).
cd /d "%~dp0backend"

if not exist .venv (
  echo Creando entorno de Python...
  python -m venv .venv
)
call .venv\Scripts\activate.bat

echo Instalando dependencias...
pip install -q -r requirements.txt

if not exist obra.db (
  echo Cargando la obra de referencia desde la plantilla...
  python seed.py
)

echo.
echo --------------------------------------------------
echo   Abre en el navegador:  http://127.0.0.1:8000
echo   Para detener: Ctrl+C
echo --------------------------------------------------
echo.
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
