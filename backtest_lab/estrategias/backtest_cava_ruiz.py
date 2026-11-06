"""
Script de Backtest Aislado para Kula Balam: Cava & Ruiz (Tríada Fractal + Zona Dorada Fibo + Secado RVOL).
Evalúa de forma estricta sobre data/btc_usdt_1h.csv y data/eth_usdt_1h.csv
con comisiones reales de Binance Spot (0.15% round-trip: 0.10% fee + 0.05% spread).
"""
import os
import sys
import types
import pandas as pd
import numpy as np

# Configurar alias para que legado/estrategias/kula_balam_cava_ruiz.py importe sin errores
raiz = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, raiz)

import legado.quant_risk as quant_risk
import legado.estrategias.base as base

# Mapear 'backend' hacia 'legado' en sys.modules
backend_pkg = types.ModuleType("backend")
backend_estrategias = types.ModuleType("backend.estrategias")

class DummyConfigManager:
    @staticmethod
    def is_sub_enabled(strategy_id, sub_id):
        return True
    def get_strategy_config(self, strategy_id):
        return {}

backend_estrategias.base = base
backend_estrategias.config_manager = types.ModuleType("backend.estrategias.config_manager")
backend_estrategias.config_manager.StrategyConfigManager = DummyConfigManager
backend_pkg.estrategias = backend_estrategias
backend_pkg.quant_risk = quant_risk

sys.modules["backend"] = backend_pkg
sys.modules["backend.estrategias"] = backend_estrategias
sys.modules["backend.estrategias.base"] = base
sys.modules["backend.estrategias.config_manager"] = backend_estrategias.config_manager
sys.modules["backend.quant_risk"] = quant_risk

from legado.estrategias.kula_balam_cava_ruiz import KulaBalamCavaRuiz
from src.indicators import calcular_atr, calcular_mecha_inferior


def calcular_rsi(series: pd.Series, periodo: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/periodo, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/periodo, adjust=False).mean()
    rs = avg_gain / np.where(avg_loss > 0, avg_loss, np.nan)
    return 100 - (100 / (1 + rs))


