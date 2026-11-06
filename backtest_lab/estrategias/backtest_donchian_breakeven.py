"""
Backtest comparativo de gestión de Breakeven para Donchian Breakout 1H (BTC y ETH).

Entrada/salida base (sin modificar): señal de generar_senales_breakout (Donchian 20 shift(1), EMA100,
compresión <= 4.5 ATR, volumen > 1.25 SMA20), SL inicial = 1.5*ATR, salida dinámica MID_EXIT
(cierre horario < donchian_mid).

Variantes:
  A: sin Breakeven.
  B: Breakeven armado cuando el máximo alcanza +0.40% bruto.
  C: Breakeven armado cuando el máximo alcanza +1.00% bruto.
Al armarse, el stop sube a entrada * (1 + 0.20%) (cubre 0.15% de costos + 0.05% neto), como en el daemon.
Orden intravela conservador: primero se evalúa el stop vigente al inicio de la vela; el armado del BE
se aplica con el máximo de esa vela y rige desde la vela siguiente.
Costos: 0.15% round-trip. Nocional = min(balance, 100 USD), posición única, sin apalancamiento.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from indicators import agregar_indicadores_breakout  # noqa: E402
from strategy import generar_senales_breakout  # noqa: E402

CAPITAL_INICIAL = 100.0
NOCIONAL_MAX = 100.0
COMISION_RT = 0.0015
BE_STOP_PCT = 0.0020


def backtest(df: pd.DataFrame, be_trigger: float | None) -> dict:
    df = df.reset_index(drop=True)
    o, h, l, c = (df[k].values for k in ("open", "high", "low", "close"))
    sig, sl_arr, mid = df["signal"].values, df["sl_price"].values, df["donchian_mid"].values

    balance = CAPITAL_INICIAL
    trades = []
    pos = None

    for i in range(len(df)):
        if pos is not None:
            motivo, salida = None, None
            if l[i] <= pos["stop"]:
                motivo = "BE" if pos["be"] else "SL"
                salida = pos["stop"]
            elif c[i] < mid[i]:
                motivo, salida = "MID_EXIT", c[i]
            if motivo:
                neto = salida / pos["entrada"] - 1.0 - COMISION_RT
                pnl = pos["notional"] * neto
                balance += pnl
                trades.append({"motivo": motivo, "pnl": pnl, "balance": balance})
                pos = None
            elif be_trigger is not None and not pos["be"] and h[i] >= pos["entrada"] * (1 + be_trigger):
                pos["be"] = True
                pos["stop"] = max(pos["stop"], pos["entrada"] * (1 + BE_STOP_PCT))
            continue

        if sig[i] == 1 and not np.isnan(sl_arr[i]):
            pos = {"entrada": c[i], "stop": sl_arr[i], "be": False, "notional": min(balance, NOCIONAL_MAX)}

    t = pd.DataFrame(trades)
    if t.empty:
        return {"trades": 0, "wr": 0.0, "pf": 0.0, "pnl": 0.0, "dd": 0.0, "motivos": ""}
    gan, per = t.loc[t.pnl > 0, "pnl"].sum(), abs(t.loc[t.pnl <= 0, "pnl"].sum())
    eq = pd.concat([pd.Series([CAPITAL_INICIAL]), t["balance"]], ignore_index=True)
    dd = ((eq - eq.cummax()) / eq.cummax()).min() * 100
    mot = t["motivo"].value_counts()
    return {"trades": len(t), "wr": (t.pnl > 0).mean() * 100, "pf": gan / per if per > 0 else float("inf"),
            "pnl": balance - CAPITAL_INICIAL, "dd": dd,
            "motivos": " ".join(f"{k}:{v}" for k, v in mot.items())}


def main():
    variantes = [("A: sin Breakeven", None), ("B: BE +0.40%", 0.0040), ("C: BE +1.00%", 0.0100)]
    filas = []
    for sym, f in (("BTC/USDT", "btc_usdt_1h.csv"), ("ETH/USDT", "eth_usdt_1h.csv")):
        raw = pd.read_csv(os.path.join("data", f))
        df = generar_senales_breakout(agregar_indicadores_breakout(raw), mult_sl=1.5, max_ancho_atr=4.5, mult_vol=1.25)
        for nombre, trig in variantes:
            r = backtest(df, trig)
            filas.append({"Activo": sym, "Variante": nombre, "Trades": r["trades"], "Win Rate": f"{r['wr']:.1f}%",
                          "Profit Factor": f"{r['pf']:.2f}", "PnL Neto USD": f"{r['pnl']:+.2f}",
                          "Max DD": f"{r['dd']:.2f}%", "Salidas": r["motivos"]})
    print("\n" + pd.DataFrame(filas).to_string(index=False) + "\n")


if __name__ == "__main__":
    main()
