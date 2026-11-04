"""
Módulo de cálculo de indicadores técnicos puros y vectorizados.
Soporta Donchian, ATR, EMA y Media Móvil de Volumen.
"""
import pandas as pd
import numpy as np

def calcular_ema(series: pd.Series, periodo: int) -> pd.Series:
    return series.ewm(span=periodo, adjust=False).mean()

def calcular_atr(df: pd.DataFrame, periodo: int = 14) -> pd.Series:
    high = df['high']
    low = df['low']
    close_prev = df['close'].shift(1)

    tr1 = high - low
    tr2 = (high - close_prev).abs()
    tr3 = (low - close_prev).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/periodo, adjust=False).mean()
    return atr

def calcular_donchian(df: pd.DataFrame, periodo: int = 20) -> pd.DataFrame:
    df = df.copy()
    df['donchian_high'] = df['high'].shift(1).rolling(window=periodo).max()
    df['donchian_low'] = df['low'].shift(1).rolling(window=periodo).min()
    df['donchian_mid'] = (df['donchian_high'] + df['donchian_low']) / 2.0
    df['donchian_width'] = df['donchian_high'] - df['donchian_low']
    return df

def agregar_indicadores_breakout(df: pd.DataFrame, periodo_donchian: int = 20) -> pd.DataFrame:
    df = df.copy()
    df['atr_14'] = calcular_atr(df, 14)
    df = calcular_donchian(df, periodo=periodo_donchian)
    df['ema_100'] = calcular_ema(df['close'], 100)
    df['vol_ma20'] = df['volume'].rolling(window=20).mean()
    return df

if __name__ == "__main__":
    import os
    ruta_csv = os.path.join("data", "btc_usdt_1h.csv")
    if os.path.exists(ruta_csv):
        raw = pd.read_csv(ruta_csv)
        res = agregar_indicadores_breakout(raw)
        print("Indicadores Donchian + Volumen calculados con éxito:")
        print(res[['datetime', 'close', 'donchian_high', 'volume', 'vol_ma20', 'atr_14']].tail())
    else:
        print("No se encontró data/btc_usdt_1h.csv")