def simular_cava_ruiz(csv_path: str, simbolo: str, capital_inicial: float = 100.0) -> dict:
    df = pd.read_csv(csv_path)
    df["atr_14"] = calcular_atr(df, 14)
    df["lower_wick_ratio"] = calcular_mecha_inferior(df)
    df["rsi"] = calcular_rsi(df["close"], 14)
    df["vol_ma20"] = df["volume"].rolling(window=20).mean()
    df["relative_volume"] = df["volume"] / np.where(df["vol_ma20"] > 0, df["vol_ma20"], np.nan)

    strat = KulaBalamCavaRuiz()
    fee_pct = 0.075   # 0.075% por lado (0.15% round-trip con spread)
    spread_pct = 0.02

    capital = capital_inicial
    posicion_abierta = False
    lado = None
    precio_entrada = 0.0
    sl_precio = 0.0
    tp1_precio = 0.0
    qty = 0.0
    peluqueado = False
    tiempo_entrada = None

    historial_trades = []

    # Requiere mínimo 65 velas para calcular swing, EMA50 y retrocesos Fibo
    inicio = 65

    for i in range(inicio, len(df)):
        fila = df.iloc[i]
        c_price = float(fila["close"])
        h_price = float(fila["high"])
        l_price = float(fila["low"])

        # 1. Si no hay posición activa, auditar si hay señal de entrada
        if not posicion_abierta:
            df_slice = df.iloc[max(0, i - 65):i + 1]
            ind_payload = {
                "symbol": simbolo,
                "timeframe": "1h",
                "live_price": c_price,
                "latest": {
                    "open": float(fila["open"]),
                    "high": h_price,
                    "low": l_price,
                    "close": c_price,
                    "volume": float(fila["volume"]),
                    "atr_14": float(fila["atr_14"]),
                    "relative_volume": float(fila["relative_volume"]),
                    "lower_wick_ratio": float(fila["lower_wick_ratio"]),
                    "rsi": float(fila["rsi"]),
                },
                "atr_14": float(fila["atr_14"]),
                "relative_volume": float(fila["relative_volume"]),
                "lower_wick_ratio": float(fila["lower_wick_ratio"]),
                "rsi": float(fila["rsi"]),
            }

            metrics, net_tp, eligible, failures, _ = strat.evaluar(
                ind=ind_payload,
                tp=2.1,
                sl=0.6,
                fee=fee_pct,
                spread=spread_pct,
                min_profit_pct=0.5,
                round_trip_cost=0.15,
                net_tp_manual=2.0,
                df=df_slice
            )

            if eligible:
                target_side = metrics.get("target_side", "LONG")
                sl_pct = float(metrics.get("calculated_sl_pct") or 1.0)
                tp_pct = float(metrics.get("calculated_tp_pct") or 2.1)

                posicion_abierta = True
                lado = target_side
                precio_entrada = c_price
                tiempo_entrada = fila.get("datetime", str(fila.get("timestamp")))
                peluqueado = False

                if lado == "LONG":
                    sl_precio = precio_entrada * (1.0 - sl_pct / 100.0)
                    tp1_precio = precio_entrada * (1.0 + tp_pct / 100.0)
                else:
                    sl_precio = precio_entrada * (1.0 + sl_pct / 100.0)
                    tp1_precio = precio_entrada * (1.0 - tp_pct / 100.0)

                qty = capital / precio_entrada
                continue

        # 2. Si hay posición activa, evaluar salidas (SL, TP1 Peluqueo 50%, Breakeven)
        if posicion_abierta:
            salida_total = False
            precio_salida = 0.0
            motivo = ""

            if lado == "LONG":
                # Verificación Stop Loss
                if l_price <= sl_precio:
                    salida_total = True
                    precio_salida = sl_precio
                    motivo = "SL" if not peluqueado else "SL_BREAKEVEN"
                # Verificación TP1 Peluqueo (50%)
                elif h_price >= tp1_precio and not peluqueado:
                    peluqueado = True
                    # Liquidar 50% de la posición en TP1
                    pnl_parcial_bruto = (tp1_precio - precio_entrada) / precio_entrada
                    pnl_parcial_neto = quant_risk.net_return_after_costs(pnl_parcial_bruto * 100.0, fee_pct, spread_pct) / 100.0
                    capital_parcial = (capital * 0.5) * (1.0 + pnl_parcial_neto)
                    capital = (capital * 0.5) + capital_parcial
                    qty = qty * 0.5
                    # Mover Stop Loss a Breakeven Real (+0.25% bruto para cubrir comisiones)
                    sl_precio = precio_entrada * 1.0025
                    continue
                # Si ya fue peluqueada, salida final si el cierre pierde la EMA 50
                elif peluqueado:
                    ema50 = float(df["close"].iloc[max(0, i-50):i+1].ewm(span=50, adjust=False).mean().iloc[-1])
                    if c_price < ema50:
                        salida_total = True
                        precio_salida = c_price
                        motivo = "TRAILING_EMA50"

            else:  # SHORT
                if h_price >= sl_precio:
                    salida_total = True
                    precio_salida = sl_precio
                    motivo = "SL" if not peluqueado else "SL_BREAKEVEN"
                elif l_price <= tp1_precio and not peluqueado:
                    peluqueado = True
                    pnl_parcial_bruto = (precio_entrada - tp1_precio) / precio_entrada
                    pnl_parcial_neto = quant_risk.net_return_after_costs(pnl_parcial_bruto * 100.0, fee_pct, spread_pct) / 100.0
                    capital_parcial = (capital * 0.5) * (1.0 + pnl_parcial_neto)
                    capital = (capital * 0.5) + capital_parcial
                    qty = qty * 0.5
                    sl_precio = precio_entrada * 0.9975
                    continue
                elif peluqueado:
                    ema50 = float(df["close"].iloc[max(0, i-50):i+1].ewm(span=50, adjust=False).mean().iloc[-1])
                    if c_price > ema50:
                        salida_total = True
                        precio_salida = c_price
                        motivo = "TRAILING_EMA50"

            if salida_total:
                if lado == "LONG":
                    retorno_bruto_pct = ((precio_salida - precio_entrada) / precio_entrada) * 100.0
                else:
                    retorno_bruto_pct = ((precio_entrada - precio_salida) / precio_entrada) * 100.0

                retorno_neto_pct = quant_risk.net_return_after_costs(retorno_bruto_pct, fee_pct, spread_pct)
                notional_trade = qty * precio_entrada
                pnl_usd = notional_trade * (retorno_neto_pct / 100.0)
                capital += pnl_usd

                historial_trades.append({
                    "lado": lado,
                    "entrada_tiempo": tiempo_entrada,
                    "salida_tiempo": fila.get("datetime", str(fila.get("timestamp"))),
                    "motivo": motivo,
                    "pnl_usd": pnl_usd,
                    "capital_acumulado": capital
                })
                posicion_abierta = False

    df_trades = pd.DataFrame(historial_trades)
    if len(df_trades) > 0:
        ganadores = df_trades[df_trades["pnl_usd"] > 0]
        perdedores = df_trades[df_trades["pnl_usd"] <= 0]
        win_rate = (len(ganadores) / len(df_trades)) * 100.0
        g_bruta = ganadores["pnl_usd"].sum()
        p_bruta = abs(perdedores["pnl_usd"].sum())
        profit_factor = (g_bruta / p_bruta) if p_bruta > 0 else np.nan
        df_trades["max_capital"] = df_trades["capital_acumulado"].cummax()
        df_trades["drawdown"] = (df_trades["capital_acumulado"] - df_trades["max_capital"]) / df_trades["max_capital"]
        max_drawdown = df_trades["drawdown"].min() * 100.0
        retorno_total_pct = ((capital - capital_inicial) / capital_inicial) * 100.0
    else:
        win_rate = 0.0
        profit_factor = 0.0
        max_drawdown = 0.0
        retorno_total_pct = 0.0

    return {
        "activo": simbolo,
        "capital_final": capital,
        "retorno_total_pct": retorno_total_pct,
        "total_trades": len(df_trades),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "max_drawdown_pct": max_drawdown,
    }


