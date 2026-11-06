"""
Script de Auditoría Cuantitativa Consolidada para Kula-Balam Ikigai.
Evalúa las 5 estrategias de legado tal cual están escritas en legado/estrategias/
sobre 4.321 velas horarias (180 días) de BTC/USDT y ETH/USDT con 0.15% round-trip de comisiones.
"""
import os
import sys
import types
import pandas as pd
import numpy as np

raiz = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, raiz)

import legado.quant_risk as quant_risk
import legado.estrategias.base as base

# Mapear 'backend' hacia 'legado' en sys.modules
backend_pkg = types.ModuleType("backend")
backend_estrategias = types.ModuleType("backend.estrategias")

class DummyConfigManager:
    @staticmethod
    def is_sub_enabled(strategy_id, sub_id, default=True):
        return True
    @staticmethod
    def is_strategy_active(strategy_id, default=True):
        return True
    @staticmethod
    def get_parameter(strategy_id, param_name, default_val):
        return default_val
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

# Importar las 5 estrategias de legado
from legado.estrategias.donchian_breakout_1h import DonchianBreakout1H
from legado.estrategias.kula_balam_cava_ruiz import KulaBalamCavaRuiz
from legado.estrategias.alex_ruiz_triada_3velas import AlexRuizTriada3Velas
from legado.estrategias.nasdaq_araujo_vwap import NasdaqAraujoVWAP
from legado.estrategias.mean_reversion_atr import MeanReversionATR

from src.indicators import calcular_atr, calcular_mecha_inferior


def calcular_rsi(series: pd.Series, periodo: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/periodo, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/periodo, adjust=False).mean()
    rs = avg_gain / np.where(avg_loss > 0, avg_loss, np.nan)
    return 100 - (100 / (1 + rs))


def calcular_z_score(series: pd.Series, periodo: int = 20) -> pd.Series:
    sma = series.rolling(window=periodo).mean()
    std = series.rolling(window=periodo).std()
    return (series - sma) / np.where(std > 0, std, np.nan)


def calcular_vwap(df: pd.DataFrame) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    vp = tp * df["volume"]
    return vp.cumsum() / df["volume"].cumsum()


