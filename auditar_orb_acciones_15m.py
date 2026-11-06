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
    df['date'] = df['datetime'].dt.date
    df['time_str'] = df['datetime'].dt.strftime('%H:%M')
    
    # Filtrar sesión regular de Wall Street (09:30 a 16:00 ET)
    df = df[(df['time_str'] >= '09:30') & (df['time_str'] <= '16:00')].copy().reset_index(drop=True)

    # Indicadores técnicos (shift 1 para evitar sesgo de anticipación)
    df['vol_sma20'] = df['volume'].rolling(window=20).mean().shift(1)

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

    trades = []
    
    # Agrupar por días de negociación
    dias = df['date'].unique()

    for dia in dias:
        df_dia = df[df['date'] == dia].reset_index(drop=True)
        if len(df_dia) < 4:
            continue

        # La primera vela (09:30 - 09:45 ET) define el rango de apertura
        vela_apertura = df_dia.iloc[0]
        if vela_apertura['time_str'] != '09:30':
            continue

        or_high = vela_apertura['high']
        or_low = vela_apertura['low']
        or_mid = (or_high + or_low) / 2.0

        in_pos = False
        pos_side = None
        entry_price = 0.0
        sl_price = 0.0
        tp_price = 0.0
        pos_size_usd = 0.0
        trade_del_dia_hecho = False

        for i in range(1, len(df_dia)):
            row = df_dia.iloc[i]
            prev = df_dia.iloc[i-1]

            # 1. Cierre obligatorio intradía a las 15:45 ET
            if in_pos and row['time_str'] >= '15:45':
                raw_pnl = (row['close'] - entry_price) / entry_price if pos_side == 'LONG' else (entry_price - row['close']) / entry_price
                net_pnl = (pos_size_usd * raw_pnl) - (pos_size_usd * 2 * fee_rate)
                trades.append({'ticker': ticker_name, 'type': 'EOD', 'side': pos_side, 'pnl': net_pnl})
                in_pos = False
                break

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
                        break

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
                        break

            # 3. Gatillo de ruptura si no hay posición y aún no se operó en el día
            # Solo permitimos entradas entre 09:45 y 12:00 ET (ventana de mayor volumen)
            if not in_pos and not trade_del_dia_hecho and ('09:45' <= row['time_str'] <= '12:00'):
                vol_mean = prev['vol_sma20']
                if pd.isna(vol_mean) or vol_mean <= 0:
                    continue

                vol_ok = prev['volume'] >= 1.0 * vol_mean

                # Ruptura alcista del High de apertura
                if prev['close'] > or_high and vol_ok:
                    entry_price = row['open']
                    sl_price = or_mid
                    risk_pct = (entry_price - sl_price) / entry_price

                    if 0.003 <= risk_pct <= 0.035:
                        tp_price = entry_price + ((entry_price - sl_price) * 2.0)
                        pos_size_usd = min(balance, risk_usd / risk_pct)
                        in_pos = True
                        pos_side = 'LONG'
                        trade_del_dia_hecho = True

                # Ruptura bajista del Low de apertura
                elif prev['close'] < or_low and vol_ok:
                    entry_price = row['open']
                    sl_price = or_mid
                    risk_pct = (sl_price - entry_price) / entry_price

                    if 0.003 <= risk_pct <= 0.035:
                        tp_price = entry_price - ((sl_price - entry_price) * 2.0)
                        pos_size_usd = min(balance, risk_usd / risk_pct)
                        in_pos = True
                        pos_side = 'SHORT'
                        trade_del_dia_hecho = True

    return trades

def run():
    print("==========================================================")
    print("  AUDITORÍA LOCAL: OPENING RANGE BREAKOUT (ORB 15M)")
    print("  Activos: NVDA y TSLA | Stop OR Mid, TP 1:2.0 | Parquet")
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
