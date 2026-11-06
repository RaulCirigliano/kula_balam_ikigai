"""
Backtest de la regla candidata: Retroceso Fibo (0.50-0.707) + BOS de 3 velas cerradas, 1H.
Criterio PASA / NO PASA: Profit Factor >= 1.0 (la regla se descarta si PF < 1.0).

Regla (LONG únicamente):
- Swing previo: ventana de 30 velas cerradas que termina justo antes de V1.
  Impulso alcista válido si el mínimo del swing ocurre antes que el máximo.
- Zona Dorada: cierre de V2 con retroceso en [0.50, 0.707] del rango del swing medido desde el máximo.
- V1 (freno): vela roja (close < open).
- V2 (absorción): mecha inferior >= 25% del rango de la vela.
- V3 (BOS): vela verde cerrada con close > High de V2. Entrada al cierre de V3.
- SL = Swing Low - 0.5 * ATR(14). TP = entrada + 2.0 * (entrada - SL).
- Si SL y TP caen dentro de la misma vela se asume SL primero (criterio conservador).
- Comisión round-trip 0.15%. Riesgo objetivo 1 USD/trade; nocional topado a min(balance, 100 USD).
- Una posición a la vez. Sin Breakeven (la distancia a TP no lo justifica).
"""
import os
import numpy as np
import pandas as pd

CAPITAL_INICIAL = 100.0
RIESGO_USD = 1.0
NOCIONAL_MAX = 100.0
COMISION_RT = 0.0015  # 0.15% round-trip
VENTANA_SWING = 30
FIBO_MIN, FIBO_MAX = 0.50, 0.707
MULT_ATR_SL = 0.5
RR = 2.0
WICK_MIN_V2 = 0.25


def calcular_atr(df: pd.DataFrame, periodo: int = 14) -> pd.Series:
    cp = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - cp).abs(), (df["low"] - cp).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / periodo, adjust=False).mean()


def backtest(df: pd.DataFrame) -> dict:
    df = df.reset_index(drop=True).copy()
    df["atr"] = calcular_atr(df)
    o, h, l, c, atr = (df[k].values for k in ("open", "high", "low", "close", "atr"))

    balance = CAPITAL_INICIAL
    trades = []
    pos = None

    for i in range(VENTANA_SWING + 3, len(df)):
        # Gestión de posición abierta
        if pos is not None:
            sl_hit = l[i] <= pos["sl"]
            tp_hit = h[i] >= pos["tp"]
            if sl_hit or tp_hit:
                salida = pos["sl"] if sl_hit else pos["tp"]
                bruto = salida / pos["entrada"] - 1.0
                neto = bruto - COMISION_RT
                pnl = pos["notional"] * neto
                balance += pnl
                trades.append({"motivo": "SL" if sl_hit else "TP", "pnl": pnl, "balance": balance,
                               "notional": pos["notional"], "sl_pct": pos["sl_pct"]})
                pos = None
            continue

        v1, v2, v3 = i - 2, i - 1, i
        w0, w1 = v1 - VENTANA_SWING, v1  # 30 velas que terminan antes de V1
        ventana_h = h[w0:w1]
        ventana_l = l[w0:w1]
        sh_idx, sl_idx = int(np.argmax(ventana_h)), int(np.argmin(ventana_l))
        if sl_idx >= sh_idx:
            continue  # sin impulso alcista previo
        swing_high, swing_low = ventana_h[sh_idx], ventana_l[sl_idx]
        rango = swing_high - swing_low
        if rango <= 0 or np.isnan(atr[v3]):
            continue

        retro = (swing_high - c[v2]) / rango
        if not (FIBO_MIN <= retro <= FIBO_MAX):
            continue
        if not (c[v1] < o[v1]):
            continue  # V1 freno
        rng_v2 = h[v2] - l[v2]
        if rng_v2 <= 0 or (min(o[v2], c[v2]) - l[v2]) / rng_v2 < WICK_MIN_V2:
            continue  # V2 absorción
        if not (c[v3] > o[v3] and c[v3] > h[v2]):
            continue  # V3 BOS

        entrada = c[v3]
        sl = swing_low - MULT_ATR_SL * atr[v3]
        if sl >= entrada:
            continue
        dist = entrada - sl
        sl_pct = dist / entrada
        notional = min(RIESGO_USD / sl_pct, balance, NOCIONAL_MAX)
        pos = {"entrada": entrada, "sl": sl, "tp": entrada + RR * dist, "notional": notional, "sl_pct": sl_pct * 100}

    t = pd.DataFrame(trades)
    if t.empty:
        return {"trades": 0, "wr": 0.0, "pf": 0.0, "pnl": 0.0, "dd": 0.0, "notional_prom": 0.0, "sl_prom": 0.0}
    gan, per = t.loc[t.pnl > 0, "pnl"].sum(), abs(t.loc[t.pnl <= 0, "pnl"].sum())
    eq = pd.concat([pd.Series([CAPITAL_INICIAL]), t["balance"]], ignore_index=True)
    dd = ((eq - eq.cummax()) / eq.cummax()).min() * 100
    return {"trades": len(t), "wr": (t.pnl > 0).mean() * 100, "pf": gan / per if per > 0 else float("inf"),
            "pnl": balance - CAPITAL_INICIAL, "dd": dd, "notional_prom": t.notional.mean(), "sl_prom": t.sl_pct.mean(),
            "tp": int((t.motivo == "TP").sum()), "sl": int((t.motivo == "SL").sum())}


def main():
    filas = []
    for sym, f in (("BTC/USDT", "btc_usdt_1h.csv"), ("ETH/USDT", "eth_usdt_1h.csv")):
        r = backtest(pd.read_csv(os.path.join("data", f)))
        filas.append({"Activo": sym, "Trades": r["trades"], "TP/SL": f"{r.get('tp', 0)}/{r.get('sl', 0)}",
                      "Win Rate": f"{r['wr']:.1f}%", "Profit Factor": f"{r['pf']:.2f}",
                      "PnL Neto USD": f"{r['pnl']:+.2f}", "Max DD": f"{r['dd']:.2f}%",
                      "Nocional prom.": f"{r['notional_prom']:.1f}", "SL prom.": f"{r['sl_prom']:.2f}%",
                      "Veredicto": "PASA" if r["pf"] >= 1.0 and r["trades"] > 0 else "DESCARTADA"})
    print("\n" + pd.DataFrame(filas).to_string(index=False) + "\n")


if __name__ == "__main__":
    main()
