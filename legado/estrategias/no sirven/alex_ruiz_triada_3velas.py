"""
===============================================================================
ESTRATEGIA CUANTITATIVA: ALEX RUIZ · LA TRÍADA DE LAS TRES VELAS (LONG & SHORT)
===============================================================================
Ecosistema: KULA · BALAM
Basado en: Metodología Fractal Multitemporal de Alex Ruiz con blindaje de parqué.

Pilares del Sistema:
1. 1D (Contexto Macro):
   - LONG: Precio > EMA 50 y pendiente no descendente (mínimos crecientes).
   - SHORT: Precio < EMA 50 y pendiente no ascendente (máximos decrecientes).
2. 1H (Estructura y Zona Dorada):
   - Retroceso correctivo en la Zona Dorada de Fibonacci (0.50 a 0.75).
   - Veto de Estructura Rota si el retroceso rebasa el 0.75.
3. 5M (Gatillo Táctico de 3 Velas):
   - Vela 1: Impulso en dirección de la corrección.
   - Vela 2: Pausa, descanso o doji de testeo en zona.
   - Vela 3: Confirmación que quiebra el extremo de la Vela 2 y cierra sobre/bajo EMA 50.
4. Shorts de Seguridad & Blindaje Contra Trampas Institucionales:
   - Veto Bear Trap: Si la vela de gatillo short tiene mecha inferior >= 40% del rango total,
     se descarta por absorción compradora (trampa de osos).
   - Veto Clímax de Sobreventa: Si RSI(14) <= 30.0, prohibido abrir cortos en el suelo
     (prevención obligatoria contra rebotes violentos y short squeezes).
   - Veto Cohete Alcista: Rechazo de cortos si el rebote previo no muestra mecha superior >= 15%.
   - Veto Bull Trap (en LONG): Mecha superior >= 40% del rango invalida compras.
   - Veto Cuchillo Cayendo (en LONG): Mecha inferior < 15% invalida compras.
5. Gestión de Riesgo Asimétrica:
   - Stop a Misa con holgura adaptativa: Extremo técnico + max(2 ticks, 0.20 x ATR).
   - Asimetría matemática estricta: R:R >= 1:2.0 neto de comisiones y spread.
   - Peluqueo 50/50: 50% liquidado en TP1 + Stop a Breakeven ($0 riesgo) + Trailing libre.
===============================================================================
"""

from typing import Any, Dict, List, Optional, Set, Tuple
import pandas as pd
from backend.estrategias.base import EstrategiaBase
from backend.estrategias.config_manager import StrategyConfigManager
from backend.quant_risk import (
    MIN_NET_RR,
    net_return_after_costs,
    net_rr_metrics,
    required_tp_gross_for_rr,
)

ALEX_RUIZ_TIMEFRAMES: Set[str] = {"1m", "5m", "15m", "1h", "4h", "1d"}


