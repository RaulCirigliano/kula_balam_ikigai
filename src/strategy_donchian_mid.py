"""
Estrategia Cuantitativa Validada: Donchian Breakout con Salida Estructural Pura (MID_EXIT).
Aplica sobre velas cerradas con shift(1) estricto para evitar sesgo del futuro y repainting.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple
import numpy as np
import pandas as pd


def calcular_indicadores_donchian_mid(
    df: pd.DataFrame,
    donchian_period: int = 20,
    ema_period: int = 200,
) -> pd.DataFrame:
    """
    Calcula Donchian Channels y EMA 200 sobre velas cerradas previas con shift(1) estricto:
    - donchian_high = high.shift(1).rolling(20).max()
    - donchian_low  = low.shift(1).rolling(20).min()
    - donchian_mid  = (donchian_high + donchian_low) / 2.0
    - ema200        = close.shift(1).ewm(span=200, adjust=False).mean()
    """
    df = df.copy()

    # Normalizar nombres de columnas a minúsculas
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0].lower() for col in df.columns]
    else:
        df.columns = [col.lower() for col in df.columns]

    for col in ("open", "high", "low", "close"):
        if col not in df.columns:
            raise ValueError(f"Columna requerida '{col}' no encontrada en el DataFrame")

    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)

    # 1. Donchian con shift(1)
    df["donchian_high"] = high.shift(1).rolling(window=donchian_period).max()
    df["donchian_low"] = low.shift(1).rolling(window=donchian_period).min()
    df["donchian_mid"] = (df["donchian_high"] + df["donchian_low"]) / 2.0
    df["donchian_width"] = df["donchian_high"] - df["donchian_low"]

    # 2. EMA 200 con shift(1) para garantizar cero sesgo del futuro
    df["ema200"] = close.shift(1).ewm(span=ema_period, adjust=False).mean()

    return df


def evaluar_senal_vela(
    row: pd.Series,
    in_position: bool,
    entry_price: Optional[float] = None,
    initial_sl: Optional[float] = None,
) -> Tuple[str, Optional[float], str]:
    """
    Evalúa la señal en una vela cerrada:
    Retorna: (accion, precio_estimado, motivo)
      - accion: 'BUY', 'EXIT_SL', 'EXIT_GAP_SL', 'EXIT_MID', 'HOLD'

    Reglas:
    1. Entrada Long:
       Si no in_position: BUY cuando close > donchian_high Y close > ema200.
    2. Salida:
       - Stop Loss de Emergencia (-1.5%):
         Si open <= initial_sl: EXIT_GAP_SL a precio open.
         Elif low <= initial_sl: EXIT_SL a precio initial_sl.
       - Salida Estructural Pura (MID_EXIT):
         Elif close < donchian_mid: EXIT_MID a precio close.
       - Sin Take Profit fijo ni Trailing Stop rígido.
    """
    close_p = float(row["close"])
    open_p = float(row.get("open", close_p))
    low_p = float(row.get("low", close_p))
    high_p = float(row.get("high", close_p))
    upper = float(row["donchian_high"]) if pd.notna(row.get("donchian_high")) else None
    mid = float(row["donchian_mid"]) if pd.notna(row.get("donchian_mid")) else None
    ema = float(row["ema200"]) if pd.notna(row.get("ema200")) else None

    # Indicadores incompletos (período de calentamiento)
    if upper is None or mid is None or ema is None:
        return "HOLD", None, "Periodo de calentamiento insuficiente (< 200 velas)"

    # --- 1. GESTIÓN DE POSICIÓN ABIERTA (SALIDA) ---
    if in_position:
        if entry_price is None or entry_price <= 0:
            return "HOLD", None, "Posición marcada pero sin entry_price válido"

        calculated_sl = initial_sl if (initial_sl and initial_sl > 0) else (entry_price * 0.985)

        # A) Cisne negro / Gap bajista en apertura
        if open_p <= calculated_sl:
            return "EXIT_GAP_SL", open_p, f"SL de Emergencia perforado en Open (${open_p:.4f} <= ${calculated_sl:.4f})"

        # B) Stop Loss de emergencia tocado intradía (-1.5%)
        if low_p <= calculated_sl:
            return "EXIT_SL", calculated_sl, f"SL de Emergencia tocado en Low (${low_p:.4f} <= ${calculated_sl:.4f})"

        # C) Salida Estructural Pura: Vela cerrada por debajo de Donchian Mid
        if close_p < mid:
            return "EXIT_MID", close_p, f"Salida Estructural MID_EXIT: Cierre (${close_p:.4f}) < Donchian Mid (${mid:.4f})"

        return "HOLD", None, f"Mantener posición activa: Cierre (${close_p:.4f}) >= Mid (${mid:.4f})"

    # --- 2. BÚSQUEDA DE ENTRADA LONG ---
    if close_p > upper and close_p > ema:
        return (
            "BUY",
            close_p,
            f"Ruptura Donchian (${close_p:.4f} > ${upper:.4f}) alineada sobre EMA 200 (${ema:.4f})",
        )

    return (
        "HOLD",
        None,
        f"Sin confluencia Long: Close=${close_p:.4f}, Upper=${upper:.4f}, EMA200=${ema:.4f}",
    )
