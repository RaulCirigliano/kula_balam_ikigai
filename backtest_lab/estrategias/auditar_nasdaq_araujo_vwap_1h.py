import ccxt
import pandas as pd
import numpy as np

def to_df(data):
    df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    return df

def calcular_indicadores(df):
    df['date'] = df['datetime'].dt.date
    df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3.0
    df['pv'] = df['typical_price'] * df['volume']

    # VWAP anclado por día (UTC)
    df['cum_pv'] = df.groupby('date')['pv'].cumsum()
    df['cum_vol'] = df.groupby('date')['volume'].cumsum()
    df['vwap'] = df['cum_pv'] / np.maximum(1e-9, df['cum_vol'])

    # Desviación estándar ponderada por volumen
    df['vol_diff_sq'] = df['volume'] * ((df['typical_price'] - df['vwap']) ** 2)
    df['cum_vol_diff_sq'] = df.groupby('date')['vol_diff_sq'].cumsum()
    df['vwap_std'] = np.sqrt(df['cum_vol_diff_sq'] / np.maximum(1e-9, df['cum_vol']))

    # Bandas +/- 2 Sigma
    df['upper_band_2'] = df['vwap'] + (2.0 * df['vwap_std'])
    df['lower_band_2'] = df['vwap'] - (2.0 * df['vwap_std'])

    # Shift 1 para evitar repintado en la vela en curso
    df['vwap_prev'] = df['vwap'].shift(1)
    df['upper_2_prev'] = df['upper_band_2'].shift(1)
    df['lower_2_prev'] = df['lower_band_2'].shift(1)

    # ATR 14 y Media de volumen
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift(1)).abs()
    low_close = (df['low'] - df['close'].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(window=14).mean().shift(1)
    df['vol_sma20'] = df['volume'].rolling(window=20).mean().shift(1)

    return df

def auditar_simbolo(symbol, exchange):
    print(f"  -> Descargando 1000 velas 1H para {symbol}...")
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=1000)
    df = to_df(ohlcv)
    df = calcular_indicadores(df)

    balance = 100.0
    risk_usd = 1.00
    fee_rate = 0.00075

    in_pos = False
    pos_side = None
    entry_price = 0.0
    sl_price = 0.0
    tp_price = 0.0
    pos_size_usd = 0.0

    trades = []

    print(f"  -> Auditando lógica en {len(df)} velas...")
    for i in range(30, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]

        # 1. Monitoreo de posición activa
        if in_pos:
            hit_exit = False
            exit_price = 0.0
            exit_reason = ""

            if pos_side == 'LONG':
                if row['low'] <= sl_price:
                    exit_price = sl_price
                    exit_reason = 'SL'
                    hit_exit = True
                elif row['high'] >= tp_price:
                    exit_price = tp_price
                    exit_reason = 'TP'
                    hit_exit = True

                if hit_exit:
                    raw_pnl = (exit_price - entry_price) / entry_price
                    net_pnl = (pos_size_usd * raw_pnl) - (pos_size_usd * 2 * fee_rate)
                    balance += net_pnl
                    trades.append({'symbol': symbol, 'side': pos_side, 'type': exit_reason, 'pnl': net_pnl})
                    in_pos = False
                    continue

            elif pos_side == 'SHORT':
                if row['high'] >= sl_price:
                    exit_price = sl_price
                    exit_reason = 'SL'
                    hit_exit = True
                elif row['low'] <= tp_price:
                    exit_price = tp_price
                    exit_reason = 'TP'
                    hit_exit = True

                if hit_exit:
                    raw_pnl = (entry_price - exit_price) / entry_price
                    net_pnl = (pos_size_usd * raw_pnl) - (pos_size_usd * 2 * fee_rate)
                    balance += net_pnl
                    trades.append({'symbol': symbol, 'side': pos_side, 'type': exit_reason, 'pnl': net_pnl})
                    in_pos = False
                    continue

        # 2. Gatillo de entrada si no hay posición
        if not in_pos:
            atr_val = prev['atr']
            vol_mean = prev['vol_sma20']
            vwap_val = prev['vwap_prev']
            lower_2 = prev['lower_2_prev']
            upper_2 = prev['upper_2_prev']

            if pd.isna(atr_val) or atr_val <= 0 or pd.isna(vol_mean) or vol_mean <= 0 or pd.isna(vwap_val):
                continue

            vol_ok = prev['volume'] >= 1.1 * vol_mean

            # Condición LONG: Mecha o vela perforó la banda -2 y cerró arriba rebotando
            if (prev['low'] <= lower_2) and (prev['close'] > lower_2) and (prev['close'] < vwap_val) and vol_ok:
                entry_price = row['open']
                sl_price = prev['low'] - (0.75 * atr_val)
                risk_pct = (entry_price - sl_price) / entry_price

                if 0.008 <= risk_pct <= 0.045:
                    tp_price = vwap_val # Salida al VWAP institucional
                    if tp_price > entry_price and ((tp_price - entry_price) / (entry_price - sl_price)) >= 1.2:
                        pos_size_usd = min(balance, risk_usd / risk_pct)
                        in_pos = True
                        pos_side = 'LONG'

            # Condición SHORT: Mecha o vela perforó la banda +2 y cerró abajo rechazando
            elif (prev['high'] >= upper_2) and (prev['close'] < upper_2) and (prev['close'] > vwap_val) and vol_ok:
                entry_price = row['open']
                sl_price = prev['high'] + (0.75 * atr_val)
                risk_pct = (sl_price - entry_price) / entry_price

                if 0.008 <= risk_pct <= 0.045:
                    tp_price = vwap_val # Salida al VWAP institucional
                    if tp_price < entry_price and ((entry_price - tp_price) / (sl_price - entry_price)) >= 1.2:
                        pos_size_usd = min(balance, risk_usd / risk_pct)
                        in_pos = True
                        pos_side = 'SHORT'

    return trades, balance