def _evaluar_simulacion_generica(
    df: pd.DataFrame,
    simbolo: str,
    strat_obj,
    nombre_strat: str,
    capital_inicial: float = 100.0,
    fee_pct: float = 0.075,
    spread_pct: float = 0.02
) -> dict:
    capital = capital_inicial
    posicion_abierta = False
    lado = "LONG"
    precio_entrada = 0.0
    sl_precio = 0.0
    tp_precio = 0.0
    qty = 0.0
    peluqueado = False
    historial_trades = []

    # Ventana mínima para cálculo de medias y retrocesos
    inicio = 65

    for i in range(inicio, len(df)):
        fila = df.iloc[i]
        c_price = float(fila["close"])
        h_price = float(fila["high"])
        l_price = float(fila["low"])

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
                    "z_score": float(fila["z_score"]),
                    "vwap": float(fila["vwap"]),
                },
                "atr_14": float(fila["atr_14"]),
                "relative_volume": float(fila["relative_volume"]),
                "lower_wick_ratio": float(fila["lower_wick_ratio"]),
                "rsi": float(fila["rsi"]),
                "z_score": float(fila["z_score"]),
                "vwap": float(fila["vwap"]),
                "ema_200_value": float(fila["ema_200"]),
                "ema_200_slope_pct": 0.01,
            }

            try:
                metrics, net_tp, eligible, failures, _ = strat_obj.evaluar(
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
            except Exception:
                eligible = False
                metrics = {}

            if eligible:
                target_side = metrics.get("target_side") or ("SHORT" if metrics.get("side") == "SHORT" else "LONG")
                sl_pct = float(metrics.get("calculated_sl_pct") or metrics.get("sl_gross_pct") or 1.5)
                tp_pct = float(metrics.get("calculated_tp_pct") or metrics.get("tp_gross_pct") or 3.0)

                posicion_abierta = True
                lado = target_side
                precio_entrada = c_price
                peluqueado = False

                if lado == "LONG":
                    sl_precio = precio_entrada * (1.0 - sl_pct / 100.0)
                    tp_precio = precio_entrada * (1.0 + tp_pct / 100.0)
                else:
                    sl_precio = precio_entrada * (1.0 + sl_pct / 100.0)
                    tp_precio = precio_entrada * (1.0 - tp_pct / 100.0)

                qty = capital / precio_entrada
                continue

        if posicion_abierta:
            salida_total = False
            precio_salida = 0.0
            motivo = ""

            # Evaluación de salida Donchian Mid-Exit
            if "donchian" in strat_obj.id:
                donchian_mid = float(fila.get("donchian_mid") or 0.0)
                if l_price <= sl_precio:
                    salida_total = True
                    precio_salida = sl_precio
                    motivo = "SL"
                elif donchian_mid > 0 and c_price < donchian_mid:
                    salida_total = True
                    precio_salida = c_price
                    motivo = "MID_EXIT"
            # Evaluación general (SL / TP / Peluqueo)
            elif lado == "LONG":
                if l_price <= sl_precio:
                    salida_total = True
                    precio_salida = sl_precio
                    motivo = "SL" if not peluqueado else "SL_BREAKEVEN"
                elif h_price >= tp_precio and not peluqueado:
                    peluqueado = True
                    pnl_parc_bruto = (tp_precio - precio_entrada) / precio_entrada
                    pnl_parc_neto = quant_risk.net_return_after_costs(pnl_parc_bruto * 100.0, fee_pct, spread_pct) / 100.0
                    cap_parc = (capital * 0.5) * (1.0 + pnl_parc_neto)
                    capital = (capital * 0.5) + cap_parc
                    qty = qty * 0.5
                    sl_precio = precio_entrada * 1.0025  # Breakeven Real
                    continue
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
                elif l_price <= tp_precio and not peluqueado:
                    peluqueado = True
                    pnl_parc_bruto = (precio_entrada - tp_precio) / precio_entrada
                    pnl_parc_neto = quant_risk.net_return_after_costs(pnl_parc_bruto * 100.0, fee_pct, spread_pct) / 100.0
                    cap_parc = (capital * 0.5) * (1.0 + pnl_parc_neto)
                    capital = (capital * 0.5) + cap_parc
                    qty = qty * 0.5
                    sl_precio = precio_entrada * 0.9975  # Breakeven Real
                    continue
                elif peluqueado:
                    ema50 = float(df["close"].iloc[max(0, i-50):i+1].ewm(span=50, adjust=False).mean().iloc[-1])
                    if c_price > ema50:
                        salida_total = True
                        precio_salida = c_price
                        motivo = "TRAILING_EMA50"

            if salida_total:
                retorno_bruto_pct = ((precio_salida - precio_entrada) / precio_entrada) * 100.0 if lado == "LONG" else ((precio_entrada - precio_salida) / precio_entrada) * 100.0
                retorno_neto_pct = quant_risk.net_return_after_costs(retorno_bruto_pct, fee_pct, spread_pct)
                notional_trade = qty * precio_entrada
                pnl_usd = notional_trade * (retorno_neto_pct / 100.0)
                capital += pnl_usd

                historial_trades.append({
                    "estrategia": nombre_strat,
                    "lado": lado,
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
        "estrategia": nombre_strat,
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

    # Pre-cargar y enriquecer series
    dfs = {}
    for item in activos:
        ruta = item["archivo"]
        if os.path.exists(ruta):
            df = pd.read_csv(ruta)
            df["atr_14"] = calcular_atr(df, 14)
            df["lower_wick_ratio"] = calcular_mecha_inferior(df)
            df["rsi"] = calcular_rsi(df["close"], 14)
            df["z_score"] = calcular_z_score(df["close"], 20)
            df["vol_ma20"] = df["volume"].rolling(window=20).mean()
            df["relative_volume"] = df["volume"] / np.where(df["vol_ma20"] > 0, df["vol_ma20"], np.nan)
            df["ema_50"] = df["close"].ewm(span=50, adjust=False).mean()
            df["ema_100"] = df["close"].ewm(span=100, adjust=False).mean()
            df["ema_200"] = df["close"].ewm(span=200, adjust=False).mean()
            df["vwap"] = calcular_vwap(df)
            df["donchian_high"] = df["high"].shift(1).rolling(window=20).max()
            df["donchian_low"] = df["low"].shift(1).rolling(window=20).min()
            df["donchian_mid"] = (df["donchian_high"] + df["donchian_low"]) / 2.0
            df["donchian_width"] = df["donchian_high"] - df["donchian_low"]
            dfs[item["simbolo"]] = df

    estrategias = [
        (DonchianBreakout1H(), "🛡️ Donchian Breakout 1H"),
        (KulaBalamCavaRuiz(), "🐅 Kula Balam (Cava & Ruiz)"),
        (AlexRuizTriada3Velas(), "🎯 Alex Ruiz: Tríada 3 Velas"),
        (NasdaqAraujoVWAP(), "⏱️ Nasdaq Araujo: VWAP Wall Street"),
        (MeanReversionATR(), "🔄 Reversión a la Media ATR"),
    ]

    print("\n" + "="*80)
    print("  AUDITORÍA CONSOLIDADA: LAS 5 ESTRATEGIAS DE LEGADO EN 1H")
    print("  Dataset: 4.321 velas (180 días) · Costos Reales Binance Spot: 0.15% Round-Trip")
    print("="*80)

    resumen = []

    for sym, df_data in dfs.items():
        for strat_inst, nombre in estrategias:
            # En MeanReversionATR original venía con long_entries_suspended = True, lo respetamos o lo probamos tal cual
            res = _evaluar_simulacion_generica(df_data, sym, strat_inst, nombre)
            resumen.append({
                "Activo": sym,
                "Estrategia": nombre,
                "Retorno %": f"{res['retorno_total_pct']:+.2f}%",
                "Win Rate": f"{res['win_rate']:.1f}%",
                "Trades": res["total_trades"],
                "Profit Factor": f"{res['profit_factor']:.2f}" if not np.isnan(res['profit_factor']) else "0.00",
                "Max DD": f"{res['max_drawdown_pct']:.2f}%"
            })

    df_final = pd.DataFrame(resumen)
    print("\n" + df_final.to_string(index=False))
    print("="*80 + "\n")


if __name__ == "__main__":
    main()
