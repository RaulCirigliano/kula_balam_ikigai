import os
import pandas as pd
import numpy as np

DATA_PATH = "/home/raul/Escritorio/proyectos/kula_balam_ikigai/datos_historicos/yf_QQQ_5m.parquet"

def calcular_indicadores(df):
    df = df.copy()
    
    # Asegurar orden temporal y zona horaria Eastern Time (Wall Street)
    df['datetime'] = pd.to_datetime(df['datetime'])
    if df['datetime'].dt.tz is None:
        df['datetime'] = df['datetime'].dt.tz_localize('UTC').dt.tz_convert('America/New_York')
    else:
        df['datetime'] = df['datetime'].dt.tz_convert('America/New_York')
        
    df = df.sort_values('datetime').reset_index(drop=True)
    df['date'] = df['datetime'].dt.date
    
    # Filtrar estrictamente la sesión regular de mercado (09:30 a 16:00 ET)
    df['time_str'] = df['datetime'].dt.strftime('%H:%M')
    df = df[(df['time_str'] >= '09:30') & (df['time_str'] <= '16:00')].copy().reset_index(drop=True)

    # Typical price y Ponderación por Volumen
    df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3.0
    df['pv'] = df['typical_price'] * df['volume']

    # VWAP anclado por sesión diaria (reinicio a las 09:30 ET de cada día)
    df['cum_pv'] = df.groupby('date')['pv'].cumsum()
    df['cum_vol'] = df.groupby('date')['volume'].cumsum()
    df['vwap'] = df['cum_pv'] / np.maximum(1e-9, df['cum_vol'])

    # Desviación estándar ponderada por volumen
    df['vol_diff_sq'] = df['volume'] * ((df['typical_price'] - df['vwap']) ** 2)
    df['cum_vol_diff_sq'] = df.groupby('date')['vol_diff_sq'].cumsum()
    df['vwap_std'] = np.sqrt(df['cum_vol_diff_sq'] / np.maximum(1e-9, df['cum_vol']))

    # Bandas +/- 2 Sigma
    df['upper_2'] = df['vwap'] + (2.0 * df['vwap_std'])
    df['lower_2'] = df['vwap'] - (2.0 * df['vwap_std'])

    # Shift 1 para evaluar solo sobre velas ya cerradas (cero repintado)
    df['vwap_prev'] = df['vwap'].shift(1)
    df['upper_2_prev'] = df['upper_2'].shift(1)
    df['lower_2_prev'] = df['lower_2'].shift(1)

    # ATR 14 y Media de volumen
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift(1)).abs()
    low_close = (df['low'] - df['close'].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(window=14).mean().shift(1)
    df['vol_sma20'] = df['volume'].rolling(window=20).mean().shift(1)

    return df

def auditar():
    print("==========================================================")
    print("  AUDITORÍA LOCAL: NASDAQ ARAUJO - VWAP QQQ (5M)")
    print("  Lectura instantánea de Parquet | Sesión 09:30-16:00 ET")
    print("==========================================================")

    if not os.path.exists(DATA_PATH):
        print(f"Error: No se encontró el archivo {DATA_PATH}")
        return

    print("Cargando dataset local...")
    raw_df = pd.read_parquet(DATA_PATH)
    print(f"Total registros cargados: {len(raw_df)}")

    df = calcular_indicadores(raw_df)
    print(f"Velas efectivas en horario regular de mercado: {len(df)}")

    balance = 100.0
    risk_usd = 1.00
    fee_rate = 0.0005  # Comisión / slippage por trade

    in_pos = False
    pos_side = None
    entry_price = 0.0
    sl_price = 0.0
    tp_price = 0.0
    pos_size_usd = 0.0

    trades = []

    for i in range(30, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]

        # Salida forzada antes del cierre de campana (15:55 ET) para evitar riesgo overnight
        if in_pos and row['time_str'] >= '15:55':
            raw_pnl = (row['close'] - entry_price) / entry_price if pos_side == 'LONG' else (entry_price - row['close']) / entry_price
            net_pnl = (pos_size_usd * raw_pnl) - (pos_size_usd * 2 * fee_rate)
            balance += net_pnl
            trades.append({'type': 'EOD', 'side': pos_side, 'pnl': net_pnl})
            in_pos = False
            continue

        # Monitoreo de salidas normales por SL / TP
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
                    trades.append({'type': exit_reason, 'side': pos_side, 'pnl': net_pnl})
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
                    trades.append({'type': exit_reason, 'side': pos_side, 'pnl': net_pnl})
                    in_pos = False
                    continue

        # Gatillo de entrada si no hay posición abierta
        if not in_pos:
            atr_val = prev['atr']
            vol_mean = prev['vol_sma20']
            vwap_val = prev['vwap_prev']
            lower_2 = prev['lower_2_prev']
            upper_2 = prev['upper_2_prev']

            if pd.isna(atr_val) or atr_val <= 0 or pd.isna(vol_mean) or vol_mean <= 0 or pd.isna(vwap_val):
                continue

            # Descartar los primeros 15 minutos de campana (09:30-09:45) por ruido de apertura
            if row['time_str'] < '09:45':
                continue

            vol_ok = prev['volume'] >= 1.2 * vol_mean

            # Condición LONG: Rechazo en banda -2 Sigma con volumen hacia el VWAP
            if (prev['low'] <= lower_2) and (prev['close'] > lower_2) and (prev['close'] < vwap_val) and vol_ok:
                entry_price = row['open']
                sl_price = prev['low'] - (0.75 * atr_val)
                risk_pct = (entry_price - sl_price) / entry_price

                if 0.001 <= risk_pct <= 0.02:
                    tp_price = vwap_val
                    # Exigir un ratio beneficio/riesgo mínimo de 1.2
                    if tp_price > entry_price and ((tp_price - entry_price) / (entry_price - sl_price)) >= 1.2:
                        pos_size_usd = min(balance, risk_usd / risk_pct)
                        in_pos = True
                        pos_side = 'LONG'

            # Condición SHORT: Rechazo en banda +2 Sigma con volumen hacia el VWAP
            elif (prev['high'] >= upper_2) and (prev['close'] < upper_2) and (prev['close'] > vwap_val) and vol_ok:
                entry_price = row['open']
                sl_price = prev['high'] + (0.75 * atr_val)
                risk_pct = (sl_price - entry_price) / entry_price

                if 0.001 <= risk_pct <= 0.02:
                    tp_price = vwap_val
                    if tp_price < entry_price and ((entry_price - tp_price) / (sl_price - entry_price)) >= 1.2:
                        pos_size_usd = min(balance, risk_usd / risk_pct)
                        in_pos = True
                        pos_side = 'SHORT'

    if not trades:
        print("No se generaron trades con los filtros aplicados.")
        return

    df_t = pd.DataFrame(trades)
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
    auditar()
