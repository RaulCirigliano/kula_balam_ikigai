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
    
    # Filtrar sesión oficial regular (09:30 a 16:00 ET)
    df = df[(df['time_str'] >= '09:30') & (df['time_str'] <= '16:00')].copy().reset_index(drop=True)

    # ATR para cálculo de Stop Loss dinámico
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

    trades = []
    dias = df['date'].unique()

    # Historial de volúmenes de apertura para calcular RVOL
    aperturas_vol = []

    for idx, dia in enumerate(dias):
        df_dia = df[df['date'] == dia].reset_index(drop=True)
        if len(df_dia) < 4:
            continue

        vela_apertura = df_dia.iloc[0]
        if vela_apertura['time_str'] != '09:30':
            continue

        vol_open = vela_apertura['volume']
        aperturas_vol.append(vol_open)

        # Necesitamos al menos 5 días previos para calcular un RVOL de apertura confiable
        if len(aperturas_vol) < 6:
            continue

        avg_vol_open = np.mean(aperturas_vol[-16:-1])
        rvol = vol_open / max(1.0, avg_vol_open)

        # Buscar el cierre del día anterior
        if idx == 0:
            continue
        dia_previo = dias[idx - 1]
        df_previo = df[df['date'] == dia_previo]
        if df_previo.empty:
            continue
        cierre_ayer = df_previo.iloc[-1]['close']

        # Cálculo del Gap porcentual
        gap_pct = ((vela_apertura['open'] - cierre_ayer) / cierre_ayer) * 100.0

        # Filtro de ignición: Gap >= 1.2% y RVOL >= 1.15
        gap_alcista = (gap_pct >= 1.2) and (rvol >= 1.15)
        gap_bajista = (gap_pct <= -1.2) and (rvol >= 1.15)

        if not (gap_alcista or gap_bajista):
            continue

        or_high = vela_apertura['high']
        or_low = vela_apertura['low']
        atr_val = vela_apertura['atr']

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

            # 1. Cierre forzado intradía a las 15:45 ET
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

            # 3. Gatillo de Ruptura de Apertura (09:45 a 12:00 ET)
            if not in_pos and not trade_del_dia_hecho and ('09:45' <= row['time_str'] <= '12:00'):
                # CASO GAP ALCISTA: Quiebre por encima del High de apertura
                if gap_alcista and prev['close'] > or_high and prev['close'] > prev['open']:
                    entry_price = row['open']
                    # Stop en el mínimo de la vela de quiebre o en la mitad del rango inicial
                    sl_candidato = max(prev['low'], (or_high + or_low) / 2.0)
                    sl_price = sl_candidato
                    risk_pct = (entry_price - sl_price) / entry_price

                    if 0.003 <= risk_pct <= 0.035:
                        tp_price = entry_price + ((entry_price - sl_price) * 2.0)
                        pos_size_usd = min(balance, risk_usd / risk_pct)
                        in_pos = True
                        pos_side = 'LONG'
                        trade_del_dia_hecho = True

                # CASO GAP BAJISTA: Quiebre por debajo del Low de apertura
                elif gap_bajista and prev['close'] < or_low and prev['close'] < prev['open']:
                    entry_price = row['open']
                    sl_candidato = min(prev['high'], (or_high + or_low) / 2.0)
                    sl_price = sl_candidato
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
    print("  AUDITORÍA: GAP & GO INSTITUCIONAL (15M)")
    print("  Filtro: |Gap| >= 1.2% + RVOL >= 1.15 | Ratio 1:2.0")
    print("  Activos: NVDA, TSLA, AMD, META | Ventana 09:45 - 12:00")
    print("==========================================================")

    tickers = ['NVDA', 'TSLA', 'AMD', 'META']
    all_trades = []

    for t in tickers:
        print(f"  -> Auditando {t}...")
        trades = auditar_ticker(t)
        all_trades.extend(trades)

    if not all_trades:
        print("No se generaron operaciones con los filtros de Gap y Volumen.")
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
