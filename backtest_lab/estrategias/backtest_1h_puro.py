import ccxt
import pandas as pd
import numpy as np

def fetch_data(symbol="BTC/USDT"):
    exchange = ccxt.binance({'enableRateLimit': True})
    print(f"Descargando datos históricos para {symbol} (1D y 1H)...")
    
    ohlcv_1h = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=1000)
    ohlcv_1d = exchange.fetch_ohlcv(symbol, timeframe='1d', limit=150)
    
    def to_df(data):
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        return df

    return to_df(ohlcv_1h), to_df(ohlcv_1d)

def run_1h_backtest():
    df_1h, df_1d = fetch_data()

    # 1. Macro 1D (Tendencia y Pendiente EMA 50 diaria cerrada previa)
    df_1d['ema_50'] = df_1d['close'].ewm(span=50, adjust=False).mean()
    df_1d['ema_slope'] = df_1d['ema_50'] - df_1d['ema_50'].shift(2)
    df_1d['macro_bias'] = np.where(
        (df_1d['close'] > df_1d['ema_50']) & (df_1d['ema_slope'] >= 0), 'LONG',
        np.where((df_1d['close'] < df_1d['ema_50']) & (df_1d['ema_slope'] <= 0), 'SHORT', 'NEUTRAL')
    )
    df_1d['date'] = df_1d['datetime'].dt.date
    df_1d['macro_bias_closed'] = df_1d['macro_bias'].shift(1)
    macro_map = dict(zip(df_1d['date'], df_1d['macro_bias_closed']))

    # 2. Indicadores en 1H
    high_low = df_1h['high'] - df_1h['low']
    high_close = (df_1h['high'] - df_1h['close'].shift(1)).abs()
    low_close = (df_1h['low'] - df_1h['close'].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df_1h['atr'] = tr.rolling(window=14).mean().shift(1)

    df_1h['vol_sma20'] = df_1h['volume'].rolling(window=20).mean().shift(1)

    # Pivotes Fractales de 5 velas confirmados
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

    df = df_1h.iloc[30:].reset_index(drop=True)

    fee = 0.00075  # 0.075% comisión spot Binance con BNB
    target_rr = 2.0
    trades = []
    in_position = False
    pos_side = None
    entry_price = 0.0
    sl_price = 0.0
    tp_price = 0.0

    print(f"Simulando {len(df)} velas de 1H con Quiebre Estructural y R:R 1:{target_rr}...")

    for i in range(4, len(df)):
        row = df.iloc[i]
        prev1 = df.iloc[i-1] # V3
        prev2 = df.iloc[i-2] # V2
        prev3 = df.iloc[i-3] # V1
        
        # Gestión de posición
        if in_position:
            if pos_side == 'LONG':
                if row['low'] <= sl_price:
                    pnl = ((sl_price - entry_price) / entry_price) - (2 * fee)
                    trades.append({'side': 'LONG', 'pnl': pnl, 'type': 'SL'})
                    in_position = False
                elif row['high'] >= tp_price:
                    pnl = ((tp_price - entry_price) / entry_price) - (2 * fee)
                    trades.append({'side': 'LONG', 'pnl': pnl, 'type': 'TP'})
                    in_position = False
            elif pos_side == 'SHORT':
                if row['high'] >= sl_price:
                    pnl = ((entry_price - sl_price) / entry_price) - (2 * fee)
                    trades.append({'side': 'SHORT', 'pnl': pnl, 'type': 'SL'})
                    in_position = False
                elif row['low'] <= tp_price:
                    pnl = ((entry_price - tp_price) / entry_price) - (2 * fee)
                    trades.append({'side': 'SHORT', 'pnl': pnl, 'type': 'TP'})
                    in_position = False
            continue

        # Reglas de Entrada
        bias = row['macro_bias']
        if bias not in ['LONG', 'SHORT']:
            continue

        s_high = row['last_fractal_high']
        s_low = row['last_fractal_low']
        s_range = max(0.0001, s_high - s_low)
        atr_val = row['atr']
        vol_mean = row['vol_sma20']
        
        volume_ok = prev1['volume'] > (vol_mean * 1.0)
        last_close = prev1['close']

        if bias == 'LONG':
            fibo = (s_high - last_close) / s_range
            in_zone = 0.45 <= fibo <= 0.75
            
            # Quiebre Estructural (BOS): V3 debe superar tanto a V2 como a V1
            trigger = (last_close > prev2['high']) and (last_close > prev3['high'])

            if in_zone and trigger and volume_ok:
                entry_price = row['open']
                base_low = min(prev1['low'], prev2['low'], prev3['low'])
                sl_price = base_low - (0.5 * atr_val)
                risk = entry_price - sl_price
                risk_pct = risk / entry_price
                
                if 0.008 <= risk_pct <= 0.030:
                    tp_price = entry_price + (risk * target_rr)
                    in_position = True
                    pos_side = 'LONG'

        elif bias == 'SHORT':
            fibo = (last_close - s_low) / s_range
            in_zone = 0.45 <= fibo <= 0.75
            
            trigger = (last_close < prev2['low']) and (last_close < prev3['low'])

            if in_zone and trigger and volume_ok:
                entry_price = row['open']
                base_high = max(prev1['high'], prev2['high'], prev3['high'])
                sl_price = base_high + (0.5 * atr_val)
                risk = sl_price - entry_price
                risk_pct = risk / entry_price
                
                if 0.008 <= risk_pct <= 0.030:
                    tp_price = entry_price - (risk * target_rr)
                    in_position = True
                    pos_side = 'SHORT'

    if not trades:
        print("No se generaron operaciones en el período.")
        return

    df_trades = pd.DataFrame(trades)
    wins = df_trades[df_trades['pnl'] > 0]
    losses = df_trades[df_trades['pnl'] <= 0]
    
    total_gain = wins['pnl'].sum() if not wins.empty else 0.0
    total_loss = abs(losses['pnl'].sum()) if not losses.empty else 0.0
    
    profit_factor = round(total_gain / total_loss, 2) if total_loss > 0 else (999.0 if total_gain > 0 else 0.0)
    win_rate = round((len(wins) / len(df_trades)) * 100, 2)
    net_cum_return = round(df_trades['pnl'].sum() * 100, 2)

    print("\n" + "=" * 55)
    print(f"📊 RESULTADOS: 1D + 1H (QUIEBRE ESTRUCTURAL BOS)")
    print("=" * 55)
    print(f"Total Operaciones:   {len(df_trades)}")
    print(f"Win Rate:            {win_rate}% ({len(wins)}W / {len(losses)}L)")
    print(f"Ganancia Bruta:      +{total_gain*100:.2f}%")
    print(f"Pérdida Bruta:       -{total_loss*100:.2f}%")
    print(f"Retorno Neto:        {net_cum_return:+.2f}%")
    print(f"PROFIT FACTOR (PF):  {profit_factor}")
    print("=" * 55)
    
    print("\nDetalle de Operaciones:")
    for idx, t in df_trades.iterrows():
        print(f"Trade {idx+1:02d}: {t['side']:<5} | Salida: {t['type']:<3} | PnL Neto: {t['pnl']*100:+.2f}%")
    print()

if __name__ == '__main__':
    run_1h_backtest()
