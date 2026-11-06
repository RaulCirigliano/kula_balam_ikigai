import os
import yfinance as yf
import pandas as pd
import numpy as np

DATA_DIR = "/home/raul/Escritorio/proyectos/kula_balam_ikigai/datos_historicos"
os.makedirs(DATA_DIR, exist_ok=True)

def descargar_si_falta(ticker_name):
    file_path = os.path.join(DATA_DIR, f"yf_{ticker_name}_1d.parquet")
    if not os.path.exists(file_path):
        print(f"  -> Descargando {ticker_name} [1d] (2 años)...")
        try:
            ticker = yf.Ticker(ticker_name)
            df = ticker.history(period="2y", interval="1d")
            if df.empty:
                print(f"     [ERROR] Sin datos para {ticker_name}")
                return False
            df = df.reset_index()
            df = df.rename(columns={
                'Date': 'datetime',
                'Datetime': 'datetime',
                'Open': 'open',
                'High': 'high',
                'Low': 'low',
                'Close': 'close',
                'Volume': 'volume'
            })
            df.to_parquet(file_path, index=False)
            df.to_csv(file_path.replace('.parquet', '.csv'), index=False)
            print(f"     [OK] Guardado: {file_path}")
        except Exception as e:
            print(f"     [ERROR] Falló descarga {ticker_name}: {e}")
            return False
    else:
        print(f"  -> {ticker_name} [1d] ya existe en disco.")
    return True

def preparar_datos(df):
    df = df.copy()
    df['datetime'] = pd.to_datetime(df['datetime'], utc=True)
    df = df.sort_values('datetime').reset_index(drop=True)

    # Indicadores técnicos sobre velas cerradas (shift 1 para evitar repintado)
    df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean().shift(1)
    df['vol_sma20'] = df['volume'].rolling(window=20).mean().shift(1)

    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift(1)).abs()
    low_close = (df['low'] - df['close'].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(window=14).mean().shift(1)

    return df

def auditar_ticker(ticker_name):
    file_path = os.path.join(DATA_DIR, f"yf_{ticker_name}_1d.parquet")
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

    for i in range(55, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]
        v2 = df.iloc[i-2]
        v3 = df.iloc[i-3]

        # Monitoreo de salidas por SL / TP (swing de varios días)
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

        # Gatillo de entrada Swing: Fibo Zona Dorada + BOS 3 Velas en Diario
        if not in_pos:
            ema50 = prev['ema_50']
            atr_val = prev['atr']
            if pd.isna(ema50) or pd.isna(atr_val) or atr_val <= 0:
                continue

            # Ventana de swing retrospectiva (últimas 30 velas diarias)
            lookback = df.iloc[i-31:i-1]
            swing_high = lookback['high'].max()
            swing_low = lookback['low'].min()
            swing_range = swing_high - swing_low

            if swing_range <= 0:
                continue

            # CASO LONG: Tendencia alcista (Close > EMA50) + Retroceso a Fibo 0.50-0.707
            if prev['close'] > ema50:
                fibo_50 = swing_high - (0.50 * swing_range)
                fibo_70 = swing_high - (0.707 * swing_range)

                low_reciente = min(v3['low'], v2['low'], prev['low'])
                en_zona = (low_reciente >= fibo_70) and (low_reciente <= fibo_50)

                # BOS Diario de 3 Velas: quiebre del máximo de la vela previa con cierre verde
                bos_long = (prev['close'] > v2['high']) and (prev['close'] > prev['open'])

                if en_zona and bos_long:
                    entry_price = row['open']
                    sl_price = low_reciente - (0.5 * atr_val)
                    risk_pct = (entry_price - sl_price) / entry_price

                    if 0.01 <= risk_pct <= 0.08:
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

                # BOS Diario de 3 Velas: quiebre del mínimo de la vela previa con cierre rojo
                bos_short = (prev['close'] < v2['low']) and (prev['close'] < prev['open'])

                if en_zona and bos_short:
                    entry_price = row['open']
                    sl_price = high_reciente + (0.5 * atr_val)
                    risk_pct = (sl_price - entry_price) / entry_price

                    if 0.01 <= risk_pct <= 0.08:
                        tp_price = entry_price - ((sl_price - entry_price) * 2.0)
                        pos_size_usd = min(balance, risk_usd / risk_pct)
                        in_pos = True
                        pos_side = 'SHORT'

    return trades

def run():
    print("==========================================================")
    print("  AUDITORÍA: ZONA DORADA FIBO + BOS 3 VELAS (DIARIO 1D)")
    print("  Swing Trading 2 Años | Ratio 1:2.0 | Sin forzado intradía")
    print("  Activos: NVDA, TSLA, AMD, META")
    print("==========================================================")

    tickers = ['NVDA', 'TSLA', 'AMD', 'META']
    for t in tickers:
        descargar_si_falta(t)

    all_trades = []
    print("\nIniciando auditoría sobre los 4 activos diarios...")
    for t in tickers:
        print(f"  -> Auditando {t} [1d]...")
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

    print("\n---------------- RESULTADOS FINALES DIARIOS ----------------")
    print(f"Total Operaciones:    {total_trades}")
    print(f"Operaciones Ganadas:  {len(wins)}")
    print(f"Operaciones Perdidas: {len(losses)}")
    print(f"Win Rate:             {win_rate:.2f}%")
    print(f"Ganancia Bruta:       +${gross_profit:.2f} USD")
    print(f"Pérdida Bruta:        -${gross_loss:.2f} USD")
    print(f"Profit Factor:        {profit_factor:.2f}")
    print(f"PnL Neto:             {net_pnl:+.2f} USD ({net_pnl:+.2f}%)")
    print("------------------------------------------------------------\n")

    print("Detalle por activo:")
    for t in tickers:
        df_sub = df_t[df_t['ticker'] == t]
        pnl_sub = df_sub['pnl'].sum() if not df_sub.empty else 0.0
        trades_sub = len(df_sub)
        print(f"  * {t:5s}: {trades_sub:2d} trades | PnL: {pnl_sub:+.2f} USD")
    print()

if __name__ == '__main__':
    run()
