import os
import ccxt
import yfinance as yf
import pandas as pd

DATA_DIR = "/home/raul/Escritorio/proyectos/kula_balam_ikigai/datos_historicos"
os.makedirs(DATA_DIR, exist_ok=True)

def descargar_cripto():
    exchange = ccxt.binance({
        'enableRateLimit': True,
        'timeout': 10000
    })
    simbolos = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
    timeframes = ['1h', '4h']

    print("==========================================================")
    print("  DESCARGANDO Y GUARDANDO CRIPTO (BINANCE - CCXT)")
    print("==========================================================")

    for sym in simbolos:
        sym_clean = sym.replace('/', '_')
        for tf in timeframes:
            print(f"  -> Descargando {sym} [{tf}] (1000 velas)...")
            try:
                ohlcv = exchange.fetch_ohlcv(sym, timeframe=tf, limit=1000)
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
                
                # Guardar en Parquet y CSV
                file_base = os.path.join(DATA_DIR, f"binance_{sym_clean}_{tf}")
                df.to_parquet(f"{file_base}.parquet", index=False)
                df.to_csv(f"{file_base}.csv", index=False)
                print(f"     [OK] Guardado: {file_base}.parquet ({len(df)} velas)")
            except Exception as e:
                print(f"     [ERROR] Falló al descargar {sym} [{tf}]: {e}")

def descargar_acciones():
    print("\n==========================================================")
    print("  DESCARGANDO Y GUARDANDO ACCIONES / ÍNDICES (YFINANCE)")
    print("==========================================================")

    tickers = ['QQQ', 'SPY', 'NVDA', 'TSLA']
    configuraciones = [
        ('5m', '60d'),
        ('15m', '60d'),
        ('1d', '2y')
    ]

    for ticker_name in tickers:
        ticker = yf.Ticker(ticker_name)
        for interval, period in configuraciones:
            print(f"  -> Descargando {ticker_name} [{interval}] (período: {period})...")
            try:
                df = ticker.history(period=period, interval=interval)
                if df.empty:
                    print(f"     [AVISO] No se obtuvieron datos para {ticker_name} [{interval}]")
                    continue
                
                # Normalizar columnas y zona horaria
                df.reset_index(inplace=True)
                df.rename(columns={
                    'Date': 'datetime',
                    'Datetime': 'datetime',
                    'Open': 'open',
                    'High': 'high',
                    'Low': 'low',
                    'Close': 'close',
                    'Volume': 'volume'
                }, inplace=True)

                file_base = os.path.join(DATA_DIR, f"yf_{ticker_name}_{interval}")
                df.to_parquet(f"{file_base}.parquet", index=False)
                df.to_csv(f"{file_base}.csv", index=False)
                print(f"     [OK] Guardado: {file_base}.parquet ({len(df)} velas)")
            except Exception as e:
                print(f"     [ERROR] Falló al descargar {ticker_name} [{interval}]: {e}")

if __name__ == '__main__':
    descargar_cripto()
    descargar_acciones()
    print("\n==========================================================")
    print(f"  PROCESO COMPLETADO. Datos guardados en:\n  {DATA_DIR}")
    print("==========================================================\n")
