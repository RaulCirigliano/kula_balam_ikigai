import os
import pandas as pd
import numpy as np

DATA_DIR = "/home/raul/Escritorio/proyectos/kula_balam_ikigai/datos_historicos"

def preparar_datos(df):
    df = df.copy()
    
    # Manejo estricto de zona horaria Eastern Time (Wall Street)
    df['datetime'] = pd.to_datetime(df['datetime'])
    if df['datetime'].dt.tz is None:
        df['datetime'] = df['datetime'].dt.tz_localize('UTC').dt.tz_convert('America/New_York')
    else:
        df['datetime'] = df['datetime'].dt.tz_convert('America/New_York')
        
    df = df.sort_values('datetime').reset_index(drop=True)
    df['time_str'] = df['datetime'].dt.strftime('%H:%M')
    
    # Filtrar sesión regular de Wall Street (09:30 a 16:00 ET)
    df = df[(df['time_str'] >= '09:30') & (df['time_str'] <= '16:00')].copy().reset_index(drop=True)

    # Indicadores técnicos base (shift 1 para evitar sesgo de anticipación)
    df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean().shift(1)
    df['vol_sma20'] = df['volume'].rolling(window=20).mean().shift(1)

    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift(1)).abs()
    low_close = (df['low'] - df['close'].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(window=14).mean().shift(1)

    return df

def auditar_ticker(ticker_name):
    file_path = os.path.join(DATA_DIR, f"yf_{ticker_name}_15m.parquet")
    if not os.path.exists(file_path):
        print(f"Error: No se encontró {file_path}")
        return []

    raw_df = pd.read_parquet(file_path)
    df = preparar_datos(raw_df)

    balance = 100.0
    risk_usd = 1.00
    fee_rate = 0.0005

    in_pos = False
    pos_side = None
    entry_price = 0.0
    sl_price = 0.0
    tp_price = 0.0
    pos_size_usd = 0.0

    trades = []

    for i in range(45, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]
        v2 = df.iloc[i-2]
        v3 = df.iloc[i-3]

        # 1. Cierre obligatorio intradía a las 15:45 ET
        if in_pos and row['time_str'] >= '15:45':
            raw_pnl = (row['close'] - entry_price) / entry_price if pos_side == 'LONG' else (entry_price - row['close']) / entry_price
            net_pnl = (pos_size_usd * raw_pnl) - (pos_size_usd * 2 * fee_rate)
            trades.append({'ticker': ticker_name, 'type': 'EOD', 'side': pos_side, 'pnl': net_pnl})
            in_pos = False
            continue

        # 2. Monitoreo de salidas por SL / TP
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
                    trades.append({'ticker': ticker_name, 'type': exit_reason, 'side': pos_side, 'pnl': net_pnl})
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
                    trades.append({'ticker': ticker_name, 'type': exit_reason, 'side': pos_side, 'pnl': net_pnl})
                    in_pos = False
                    continue

        # 3. Gatillo Kula Balam: Fibo Zona Dorada + BOS 3 Velas
        if not in_pos:
            if row['time_str'] < '10:00':
                continue

            ema50 = prev['ema_50']
            atr_val = prev['atr']
            if pd.isna(ema50) or pd.isna(atr_val) or atr_val <= 0:
                continue

            # Ventana de swing retrospectiva (últimas 30 velas)
            lookback = df.iloc[i-31:i-1]
            swing_high = lookback['high'].max()
            swing_low = lookback['low'].min()
            swing_range = swing_high - swing_low

            if swing_range <= 0:
                continue

            # CASO LONG: Tendencia alcista (Close > EMA50) + Retroceso a Fibo 0.50-0.707
            if prev['close'] > ema50:
                # Niveles Fibo desde el Swing High
                fibo_50 = swing_high - (0.50 * swing_range)
                fibo_70 = swing_high - (0.707 * swing_range)

                # Retroceso en zona dorada testeado recientemente
                low_reciente = min(v3['low'], v2['low'], prev['low'])
                en_zona = (low_reciente >= fibo_70) and (low_reciente <= fibo_50)

                # BOS de 3 Velas: v3 cae, v2 pausa/vela interna, prev rompe el máximo de v2 y cierra verde
                bos_long = (prev['close'] > v2['high']) and (prev['close'] > prev['open'])

                if en_zona and bos_long:
                    entry_price = row['open']
                    sl_price = low_reciente - (0.5 * atr_val)
                    risk_pct = (entry_price - sl_price) / entry_price

                    if 0.003 <= risk_pct <= 0.035:
                        tp_price = entry_price + ((entry_price - sl_price) * 2.0)
                        pos_size_usd = min(balance, risk_usd / risk_pct)
                        in_pos = True
                        pos_side = 'LONG'

            # CASO SHORT: Tendencia bajista (Close < EMA50) + Retroceso a Fibo 0.50-0.707
            elif prev['close'] < ema50:
                fibo_50 = swing_low + (0.50 * swing_range)
                fibo_70 = swing_low + (0.707 * swing_range)

                high_reciente = max(v3['high'], v2['high'], prev['high'])
                en_zona = (high_reciente <= fibo_70) and (high_reciente >= fibo_50)

                # BOS de 3 Velas: v3 sube, v2 pausa, prev rompe el mínimo de v2 y cierra roja
                bos_short = (prev['close'] < v2['low']) and (prev['close'] < prev['open'])

                if en_zona and bos_short:
                    entry_price = row['open']
                    sl_price = high_reciente + (0.5 * atr_val)
                    risk_pct = (sl_price - entry_price) / entry_price

                    if 0.003 <= risk_pct <= 0.035:
                        tp_price = entry_price - ((sl_price - entry_price) * 2.0)
                        pos_size_usd = min(balance, risk_usd / risk_pct)
                        in_pos = True
                        pos_side = 'SHORT'

    return trades

def run():
    print("==========================================================")
    print("  AUDITORÍA: ZONA DORADA FIBO + BOS 3 VELAS (15M)")
    print("  Adaptación Kula Balam a Wall Street | Canasta 4 Activos")
    print("  Activos: NVDA, TSLA, AMD, META | Ratio 1:2.0")
    print("==========================================================")

    tickers = ['NVDA', 'TSLA', 'AMD', 'META']
    all_trades = []

    for t in tickers:
        print(f"  -> Auditando {t}...")
        trades = auditar_ticker(t)
        all_trades.extend(trades)

    if not all_trades:
        print("No se generaron operaciones con las condiciones actuales.")
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

    print("\n---------------- RESULTADOS FINALES AMPLIADOS ----------------")
    print(f"Total Operaciones:    {total_trades}")
    print(f"Operaciones Ganadas:  {len(wins)}")
    print(f"Operaciones Perdidas: {len(losses)}")
    print(f"Win Rate:             {win_rate:.2f}%")
    print(f"Ganancia Bruta:       +${gross_profit:.2f} USD")
    print(f"Pérdida Bruta:        -${gross_loss:.2f} USD")
    print(f"Profit Factor:        {profit_factor:.2f}")
    print(f"PnL Neto:             {net_pnl:+.2f} USD ({net_pnl:+.2f}%)")
    print("--------------------------------------------------------------\n")

    print("Detalle por activo:")
    for t in tickers:
        df_sub = df_t[df_t['ticker'] == t]
        pnl_sub = df_sub['pnl'].sum() if not df_sub.empty else 0.0
        trades_sub = len(df_sub)
        print(f"  * {t:5s}: {trades_sub:2d} trades | PnL: {pnl_sub:+.2f} USD")
    print()

if __name__ == '__main__':
    run()
