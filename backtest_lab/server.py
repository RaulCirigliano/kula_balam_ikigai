import os
import sys
import subprocess
import tempfile
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="Kula Balam - Sandbox de Backtesting")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1. Ruta absoluta exacta a tu Data Lake
DATA_DIR = r"C:\Users\raulc\Desktop\proyectos\kula_balam_ikigai\data"
WEB_DIR = r"C:\Users\raulc\Desktop\proyectos\kula_balam_ikigai\backtest_lab\web"

class ExecutionRequest(BaseModel):
    category: str    # "crypto_1h" o "tradfi_1d"
    ticker: str      # "ETH-USD", "NVDA", etc.
    code: str        # Script Python pegado

@app.get("/api/datasets")
def list_datasets():
    datasets = {}
    if os.path.exists(DATA_DIR):
        for cat in os.listdir(DATA_DIR):
            cat_path = os.path.join(DATA_DIR, cat)
            if os.path.isdir(cat_path):
                files = [f.replace(".parquet", "") for f in os.listdir(cat_path) if f.endswith(".parquet")]
                datasets[cat] = sorted(files)
    return datasets

@app.post("/api/run")
def run_strategy(req: ExecutionRequest):
    file_path = os.path.join(DATA_DIR, req.category, f"{req.ticker}.parquet")
    if not os.path.exists(file_path):
        return {"status": "error", "output": f"Error: No se encontró el dataset en la ruta:\n{file_path}"}

    # Creamos script temporal
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as temp_file:
        temp_file.write(req.code)
        temp_path = temp_file.name

    try:
        proc = subprocess.run(
            [sys.executable, temp_path, file_path],
            capture_output=True,
            text=True,
            timeout=40
        )
        output = proc.stdout
        if proc.stderr:
            output += "\n--- ERRORES / ALERTAS ---\n" + proc.stderr
        return {"status": "ok", "output": output if output.strip() else "El script se ejecutó pero no imprimió nada por consola."}
    except subprocess.TimeoutExpired:
        return {"status": "error", "output": "Error: Tiempo de ejecución excedido (Timeout > 40s)."}
    except Exception as e:
        return {"status": "error", "output": f"Excepción en el backend: {str(e)}"}
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

@app.get("/")
def serve_index():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8080)