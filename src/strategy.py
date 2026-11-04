"""
Módulo de generación de señales para Donchian Breakout 1H (Variante 3.2 - Salida Dinámica).
Entrada: Ruptura de máximo + Tendencia (EMA 100) + Volumen + Compresión.
Salida: Stop Loss inicial (1.5x ATR) y salida tendencial dinámica al perder donchian_mid.
"""
import pandas as pd
import numpy as np

def generar_senales_breakout(
    df: pd.DataFrame,
    mult_sl: float = 1.5,
    max_ancho_atr: float = 4.5,
    mult_vol: float = 1.25
) -> pd.DataFrame:
    df = df.copy()

    # Condiciones de entrada
    quiebre_maximo = df['close'] > df['donchian_high']
    tendencia_alcista = df['close'] > df['ema_100']
    canal_comprimido = df['donchian_width'] <= (max_ancho_atr * df['atr_14'])
    volumen_fuerte = df['volume'] > (df['vol_ma20'] * mult_vol)

    condicion_long = quiebre_maximo & tendencia_alcista & canal_comprimido & volumen_fuerte
    df['signal'] = np.where(condicion_long, 1, 0)

    # Stop Loss inicial como red de seguridad
    df['sl_price'] = np.where(df['signal'] == 1, df['close'] - (mult_sl * df['atr_14']), np.nan)

    return df

if __name__ == "__main__":
    import os
    from indicators import agregar_indicadores_breakout

    ruta_csv = os.path.join("data", "btc_usdt_1h.csv")
    if os.path.exists(ruta_csv):
        raw_df = pd.read_csv(ruta_csv)
        df_ind = agregar_indicadores_breakout(raw_df)
        df_strat = generar_senales_breakout(df_ind)
        print(f"Total de señales generadas: {(df_strat['signal'] == 1).sum()}")