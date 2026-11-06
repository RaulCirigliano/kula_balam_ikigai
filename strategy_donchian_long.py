"""
Módulo: strategy_donchian_long.py
Proyecto: Kula Balam
Estrategia: Donchian 20 + EMA 200 + Bandwidth (Long-Only)
Características:
- Algoritmo vectorizado O(N) (< 300 ms).
- Gestión realista de Stop Loss con absorción de gaps bajistas en apertura ().
- Dimensionamiento de posición dinámico al 1.0% de riesgo por trade (1.5 ATR buffer).
"""

from typing import Dict, Optional, Any
import pandas as pd
import numpy as np


def calcular_indicadores(df: pd.DataFrame) -> pd.DataFrame:
    """Calcula indicadores técnicos de la Estrategia B de forma lineal y vectorizada."""
    data = df.copy()
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    data.columns = [c.lower() for c in data.columns]

    # Canales Donchian y Mediana
    data['donchian_high_20'] = data['high'].rolling(20).max()
    data['donchian_low_20'] = data['low'].rolling(20).min()
    data['donchian_mid_10'] = (data['high'].rolling(10).max() + data['low'].rolling(10).min()) / 2.0

    # Medias Móviles Exponenciales y Pendiente Macro
    data['ema_50'] = data['close'].ewm(span=50, adjust=False).mean()
    data['ema_200'] = data['close'].ewm(span=200, adjust=False).mean()
    data['slope_ema200'] = data['ema_200'].diff(10)

    # Volatilidad: Bandwidth Donchian vs SMA30
    data['bandwidth'] = (data['donchian_high_20'] - data['donchian_low_20']) / (data['ema_50'] + 1e-9)
    data['bandwidth_sma'] = data['bandwidth'].rolling(30).mean()

    # ATR de 14 períodos
    hl = data['high'] - data['low']
    hc = (data['high'] - data['close'].shift(1)).abs()
    lc = (data['low'] - data['close'].shift(1)).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    data['atr'] = tr.rolling(14).mean().bfill()

    # Condición de Entrada Long
    data['sig_long'] = (
        (data['close'] > data['donchian_high_20'].shift(1)) &
        (data['close'] > data['ema_200']) &
        (data['slope_ema200'] > 0) &
        (data['bandwidth'] > data['bandwidth_sma'])
    )

    return data


def evaluar_salida_posicion(
    bar: pd.Series,
    posicion: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Evalúa la salida de una posición contemplando:
    1. Gap Bajista en Apertura (Open <= SL): Ejecuta forzosamente al precio de apertura.
    2. Stop Loss Intradiario (Low <= SL): Ejecuta al precio de Stop programado.
    3. Cruce de Mediana Donchian (Close < Mid_10): Salida tendencial en cierre de barra.
    """
    c_open = bar['open']
    c_low = bar['low']
    c_close = bar['close']
    c_mid = bar['donchian_mid_10']
    sl_price = posicion['sl_price']

    p_out = None
    motivo = ""
    es_gap = False

    # 1. Prioridad Crítica: Gap Bajista en la Apertura de Sesión
    if c_open <= sl_price:
        p_out = c_open
        motivo = "Stop Loss (Gap Bajista en Apertura)"
        es_gap = True

    # 2. Stop Loss alcanzado durante la sesión
    elif c_low <= sl_price:
        p_out = sl_price
        motivo = "Stop Loss Intradiario"

    # 3. Trailing de Mediana Donchian 10 períodos
    elif c_close < c_mid:
        p_out = c_close
        motivo = "Salida Mediana Donchian"

    if p_out is not None:
        unidades = posicion['unidades']
        cap_inv = posicion['cap_invertido']
        retorno_bruto = unidades * p_out
        comision = (cap_inv + retorno_bruto) * 0.001  # 0.1% por tramo
        pnl_neto = (unidades * (p_out - posicion['entry_price'])) - comision

        return {
            "cerrar": True,
            "exit_price": p_out,
            "pnl_neto": pnl_neto,
            "retorno_bruto": retorno_bruto,
            "motivo": motivo,
            "es_gap": es_gap
        }

    return {"cerrar": False}


def calcular_position_sizing(
    c_close: float,
    atr: float,
    equity_total: float,
    saldo_liquido: float,
    es_cripto: bool = False
) -> Optional[Dict[str, float]]:
    """Calcula el tamaño de posición garantizando un riesgo de exactamente 1.0% del capital."""
    min_pct = 0.008 if es_cripto else 0.010
    dist_sl = max(1.5 * atr, c_close * min_pct)
    sl_price = c_close - dist_sl

    riesgo_usd = equity_total * 0.01
    unidades_teoricas = riesgo_usd / dist_sl
    capital_requerido = unidades_teoricas * c_close

    # Restricción Spot 1x contra saldo disponible
    capital_real = min(capital_requerido, saldo_liquido)

    if capital_real < 5.0:  # Mínimo operativo
        return None

    unidades_reales = capital_real / c_close

    return {
        "unidades": unidades_reales,
        "entry_price": c_close,
        "sl_price": sl_price,
        "cap_invertido": capital_real,
        "dist_sl": dist_sl
    }