class AlexRuizTriada3Velas(EstrategiaBase):
    """
    Estrategia de la Tríada Fractal de Tres Velas (Alex Ruiz)
    con módulo de seguridad reforzado para posiciones LONG y SHORT.
    """

    id: str = "alex_ruiz_triada_3velas"
    nombre: str = "🎯 Alex Ruiz: La Tríada de las 3 Velas (LONG & SHORT)"
    descripcion: str = (
        "Estrategia fractal multitemporal de Alex Ruiz (1D Contexto · 1H Zona Dorada Fibo 0.50-0.75 · 5M Gatillo 3 Velas) "
        "con blindaje reforzado para SHORTs de seguridad (Veto Bear Trap mecha < 40%, Veto Sobreventa RSI <= 30 contra short squeezes, "
        "Stop a Misa con holgura adaptativa de 2 ticks y Peluqueo TP1 con R:R >= 1:2.0 neto tras comisiones y spread)."
    )
    autor: str = "Alex Ruiz (Adaptación Cuantitativa Kula Balam)"
    activos_recomendados: List[str] = [
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "BNB/USDT",
        "SPY", "QQQ", "NVDA", "AAPL", "MSFT", "GC=F", "CL=F"
    ]
    temporalidades_permitidas: Set[str] = ALEX_RUIZ_TIMEFRAMES
    horario_operativo: str = "24/7 Cripto | 10:30-17:00 ARG Wall Street | 09:30-14:00 ARG Oro COMEX"

    parametros_por_defecto: Dict[str, Any] = {
        "direction_mode": "dual",           # "dual" (Long + Short), "long_only", "short_only"
        "periodo_ema_macro": 50,           # EMA 50 para régimen estructural
        "periodo_ema_micro": 50,           # EMA 50 para confirmación intradía
        "fibo_golden_zone_min": 0.50,      # Zona dorada mínima (50%)
        "fibo_golden_zone_max": 0.75,      # Zona dorada máxima (75% - invalidación si supera)
        "min_rr_ratio": 2.0,               # Asimetría obligatoria R:R >= 1:2.0
        "factor_atr_stop": 0.20,           # Holgura de seguridad ATR para el Stop Loss
        "ticks_seguridad": 2,              # Margen anti-stop hunting (2 ticks)
        "tick_size": 0.01,
        "bear_trap_wick_max": 0.40,        # Veto SHORT si mecha inferior >= 40% (trampa de osos)
        "bull_trap_wick_max": 0.40,        # Veto LONG si mecha superior >= 40% (trampa de toros)
        "rsi_oversold_short_veto": 30.0,   # Veto SHORT si RSI <= 30 (suelo de mercado)
        "rsi_overbought_long_veto": 70.0,  # Veto LONG si RSI >= 70 (techo de mercado)
        "peluqueo_active": True,           # Cierre parcial 50% en TP1 + Breakeven
        "peluqueo_partial_pct": 50.0,
    }

    @staticmethod
    def _calcular_ema(series: pd.Series, period: int = 50) -> pd.Series:
        """Calcula la Media Móvil Exponencial (EMA)."""
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def _calcular_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calcula el Average True Range (ATR) de Welles Wilder."""
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift(1)).abs()
        low_close = (df["low"] - df["close"].shift(1)).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()

    def evaluar(
        self,
        ind: Dict[str, Any],
        tp: float,
        sl: float,
        fee: float,
        spread: float,
        min_profit_pct: float,
        round_trip_cost: float,
        net_tp_manual: float,
        df: Optional[Any] = None,
    ) -> Tuple[Dict[str, Any], float, bool, List[str], float]:
        """
        Evalúa la oportunidad bajo la doctrina de Alex Ruiz:
        1. Contexto Macro 1D / Tendencia EMA 50.
        2. Estructura 1H: Zona Dorada Fibonacci (0.50 - 0.75) y Veto de Estructura Rota.
        3. Gatillo Táctico de 3 Velas en 5M (V1 impulso -> V2 pausa -> V3 confirmación).
        4. Shorts de Seguridad Reforzados (Veto Bear Trap, Veto RSI Sobreventa, Veto Cohete).
        5. Stop a Misa con holgura adaptativa y R:R >= 1:2.0 neto garantizado.
        """
        filter_failures: List[str] = []
        metrics: Dict[str, Any] = {}

        latest_raw = ind.get("latest")
        latest = latest_raw if latest_raw is not None else {}
        close_price = float(
            ind.get("live_price")
            or ind.get("price")
            or (latest.get("close") if hasattr(latest, "get") else 0.0)
            or 0.0
        )
        atr = float(
            ind.get("atr_14")
            or (latest.get("atr_14") if hasattr(latest, "get") else 0.0)
            or 0.0
        )
        rvol = float(
            ind.get("relative_volume")
            or (latest.get("relative_volume") if hasattr(latest, "get") else 1.0)
            or 1.0
        )
        rsi_val = float(
            ind.get("rsi")
            or (latest.get("rsi") if hasattr(latest, "get") else 50.0)
            or 50.0
        )
        symbol = str(ind.get("symbol") or "BTC/USDT").strip().upper()
        is_gold_or_commodity = ("=F" in symbol or symbol == "GC=F")

        # Candado Horario Institucional para Materias Primas / Oro (GC=F): Lunes a Viernes 09:30 a 14:00 ARG
        if is_gold_or_commodity and not ind.get("ignore_time_window", False):
            now_dt = ind.get("now_dt")
            if now_dt is None:
                from datetime import datetime, timezone, timedelta
                now_dt = datetime.now(timezone(timedelta(hours=-3)))
            elif getattr(now_dt, "tzinfo", None) is None:
                from datetime import timezone, timedelta
                now_dt = now_dt.replace(tzinfo=timezone(timedelta(hours=-3)))

            weekday = now_dt.weekday()
            current_minutes = now_dt.hour * 60 + now_dt.minute
            if weekday >= 5 or not (570 <= current_minutes <= 840):
                filter_failures.append(
                    f"Horario fuera de ventana institucional COMEX ({now_dt.strftime('%H:%M')} ARG). "
                    "Operativa en GC=F habilitada exclusivamente de Lunes a Viernes de 09:30 a 14:00 ARG (cruce Londres-NY)."
                )

        if close_price <= 0:
            return (
                {"mode": self.id, "error": "Precio inválido o nulo"},
                0.0,
                False,
                ["Precio actual inválido para evaluación."],
                min_profit_pct,
            )

        atr_pct = (atr / close_price * 100.0) if close_price > 0 else 1.0

        # =====================================================================
        # FASE 1: CONTEXTO MACRO Y DIRECCIÓN OPERATIVA (EMA 50)
        # =====================================================================
        ema_50_val = close_price
        ema_50_prev = close_price
        has_df = df is not None and isinstance(df, pd.DataFrame) and len(df) >= 30

        if has_df:
            ema50_series = self._calcular_ema(df["close"], self.parametros_por_defecto["periodo_ema_macro"])
            ema_50_val = float(ema50_series.iloc[-1])
            ema_50_prev = float(ema50_series.iloc[-5]) if len(ema50_series) >= 5 else ema_50_val
        elif ind.get("sma_50"):
            ema_50_val = float(ind["sma_50"])
            ema_50_prev = ema_50_val

        direction_pref = str(self.parametros_por_defecto.get("direction_mode", "dual")).lower()

        # Determinación de dirección estructural (Alex Ruiz Tríada)
        is_ema_falling = (ema_50_val < ema_50_prev * 0.998)
        is_ema_rising = (ema_50_val > ema_50_prev * 1.0005)

        if has_df:
            high_idx = df["high"].tail(60).idxmax()
            low_idx = df["low"].tail(60).idxmin()
            swing_bias_long = (high_idx >= low_idx)
        else:
            swing_bias_long = True

        if direction_pref == "long_only":
            target_side = "LONG"
            macro_bias = "ALCISTA" if close_price >= ema_50_val else "NEUTRAL"
        elif direction_pref == "short_only":
            target_side = "SHORT"
            macro_bias = "BAJISTA" if close_price <= ema_50_val else "NEUTRAL"
        elif str(ind.get("side") or ind.get("direction") or "").upper() == "SHORT":
            target_side = "SHORT"
            macro_bias = "BAJISTA"
        elif str(ind.get("side") or ind.get("direction") or "").upper() == "LONG":
            target_side = "LONG"
            macro_bias = "ALCISTA"
        else:
            # Modo "dual" determinista
            if is_ema_falling and not swing_bias_long and close_price < (ema_50_val * 0.998):
                target_side = "SHORT"
                macro_bias = "BAJISTA"
            elif swing_bias_long:
                target_side = "LONG"
                macro_bias = "ALCISTA" if close_price >= (ema_50_val * 0.998) else "CORRECCION"
            else:
                target_side = "SHORT" if close_price < ema_50_val else "LONG"
                macro_bias = "TRANSICION"

        metrics["macro_bias"] = macro_bias
        metrics["target_side"] = target_side
        metrics["sub_strategy"] = f"triada_3velas_{target_side.lower()}"
        metrics["ema_50"] = round(ema_50_val, 2)
        metrics["close_vs_ema50"] = round(((close_price - ema_50_val) / ema_50_val) * 100.0, 2)

        # Validación de subestrategias activas según el panel táctico del operador
        if target_side == "SHORT" and not StrategyConfigManager.is_sub_enabled(self.id, "operar_short"):
            filter_failures.append("Subestrategia deshabilitada: el operador desactivó la operativa en corto (SHORT) en el panel táctico.")
        if target_side == "LONG" and not StrategyConfigManager.is_sub_enabled(self.id, "operar_long"):
            filter_failures.append("Subestrategia deshabilitada: el operador desactivó la operativa en largo (LONG) en el panel táctico.")

        # =====================================================================
        # FASE 2: ESTRUCTURA Y ZONA DORADA DE FIBONACCI (0.50 A 0.75)
        # =====================================================================
        swing_high = close_price * 1.03
        swing_low = close_price * 0.97

        if has_df:
            lookback = min(len(df), 60)
            tail_df = df.tail(lookback)
            swing_high = float(tail_df["high"].max())
            swing_low = float(tail_df["low"].min())

        swing_range = max(0.0001, swing_high - swing_low)
        default_fibo_max = 0.70 if is_gold_or_commodity else 0.75
        fibo_min = float(StrategyConfigManager.get_parameter(self.id, "fibo_golden_zone_min", 0.50))
        fibo_max = float(StrategyConfigManager.get_parameter(self.id, "fibo_golden_zone_max", default_fibo_max))
        fibo_tolerance_max = (fibo_max + 0.03)
        fibo_tolerance_min = (fibo_min - 0.05)

        if target_side == "LONG":
            # En largo: retroceso medido desde el máximo hacia abajo
            current_retracement = (swing_high - close_price) / swing_range
            fibo_50 = swing_high - (0.50 * swing_range)
            fibo_618 = swing_high - (0.618 * swing_range)
            fibo_75 = swing_high - (fibo_max * swing_range)
            in_golden_zone = bool(fibo_tolerance_min <= current_retracement <= fibo_tolerance_max)

            if current_retracement > fibo_tolerance_max:
                filter_failures.append(
                    f"Estructura rota: retroceso {current_retracement:.2f} superó Fibo {fibo_max:.2f} (Fase 2 abortada)."
                )
            elif current_retracement < fibo_tolerance_min:
                filter_failures.append(
                    f"Precio caro: retroceso {current_retracement:.2f} aún no alcanza la Zona Dorada {fibo_min:.2f}-{fibo_max:.2f}."
                )
        else:
            # En corto: rebote correctivo medido desde el mínimo hacia arriba
            current_retracement = (close_price - swing_low) / swing_range
            fibo_50 = swing_low + (0.50 * swing_range)
            fibo_618 = swing_low + (0.618 * swing_range)
            fibo_75 = swing_low + (fibo_max * swing_range)
            in_golden_zone = bool(fibo_tolerance_min <= current_retracement <= fibo_tolerance_max)

            if current_retracement > fibo_tolerance_max:
                filter_failures.append(
                    f"Estructura rota: rebote bajista {current_retracement:.2f} superó Fibo {fibo_max:.2f} (Fase 2 abortada)."
                )
            elif current_retracement < fibo_tolerance_min:
                filter_failures.append(
                    f"Precio en suelo: rebote {current_retracement:.2f} aún no alcanza la Zona Dorada {fibo_min:.2f}-{fibo_max:.2f} para vender caro."
                )

        metrics["swing_high"] = round(swing_high, 2)
        metrics["swing_low"] = round(swing_low, 2)
        metrics["fibo_retracement_ratio"] = round(current_retracement, 3)
        metrics["in_golden_zone"] = in_golden_zone

        # =====================================================================
        # FASE 3: GATILLO TÁCTICO DE TRES VELAS (5M)
        # =====================================================================
        gatillo_3velas_confirmado = True
        v2_extremo = 0.0
        v3_extremo = 0.0

        if has_df and len(df) >= 3:
            v2 = df.iloc[-2]
            v3 = df.iloc[-1]
            if target_side == "LONG":
                # V3 cierra por encima del máximo de V2
                v2_extremo = float(v2["high"])
                v3_extremo = float(v3["close"])
                if not (v3_extremo > v2_extremo):
                    gatillo_3velas_confirmado = False
                    filter_failures.append(
                        f"Gatillo 3 Velas incompleto: cierre V3 ({v3_extremo:.2f}) no superó máximo de V2 ({v2_extremo:.2f})."
                    )
            else:
                # V3 cierra por debajo del mínimo de V2
                v2_extremo = float(v2["low"])
                v3_extremo = float(v3["close"])
                if not (v3_extremo < v2_extremo):
                    gatillo_3velas_confirmado = False
                    filter_failures.append(
                        f"Gatillo 3 Velas incompleto: cierre V3 ({v3_extremo:.2f}) no perforó mínimo de V2 ({v2_extremo:.2f})."
                    )
        else:
            gatillo_3velas_confirmado = True

        metrics["gatillo_3velas_confirmado"] = gatillo_3velas_confirmado

        # Confirmación de cierre respecto a EMA 50
        if target_side == "LONG":
            close_ema50_ok = bool(close_price >= (ema_50_val * 0.999))
            if not close_ema50_ok:
                filter_failures.append(
                    f"Vela sin confirmar: precio ({close_price:.2f}) cerró por debajo de EMA 50 ({ema_50_val:.2f})."
                )
        else:
            close_ema50_ok = bool(close_price <= (ema_50_val * 1.001))
            if not close_ema50_ok:
                filter_failures.append(
                    f"Vela sin confirmar: precio ({close_price:.2f}) cerró por encima de EMA 50 ({ema_50_val:.2f})."
                )
        metrics["cruce_ema50_confirmado"] = close_ema50_ok

        # =====================================================================
        # FASE 4: SHORTS DE SEGURIDAD & COMPUERTAS DE BLINDAJE ANTITRAMPAS
        # =====================================================================
        default_wick_max = 0.35 if is_gold_or_commodity else 0.40
        bear_trap_wick_max = float(StrategyConfigManager.get_parameter(self.id, "bear_trap_wick_max", default_wick_max))
        bull_trap_wick_max = float(StrategyConfigManager.get_parameter(self.id, "bull_trap_wick_max", default_wick_max))
        rsi_oversold_veto = float(StrategyConfigManager.get_parameter(self.id, "rsi_oversold_short_veto", 30.0))
        rsi_overbought_veto = float(StrategyConfigManager.get_parameter(self.id, "rsi_overbought_long_veto", 70.0))

        if target_side == "SHORT":
            # 1. Veto Bear Trap: Mecha inferior excesiva (absorción compradora)
            if StrategyConfigManager.is_sub_enabled(self.id, "veto_bear_trap") and has_df:
                last_candle = df.iloc[-1]
                tot_h_l = float(last_candle["high"] - last_candle["low"])
                if tot_h_l > 0:
                    lower_wick = float(min(last_candle["open"], last_candle["close"]) - last_candle["low"])
                    lower_wick_ratio_val = lower_wick / tot_h_l
                    if lower_wick_ratio_val >= bear_trap_wick_max:
                        filter_failures.append(
                            f"Veto Bear Trap: Mecha inferior ({lower_wick_ratio_val:.2f}) >= {bear_trap_wick_max:.2f} del rango (absorción compradora, trampa de osos)."
                        )

            # 2. Veto Clímax de Sobreventa: Prohibido shortear con RSI <= 30 (riesgo extremo de squeeze)
            if StrategyConfigManager.is_sub_enabled(self.id, "veto_rsi_oversold") and rsi_val <= rsi_oversold_veto:
                filter_failures.append(
                    f"Veto Clímax de Sobreventa: RSI={rsi_val:.1f} <= {rsi_oversold_veto:.1f} (suelo de mercado; shorting prohibido por riesgo de rebote violento)."
                )

            # 3. Veto Cohete Alcista: Rechazo de cortos si el rebote sube con fuerza sin mecha superior
            if StrategyConfigManager.is_sub_enabled(self.id, "veto_cohete_alcista"):
                upper_wick_ratio = float(ind.get("upper_wick_ratio") or 0.0)
                if upper_wick_ratio < 0.15 and close_price > ema_50_val:
                    filter_failures.append("Veto Cohete Alcista: mecha de rechazo superior insuficiente (< 15%).")

        elif target_side == "LONG":
            # 1. Veto Bull Trap: Mecha superior excesiva (rechazo de oferta)
            if StrategyConfigManager.is_sub_enabled(self.id, "veto_bull_trap") and has_df:
                last_candle = df.iloc[-1]
                tot_h_l = float(last_candle["high"] - last_candle["low"])
                if tot_h_l > 0:
                    upper_wick = float(last_candle["high"] - max(last_candle["open"], last_candle["close"]))
                    upper_wick_ratio_val = upper_wick / tot_h_l
                    if upper_wick_ratio_val >= bull_trap_wick_max:
                        filter_failures.append(
                            f"Veto Bull Trap: Mecha superior ({upper_wick_ratio_val:.2f}) >= {bull_trap_wick_max:.2f} del rango (rechazo vendedor en máximos)."
                        )

            # 2. Veto Sobrecompra Extrema en LONG
            if rsi_val >= rsi_overbought_veto:
                filter_failures.append(
                    f"Veto Sobrecompra Extrema: RSI={rsi_val:.1f} >= {rsi_overbought_veto:.1f} (techo de mercado; compra en resistencia prohibida)."
                )

            # 3. Veto Cuchillo Cayendo
            lower_wick_ratio = float(ind.get("lower_wick_ratio") or 0.0)
            if lower_wick_ratio < 0.15 and close_price < ema_50_val:
                filter_failures.append("Veto Cuchillo Cayendo: mecha de absorción insuficiente (< 15%).")

        # =====================================================================
        # FASE 5: GESTIÓN DE RIESGO ASIMÉTRICA (STOP A MISA + 2 TICKS & PELUQUEO)
        # =====================================================================
        tick_size = float(self.parametros_por_defecto.get("tick_size", 0.01))
        ticks_seguridad = int(StrategyConfigManager.get_parameter(self.id, "ticks_seguridad", 2))
        default_factor_atr = 0.25 if is_gold_or_commodity else 0.20
        factor_atr = float(StrategyConfigManager.get_parameter(self.id, "factor_atr_stop", default_factor_atr))
        target_rr = float(StrategyConfigManager.get_parameter(self.id, "min_rr_ratio", 2.0))

        invalid_margin_pts = max(ticks_seguridad * tick_size, factor_atr * atr, 0.0015 * close_price)
        invalid_margin_pct = (invalid_margin_pts / close_price) * 100.0

        if target_side == "LONG":
            suelo_tecnico = swing_low
            if has_df and len(df) >= 3:
                suelo_tecnico = min(float(df["low"].iloc[-2]), float(df["low"].iloc[-1]))
            dist_to_suelo_pct = max(0.20, ((close_price - suelo_tecnico) / close_price) * 100.0)
            technical_sl_pct = dist_to_suelo_pct + invalid_margin_pct
        else:
            techo_tecnico = swing_high
            if has_df and len(df) >= 3:
                techo_tecnico = max(float(df["high"].iloc[-2]), float(df["high"].iloc[-1]))
            dist_to_techo_pct = max(0.20, ((techo_tecnico - close_price) / close_price) * 100.0)
            technical_sl_pct = dist_to_techo_pct + invalid_margin_pct

        # Candado de Riesgo Máximo Intradía: adaptativo a la volatilidad del activo (tope 3.0x ATR%)
        max_intraday_sl = max(0.85, 3.0 * atr_pct)
        min_intraday_sl = max(0.20, 1.0 * atr_pct)
        calculated_sl_pct = round(min(max_intraday_sl, max(min_intraday_sl, technical_sl_pct)), 2)

        # Cálculo de TP1 para asimetría R:R >= 2.0 tras comisiones y spread
        min_gross_tp_for_rr = required_tp_gross_for_rr(calculated_sl_pct, fee, spread, target_rr=target_rr)
        calculated_tp_pct = round(max(tp, min_gross_tp_for_rr), 2)

        net_tp = round(net_return_after_costs(calculated_tp_pct, fee, spread), 4)
        net_sl = round(net_return_after_costs(-calculated_sl_pct, fee, spread), 4)
        minimum_strategy_net_tp = max(min_profit_pct, (calculated_sl_pct * target_rr) - round_trip_cost)

        rr_info = net_rr_metrics(calculated_tp_pct, calculated_sl_pct, fee, spread)
        effective_rr = round(float(rr_info.get("net_rr") or 0.0), 2)

        metrics["sl_margin_2ticks_pct"] = round(invalid_margin_pct, 3)
        metrics["sl_gross_pct"] = calculated_sl_pct
        metrics["tp_gross_pct"] = calculated_tp_pct
        metrics["tp1_peluqueo_pct"] = round(calculated_sl_pct * target_rr, 2)
        metrics["tp2_runner_pct"] = round(calculated_sl_pct * target_rr * 1.618, 2)
        metrics["net_rr"] = effective_rr
        metrics["peluqueo_rule"] = "50% liquidado en TP1 + Stop a Breakeven ($0 riesgo) + Trailing libre del 50% remanente"

        if net_tp < min_profit_pct:
            filter_failures.append(
                f"Rendimiento neto (+{net_tp:.2f}%) inferior al umbral mínimo (+{min_profit_pct:.2f}%)."
            )

        if not rr_info.get("valid") or effective_rr < MIN_NET_RR:
            filter_failures.append(f"R:R neto {effective_rr:.2f} < {MIN_NET_RR:.2f} tras comisiones y spread.")

        candidate_eligible = (len(filter_failures) == 0)
        signal = ("COMPRAR" if target_side == "LONG" else "SHORT") if candidate_eligible else "MANTENER"
        side = target_side if candidate_eligible else "NEUTRAL"
        effective_net_tp = net_tp if candidate_eligible else 0.0

        strategy_metrics = {
            "mode": self.id,
            "side": side,
            "sub_strategy": f"triada_3velas_{target_side.lower()}",
            "setup": f"Alex Ruiz: Tríada 3 Velas ({target_side})",
            "current_price": round(close_price, 2),
            "macro_bias": macro_bias,
            "target_side": target_side,
            "ema_50": round(ema_50_val, 2),
            "in_golden_zone": in_golden_zone,
            "fibo_retracement": round(current_retracement, 3),
            "gatillo_3velas_confirmado": gatillo_3velas_confirmado,
            "cruce_ema50_confirmado": close_ema50_ok,
            "sl_margin_2ticks_pct": round(invalid_margin_pct, 3),
            "peluqueo_rule": "50% liquidado en TP1 + Stop a Breakeven ($0 riesgo) + Trailing libre en TP2",
            "sl_gross_pct": calculated_sl_pct,
            "sl_net_pct": net_sl,
            "tp_gross_pct": calculated_tp_pct,
            "tp_net_pct": net_tp,
            "net_rr_ratio": effective_rr,
            "minimum_net_tp_pct": minimum_strategy_net_tp,
            "suggested_signal": signal,
            "policy": f"Alex Ruiz {target_side}: 1D Contexto -> 1H Zona Dorada -> 5M Gatillo 3 Velas con Shorts Blindados y R:R >= 1:2.0",
        }

        return (strategy_metrics, effective_net_tp, candidate_eligible, filter_failures, minimum_strategy_net_tp)

    # =========================================================================
    # MÉTODO AUXILIAR NATIVO PARA SIMULACIÓN MULTITEMPORAL PURA (1D, 1H, 5M)
    # =========================================================================
    def evaluar_oportunidad(
        self,
        activo: str,
        df_1d: pd.DataFrame,
        df_1h: pd.DataFrame,
        df_5m: pd.DataFrame,
    ) -> Optional[Dict[str, Any]]:
        """
        Orquesta la validación fractal completa 1D -> 1H -> 5M para backtests.
        """
        if len(df_1d) < 55 or len(df_1h) < 30 or len(df_5m) < 55:
            return None

        # 1. 1D Macro
        ema_1d = self._calcular_ema(df_1d["close"], 50)
        close_1d = float(df_1d["close"].iloc[-1])
        ema_1d_val = float(ema_1d.iloc[-1])
        ema_1d_prev = float(ema_1d.iloc[-5])

        if close_1d > ema_1d_val and ema_1d_val >= ema_1d_prev:
            dir_macro = "LONG"
        elif close_1d < ema_1d_val and ema_1d_val <= ema_1d_prev:
            dir_macro = "SHORT"
        else:
            return None

        # 2. 1H Estructura Fibo
        tail_1h = df_1h.tail(30)
        h_max = float(tail_1h["high"].max())
        l_min = float(tail_1h["low"].min())
        rng = max(0.0001, h_max - l_min)
        close_1h = float(df_1h["close"].iloc[-1])

        if dir_macro == "LONG":
            ret = (h_max - close_1h) / rng
            if not (0.50 <= ret <= 0.75):
                return None
        else:
            reb = (close_1h - l_min) / rng
            if not (0.50 <= reb <= 0.75):
                return None

        # 3. 5M Gatillo 3 Velas + Shorts de Seguridad
        v2 = df_5m.iloc[-2]
        v3 = df_5m.iloc[-1]
        ema_5m = float(self._calcular_ema(df_5m["close"], 50).iloc[-1])
        atr_5m = float(self._calcular_atr(df_5m, 14).iloc[-1])
        rango_v3 = float(v3["high"] - v3["low"])

        if rango_v3 <= 0:
            return None

        px = float(v3["close"])
        margen = max(2 * 0.01, 0.20 * atr_5m)

        if dir_macro == "LONG":
            if not (px > float(v2["high"]) and px > ema_5m):
                return None
            upper_w = float(v3["high"] - max(v3["open"], v3["close"]))
            if (upper_w / rango_v3) >= 0.40:
                return None  # Bull trap
            sl = min(float(v2["low"]), float(v3["low"])) - margen
            dist = px - sl
            if dist <= 0:
                return None
            tp1 = px + (dist * 2.0)
            tp2 = px + (dist * 3.236)
        else:
            if not (px < float(v2["low"]) and px < ema_5m):
                return None
            lower_w = float(min(v3["open"], v3["close"]) - v3["low"])
            if (lower_w / rango_v3) >= 0.40:
                return None  # Bear trap de seguridad
            sl = max(float(v2["high"]), float(v3["high"])) + margen
            dist = sl - px
            if dist <= 0:
                return None
            tp1 = px - (dist * 2.0)
            tp2 = px - (dist * 3.236)

        return {
            "activo": activo,
            "direccion": dir_macro,
            "precio_entrada": round(px, 4),
            "stop_loss": round(sl, 4),
            "take_profit_1": round(tp1, 4),
            "take_profit_2": round(tp2, 4),
            "ratio_rr": "1:2.00",
            "riesgo_pct": round((dist / px) * 100.0, 2),
            "fibo_retroceso_1h": round(ret if dir_macro == "LONG" else reb, 2),
        }
