@echo off
cd /d "%~dp0"

:: Activar entorno virtual si existe
if exist ".venv\Scriptsctivate.bat" (
    call .venv\Scriptsctivate.bat
) else if exist "venv\Scriptsctivate.bat" (
    call venv\Scriptsctivate.bat
) else if exist "..env\Scriptsctivate.bat" (
    call ..env\Scriptsctivate.bat
)

:: Abrir navegador
start http://127.0.0.1:8000

:: Lanzar servidor
python -m uvicorn server:app --host 127.0.0.1 --port 8000 --reload
pause
