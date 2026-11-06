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

def preparar_datos_individuales(ticker_name):
    file_path = os.path.join(DATA_DIR, f"yf_{ticker_name}_1d.parquet")
    df = pd.read_parquet(file_path)
    df['datetime'] = pd.to_datetime(df['datetime'], utc=True)
    df = df.sort_values('datetime').reset_index(drop=True)
    df['date'] = df['datetime'].dt.date

    # Indicadores técnicos sobre velas cerradas (shift 1)
    df['sma_20'] = df['close'].rolling(window=20).mean().shift(1)
    df['sma_50'] = df['close'].rolling(window=50).mean().shift(1)
    df['donchian_high_20'] = df['high'].rolling(window=20).max().shift(1)

    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift(1)).abs()
    low_close = (df['low'] - df['close'].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(window=14).mean().shift(1)

    return df

def run():
    print("==========================================================")
    print("  AUDITORÍA AMPLIADA: MOMENTUM RELATIVO VS SPY (1D)")
    print("  Filtro Macro SPY SMA200 | Líder #1 en RS 60d | Trailing SMA20")
    print("  Canasta 9 Activos: NVDA, TSLA, AMD, META, MSFT, GOOGL, AAPL, AMZN, AVGO")
    print("==========================================================")

    descargar_si_falta('SPY')
    tickers = ['NVDA', 'TSLA', 'AMD', 'META', 'MSFT', 'GOOGL', 'AAPL', 'AMZN', 'AVGO']
    for t in tickers:
        descargar_si_falta(t)

    # Cargar y preparar SPY
    spy_df = pd.read_parquet(os.path.join(DATA_DIR, "yf_SPY_1d.parquet"))
    spy_df['datetime'] = pd.to_datetime(spy_df['datetime'], utc=True)
    spy_df = spy_df.sort_values('datetime').reset_index(drop=True)
    spy_df['date'] = spy_df['datetime'].dt.date
    spy_df['spy_sma200'] = spy_df['close'].rolling(window=200).mean().shift(1)
    spy_map = spy_df.set_index('date')

    # Cargar activos
    dfs = {}
    for t in tickers:
        dfs[t] = preparar_datos_individuales(t).set_index('date')

    # Fechas comunes entre todos los activos y SPY
    fechas = sorted(list(set(spy_map.index).intersection(*(d.index for d in dfs.values()))))

    balance = 100.0
    risk_usd = 1.00
    fee_rate = 0.0005

    in_pos = False
    pos_ticker = None
    entry_price = 0.0
    sl_price = 0.0
    pos_size_usd = 0.0

    trades = []

    for idx in range(200, len(fechas)):
        fecha_actual = fechas[idx]
        fecha_previa = fechas[idx - 1]

        spy_row = spy_map.loc[fecha_actual]
        spy_prev = spy_map.loc[fecha_previa]

        # 1. Monitoreo de posición abierta
        if in_pos:
            row_act = dfs[pos_ticker].loc[fecha_actual]
            row_prev = dfs[pos_ticker].loc[fecha_previa]

            # Salida por Stop Loss
            if row_act['low'] <= sl_price:
                exit_price = sl_price
                raw_pnl = (exit_price - entry_price) / entry_price
                net_pnl = (pos_size_usd * raw_pnl) - (pos_size_usd * 2 * fee_rate)
                trades.append({'ticker': pos_ticker, 'type': 'SL', 'pnl': net_pnl})
                in_pos = False
                continue

            # Salida por cierre bajo SMA 20 (Trailing de tendencia institucional)
            elif row_prev['close'] < row_prev['sma_20']:
                exit_price = row_act['open']
                raw_pnl = (exit_price - entry_price) / entry_price
                net_pnl = (pos_size_usd * raw_pnl) - (pos_size_usd * 2 * fee_rate)
                trades.append({'ticker': pos_ticker, 'type': 'TRAIL_SMA20', 'pnl': net_pnl})
                in_pos = False
                continue

        # 2. Evaluación de nuevas entradas si no hay posición
        if not in_pos:
            # Filtro macro: SPY sobre su SMA 200
            if pd.isna(spy_prev['spy_sma200']) or spy_prev['close'] <= spy_prev['spy_sma200']:
                continue

            # Calcular Momentum Relativo a 60 días para cada ticker de la canasta
            fecha_60d = fechas[idx - 60]
            spy_cierre_hoy = spy_prev['close']
            spy_cierre_60d = spy_map.loc[fecha_60d]['close']

            rs_momentum = {}
            for t in tickers:
                c_prev = dfs[t].loc[fecha_previa]['close']
                c_60d = dfs[t].loc[fecha_60d]['close']
                rs_hoy = c_prev / spy_cierre_hoy
                rs_pasado = c_60d / spy_cierre_60d
                mom = (rs_hoy - rs_pasado) / rs_pasado
                rs_momentum[t] = mom

            # Líder absoluto (#1) en aceleración relativa
            lider = max(rs_momentum, key=rs_momentum.get)
            mom_lider = rs_momentum[lider]

            if mom_lider <= 0:
                continue

            row_lider_act = dfs[lider].loc[fecha_actual]
            row_lider_prev = dfs[lider].loc[fecha_previa]

            # Gatillo de confirmación en el líder
            donchian = row_lider_prev['donchian_high_20']
            sma50 = row_lider_prev['sma_50']
            atr_val = row_lider_prev['atr']

            if pd.isna(donchian) or pd.isna(sma50) or pd.isna(atr_val) or atr_val <= 0:
                continue

            rompio_maximo = row_lider_prev['close'] >= donchian
            sobre_sma50 = row_lider_prev['close'] > sma50

            if rompio_maximo and sobre_sma50:
                pos_ticker = lider
                entry_price = row_lider_act['open']
                sl_price = entry_price - (2.0 * atr_val)
                risk_pct = (entry_price - sl_price) / entry_price

                if 0.02 <= risk_pct <= 0.12:
                    pos_size_usd = min(balance, risk_usd / risk_pct)
                    in_pos = True

    if not trades:
        print("No se generaron operaciones con los filtros establecidos.")
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

    print("\n---------------- RESULTADOS FINALES AMPLIADOS (9 ACTIVOS) ----------------")
    print(f"Total Operaciones:    {total_trades}")
    print(f"Operaciones Ganadas:  {len(wins)}")
    print(f"Operaciones Perdidas: {len(losses)}")
    print(f"Win Rate:             {win_rate:.2f}%")
    print(f"Ganancia Bruta:       +${gross_profit:.2f} USD")
    print(f"Pérdida Bruta:        -${gross_loss:.2f} USD")
    print(f"Profit Factor:        {profit_factor:.2f}")
    print(f"PnL Neto:             {net_pnl:+.2f} USD ({net_pnl:+.2f}%)")
    print("--------------------------------------------------------------------------\n")

    print("Detalle por activo:")
    for t in tickers:
        df_sub = df_t[df_t['ticker'] == t]
        pnl_sub = df_sub['pnl'].sum() if not df_sub.empty else 0.0
        trades_sub = len(df_sub)
        if trades_sub > 0:
            print(f"  * {t:5s}: {trades_sub:2d} trades | PnL: {pnl_sub:+.2f} USD")
    print()

if __name__ == '__main__':
    run()
