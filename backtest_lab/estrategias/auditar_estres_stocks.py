import yfinance as yf
import pandas as pd
import numpy as np

def run_stress_backtest(ticker, start_date, end_date, label, fee_rate=0.0005):
    df = yf.download(ticker, start=start_date, end=end_date, interval='1d', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0].lower() for col in df.columns]
    else:
        df.columns = [col.lower() for col in df.columns]
    df = df.dropna().copy()

    if len(df) < 220:
        return None

    # Donchian 20 y EMA 200 con shift(1) estricto (cero repainting)
    df['donchian_high'] = df['high'].shift(1).rolling(20).max()
    df['donchian_low'] = df['low'].shift(1).rolling(20).min()
    df['donchian_mid'] = (df['donchian_high'] + df['donchian_low']) / 2.0
    df['ema200'] = df['close'].shift(1).ewm(span=200, adjust=False).mean()

    capital = 100.0
    peak_equity = 100.0
    max_dd = 0.0
    trades = []
    in_pos = False
    entry_price = 0.0

    for i in range(201, len(df)):
        row = df.iloc[i]
        open_p = float(row['open'])
        close = float(row['close'])
        low = float(row['low'])
        mid = float(row['donchian_mid'])
        upper = float(row['donchian_high'])
        ema = float(row['ema200'])

        if in_pos:
            exit_price = None
            exit_reason = None
            initial_sl = entry_price * 0.985  # SL teórico al -1.5%

            # 1. Chequeo de GAP bajista al Open (deslizamiento nocturno real)
            if open_p <= initial_sl:
                exit_price = open_p
                exit_reason = 'GAP_SL'
            # 2. Intradía toca SL teórico
            elif low <= initial_sl:
                exit_price = initial_sl
                exit_reason = 'SL'
            # 3. Salida Estructural por Banda Media (MID_EXIT) al cierre
            elif close < mid:
                exit_price = close
                exit_reason = 'MID_EXIT'

            if exit_price is not None:
                raw_return = (exit_price - entry_price) / entry_price
                net_return = raw_return - fee_rate
                trade_usd = min(capital, 100.0) * net_return
                capital += trade_usd

                if capital > peak_equity:
                    peak_equity = capital
                dd = (peak_equity - capital) / peak_equity * 100.0
                if dd > max_dd:
                    max_dd = dd

                trades.append({
                    'exit_reason': exit_reason,
                    'net_return': net_return,
                    'pnl_usd': trade_usd
                })
                in_pos = False

        if not in_pos:
            # Entrada: Ruptura de Donchian High con filtro macro EMA 200
            if close > upper and close > ema:
                in_pos = True
                entry_price = close

    if not trades:
        return {'N': 0, 'WR': 0.0, 'PF': 0.0, 'PnL': 0.0, 'MaxDD': 0.0, 'Salidas': {}}

    df_t = pd.DataFrame(trades)
    wins = df_t[df_t['pnl_usd'] > 0]
    losses = df_t[df_t['pnl_usd'] <= 0]
    wr = (len(wins) / len(df_t)) * 100.0
    gross_profit = wins['pnl_usd'].sum()
    gross_loss = abs(losses['pnl_usd'].sum())
    pf = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)
    pnl = df_t['pnl_usd'].sum()
    salidas = df_t['exit_reason'].value_counts().to_dict()

    return {
        'N': len(df_t),
        'WR': round(wr, 2),
        'PF': round(pf, 2),
        'PnL': round(pnl, 2),
        'MaxDD': round(max_dd, 2),
        'Salidas': salidas
    }

def main():
    tickers = ['SPY', 'NVDA', 'AAPL', 'MSFT']
    
    print("=" * 82)
    print(" AUDITORÍA DE ESTRÉS: WALL STREET 1D CON GAPS NOCTURNOS REALES")
    print("=" * 82)

    # 1. Test 5 Años Completos (2021-2026) con penalización por Gaps
    print("\n--- TEST 1: HISTÓRICO GLOBAL (5 AÑOS) CON GAPS NOCTURNOS REALES ---")
    print(f"{'Activo':<8} | {'Trades':<8} | {'Win Rate':<10} | {'Profit Factor':<14} | {'PnL ($100)':<12} | {'Max DD':<10} | {'Salidas':<20}")
    print("-" * 82)
    for t in tickers:
        res = run_stress_backtest(t, '2021-01-01', '2026-10-30', '5y')
        if res:
            salidas_str = f"GAP:{res['Salidas'].get('GAP_SL',0)} SL:{res['Salidas'].get('SL',0)} MID:{res['Salidas'].get('MID_EXIT',0)}"
            print(f"{t:<8} | {res['N']:<8} | {res['WR']:<9}% | {res['PF']:<14} | ${res['PnL']:<11} | {res['MaxDD']:<9}% | {salidas_str:<20}")

    # 2. Test Año Bajista Brutal: 2022 Aislado
    print("\n--- TEST 2: PRUEBA DE FUEGO EN BEAR MARKET (AÑO 2022 COMPLETO) ---")
    print(f"{'Activo':<8} | {'Trades':<8} | {'Win Rate':<10} | {'Profit Factor':<14} | {'PnL ($100)':<12} | {'Max DD':<10} | {'Salidas':<20}")
    print("-" * 82)
    for t in tickers:
        # Se toma desde 2021 para que la EMA200 y Donchian ya estén calculados al arrancar 2022
        res = run_stress_backtest(t, '2021-01-01', '2023-01-01', '2022')
        if res:
            salidas_str = f"GAP:{res['Salidas'].get('GAP_SL',0)} SL:{res['Salidas'].get('SL',0)} MID:{res['Salidas'].get('MID_EXIT',0)}"
            print(f"{t:<8} | {res['N']:<8} | {res['WR']:<9}% | {res['PF']:<14} | ${res['PnL']:<11} | {res['MaxDD']:<9}% | {salidas_str:<20}")
    print("-" * 82)

if __name__ == '__main__':
    main()
