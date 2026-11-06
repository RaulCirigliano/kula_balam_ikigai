import os
import pandas as pd
import numpy as np

DATA_DIR = "/home/raul/Escritorio/proyectos/kula_balam_ikigai/datos_historicos"

def run():
    print("==========================================================")
    print("  AUDITORÍA: PAIRS TRADING (ARBITRAJE ESTADÍSTICO 1D)")
    print("  Par: NVDA vs AMD | Market-Neutral OLS Hedge Ratio")
    print("  Entrada: |Z| >= 2.0 | Salida: Z = 0.0 | Stop: |Z| >= 3.5")
    print("==========================================================")

    f_nvda = os.path.join(DATA_DIR, "yf_NVDA_1d.parquet")
    f_amd = os.path.join(DATA_DIR, "yf_AMD_1d.parquet")

    if not os.path.exists(f_nvda) or not os.path.exists(f_amd):
        print("Error: Faltan archivos locales de NVDA o AMD.")
        return

    df_a = pd.read_parquet(f_nvda)
    df_b = pd.read_parquet(f_amd)

    df_a['date'] = pd.to_datetime(df_a['datetime'], utc=True).dt.date
    df_b['date'] = pd.to_datetime(df_b['datetime'], utc=True).dt.date

    df_a = df_a.sort_values('date').set_index('date')
    df_b = df_b.sort_values('date').set_index('date')

    fechas = sorted(list(set(df_a.index).intersection(df_b.index)))
    
    df = pd.DataFrame(index=fechas)
    df['close_a'] = df_a.loc[fechas, 'close']
    df['close_b'] = df_b.loc[fechas, 'close']
    df['open_a'] = df_a.loc[fechas, 'open']
    df['open_b'] = df_b.loc[fechas, 'open']

    # Parámetros cuantitativos
    window = 40        # Ventana rodante para estimar Beta y Media
    entry_z = 2.0      # Umbral de apertura de desvío
    exit_z = 0.0       # Reversión a la media (Take Profit)
    stop_z = 3.5       # Salida por desacople estructural (Stop Loss)
    fee_rate = 0.0005  # Fricción comisiones/slippage

    # Vectores para cálculo rodante
    spreads = []
    betas = []

    for i in range(len(df)):
        if i < window:
            spreads.append(np.nan)
            betas.append(np.nan)
            continue
        
        # OLS rodante cerrado previo (shift 1 para evitar repintado)
        y = df['close_a'].iloc[i-window:i].values
        x = df['close_b'].iloc[i-window:i].values
        
        # cov(x,y) / var(x)
        cov_mat = np.cov(y, x)
        beta_val = cov_mat[0, 1] / max(1e-6, cov_mat[1, 1])
        spread_val = df['close_a'].iloc[i-1] - (beta_val * df['close_b'].iloc[i-1])
        
        betas.append(beta_val)
        spreads.append(spread_val)

    df['beta'] = betas
    df['spread'] = spreads
    df['spread_mean'] = df['spread'].rolling(window=window).mean()
    df['spread_std'] = df['spread'].rolling(window=window).std()
    df['z_score'] = (df['spread'] - df['spread_mean']) / np.maximum(1e-6, df['spread_std'])

    balance = 100.0
    risk_usd_leg = 25.0  # $25 por pata para mantener neutralidad ($50 exposición)

    in_pos = False
    pos_type = None  # 'SHORT_A_LONG_B' (Z >= 2.0) o 'LONG_A_SHORT_B' (Z <= -2.0)
    entry_pa = 0.0
    entry_pb = 0.0
    active_beta = 1.0

    trades = []

    for i in range(window * 2, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]

        z_val = prev['z_score']
        beta_curr = prev['beta']

        if pd.isna(z_val) or pd.isna(beta_curr):
            continue

        # 1. Monitoreo de salidas si hay posición abierta
        if in_pos:
            hit_exit = False
            exit_reason = ""

            # Condición de salida para SHORT NVDA / LONG AMD
            if pos_type == 'SHORT_A_LONG_B':
                if z_val <= exit_z:
                    hit_exit = True
                    exit_reason = 'TP_MEAN'
                elif z_val >= stop_z:
                    hit_exit = True
                    exit_reason = 'SL_DIVERGENCE'

            # Condición de salida para LONG NVDA / SHORT AMD
            elif pos_type == 'LONG_A_SHORT_B':
                if z_val >= exit_z:
                    hit_exit = True
                    exit_reason = 'TP_MEAN'
                elif z_val <= -stop_z:
                    hit_exit = True
                    exit_reason = 'SL_DIVERGENCE'

            if hit_exit:
                exit_pa = row['open_a']
                exit_pb = row['open_b']

                if pos_type == 'SHORT_A_LONG_B':
                    pnl_a = (entry_pa - exit_pa) / entry_pa
                    pnl_b = (exit_pb - entry_pb) / entry_pb
                else:
                    pnl_a = (exit_pa - entry_pa) / entry_pa
                    pnl_b = (entry_pb - exit_pb) / entry_pb

                net_usd_a = (risk_usd_leg * pnl_a) - (risk_usd_leg * 2 * fee_rate)
                net_usd_b = (risk_usd_leg * pnl_b) - (risk_usd_leg * 2 * fee_rate)
                total_trade_pnl = net_usd_a + net_usd_b

                trades.append({
                    'type': exit_reason,
                    'side': pos_type,
                    'pnl': total_trade_pnl,
                    'pnl_nvda': net_usd_a,
                    'pnl_amd': net_usd_b
                })
                in_pos = False
                continue

        # 2. Evaluación de nuevas entradas
        if not in_pos:
            # Spread sobreextendido al alza (NVDA cara respecto a AMD)
            if z_val >= entry_z:
                in_pos = True
                pos_type = 'SHORT_A_LONG_B'
                entry_pa = row['open_a']
                entry_pb = row['open_b']
                active_beta = beta_curr

            # Spread sobreextendido a la baja (NVDA barata respecto a AMD)
            elif z_val <= -entry_z:
                in_pos = True
                pos_type = 'LONG_A_SHORT_B'
                entry_pa = row['open_a']
                entry_pb = row['open_b']
                active_beta = beta_curr

    if not trades:
        print("No se generaron operaciones de arbitraje con los parámetros actuales.")
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

    print("\n---------------- RESULTADOS FINALES PAIRS TRADING ----------------")
    print(f"Total Operaciones del Par: {total_trades}")
    print(f"Operaciones Ganadas:       {len(wins)}")
    print(f"Operaciones Perdidas:      {len(losses)}")
    print(f"Win Rate:                  {win_rate:.2f}%")
    print(f"Ganancia Bruta:            +${gross_profit:.2f} USD")
    print(f"Pérdida Bruta:             -${gross_loss:.2f} USD")
    print(f"Profit Factor:             {profit_factor:.2f}")
    print(f"PnL Neto Combinado:        {net_pnl:+.2f} USD ({net_pnl:+.2f}%)")
    print("-------------------------------------------------------------------\n")

    print("Detalle de las operaciones:")
    for idx, r in df_t.iterrows():
        print(f"  Trade {idx+1:2d} | Tipo: {r['type']:13s} | Lado: {r['side']:16s} | NVDA: {r['pnl_nvda']:+.2f} | AMD: {r['pnl_amd']:+.2f} | Total: {r['pnl']:+.2f} USD")
    print()

if __name__ == '__main__':
    run()
