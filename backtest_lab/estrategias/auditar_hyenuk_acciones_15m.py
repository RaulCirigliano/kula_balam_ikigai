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
    
    # Filtrar horario oficial de sesión regular (09:30 a 16:00 ET)
    df = df[(df['time_str'] >= '09:30') & (df['time_str'] <= '16:00')].copy().reset_index(drop=True)

    # Indicadores técnicos en velas cerradas (shift 1 para evitar sesgo de anticipación)
    df['ema_20'] = df['close'].ewm(span=20, adjust=False).mean().shift(1)
    df['vol_sma20'] = df['volume'].rolling(window=20).mean().shift(1)

    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift(1)).abs()
    low_close = (df['low'] - df['close'].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(window=14).mean().shift(1)

    df['body'] = (df['close'] - df['open']).abs()
    df['prev_max_body_8'] = df['body'].rolling(window=8).max().shift(1)

    return df

def auditar_ticker(ticker_name):
    file_path = os.path.join(DATA_DIR, f"yf_{ticker_name}_15m.parquet")
    if not os.path.exists(file_path):
        print(f"Error: No se encontró {file_path}")
        return []

    print(f"  -> Procesando {ticker_name} (15M)...")
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

    for i in range(25, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]

        # 1. Cierre forzado intradía a las 15:45 ET
        if in_pos and row['time_str'] >= '15:45':
            raw_pnl = (row['close'] - entry_price) / entry_price if pos_side == 'LONG' else (entry_price - row['close']) / entry_price
            net_pnl = (pos_size_usd * raw_pnl) - (pos_size_usd * 2 * fee_rate)
            trades.append({'ticker': ticker_name, 'type': 'EOD', 'side': pos_side, 'pnl': net_pnl})
            in_pos = False
            continue

        # 2. Monitoreo de salidas normales (SL / TP)
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

        # 3. Gatillo de entrada si no hay posición
        if not in_pos:
            # Descartar primeros 15 minutos (09:30) por ruido de campana
            if row['time_str'] <= '09:45':
                continue

            atr_val = prev['atr']
            vol_mean = prev['vol_sma20']
            body_val = prev['body']
            prev_max = prev['prev_max_body_8']

            if pd.isna(atr_val) or atr_val <= 0 or pd.isna(vol_mean) or vol_mean <= 0:
                continue

            # Filtro institucional de Vela Elefante
            is_elephant = (body_val >= 1.8 * atr_val) and (body_val >= prev_max) and (prev['volume'] >= 1.3 * vol_mean)

            if is_elephant:
                # Caso LONG: Vela elefante alcista sobre EMA 20
                if prev['close'] > prev['open'] and prev['close'] > row['ema_20']:
                    entry_price = row['open']
                    sl_price = prev['open'] + (body_val * 0.50) # Stop 50%
                    risk_pct = (entry_price - sl_price) / entry_price

                    if 0.003 <= risk_pct <= 0.035:
                        tp_price = entry_price + ((entry_price - sl_price) * 2.0) # TP 1:2.0
                        pos_size_usd = min(balance, risk_usd / risk_pct)
                        in_pos = True
                        pos_side = 'LONG'

                # Caso SHORT: Vela elefante bajista bajo EMA 20
                elif prev['close'] < prev['open'] and prev['close'] < row['ema_20']:
                    entry_price = row['open']
                    sl_price = prev['open'] - (body_val * 0.50) # Stop 50%
                    risk_pct = (sl_price - entry_price) / entry_price

                    if 0.003 <= risk_pct <= 0.035:
                        tp_price = entry_price - ((sl_price - entry_price) * 2.0) # TP 1:2.0
                        pos_size_usd = min(balance, risk_usd / risk_pct)
                        in_pos = True
                        pos_side = 'SHORT'

    return trades

def run():
    print("==========================================================")
    print("  AUDITORÍA LOCAL: HYENUK CHU / VELA ELEFANTE (15M)")
    print("  Activos: NVDA y TSLA | Stop 50%, TP 1:2.0 | Parquet")
    print("==========================================================")

    tickers = ['NVDA', 'TSLA']
    all_trades = []

    for t in tickers:
        trades = auditar_ticker(t)
        all_trades.extend(trades)

    if not all_trades:
        print("No se generaron operaciones con los filtros definidos.")
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
