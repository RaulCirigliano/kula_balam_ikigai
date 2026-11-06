"""
Auditoría offline: Donchian 1H con TP fijo (Control) vs salida tendencial pura sin techo (Experimental).

Base común (señal de entrada sin cambios): Donchian 20 shift(1), EMA100, compresión <= 4.5*ATR, volumen > 1.25*SMA20.
Entrada al cierre de la vela de señal. Una posición a la vez.
SL inicial = max(1.0%, 1.5*ATR%) del precio de entrada (misma regla del módulo de estrategia).
TP de control = max(3*ATR%, TP bruto requerido para R:R neto 2.0 con fee 0.10% + spread 0.05%),
    que es la misma derivación del daemon (≈ +2.91% con SL 1.0%).
Breakeven desacoplado: al tocar +1.00% bruto el stop sube al cerrojo de +0.80% bruto (comportamiento del daemon).
Control: salidas SL / BE / TP / MID_EXIT (sin trailing).
Experimental: sin TP; tras armar el BE rige un Trailing Stop = máx(cerrojo +0.80%, pico - max(1.5%, SL%)).
    [Inferencia] La distancia de trailing (máx(1.5%, SL%)) replica el "modo holgado" base del daemon;
    el daemon real la comprime según RSI/avance, lo que no se modela aquí.
MID_EXIT: cierre horario < donchian_mid, en ambas variantes.
Orden intravela conservador: primero el stop vigente al inicio de la vela, luego TP, luego MID_EXIT al cierre;
el armado de BE/trailing con el máximo de la vela rige desde la vela siguiente.
Costos: 0.15% round-trip plano. Nocional = min(balance, 100 USD), sin componer posiciones sobre 100.
"""
import os
import sys

import numpy as np
import pandas as pd

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "src"))
from indicators import agregar_indicadores_breakout  # noqa: E402
from strategy import generar_senales_breakout  # noqa: E402
from legado.quant_risk import required_tp_gross_for_rr  # noqa: E402

CAPITAL_INICIAL = 100.0
NOCIONAL_MAX = 100.0
COMISION_RT = 0.0015
BE_TRIGGER = 0.0100
BE_LOCK = 0.0080
SL_MIN_PCT = 1.0
TRAIL_MIN_PCT = 1.5


def backtest(df: pd.DataFrame, con_tp: bool) -> dict:
    df = df.reset_index(drop=True)
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    sig, mid, atr = df["signal"].values, df["donchian_mid"].values, df["atr_14"].values

    balance = CAPITAL_INICIAL
    trades, pos = [], None

    for i in range(len(df)):
        if pos is not None:
            motivo = salida = None
            if l[i] <= pos["stop"]:
                salida = pos["stop"]
                if not pos["armado"]:
                    motivo = "SL"
                elif pos["stop"] > pos["entrada"] * (1 + BE_LOCK) * (1 + 1e-12):
                    motivo = "TRAILING"
                else:
                    motivo = "BE"
            elif con_tp and h[i] >= pos["tp"]:
                motivo, salida = "TP", pos["tp"]
            elif c[i] < mid[i]:
                motivo, salida = "MID_EXIT", c[i]

            if motivo:
                neto = salida / pos["entrada"] - 1.0 - COMISION_RT
                pnl = pos["notional"] * neto
                balance += pnl
                trades.append({"motivo": motivo, "pnl": pnl, "balance": balance, "ret": neto * 100,
                               "sl": pos["sl_pct"], "tp": pos["tp_pct"]})
                pos = None
            else:
                pos["pico"] = max(pos["pico"], h[i])
                if not pos["armado"] and h[i] >= pos["entrada"] * (1 + BE_TRIGGER):
                    pos["armado"] = True
                if pos["armado"]:
                    nuevo = pos["entrada"] * (1 + BE_LOCK)
                    if not con_tp:
                        nuevo = max(nuevo, pos["pico"] * (1 - max(TRAIL_MIN_PCT, pos["sl_pct"]) / 100.0))
                    pos["stop"] = max(pos["stop"], nuevo)
            continue

        if sig[i] == 1 and not np.isnan(atr[i]):
            entrada = c[i]
            atr_pct = atr[i] / entrada * 100.0
            sl_pct = max(SL_MIN_PCT, 1.5 * atr_pct)
            tp_pct = max(3.0 * atr_pct, required_tp_gross_for_rr(sl_pct, 0.10, 0.05, 2.0))
            pos = {"entrada": entrada, "stop": entrada * (1 - sl_pct / 100.0), "tp": entrada * (1 + tp_pct / 100.0),
                   "sl_pct": sl_pct, "tp_pct": tp_pct, "armado": False, "pico": entrada,
                   "notional": min(balance, NOCIONAL_MAX)}

    t = pd.DataFrame(trades)
    if t.empty:
        return {"n": 0, "wr": 0, "pf": 0, "pnl": 0, "dd": 0, "mot": {}, "ret_ganador": 0, "ret_perdedor": 0, "sl": 0, "tp": 0}
    gan, per = t.loc[t.pnl > 0, "pnl"].sum(), abs(t.loc[t.pnl <= 0, "pnl"].sum())
    eq = pd.concat([pd.Series([CAPITAL_INICIAL]), t["balance"]], ignore_index=True)
    return {"n": len(t), "wr": (t.pnl > 0).mean() * 100, "pf": gan / per if per > 0 else float("inf"),
            "pnl": balance - CAPITAL_INICIAL, "dd": ((eq - eq.cummax()) / eq.cummax()).min() * 100,
            "mot": t["motivo"].value_counts().to_dict(),
            "ret_ganador": t.loc[t.pnl > 0, "ret"].mean() if (t.pnl > 0).any() else 0.0,
            "ret_perdedor": t.loc[t.pnl <= 0, "ret"].mean() if (t.pnl <= 0).any() else 0.0,
            "sl": t["sl"].mean(), "tp": t["tp"].mean()}


def main():
    filas = []
    for sym, f in (("BTC/USDT", "btc_usdt_1h.csv"), ("ETH/USDT", "eth_usdt_1h.csv")):
        raw = pd.read_csv(os.path.join(RAIZ, "data", f))
        df = generar_senales_breakout(agregar_indicadores_breakout(raw), mult_sl=1.5, max_ancho_atr=4.5, mult_vol=1.25)
        for nombre, con_tp in (("Control: TP fijo", True), ("Experimental: sin techo", False)):
            r = backtest(df, con_tp)
            m = r["mot"]
            filas.append({"Activo": sym, "Variante": nombre, "N": r["n"], "Win Rate": f"{r['wr']:.1f}%",
                          "PF": f"{r['pf']:.2f}", "PnL USD": f"{r['pnl']:+.2f}", "Max DD": f"{r['dd']:.2f}%",
                          "SL": m.get("SL", 0), "BE": m.get("BE", 0), "TP": m.get("TP", 0),
                          "MID": m.get("MID_EXIT", 0), "TRAIL": m.get("TRAILING", 0),
                          "Ret gan.": f"{r['ret_ganador']:+.2f}%", "Ret perd.": f"{r['ret_perdedor']:+.2f}%",
                          "SL% prom": f"{r['sl']:.2f}", "TP% prom": f"{r['tp']:.2f}"})
    print("\n" + pd.DataFrame(filas).to_string(index=False) + "\n")


if __name__ == "__main__":
    main()