def main():
    activos = [
        {"simbolo": "BTC/USDT", "archivo": os.path.join("data", "btc_usdt_1h.csv")},
        {"simbolo": "ETH/USDT", "archivo": os.path.join("data", "eth_usdt_1h.csv")},
    ]

    print("\n" + "="*75)
    print("  AUDITORÍA CUANTITATIVA AISLADA: KULA BALAM (CAVA & RUIZ)")
    print("  Módulo: legado/estrategias/kula_balam_cava_ruiz.py")
    print("  Reglas: Zona Dorada Fibo 0.50-0.75 + Fallo MACD + RVOL Secado < 0.85")
    print("  Costos: 0.15% round-trip (Binance Spot)")
    print("="*75)

    resumen = []
    for item in activos:
        ruta = item["archivo"]
        sym = item["simbolo"]
        if not os.path.exists(ruta):
            print(f"⚠️ Archivo no encontrado: {ruta}")
            continue

        res = simular_cava_ruiz(ruta, sym, capital_inicial=100.0)
        resumen.append({
            "Activo": sym,
            "Estrategia": "🐅 Kula Balam (Cava & Ruiz)",
            "Retorno %": f"{res['retorno_total_pct']:+.2f}%",
            "Win Rate": f"{res['win_rate']:.1f}%",
            "Trades": res["total_trades"],
            "Profit Factor": f"{res['profit_factor']:.2f}",
            "Max DD": f"{res['max_drawdown_pct']:.2f}%"
        })

    df_out = pd.DataFrame(resumen)
    print("\n" + df_out.to_string(index=False))
    print("="*75 + "\n")


if __name__ == "__main__":
    main()
