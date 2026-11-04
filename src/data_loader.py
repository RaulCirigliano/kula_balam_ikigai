"""
Módulo de descarga y persistencia de velas OHLCV limpias usando ccxt.
"""
from datetime import datetime, timezone
import os
import ccxt
import pandas as pd


def descargar_velas_binance(
    symbol: str = "BTC/USDT",
    timeframe: str = "5m",
    dias_atras: int = 45,
    carpeta_salida: str = "data",
) -> str:
    """Descarga el histórico de velas de Binance y lo guarda en CSV."""
    exchange = ccxt.binance({"enableRateLimit": True})

    ahora = datetime.now(timezone.utc)
    desde_ms = int((ahora.timestamp() - (dias_atras * 24 * 60 * 60)) * 1000)

    print(
        f"Descargando {symbol} [{timeframe}] de los últimos {dias_atras} días..."
    )

    todas_las_velas = []
    limite_por_llamada = 1000

    while True:
        velas = exchange.fetch_ohlcv(
            symbol, timeframe=timeframe, since=desde_ms, limit=limite_por_llamada
        )
        if not velas:
            break

        todas_las_velas.extend(velas)
        desde_ms = velas[-1][0] + 1

        if len(velas) < limite_por_llamada:
            break

    df = pd.DataFrame(
        todas_las_velas,
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")

    os.makedirs(carpeta_salida, exist_ok=True)
    nombre_limpio = symbol.replace("/", "_").lower()
    ruta_archivo = os.path.join(
        carpeta_salida, f"{nombre_limpio}_{timeframe}.csv"
    )

    df.to_csv(ruta_archivo, index=False)
    print(f"Listo: {len(df)} velas guardadas en {ruta_archivo}")
    return ruta_archivo

if __name__ == "__main__":
    descargar_velas_binance(symbol="BTC/USDT", timeframe="15m", dias_atras=90)