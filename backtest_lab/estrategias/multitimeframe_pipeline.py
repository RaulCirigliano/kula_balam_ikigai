import time
from typing import Dict, Tuple
import ccxt
import pandas as pd


class MultiTimeframePipeline:

  def __init__(self, symbol: str = "BTC/USDT"):
    self.symbol = symbol
    self.exchange = ccxt.binance({
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })

  def fetch_candles(
      self, timeframe: str, limit: int = 100
  ) -> pd.DataFrame:
    raw = self.exchange.fetch_ohlcv(self.symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(
        raw, columns=["timestamp", "open", "high", "low", "close", "volume"]
    )
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("datetime", inplace=True)
    return df

  @staticmethod
  def calc_ema(series: pd.Series, span: int = 50) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()

  def evaluate_macro_1d(self, df_1d: pd.DataFrame) -> Tuple[bool, str]:
    closed = df_1d.iloc[-2]
    ema_50 = self.calc_ema(df_1d["close"], 50).iloc[-2]
    is_bullish = closed["close"] > ema_50
    bias = "LONG" if is_bullish else "SHORT"
    return is_bullish, bias

  def evaluate_zone_1h(
      self, df_1h: pd.DataFrame, bias: str
  ) -> Tuple[bool, Dict[str, float]]:
    swing_window = df_1h.iloc[-49:-1]
    swing_high = float(swing_window["high"].max())
    swing_low = float(swing_window["low"].min())
    swing_range = max(0.0001, swing_high - swing_low)
    last_closed_1h = df_1h.iloc[-2]["close"]

    levels = {"high": swing_high, "low": swing_low}
    if bias == "LONG":
      retracement = (swing_high - last_closed_1h) / swing_range
      in_zone = 0.50 <= retracement <= 0.75
    else:
      retracement = (last_closed_1h - swing_low) / swing_range
      in_zone = 0.50 <= retracement <= 0.75

    levels["retracement"] = round(retracement, 3)
    return in_zone, levels

  def evaluate_trigger_5m(self, df_5m: pd.DataFrame, bias: str) -> bool:
    if len(df_5m) < 4:
      return False
    v2 = df_5m.iloc[-3]
    v3 = df_5m.iloc[-2]
    if bias == "LONG":
      return float(v3["close"]) > float(v2["high"])
    else:
      return float(v3["close"]) < float(v2["low"])

  def run_cycle(self):
    try:
      df_1d = self.fetch_candles("1d", limit=60)
      df_1h = self.fetch_candles("1h", limit=80)
      df_5m = self.fetch_candles("5m", limit=30)

      macro_ok, bias = self.evaluate_macro_1d(df_1d)
      print(f"[{self.symbol}] 1D Macro: {bias} (Cierre > EMA50: {macro_ok})")

      if not macro_ok and bias == "LONG":
        print("  └─► Veto 1D: Mercado bajista estructural. Esperando.")
        return

      in_zone, levels = self.evaluate_zone_1h(df_1h, bias)
      print(
          f"  └─► 1H Fibo: Retroceso {levels['retracement']} | En Zona Dorada:"
          f" {in_zone}"
      )

      if not in_zone:
        print("      └─► Fuera de zona de valor (0.50-0.75). No se opera.")
        return

      triggered = self.evaluate_trigger_5m(df_5m, bias)
      print(f"      └─► 5M Gatillo 3 Velas: {triggered}")

      if triggered:
        entry_price = df_5m.iloc[-2]["close"]
        sl_price = min(df_5m.iloc[-3]["low"], df_5m.iloc[-2]["low"])
        risk_pct = ((entry_price - sl_price) / entry_price) * 100
        print("\n" + "=" * 50)
        print(f"🔥 SEÑAL EJECUTABLE {bias} CONFIRMADA")
        print(f"Precio Entrada: {entry_price:.2f}")
        print(f"Stop Loss 5M: {sl_price:.2f} (Riesgo: {risk_pct:.2f}%)")
        print("=" * 50 + "\n")

    except Exception as e:
      print(f"Error en ciclo: {e}")


if __name__ == "__main__":
  pipeline = MultiTimeframePipeline("BTC/USDT")
  print("Ejecutando prueba de lectura multitemporal...")
  pipeline.run_cycle()
