import yfinance as yf
import pandas as pd
import numpy as np

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def run_forex_reversion(ticker='EURUSD=X', interval='1h', period='700d', spread_pips=1.5):
    print(f"[*] Descargando {ticker} ({interval}, {period})...")
    df = yf.download(ticker, period=period, interval=interval, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0].lower() for col in df.columns]
    else:
        df.columns = [col.lower() for col in df.columns]
    df = df.dropna().copy()

    if len(df) < 200:
        print("[!] Datos insuficientes.")
        return

    # Indicadores con shift(1) estricto (cero repainting)
    close_prev = df['close'].shift(1)
    df['sma20'] = close_prev.rolling(20).mean()
    df['std20'] = close_prev.rolling(20).std()
    df['upper_bb'] = df['sma20'] + (2.0 * df['std20'])
    df['lower_bb'] = df['sma20'] - (2.0 * df['std20'])
    df['rsi14'] = calculate_rsi(close_prev, 14)

    capital = 100.0
    peak_equity = 100.0
    max_dd = 0.0
    trades = []
    
    in_pos = False
    side = None  # 'LONG' o 'SHORT'
    entry_price = 0.0
    spread_cost = spread_pips * 0.0001  # En EUR/USD 1 pip = 0.0001

    for i in range(50, len(df)):
        row = df.iloc[i]
        close = float(row['close'])
        low = float(row['low'])
        high = float(row['high'])
        sma = float(row['sma20'])
        upper = float(row['upper_bb'])
        lower = float(row['lower_bb'])
        rsi = float(row['rsi14'])

        if in_pos:
            exit_price = None
            exit_reason = None

            if side == 'LONG':
                initial_sl = entry_price * 0.985  # -1.5%
                if low <= initial_sl:
                    exit_price = initial_sl
                    exit_reason = 'SL'
                elif close >= sma:
                    exit_price = close
                    exit_reason = 'TP_SMA'
                
                if exit_price:
                    # Retorno neto descontando spread
                    net_return = (exit_price - entry_price - spread_cost) / entry_price
            
            elif side == 'SHORT':
                initial_sl = entry_price * 1.015  # +1.5%
                if high >= initial_sl:
                    exit_price = initial_sl
                    exit_reason = 'SL'
                elif close <= sma:
                    exit_price = close
                    exit_reason = 'TP_SMA'

                if exit_price:
                    # Retorno neto short descontando spread
                    net_return = (entry_price - exit_price - spread_cost) / entry_price

            if exit_price:
                trade_usd = min(capital, 100.0) * net_return
                capital += trade_usd
                if capital > peak_equity:
                    peak_equity = capital
                dd = (peak_equity - capital) / peak_equity * 100.0
                if dd > max_dd:
                    max_dd = dd

                trades.append({
                    'side': side,
                    'exit_reason': exit_reason,
                    'net_return': net_return,
                    'pnl_usd': trade_usd
                })
                in_pos = False
                side = None

        if not in_pos:
            # Entrada LONG: Perfora banda inferior y RSI sobrevendido (< 35)
            if close < lower and rsi < 35:
                in_pos = True
                side = 'LONG'
                entry_price = close
            # Entrada SHORT: Perfora banda superior y RSI sobrecomprado (> 65)
            elif close > upper and rsi > 65:
                in_pos = True
                side = 'SHORT'
                entry_price = close

    if not trades:
        print("[!] No se generaron operaciones con estos filtros.")
        return

    df_t = pd.DataFrame(trades)
    wins = df_t[df_t['pnl_usd'] > 0]
    losses = df_t[df_t['pnl_usd'] <= 0]
    wr = (len(wins) / len(df_t)) * 100.0
    gross_profit = wins['pnl_usd'].sum()
    gross_loss = abs(losses['pnl_usd'].sum())
    pf = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)
    pnl = df_t['pnl_usd'].sum()
    salidas = df_t['exit_reason'].value_counts().to_dict()

    print("\n" + "=" * 70)
    print(f" RESULTADOS REVERSIÓN A LA MEDIA: {ticker} (Spread: {spread_pips} pips)")
    print("=" * 70)
    print(f"Trades Totales (N) : {len(df_t)}")
    print(f"Win Rate (%)       : {wr:.2f}%")
    print(f"Profit Factor (PF) : {pf:.2f}")
    print(f"PnL Neto ($100 USD): ${pnl:.2f}")
    print(f"Max Drawdown (%)   : {max_dd:.2f}%")
    print(f"Desglose Salidas   : {salidas}")
    print("=" * 70)

if __name__ == '__main__':
    run_forex_reversion(ticker='EURUSD=X', interval='1h', period='700d', spread_pips=1.5)
