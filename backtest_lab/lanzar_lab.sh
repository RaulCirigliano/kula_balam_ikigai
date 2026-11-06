#!/bin/bash
# Obtener directorio real del script de forma dinamica y portable
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Buscar entorno virtual: primero local (.venv o venv), luego un nivel arriba
if [ -d "$DIR/.venv" ]; then
    source "$DIR/.venv/bin/activate"
elif [ -d "$DIR/venv" ]; then
    source "$DIR/venv/bin/activate"
elif [ -d "$DIR/../venv" ]; then
    source "$DIR/../venv/bin/activate"
fi

# Abrir el navegador en segundo plano
(sleep 2 && xdg-open "http://127.0.0.1:8000") &

# Lanzar FastAPI
python3 -m uvicorn server:app --host 127.0.0.1 --port 8000 --reload
