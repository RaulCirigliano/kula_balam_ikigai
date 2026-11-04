"""
Motor de simulación cuantitativa para Donchian Breakout 1H con Salida Dinámica por Canal Medio.
Deduce comisiones reales de Binance (0.15% round-trip).
"""
import os
import pandas as pd
import numpy as np
from indicators import agregar_indicadores_breakout
from strategy import generar_senales_breakout

def ejecutar_backtest_breakout_dinamico(
    df: pd.DataFrame,
    capital_inicial: float = 100.0,
    comision_pct: float = 0.00075
) -> dict:
    posicion_abierta = False
    precio_entrada = 0.0
    sl = 0.0
    tiempo_entrada = None

    historial_trades = []
    capital = capital_inicial

    for i in range(len(df)):
        fila = df.iloc[i]

        # 1. Apertura si no hay posición activa
        if not posicion_abierta:
            if fila['signal'] == 1:
                posicion_abierta = True
                precio_entrada = fila['close']
                sl = fila['sl_price']
                tiempo_entrada = fila['datetime']
                continue

        # 2. Evaluación de salida dinámica
        if posicion_abierta:
            salida_ejecutada = False
            precio_salida = 0.0
            motivo = ""

            # Prioridad 1: Corte de pérdida por Stop Loss inicial
            if fila['low'] <= sl:
                salida_ejecutada = True
                precio_salida = sl
                motivo = "SL"
            # Prioridad 2: Salida dinámica si el cierre horario cae bajo el canal medio
            elif fila['close'] < fila['donchian_mid']:
                salida_ejecutada = True
                precio_salida = fila['close']
                motivo = "MID_EXIT"

            if salida_ejecutada:
                retorno_bruto = (precio_salida - precio_entrada) / precio_entrada
                costo_comision = comision_pct * 2
                retorno_neto = retorno_bruto - costo_comision

                pnl_usd = capital * retorno_neto
                capital += pnl_usd

                historial_trades.append({
                    "entrada_tiempo": tiempo_entrada,
                    "salida_tiempo": fila['datetime'],
                    "precio_entrada": precio_entrada,
                    "precio_salida": precio_salida,
                    "motivo": motivo,
                    "retorno_neto_pct": retorno_neto * 100,
                    "pnl_usd": pnl_usd,
                    "capital_acumulado": capital
                })

                posicion_abierta = False

    df_trades = pd.DataFrame(historial_trades)

    if len(df_trades) > 0:
        trades_ganadores = df_trades[df_trades['pnl_usd'] > 0]
        trades_perdedores = df_trades[df_trades['pnl_usd'] <= 0]

        win_rate = (len(trades_ganadores) / len(df_trades)) * 100
        ganancia_bruta = trades_ganadores['pnl_usd'].sum()
        perdida_bruta = abs(trades_perdedores['pnl_usd'].sum())
        profit_factor = (ganancia_bruta / perdida_bruta) if perdida_bruta > 0 else np.nan

        df_trades['max_capital'] = df_trades['capital_acumulado'].cummax()
        df_trades['drawdown'] = (df_trades['capital_acumulado'] - df_trades['max_capital']) / df_trades['max_capital']
        max_drawdown = df_trades['drawdown'].min() * 100

        retorno_total_pct = ((capital - capital_inicial) / capital_inicial) * 100
    else:
        win_rate = 0.0
        profit_factor = 0.0
        max_drawdown = 0.0
        retorno_total_pct = 0.0

    return {
        "capital_final": capital,
        "retorno_total_pct": retorno_total_pct,
        "total_trades": len(df_trades),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "max_drawdown_pct": max_drawdown,
        "detalle_trades": df_trades
    }

if __name__ == "__main__":
    ruta_csv = os.path.join("data", "btc_usdt_1h.csv")
    if os.path.exists(ruta_csv):
        raw_df = pd.read_csv(ruta_csv)
        df_ind = agregar_indicadores_breakout(raw_df)
        df_strat = generar_senales_breakout(df_ind, mult_sl=1.5, max_ancho_atr=4.5, mult_vol=1.25)

        print("Ejecutando backtest cuantitativo: Donchian 1H (Salida Dinámica MID)...")
        resultados = ejecutar_backtest_breakout_dinamico(df_strat, capital_inicial=100.0)

        print("\n" + "="*45)
        print("  RESULTADOS: DONCHIAN 1H (SALIDA DINAMICA)")
        print("="*45)
        print(f"Capital Inicial:     $100.00 USD")
        print(f"Capital Final:       ${resultados['capital_final']:.2f} USD")
        print(f"Retorno Neto:        {resultados['retorno_total_pct']:.2f}%")
        print(f"Total Operaciones:   {resultados['total_trades']}")
        print(f"Tasa de Acierto:     {resultados['win_rate']:.2f}%")
        print(f"Profit Factor:       {resultados['profit_factor']:.2f}")
        print(f"Drawdown Maximo:     {resultados['max_drawdown_pct']:.2f}%")
        print("="*45)

        df_t = resultados['detalle_trades']
        if len(df_t) > 0:
            print("\nDistribución por motivo de salida:")
            print(df_t['motivo'].value_counts())
            print("\nÚltimos 5 trades ejecutados:")
            cols = ['salida_tiempo', 'motivo', 'retorno_neto_pct', 'pnl_usd', 'capital_acumulado']
            print(df_t[cols].tail())
    else:
        print("No se encontró data/btc_usdt_1h.csv")