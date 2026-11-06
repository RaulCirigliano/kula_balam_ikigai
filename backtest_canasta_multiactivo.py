import ccxt
import pandas as pd
import numpy as np

def fetch_asset_data(exchange, symbol):
    print(f"Descargando datos históricos para {symbol} (1D y 1H)...")
    ohlcv_1h = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=1000)
    ohlcv_1d = exchange.fetch_ohlcv(symbol, timeframe='1d', limit=150)
    
    def to_df(data):
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        return df

    return to_df(ohlcv_1h), to_df(ohlcv_1d)

def prepare_indicators(df_1h, df_1d, atr_mult=0.5):
    # 1. Macro 1D (Sesgo tendencial)
    df_1d['ema_50'] = df_1d['close'].ewm(span=50, adjust=False).mean()
    df_1d['ema_slope'] = df_1d['ema_50'] - df_1d['ema_50'].shift(2)
    df_1d['macro_bias'] = np.where(
        (df_1d['close'] > df_1d['ema_50']) & (df_1d['ema_slope'] >= 0), 'LONG',
        np.where((df_1d['close'] < df_1d['ema_50']) & (df_1d['ema_slope'] <= 0), 'SHORT', 'NEUTRAL')
    )
    df_1d['date'] = df_1d['datetime'].dt.date
    df_1d['macro_bias_closed'] = df_1d['macro_bias'].shift(1)
    macro_map = dict(zip(df_1d['date'], df_1d['macro_bias_closed']))

    # 2. Indicadores 1H
    high_low = df_1h['high'] - df_1h['low']
    high_close = (df_1h['high'] - df_1h['close'].shift(1)).abs()
    low_close = (df_1h['low'] - df_1h['close'].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df_1h['atr'] = tr.rolling(window=14).mean().shift(1)
    df_1h['vol_sma20'] = df_1h['volume'].rolling(window=20).mean().shift(1)

    # 3. KER calibrado (ventana 20 períodos)
    change = (df_1h['close'] - df_1h['close'].shift(20)).abs()
    volatility = (df_1h['close'] - df_1h['close'].shift(1)).abs().rolling(window=20).sum()
    df_1h['ker'] = (change / volatility.replace(0, np.nan)).shift(1)

    # Fractales Williams 5 velas
    h = df_1h['high']
    l = df_1h['low']
    is_f_high = (h.shift(2) > h.shift(3)) & (h.shift(2) > h.shift(4)) & (h.shift(2) > h.shift(1)) & (h.shift(2) > h)
    is_f_low = (l.shift(2) < l.shift(3)) & (l.shift(2) < l.shift(4)) & (l.shift(2) < l.shift(1)) & (l.shift(2) < l)

    df_1h['fractal_high'] = np.where(is_f_high, h.shift(2), np.nan)
    df_1h['fractal_low'] = np.where(is_f_low, l.shift(2), np.nan)
    df_1h['last_fractal_high'] = df_1h['fractal_high'].ffill().bfill().shift(1)
    df_1h['last_fractal_low'] = df_1h['fractal_low'].ffill().bfill().shift(1)

    df_1h['date'] = df_1h['datetime'].dt.date
    df_1h['macro_bias'] = df_1h['date'].map(macro_map)
    df_1h['atr_mult'] = atr_mult

    return df_1h.iloc[35:].reset_index(drop=True)

def run_portfolio_simulation():
    exchange = ccxt.binance({'enableRateLimit': True})
    symbols_config = {
        'BTC/USDT': {'atr_mult': 0.50},
        'ETH/USDT': {'atr_mult': 0.50},
        'SOL/USDT': {'atr_mult': 0.85}
    }
    
    asset_dfs = {}
    for sym, conf in symbols_config.items():
        df_1h, df_1d = fetch_asset_data(exchange, sym)
        asset_dfs[sym] = prepare_indicators(df_1h, df_1d, conf['atr_mult'])

    min_len = min(len(df) for df in asset_dfs.values())
    for sym in asset_dfs:
        asset_dfs[sym] = asset_dfs[sym].iloc[-min_len:].reset_index(drop=True)

    fee_rate = 0.00075
    target_rr = 2.0
    account_balance = 100.0
    risk_per_trade_usd = 1.00

    active_positions = {}
    completed_trades = []

    print(f"\nSimulando {min_len} velas con KER Calibrado (>0.20) y No-Clímax en Retroceso...")

    for i in range(4, min_len):
        # 1. Monitoreo de salidas
        closed_syms = []
        for sym, pos in active_positions.items():
            row = asset_dfs[sym].iloc[i]
            entry_price = pos['entry_price']
            sl_price = pos['sl_price']
            tp_price = pos['tp_price']
            pos_size = pos['pos_size_usd']

            if pos['side'] == 'LONG':
                if row['low'] <= sl_price:
                    raw_pnl_pct = (sl_price - entry_price) / entry_price
                    net_pnl_usd = (pos_size * raw_pnl_pct) - (pos_size * 2 * fee_rate)
                    account_balance += net_pnl_usd
                    completed_trades.append({
                        'symbol': sym, 'side': 'LONG', 'entry_time': pos['entry_time'],
                        'exit_time': row['datetime'], 'pnl_usd': net_pnl_usd, 'type': 'SL',
                        'balance': account_balance
                    })
                    closed_syms.append(sym)
                elif row['high'] >= tp_price:
                    raw_pnl_pct = (tp_price - entry_price) / entry_price
                    net_pnl_usd = (pos_size * raw_pnl_pct) - (pos_size * 2 * fee_rate)
                    account_balance += net_pnl_usd
                    completed_trades.append({
                        'symbol': sym, 'side': 'LONG', 'entry_time': pos['entry_time'],
                        'exit_time': row['datetime'], 'pnl_usd': net_pnl_usd, 'type': 'TP',
                        'balance': account_balance
                    })
                    closed_syms.append(sym)

            elif pos['side'] == 'SHORT':
                if row['high'] >= sl_price:
                    raw_pnl_pct = (entry_price - sl_price) / entry_price
                    net_pnl_usd = (pos_size * raw_pnl_pct) - (pos_size * 2 * fee_rate)
                    account_balance += net_pnl_usd
                    completed_trades.append({
                        'symbol': sym, 'side': 'SHORT', 'entry_time': pos['entry_time'],
                        'exit_time': row['datetime'], 'pnl_usd': net_pnl_usd, 'type': 'SL',
                        'balance': account_balance
                    })
                    closed_syms.append(sym)
                elif row['low'] <= tp_price:
                    raw_pnl_pct = (entry_price - tp_price) / entry_price
                    net_pnl_usd = (pos_size * raw_pnl_pct) - (pos_size * 2 * fee_rate)
                    account_balance += net_pnl_usd
                    completed_trades.append({
                        'symbol': sym, 'side': 'SHORT', 'entry_time': pos['entry_time'],
                        'exit_time': row['datetime'], 'pnl_usd': net_pnl_usd, 'type': 'TP',
                        'balance': account_balance
                    })
                    closed_syms.append(sym)

        for sym in closed_syms:
            del active_positions[sym]

        # 2. Evaluación de nuevas entradas
        pending_signals = []
        for sym, df in asset_dfs.items():
            if sym in active_positions:
                continue

            row = df.iloc[i]
            prev1 = df.iloc[i-1] # V3
            prev2 = df.iloc[i-2] # V2
            prev3 = df.iloc[i-3] # V1

            bias = row['macro_bias']
            if bias not in ['LONG', 'SHORT']:
                continue

            # Filtro KER Calibrado: Bloquea solo mercados totalmente estancados (<0.20)
            ker_val = row['ker']
            if pd.isna(ker_val) or ker_val < 0.20:
                continue

            s_high = row['last_fractal_high']
            s_low = row['last_fractal_low']
            s_range = max(0.0001, s_high - s_low)
            atr_val = row['atr']
            vol_mean = row['vol_sma20']
            atr_mult = row['atr_mult']

            rvol_trigger = prev1['volume'] / max(1.0, vol_mean)
            trigger_vol_ok = rvol_trigger > 1.0

            # Filtro No-Clímax en retroceso: ni V2 ni V3 (en formación de retroceso) deben tener volumen clímax adverso (>1.8x)
            no_climax_against = (prev2['volume'] < 1.8 * vol_mean) and (prev3['volume'] < 1.8 * vol_mean)

            last_close = prev1['close']

            if bias == 'LONG':
                fibo = (s_high - last_close) / s_range
                in_zone = 0.45 <= fibo <= 0.75
                trigger = (last_close > prev2['high']) and (last_close > prev3['high'])

                if in_zone and trigger and trigger_vol_ok and no_climax_against:
                    entry = row['open']
                    base_low = min(prev1['low'], prev2['low'], prev3['low'])
                    sl = base_low - (atr_mult * atr_val)
                    risk_pct = (entry - sl) / entry
                    if 0.008 <= risk_pct <= 0.045:
                        pending_signals.append({
                            'symbol': sym, 'side': 'LONG', 'entry': entry,
                            'sl': sl, 'tp': entry + ((entry - sl) * target_rr),
                            'risk_pct': risk_pct, 'rvol': rvol_trigger, 'datetime': row['datetime']
                        })

            elif bias == 'SHORT':
                fibo = (last_close - s_low) / s_range
                in_zone = 0.45 <= fibo <= 0.75
                trigger = (last_close < prev2['low']) and (last_close < prev3['low'])

                if in_zone and trigger and trigger_vol_ok and no_climax_against:
                    entry = row['open']
                    base_high = max(prev1['high'], prev2['high'], prev3['high'])
                    sl = base_high + (atr_mult * atr_val)
                    risk_pct = (sl - entry) / entry
                    if 0.008 <= risk_pct <= 0.045:
                        pending_signals.append({
                            'symbol': sym, 'side': 'SHORT', 'entry': entry,
                            'sl': sl, 'tp': entry - ((sl - entry) * target_rr),
                            'risk_pct': risk_pct, 'rvol': rvol_trigger, 'datetime': row['datetime']
                        })

        # 3. Filtro Anti-Correlación: Solo 1 trade abierto por dirección
        for sig in pending_signals:
            direction_occupied = any(p['side'] == sig['side'] for p in active_positions.values())
            if not direction_occupied:
                pos_size_usd = min(100.0, risk_per_trade_usd / sig['risk_pct'])
                active_positions[sig['symbol']] = {
                    'side': sig['side'], 'entry_price': sig['entry'],
                    'sl_price': sig['sl'], 'tp_price': sig['tp'],
                    'pos_size_usd': pos_size_usd, 'entry_time': sig['datetime']
                }

    if not completed_trades:
        print("No se completaron operaciones en el período.")
        return

    df_res = pd.DataFrame(completed_trades)
    wins = df_res[df_res['pnl_usd'] > 0]
    losses = df_res[df_res['pnl_usd'] <= 0]
    
    total_gain = wins['pnl_usd'].sum() if not wins.empty else 0.0
    total_loss = abs(losses['pnl_usd'].sum()) if not losses.empty else 0.0
    
    pf_global = round(total_gain / total_loss, 2) if total_loss > 0 else (999.0 if total_gain > 0 else 0.0)
    wr_global = round((len(wins) / len(df_res)) * 100, 2)
    net_return_usd = round(df_res['pnl_usd'].sum(), 2)
    final_balance = round(account_balance, 2)

    print("=" * 65)
    print("🌐 RESULTADOS: CANASTA CALIBRADA (KER > 0.20 + NO-CLÍMAX)")
    print("=" * 65)
    print(f"Total Operaciones:       {len(df_res)}")
    print(f"Win Rate Global:         {wr_global}% ({len(wins)}W / {len(losses)}L)")
    print(f"Ganancia Bruta:          +${total_gain:.2f} USD")
    print(f"Pérdida Bruta:           -${total_loss:.2f} USD")
    print(f"Retorno Neto ($100 cap): {net_return_usd:+.2f} USD ({net_return_usd:+.2f}%)")
    print(f"Balance Final de Cuenta: ${final_balance:.2f} USD")
    print(f"PROFIT FACTOR GLOBAL:    {pf_global}")
    print("=" * 65)
    
    print("\nDetalle de Operaciones Filtradas:")
    for idx, t in df_res.iterrows():
        t_str = str(t['entry_time'])[:16]
        print(f"[{t_str}] {t['symbol']:<8} | {t['side']:<5} | Salida: {t['type']:<3} | PnL: {t['pnl_usd']:+.2f} USD | Balance: ${t['balance']:.2f}")
    print()

if __name__ == '__main__':
    run_portfolio_simulation()
