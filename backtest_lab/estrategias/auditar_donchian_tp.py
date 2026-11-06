import ccxt
import pandas as pd
import numpy as np
import time

def fetch_candles(exchange, symbol, limit=4321):
    print(f"[*] Descargando {limit} velas de 1H para {symbol}...")
    all_candles = []
    target_ms = limit * 3600 * 1000
    now_ms = exchange.milliseconds()
    since = now_ms - target_ms
    
    while len(all_candles) < limit:
        candles = exchange.fetch_ohlcv(symbol, timeframe='1h', since=since, limit=1000)
        if not candles:
            break
        all_candles.extend(candles)
        since = candles[-1][0] + 3600 * 1000
        time.sleep(0.2)
        if len(candles) < 1000:
            break

    df = pd.DataFrame(all_candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').copy()
    df = df.iloc[-limit:].reset_index(drop=True)
    return df

def simulate_donchian(df, mode='trailing_be'):
    # mode: 'trailing_be' o 'pure_mid'
    df = df.copy()
    df['donchian_high'] = df['high'].shift(1).rolling(20).max()
    df['donchian_low'] = df['low'].shift(1).rolling(20).min()
    df['donchian_mid'] = (df['donchian_high'] + df['donchian_low']) / 2.0
    df['ema200'] = df['close'].shift(1).ewm(span=200, adjust=False).mean()

    trades = []
    capital = 100.0
    peak_equity = 100.0
    max_dd = 0.0

    in_pos = False
    entry_price = 0.0
    pos_peak = 0.0
    be_armed = False
    trailing_stop = 0.0

    fee_rate = 0.0015  # 0.15% round-trip

    for i in range(201, len(df)):
        row = df.iloc[i]
        close = row['close']
        high = row['high']
        low = row['low']
        mid = row['donchian_mid']
        upper = row['donchian_high']
        ema = row['ema200']

        if in_pos:
            if high > pos_peak:
                pos_peak = high

            exit_price = None
            exit_reason = None

            if mode == 'trailing_be':
                gross_gain_pct = (pos_peak - entry_price) / entry_price
                if not be_armed and gross_gain_pct >= 0.010:
                    be_armed = True
                    trailing_stop = entry_price * 1.008

                if be_armed:
                    dyn_trail = pos_peak * (1 - 0.015)
                    if dyn_trail > trailing_stop:
                        trailing_stop = dyn_trail

                initial_sl = entry_price * 0.99
                if not be_armed and low <= initial_sl:
                    exit_price = initial_sl
                    exit_reason = 'SL'
                elif be_armed and low <= trailing_stop:
                    exit_price = trailing_stop
                    exit_reason = 'TRAILING' if trailing_stop > entry_price * 1.008 else 'BE'
                elif close < mid:
                    exit_price = close
                    exit_reason = 'MID_EXIT'

            elif mode == 'pure_mid':
                # Salida pura de Donchian: SL inicial de contención de desastre o cierre bajo banda media
                initial_sl = entry_price * 0.985  # SL amplio de seguridad (1.5%)
                if low <= initial_sl:
                    exit_price = initial_sl
                    exit_reason = 'SL'
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
            if close > upper and close > ema:
                in_pos = True
                entry_price = close
                pos_peak = close
                be_armed = False
                trailing_stop = entry_price * 0.99

    if not trades:
        return {'N': 0, 'WR': 0.0, 'PF': 0.0, 'PnL': 0.0, 'MaxDD': 0.0, 'Salidas': {}}

    df_t = pd.DataFrame(trades)
    wins = df_t[df_t['pnl_usd'] > 0]
    losses = df_t[df_t['pnl_usd'] <= 0]

    wr = (len(wins) / len(df_t)) * 100.0
    gross_profit = wins['pnl_usd'].sum()
    gross_loss = abs(losses['pnl_usd'].sum())
    pf = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)
    pnl_neto = df_t['pnl_usd'].sum()
    salidas = df_t['exit_reason'].value_counts().to_dict()

    return {
        'N': len(df_t),
        'WR': round(wr, 2),
        'PF': round(pf, 2),
        'PnL': round(pnl_neto, 2),
        'MaxDD': round(max_dd, 2),
        'Salidas': salidas
    }

def main():
    exchange = ccxt.binance()
    symbols = ['BTC/USDT', 'ETH/USDT']
    
    print("=" * 76)
    print(" AUDITORÍA: TRAILING/BE (1.5%) VS SALIDA ESTRUCTURAL PURA (MID_EXIT)")
    print("=" * 76)

    for sym in symbols:
        df = fetch_candles(exchange, sym, limit=4321)
        res_trail = simulate_donchian(df, mode='trailing_be')
        res_pure = simulate_donchian(df, mode='pure_mid')

        print(f"\nResultados para {sym} (4.321 velas ~180 días con EMA200):")
        print("-" * 76)
        print(f"{'Métrica':<22} | {'Trailing/BE (1.5%)':<23} | {'Salida Pura (MID_EXIT)':<23}")
        print("-" * 76)
        print(f"{'Trades Totales (N)':<22} | {res_trail['N']:<23} | {res_pure['N']:<23}")
        print(f"{'Win Rate (%)':<22} | {res_trail['WR']:<23} | {res_pure['WR']:<23}")
        print(f"{'Profit Factor (PF)':<22} | {res_trail['PF']:<23} | {res_pure['PF']:<23}")
        print(f"{'PnL Neto (USD)':<22} | ${res_trail['PnL']:<22} | ${res_pure['PnL']:<22}")
        print(f"{'Max Drawdown (%)':<22} | {res_trail['MaxDD']}%{'' :<22} | {res_pure['MaxDD']}%{'' :<22}")
        print(f"{'Desglose Salidas':<22} | {str(res_trail['Salidas']):<23} | {str(res_pure['Salidas']):<23}")
        print("-" * 76)

if __name__ == '__main__':
    main()
