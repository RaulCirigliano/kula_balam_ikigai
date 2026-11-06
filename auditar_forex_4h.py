import yfinance as yf
import pandas as pd
import numpy as np

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def test_reversion_4h(ticker='EURUSD=X', spread_pips=1.5):
    print(f"\n[*] Auditando Reversión a la Media en 4H: {ticker}...")
    df = yf.download(ticker, period='700d', interval='1h', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0].lower() for col in df.columns]
    else:
        df.columns = [col.lower() for col in df.columns]
    
    # Resample a 4H para análisis macro
    df_4h = df.resample('4h').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'
    }).dropna().copy()

    close_prev = df_4h['close'].shift(1)
    df_4h['sma20'] = close_prev.rolling(20).mean()
    df_4h['std20'] = close_prev.rolling(20).std()
    df_4h['upper_bb'] = df_4h['sma20'] + (2.2 * df_4h['std20'])
    df_4h['lower_bb'] = df_4h['sma20'] - (2.2 * df_4h['std20'])
    df_4h['rsi14'] = calculate_rsi(close_prev, 14)

    capital = 100.0
    trades = []
    in_pos = False
    side = None
    entry_p = 0.0
    spread_cost = spread_pips * 0.0001

    for i in range(30, len(df_4h)):
        row = df_4h.iloc[i]
        c, l, h = float(row['close']), float(row['low']), float(row['high'])
        sma, up, low_b, rsi = float(row['sma20']), float(row['upper_bb']), float(row['lower_bb']), float(row['rsi14'])

        if in_pos:
            exit_p = None
            if side == 'LONG':
                sl = entry_p * 0.985
                if l <= sl: exit_p = sl
                elif c >= sma: exit_p = c
                if exit_p: net_ret = (exit_p - entry_p - spread_cost) / entry_p
            elif side == 'SHORT':
                sl = entry_p * 1.015
                if h >= sl: exit_p = sl
                elif c <= sma: exit_p = c
                if exit_p: net_ret = (entry_p - exit_p - spread_cost) / entry_p

            if exit_p:
                pnl = min(capital, 100.0) * net_ret
                capital += pnl
                trades.append(pnl)
                in_pos = False
                side = None

        if not in_pos:
            if c < low_b and rsi < 30:
                in_pos, side, entry_p = True, 'LONG', c
            elif c > up and rsi > 70:
                in_pos, side, entry_p = True, 'SHORT', c

    report(trades, f"{ticker} (Reversión 4H)")

def test_trend_donchian_4h(ticker='USDJPY=X', spread_pips=2.0):
    print(f"\n[*] Auditando Donchian 20 + MID_EXIT en 4H: {ticker}...")
    df = yf.download(ticker, period='700d', interval='1h', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0].lower() for col in df.columns]
    else:
        df.columns = [col.lower() for col in df.columns]

    df_4h = df.resample('4h').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'
    }).dropna().copy()

    df_4h['donchian_high'] = df_4h['high'].shift(1).rolling(20).max()
    df_4h['donchian_low'] = df_4h['low'].shift(1).rolling(20).min()
    df_4h['donchian_mid'] = (df_4h['donchian_high'] + df_4h['donchian_low']) / 2.0
    df_4h['ema200'] = df_4h['close'].shift(1).ewm(span=200, adjust=False).mean()

    capital = 100.0
    trades = []
    in_pos = False
    entry_p = 0.0
    spread_cost = spread_pips * 0.01  # Para JPY 1 pip = 0.01

    for i in range(201, len(df_4h)):
        row = df_4h.iloc[i]
        c, l = float(row['close']), float(row['low'])
        up, mid, ema = float(row['donchian_high']), float(row['donchian_mid']), float(row['ema200'])

        if in_pos:
            exit_p = None
            sl = entry_p * 0.985
            if l <= sl: exit_p = sl
            elif c < mid: exit_p = c

            if exit_p:
                net_ret = (exit_p - entry_p - spread_cost) / entry_p
                pnl = min(capital, 100.0) * net_ret
                capital += pnl
                trades.append(pnl)
                in_pos = False

        if not in_pos:
            if c > up and c > ema:
                in_pos, entry_p = True, c

    report(trades, f"{ticker} (Donchian 4H Tendencial)")

def report(trades, name):
    if not trades:
        print(f"[{name}] Sin operaciones.")
        return
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    wr = (len(wins) / len(trades)) * 100.0
    gp = sum(wins)
    gl = abs(sum(losses))
    pf = (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0)
    pnl = sum(trades)
    print("=" * 65)
    print(f" {name}")
    print("=" * 65)
    print(f"Trades: {len(trades)} | WinRate: {wr:.2f}% | PF: {pf:.2f} | PnL: ${pnl:.2f} USD")
    print("=" * 65)

if __name__ == '__main__':
    test_reversion_4h('EURUSD=X', 1.5)
    test_trend_donchian_4h('JPY=X', 2.0)