def run():
    exchange = ccxt.binance({
        'enableRateLimit': True,
        'timeout': 10000
    })
    symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
    all_trades = []

    print("==========================================================")
    print("  AUDITORÍA: NASDAQ ARAUJO - VWAP WALL STREET (1H)")
    print("  Banda +/-2 Sigma, Salida en VWAP | 1000 velas 1H")
    print("==========================================================")

    for sym in symbols:
        trades, _ = auditar_simbolo(sym, exchange)
        all_trades.extend(trades)

    if not all_trades:
        print("No se generaron trades con los filtros aplicados.")
        return

    df_t = pd.DataFrame(all_trades)
    total_trades = len(df_t)
    wins = df_t[df_t['pnl'] > 0]
    losses = df_t[df_t['pnl'] <= 0]

    win_rate = (len(wins) / total_trades) * 100
    gross_profit = wins['pnl'].sum() if not wins.empty else 0.0
    gross_loss = abs(losses['pnl'].sum()) if not losses.empty else 0.0
    net_pnl = df_t['pnl'].sum()
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0.0

    print("\n---------------- RESULTADOS FINALES ----------------")
    print(f"Total Operaciones:    {total_trades}")
    print(f"Operaciones Ganadas:  {len(wins)}")
    print(f"Operaciones Perdidas: {len(losses)}")
    print(f"Win Rate:             {win_rate:.2f}%")
    print(f"Ganancia Bruta:       +${gross_profit:.2f} USD")
    print(f"Pérdida Bruta:        -${gross_loss:.2f} USD")
    print(f"Profit Factor:        {profit_factor:.2f}")
    print(f"PnL Neto:             {net_pnl:+.2f} USD ({net_pnl:+.2f}%)")
    print("----------------------------------------------------\n")

if __name__ == '__main__':
    run()
