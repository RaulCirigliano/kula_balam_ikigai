import os
import yfinance as yf
import pandas as pd
import numpy as np

DATA_DIR = "/home/raul/Escritorio/proyectos/kula_balam_ikigai/datos_historicos"
os.makedirs(DATA_DIR, exist_ok=True)

def descargar_si_falta(ticker_name):
    file_path = os.path.join(DATA_DIR, f"yf_{ticker_name}_15m.parquet")
    if not os.path.exists(file_path):
        print(f"  -> Descargando {ticker_name} [15m] (60d)...")
        try:
            ticker = yf.Ticker(ticker_name)
            df = ticker.history(period="60d", interval="15m")
            if df.empty:
                print(f"     [ERROR] Sin datos para {ticker_name}")
                return False
            df.reset_index(inplace=True)
            df.rename(columns={
                'Date': 'datetime',
                'Datetime': 'datetime',
                'Open': 'open',
                'High': 'high',
                'Low': 'low',
                'Close': 'close',
                'Volume': 'volume'
            }, inplace=True)
            df.to_parquet(file_path, index=False)
            df.to_csv(file_path.replace('.parquet', '.csv'), index=False)
            print(f"     [OK] Guardado: {file_path}")
        except Exception as e:
            print(f"     [ERROR] Falló descarga {ticker_name}: {e}")
            return False
    else:
        print(f"  -> {ticker_name} ya existe en disco.")
    return True

def preparar_datos(df):
    df = df.copy()
    df['datetime'] = pd.to_datetime(df['datetime'])
    if df['datetime'].dt.tz is None:
        df['datetime'] = df['datetime'].dt.tz_localize('UTC').dt.tz_convert('America/New_York')
    else:
        df['datetime'] = df['datetime'].dt.tz_convert('America/New_York')
        
    df = df.sort_values('datetime').reset_index(drop=True)
    df['time_str'] = df['datetime'].dt.strftime('%H:%M')
    
    # Horario oficial de Wall Street (09:30 a 16:00 ET)
    df = df[(df['time_str'] >= '09:30') & (df['time_str'] <= '16:00')].copy().reset_index(drop=True)

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

        # Cierre forzado intradía 15:45 ET
        if in_pos and row['time_str'] >= '15:45':
            raw_pnl = (row['close'] - entry_price) / entry_price if pos_side == 'LONG' else (entry_price - row['close']) / entry_price
            net_pnl = (pos_size_usd * raw_pnl) - (pos_size_usd * 2 * fee_rate)
            trades.append({'ticker': ticker_name, 'type': 'EOD', 'side': pos_side, 'pnl': net_pnl})
            in_pos = False
            continue

        # Monitoreo de salidas normales (SL / TP)
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

        # Detección de Vela Elefante
        if not in_pos:
            if row['time_str'] <= '09:45':
                continue

            atr_val = prev['atr']
            vol_mean = prev['vol_sma20']
            body_val = prev['body']
            prev_max = prev['prev_max_body_8']

            if pd.isna(atr_val) or atr_val <= 0 or pd.isna(vol_mean) or vol_mean <= 0:
                continue

            is_elephant = (body_val >= 1.8 * atr_val) and (body_val >= prev_max) and (prev['volume'] >= 1.3 * vol_mean)

            if is_elephant:
                if prev['close'] > prev['open'] and prev['close'] > row['ema_20']:
                    entry_price = row['open']
                    sl_price = prev['open'] + (body_val * 0.50)
                    risk_pct = (entry_price - sl_price) / entry_price

                    if 0.003 <= risk_pct <= 0.035:
                        tp_price = entry_price + ((entry_price - sl_price) * 2.0)
                        pos_size_usd = min(balance, risk_usd / risk_pct)
                        in_pos = True
                        pos_side = 'LONG'

                elif prev['close'] < prev['open'] and prev['close'] < row['ema_20']:
                    entry_price = row['open']
                    sl_price = prev['open'] - (body_val * 0.50)
                    risk_pct = (sl_price - entry_price) / entry_price

                    if 0.003 <= risk_pct <= 0.035:
                        tp_price = entry_price - ((sl_price - entry_price) * 2.0)
                        pos_size_usd = min(balance, risk_usd / risk_pct)
                        in_pos = True
                        pos_side = 'SHORT'

    return trades

def run():
    print("==========================================================")
    print("  DESCARGA Y AUDITORÍA ROBUSTA: VELA ELEFANTE 15M")
    print("  Canasta: NVDA, TSLA, AMD, META | Stop 50%, TP 1:2.0")
    print("==========================================================")

    tickers = ['NVDA', 'TSLA', 'AMD', 'META']
    for t in tickers:
        descargar_si_falta(t)

    all_trades = []
    print("\nIniciando auditoría sobre los 4 activos...")
    for t in tickers:
        print(f"  -> Auditando {t}...")
        trades = auditar_ticker(t)
        all_trades.extend(trades)

    if not all_trades:
        print("No se generaron operaciones.")
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

    # Rendimiento individual por activo
    print("Detalle por activo:")
    for t in tickers:
        df_sub = df_t[df_t['ticker'] == t]
        pnl_sub = df_sub['pnl'].sum()
        trades_sub = len(df_sub)
        print(f"  * {t:5s}: {trades_sub:2d} trades | PnL: {pnl_sub:+.2f} USD")
    print()

if __name__ == '__main__':
    run()
