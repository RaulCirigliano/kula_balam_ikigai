"""
Módulo de generación de señales para Reversión a la Media + ATR (1H).
Lógica pura extraída de legado/estrategias/mean_reversion_atr.py.

Camino 1: Pullback saludable en tendencia alcista (Close > EMA 200, Z-Score en [-1.5, -0.5] con absorción).
Camino 2: Rebote de pánico / capitulación extrema (Z-Score <= -2.0 con mecha inferior de absorción >= 25%).
Salida dinámica: Reversión al equilibrio (Close >= SMA 20) o Stop Loss inicial (1.5x ATR).
"""
import pandas as pd
import numpy as np


def generar_senales_reversion(
    df: pd.DataFrame,
    z_panico: float = -2.0,
    z_pullback_min: float = -1.5,
    z_pullback_max: float = -0.5,
    wick_min_panico: float = 0.25,
    wick_min_pullback: float = 0.20,
    mult_sl: float = 1.5,
    mult_tp: float = 3.0,
) -> pd.DataFrame:
    df = df.copy()

    # 1. Camino A: Pullback en Tendencia Alcista
    cond_tendencia = df['close'] > df['ema_200']
    cond_pullback_z = (df['z_score'] >= z_pullback_min) & (df['z_score'] <= z_pullback_max)
    cond_mecha_pullback = df['lower_wick_ratio'] >= wick_min_pullback
    camino_pullback = cond_tendencia & cond_pullback_z & cond_mecha_pullback

    # 2. Camino B: Rebote por Pánico Extremo / Capitulación
    cond_panico_z = df['z_score'] <= z_panico
    cond_mecha_panico = df['lower_wick_ratio'] >= wick_min_panico
    cond_vol_absorcion = df['volume'] > (df['vol_ma20'] * 0.80)
    camino_panico = cond_panico_z & cond_mecha_panico & cond_vol_absorcion

    # Disparo de Compra
    senal_compra = camino_pullback | camino_panico
    df['signal'] = np.where(senal_compra, 1, 0)
    df['camino'] = np.where(camino_pullback, "PULLBACK", np.where(camino_panico, "PANICO", "NINGUNO"))

    # Stop Loss y Take Profit iniciales
    df['sl_price'] = np.where(df['signal'] == 1, df['close'] - (mult_sl * df['atr_14']), np.nan)
    df['tp_price'] = np.where(df['signal'] == 1, df['close'] + (mult_tp * df['atr_14']), np.nan)

    return df
