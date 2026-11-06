import time
import ccxt
import pandas as pd
from datetime import datetime, timezone
from balam import BalamQuant
from kula import KulaRisk

def to_df(data):
    df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    return df

def run_loop():
    print("==========================================================")
    print("  KULA BALAM: SIMULADOR EN TIEMPO REAL (CANASTA 1H)")
    print("  Activos: BTC/USDT, ETH/USDT, SOL/USDT | Saldo Inicial: $100")
    print("==========================================================")

    exchange = ccxt.binance({'enableRateLimit': True})
    symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
    
    balam = BalamQuant()
    kula = KulaRisk(initial_balance=100.0, risk_usd=1.00)

    last_processed_hour = None

    while True:
        try:
            now = datetime.now(timezone.utc)

            # 1. Monitoreo de salidas continuo cada 30 segundos
            for sym in symbols:
                ticker = exchange.fetch_ticker(sym)
                current_price = ticker['last']
                out = kula.monitorear_salidas(sym, current_price, current_price, now)
                if out:
                    print(f"\n[CIERRE TRADE] {out['symbol']} | {out['side']} cerrado por {out['type']} | PnL: {out['pnl']:+.2f} USD | Balance: ${out['balance_actual']:.2f} USD")

            # 2. Evaluación de nuevas velas al completar cada hora
            if last_processed_hour != now.hour and now.minute >= 1:
                print(f"\n[{now.strftime('%Y-%m-%d %H:%M:%S')} UTC] Analizando cierre de vela 1H...")

                for sym in symbols:
                    ohlcv_1h = exchange.fetch_ohlcv(sym, timeframe='1h', limit=60)
                    ohlcv_1d = exchange.fetch_ohlcv(sym, timeframe='1d', limit=60)
                    df_1h = to_df(ohlcv_1h)
                    df_1d = to_df(ohlcv_1d)

                    df_1h = balam.calcular_indicadores(df_1h, df_1d, sym)
                    senal = balam.escanear_senal(df_1h, sym)

                    if senal:
                        ok, msg = kula.auditar_y_ejecutar(senal)
                        print(f"  -> Señal detectada en {sym}: {msg}")

                last_processed_hour = now.hour
                print(f"  Posiciones activas: {len(kula.active_positions)} | Balance: ${kula.balance:.2f} USD")

            time.sleep(30)

        except Exception as e:
            print(f"[Error en loop]: {e}")
            time.sleep(15)

if __name__ == '__main__':
    run_loop()
