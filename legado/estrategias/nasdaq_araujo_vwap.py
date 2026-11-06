"""
===============================================================================
ESTRATEGIA CUANTITATIVA: FRANKLIN ARAUJO · FRANCOTIRADOR VWAP WALL STREET
===============================================================================
Ecosistema: KULA · BALAM
Basado en: Metodología operativa de Franklin Araujo para el índice Nasdaq (QQQ, NQ)
y grandes tecnológicos de Wall Street (SPY, NVDA, AAPL, MSFT, TSLA, CEDEARs BYMA).

Pilares del Sistema:
1. Especialización de Activo:
   - Exclusivo para renta variable de Wall Street y CEDEARs (.BA).
   - Veto terminante a criptomonedas 24/7 (donde el VWAP carece de campana de apertura).
2. Candado de Ventana Horaria Institucional (Time-Window Gate):
   - Rueda de Lunes a Viernes.
   - Ventana de Francotirador: 09:35 a 11:00 NY (10:35 a 12:00 ARG).
   - Veto de los Primeros 5 Minutos (09:30 - 09:35 NY): Neutraliza el caos del Opening Cross.
   - El resto de la jornada duerme para evitar el "Lunch Lull" y trampas de poco volumen.
3. El VWAP como Juez Absoluto & Confluencia Táctica:
   - LONG: Precio sobre VWAP; entrada por rechazo alcista en VWAP (mecha inferior >= 30%)
     o por ruptura de la sesión europea de Londres con volumen.
   - SHORT: Precio bajo VWAP; entrada por rechazo bajista en VWAP (mecha superior >= 30%)
     o por quiebre de soporte de Londres con volumen.
   - Volumen Institucional: RVOL >= 1.2 confirmando defensa algorítmica del benchmark.
4. Compuertas Defensivas de Parqué (Risk-Guards Blindados):
   - Veto Bear Trap (en Cortos): Si mecha inferior >= 40%, invalida por absorción de compra.
   - Veto Clímax de Sobreventa: Prohibido abrir cortos con RSI(14) <= 30 (anti-short squeeze).
   - Veto Bull Trap (en Largos): Si mecha superior >= 40%, invalida por rechazo en techos.
   - Veto de Sobrecompra: Prohibido abrir largos con RSI(14) >= 70.
5. Gestión de Riesgo Asimétrica:
   - Stop a Misa: Nivel de invalidación en extremo/VWAP + max(2 ticks, 0.15 x ATR).
   - Asimetría matemática estricta: R:R >= 1:2.0 neto tras comisiones y spread.
   - Peluqueo 50/50: 50% liquidado en TP1 + Stop a Breakeven ($0 riesgo) + Trailing libre.
===============================================================================
"""

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo
import pandas as pd

from backend.estrategias.base import EstrategiaBase
from backend.estrategias.config_manager import StrategyConfigManager
from backend.quant_risk import (
    MIN_NET_RR,
    net_return_after_costs,
    net_rr_metrics,
    required_tp_gross_for_rr,
)

ARAUJO_STRATEGY_TIMEFRAMES: Set[str] = {"15m"}
NY_TIMEZONE = ZoneInfo("America/New_York")
ARG_TIMEZONE = timezone(timedelta(hours=-3))


class NasdaqAraujoVWAP(EstrategiaBase):
    """
    Francotirador Cuantitativo de Apertura Wall Street (Franklin Araujo)
    con candados horarios, filtro anti-caos de campana y operativa bidireccional VWAP.
    """

    id: str = "nasdaq_araujo_vwap"
    nombre: str = "⏱️ Nasdaq Araujo: Francotirador VWAP Wall Street (LONG & SHORT)"
    descripcion: str = (
        "Estrategia determinista especializada en la apertura de Wall Street (QQQ, SPY, NVDA, AAPL, CEDEARs). "
        "Opera exclusivamente de 09:35 a 11:00 NY (10:35 a 12:00 ARG) tras el salto de los primeros 5 minutos. "
        "Exige confluencia con VWAP diario, rechazo con mecha >= 30% o ruptura de sesión europea con volumen RVOL >= 1.2, "
        "veto anti-squeeze RSI <= 30 y Stop a Misa con 2 ticks de margen estructural para ratio asimétrico R:R >= 1:2.0 neto."
    )
    autor: str = "Franklin Araujo (Adaptación Cuantitativa Kula Balam)"
    activos_recomendados: List[str] = [
        "QQQ", "SPY", "NQ=F", "NVDA", "AAPL", "MSFT", "TSLA", "AMZN", "META", "AMD",
        "GGAL.BA", "BMA.BA", "YPFD.BA", "PAMP.BA"
    ]
    temporalidades_permitidas: Set[str] = ARAUJO_STRATEGY_TIMEFRAMES
    horario_operativo: str = "Lunes a Viernes: 09:35 - 11:00 NY (10:35 - 12:00 ARG)"

    parametros_por_defecto: Dict[str, Any] = {
        "direction_mode": "dual",              # "dual", "long_only", "short_only"
        "min_rr_ratio": 2.0,                  # Asimetría mínima R:R >= 1:2.0
        "min_rvol": 1.20,                     # Volumen relativo mínimo para confirmar defensa institucional
        "min_rejection_wick": 0.30,           # Mecha de rechazo mínima contra VWAP (30%)
        "vwap_tolerance_pct": 0.003,          # Tolerancia para considerar testeo del VWAP (0.3%)
        "lookback_extremes": 8,               # Velas para soporte/resistencia M15
        "bear_trap_wick_max": 0.40,           # Veto SHORT si mecha inferior >= 40%
        "bull_trap_wick_max": 0.40,           # Veto LONG si mecha superior >= 40%
        "rsi_oversold_short_veto": 30.0,      # Prohibido abrir cortos si RSI <= 30
        "rsi_overbought_long_veto": 70.0,     # Prohibido abrir largos si RSI >= 70
        "factor_atr_stop": 0.15,              # Margen adicional ATR para Stop a Misa
        "ticks_seguridad": 2,                 # Margen estructural de 2 ticks
        "tick_size": 0.01,
        "peluqueo_partial_pct": 50.0,         # Cierre del 50% en TP1
    }

    def _evaluar_candado_horario(
        self,
        now_dt: Optional[datetime],
        permitir_primeros_5min: bool = False,
    ) -> Tuple[bool, bool, str]:
        if now_dt is None:
            now_dt = datetime.now(timezone.utc)
        elif now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=timezone.utc)

        now_ny = now_dt.astimezone(NY_TIMEZONE)
        weekday = now_ny.weekday()  # 0=Lunes ... 4=Viernes, 5=Sábado, 6=Domingo

        if weekday >= 5:
            return False, False, f"Mercado cerrado por fin de semana ({now_ny.strftime('%A')}). Rueda Wall Street inactiva."

        minutes = now_ny.hour * 60 + now_ny.minute
        time_str = now_ny.strftime("%H:%M NY")

        # Rango 09:30 a 09:35 NY (primeros 5 minutos de ruido caótico)
        if 9 * 60 + 30 <= minutes < 9 * 60 + 35:
            if not permitir_primeros_5min:
                return False, True, f"Veto de Apertura: Primeros 5 min de subasta caótica ({time_str}). Esperando estabilización del VWAP."

        # Ventana oficial: 09:35 a 11:00 NY (575 a 660 min)
        if 9 * 60 + 35 <= minutes < 11 * 60:
            return True, False, f"Ventana institucional activa ({time_str})."

        return False, False, f"Fuera de la ventana institucional de Wall Street (09:35 - 11:00 NY). Hora actual: {time_str}."

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
        now_dt: Optional[datetime] = None,
    ) -> Tuple[Dict[str, Any], float, bool, List[str], float]:
        latest = ind.get("latest", {})
        previous = ind.get("previous", latest)
        symbol = str(ind.get("symbol") or latest.get("symbol") or "QQQ").strip().upper()

        current_price = float(ind.get("live_price") or latest.get("close") or 0.0)
        high = float(latest.get("high", current_price))
        low = float(latest.get("low", current_price))
        open_px = float(latest.get("open", current_price))
        candle_range = max(high - low, 0.0001)

        # 0. Sincronización con el Gestor de Configuración Dinámica
        is_active = StrategyConfigManager.is_strategy_active(self.id, default=True)
        sub_long_enabled = StrategyConfigManager.is_sub_enabled(self.id, "operar_long", default=True)
        sub_short_enabled = StrategyConfigManager.is_sub_enabled(self.id, "operar_short", default=True)
        sub_time_gate_enabled = StrategyConfigManager.is_sub_enabled(self.id, "filtro_horario_wall_street", default=True)
        sub_skip_5min_enabled = StrategyConfigManager.is_sub_enabled(self.id, "salto_primeros_5min", default=True)
        sub_rejection_enabled = StrategyConfigManager.is_sub_enabled(self.id, "filtro_rechazo_vwap", default=True)
        sub_rvol_enabled = StrategyConfigManager.is_sub_enabled(self.id, "filtro_rvol_institucional", default=True)
        sub_bear_trap_enabled = StrategyConfigManager.is_sub_enabled(self.id, "veto_bear_trap", default=True)
        sub_bull_trap_enabled = StrategyConfigManager.is_sub_enabled(self.id, "veto_bull_trap", default=True)
        sub_rsi_oversold_enabled = StrategyConfigManager.is_sub_enabled(self.id, "veto_rsi_oversold", default=True)
        sub_peluqueo_enabled = StrategyConfigManager.is_sub_enabled(self.id, "peluqueo_tp1", default=True)

        min_rr_target = float(StrategyConfigManager.get_parameter(self.id, "min_rr_ratio", self.parametros_por_defecto["min_rr_ratio"]))
        min_rvol = float(StrategyConfigManager.get_parameter(self.id, "min_rvol", self.parametros_por_defecto["min_rvol"]))
        min_rejection_wick = float(StrategyConfigManager.get_parameter(self.id, "min_rejection_wick", self.parametros_por_defecto["min_rejection_wick"]))
        vwap_tolerance = float(StrategyConfigManager.get_parameter(self.id, "vwap_tolerance_pct", self.parametros_por_defecto["vwap_tolerance_pct"]))
        lookback = int(StrategyConfigManager.get_parameter(self.id, "lookback_extremes", self.parametros_por_defecto["lookback_extremes"]))
        bear_trap_max = float(StrategyConfigManager.get_parameter(self.id, "bear_trap_wick_max", self.parametros_por_defecto["bear_trap_wick_max"]))
        bull_trap_max = float(StrategyConfigManager.get_parameter(self.id, "bull_trap_wick_max", self.parametros_por_defecto["bull_trap_wick_max"]))
        rsi_oversold_veto = float(StrategyConfigManager.get_parameter(self.id, "rsi_oversold_short_veto", self.parametros_por_defecto["rsi_oversold_short_veto"]))
        rsi_overbought_veto = float(StrategyConfigManager.get_parameter(self.id, "rsi_overbought_long_veto", self.parametros_por_defecto["rsi_overbought_long_veto"]))
        factor_atr = float(StrategyConfigManager.get_parameter(self.id, "factor_atr_stop", self.parametros_por_defecto["factor_atr_stop"]))
        ticks_seguridad = int(StrategyConfigManager.get_parameter(self.id, "ticks_seguridad", self.parametros_por_defecto["ticks_seguridad"]))
        tick_size = float(StrategyConfigManager.get_parameter(self.id, "tick_size", self.parametros_por_defecto["tick_size"]))

        filter_failures: List[str] = []
        applied_safeguards: List[str] = []
        signal = "MANTENER"
        action = "HOLD"
        bias = "NEUTRAL"
        sub_strategy_id = "araujo_vwap_neutral"

        # 1. Candado de Estrategia Activa
        if not is_active:
            filter_failures.append("Estrategia Nasdaq Araujo VWAP archivada o desactivada por el operador.")
            return (
                self._build_metrics("MANTENER", "HOLD", "NEUTRAL", "araujo_vwap_inactive", 0.0, 0.0, 0.0, filter_failures, applied_safeguards, current_price, current_price),
                0.0, False, filter_failures, min_profit_pct
            )

        # 2. Candado de Activos: Prohibido operar Cripto 24/7 con VWAP institucional
        if "/" in symbol:
            filter_failures.append(
                f"Veto de Activo: {symbol} es un par cripto 24/7 sin campana de apertura ni reinicio diario de volumen. "
                "La estrategia de Araujo exige acciones, ETFs de Wall Street o CEDEARs (QQQ, SPY, NVDA, AAPL, GGAL.BA)."
            )

        # 3. Candado de Ventana Horaria Institucional (09:35 - 11:00 NY)
        # Si se pasa now_dt o ind["now_dt"], se utiliza; si ind["ignore_time_gate"] es True, se omite (para backtesting)
        eval_dt = now_dt or ind.get("now_dt")
        if sub_time_gate_enabled and not ind.get("ignore_time_gate", False):
            if eval_dt is not None:
                is_in_window, is_opening_noise, window_reason = self._evaluar_candado_horario(
                    eval_dt, permitir_primeros_5min=not sub_skip_5min_enabled
                )
                if not is_in_window:
                    filter_failures.append(window_reason)
                else:
                    applied_safeguards.append("Ventana institucional 09:35-11:00 NY activa")

        # 4. Obtención y Validación del VWAP y Extremos M15 / Londres
        vwap_val = float(latest.get("vwap") or ind.get("vwap") or 0.0)
        if vwap_val <= 0.0:
            if df is not None and isinstance(df, pd.DataFrame) and "volume" in df.columns:
                try:
                    typical_px = (df["high"] + df["low"] + df["close"]) / 3.0
                    cum_vol = df["volume"].cumsum()
                    cum_vp = (typical_px * df["volume"]).cumsum()
                    vwap_val = float((cum_vp / cum_vol).iloc[-1])
                except Exception:
                    vwap_val = current_price
            else:
                vwap_val = current_price

        # Rango de Londres y extremos M15
        if df is not None and isinstance(df, pd.DataFrame) and len(df) >= lookback + 1:
            slice_prev = df.iloc[-(lookback + 1):-1]
            m15_high = float(slice_prev["high"].max())
            m15_low = float(slice_prev["low"].min())
            london_slice = df.iloc[-min(len(df), 24):-min(len(df), lookback)]
            if len(london_slice) > 0:
                london_high = float(london_slice["high"].max())
                london_low = float(london_slice["low"].min())
            else:
                london_high = m15_high
                london_low = m15_low
        else:
            m15_high = float(previous.get("high", current_price * 1.005))
            m15_low = float(previous.get("low", current_price * 0.995))
            london_high = m15_high
            london_low = m15_low

        lower_wick = max(min(open_px, current_price) - low, 0.0)
        upper_wick = max(high - max(open_px, current_price), 0.0)
        lower_wick_ratio = lower_wick / candle_range
        upper_wick_ratio = upper_wick / candle_range
        rvol = float(ind.get("relative_volume") or latest.get("relative_volume") or 1.0)
        rsi_14 = float(ind.get("rsi_14") or latest.get("rsi_14") or 50.0)
        atr_14 = float(ind.get("atr_14") or latest.get("atr_14") or candle_range)

        # Condiciones tácticas
        above_vwap = current_price >= vwap_val
        below_vwap = current_price < vwap_val
        low_tested_vwap = low <= vwap_val * (1.0 + vwap_tolerance)
        high_tested_vwap = high >= vwap_val * (1.0 - vwap_tolerance)
        breaking_high = current_price >= m15_high or float(latest.get("high", current_price)) > m15_high
        breaking_low = current_price <= m15_low or float(latest.get("low", current_price)) < m15_low
        above_london = current_price > london_high
        below_london = current_price < london_low

        sl_calc_pct = 1.0

        # =========================================================================
        # 5. EVALUACIÓN DIRECCIONAL: LONG vs SHORT
        # =========================================================================
        if above_vwap:
            bias = "ALCISTA (SOBRE VWAP)"
            sub_strategy_id = "araujo_vwap_long"

            if not sub_long_enabled:
                filter_failures.append("Subestrategia LONG desactivada en el Gestor de Estrategias.")

            # Gatillo dual: Rechazo en VWAP O Ruptura de Sesión de Londres con precio sobre VWAP
            has_vwap_rejection = low_tested_vwap and (lower_wick_ratio >= min_rejection_wick)
            has_london_breakout = above_london and breaking_high

            if sub_rejection_enabled:
                if not (has_vwap_rejection or has_london_breakout):
                    filter_failures.append(
                        f"Falta confluencia táctica: Sin rechazo en VWAP (${vwap_val:.2f}, mecha {lower_wick_ratio*100:.1f}%) "
                        f"ni ruptura de Londres (${london_high:.2f}) / Resistencia M15 (${m15_high:.2f})."
                    )
                elif has_vwap_rejection:
                    applied_safeguards.append(f"Rechazo alcista en VWAP confirmado (Mecha {lower_wick_ratio*100:.1f}%)")
                elif has_london_breakout:
                    applied_safeguards.append(f"Ruptura de apertura sobre Londres (${london_high:.2f}) confirmada")

            if sub_rvol_enabled and rvol < min_rvol:
                filter_failures.append(
                    f"Falta de volumen institucional: RVOL {rvol:.2f} < {min_rvol:.2f} mínimo requerido en defensa de VWAP."
                )
            elif sub_rvol_enabled:
                applied_safeguards.append(f"Volumen institucional verificado (RVOL {rvol:.2f})")

            if sub_bull_trap_enabled and upper_wick_ratio >= bull_trap_max:
                filter_failures.append(
                    f"Veto Bull Trap: Mecha superior {upper_wick_ratio*100:.1f}% >= {bull_trap_max*100:.1f}% indica rechazo en techos."
                )

            if rsi_14 >= rsi_overbought_veto:
                filter_failures.append(
                    f"Veto Sobrecompra: RSI {rsi_14:.1f} >= {rsi_overbought_veto:.1f}."
                )

            # Stop a Misa
            delta_prot = max(ticks_seguridad * tick_size, factor_atr * atr_14, 0.0015 * current_price)
            sl_level = min(low, vwap_val, m15_low) - delta_prot
            sl_calc_pct = round(max(0.40, min(4.0, (current_price - sl_level) / max(current_price, 0.0001) * 100.0)), 2)
            applied_safeguards.append(f"Stop a Misa bajo VWAP en ${sl_level:.2f} (+{ticks_seguridad} ticks holgura)")

            if len(filter_failures) == 0:
                signal = "COMPRAR"
                action = "BUY"
        else:
            bias = "BAJISTA (BAJO VWAP)"
            sub_strategy_id = "araujo_vwap_short"

            if not sub_short_enabled:
                filter_failures.append("Subestrategia SHORT desactivada en el Gestor de Estrategias.")

            has_vwap_rejection = high_tested_vwap and (upper_wick_ratio >= min_rejection_wick)
            has_london_breakdown = below_london and breaking_low

            if sub_rejection_enabled:
                if not (has_vwap_rejection or has_london_breakdown):
                    filter_failures.append(
                        f"Falta confluencia táctica: Sin rechazo en VWAP (${vwap_val:.2f}, mecha {upper_wick_ratio*100:.1f}%) "
                        f"ni quiebre bajista de Londres (${london_low:.2f}) / Soporte M15 (${m15_low:.2f})."
                    )
                elif has_vwap_rejection:
                    applied_safeguards.append(f"Rechazo bajista en VWAP confirmado (Mecha {upper_wick_ratio*100:.1f}%)")
                elif has_london_breakdown:
                    applied_safeguards.append(f"Quiebre de apertura bajo Londres (${london_low:.2f}) confirmado")

            if sub_rvol_enabled and rvol < min_rvol:
                filter_failures.append(
                    f"Falta de volumen institucional: RVOL {rvol:.2f} < {min_rvol:.2f} mínimo requerido en rechazo de VWAP."
                )
            elif sub_rvol_enabled:
                applied_safeguards.append(f"Volumen institucional verificado (RVOL {rvol:.2f})")

            if sub_bear_trap_enabled and lower_wick_ratio >= bear_trap_max:
                filter_failures.append(
                    f"Veto Bear Trap: Mecha inferior {lower_wick_ratio*100:.1f}% >= {bear_trap_max*100:.1f}% indica absorción compradora."
                )

            if sub_rsi_oversold_enabled and rsi_14 <= rsi_oversold_veto:
                filter_failures.append(
                    f"Veto Clímax de Sobreventa: RSI {rsi_14:.1f} <= {rsi_oversold_veto:.1f} (Prohibido abrir cortos en el piso)."
                )

            # Stop a Misa
            delta_prot = max(ticks_seguridad * tick_size, factor_atr * atr_14, 0.0015 * current_price)
            sl_level = max(high, vwap_val, m15_high) + delta_prot
            sl_calc_pct = round(max(0.40, min(4.0, (sl_level - current_price) / max(current_price, 0.0001) * 100.0)), 2)
            applied_safeguards.append(f"Stop a Misa sobre VWAP en ${sl_level:.2f} (+{ticks_seguridad} ticks holgura)")

            if len(filter_failures) == 0:
                signal = "VENDER"
                action = "SELL"

        # =========================================================================
        # 6. ASIMETRÍA MATEMÁTICA Y COSTES FINANCIEROS
        # =========================================================================
        tp_calc_pct = round(required_tp_gross_for_rr(sl_calc_pct, fee, spread, target_rr=min_rr_target), 2)
        net_tp = round(net_return_after_costs(tp_calc_pct, fee, spread), 4)

        rr_info = net_rr_metrics(tp_calc_pct, sl_calc_pct, fee, spread)
        if not rr_info["valid"] or round(rr_info["net_rr"], 2) < min_rr_target:
            filter_failures.append(
                f"Asimetría insuficiente: R:R neto {rr_info['net_rr']:.2f} < {min_rr_target:.2f} exigido tras costes."
            )

        if net_tp < min_profit_pct:
            filter_failures.append(
                f"TP neto estimado ({net_tp:.2f}%) no cubre el beneficio mínimo exigido ({min_profit_pct:.2f}%)."
            )

        candidate_eligible = (signal in {"COMPRAR", "VENDER"}) and (len(filter_failures) == 0)
        effective_net_tp = net_tp if candidate_eligible else 0.0

        if sub_peluqueo_enabled and candidate_eligible:
            applied_safeguards.append("Peluqueo 50% en TP1 (R:R >= 2.0) + Pase a Breakeven ($0 riesgo)")

        strategy_metrics = {
            "mode": self.id,
            "strategy_id": self.id,
            "sub_strategy": sub_strategy_id,
            "suggested_signal": signal,
            "signal": signal,
            "action": action,
            "bias": bias,
            "current_price": round(current_price, 4),
            "vwap": round(vwap_val, 4),
            "relative_volume": round(rvol, 2),
            "rsi_14": round(rsi_14, 2),
            "lower_wick_ratio": round(lower_wick_ratio, 4),
            "upper_wick_ratio": round(upper_wick_ratio, 4),
            "m15_high": round(m15_high, 2),
            "m15_low": round(m15_low, 2),
            "london_high": round(london_high, 2),
            "london_low": round(london_low, 2),
            "tp_gross_pct": tp_calc_pct,
            "sl_gross_pct": sl_calc_pct,
            "tp_net_pct": net_tp,
            "candidate_eligible": candidate_eligible,
            "filter_failures": filter_failures,
            "applied_safeguards": applied_safeguards,
            "peluqueo_active": True,
        }

        return (strategy_metrics, effective_net_tp, candidate_eligible, filter_failures, min_profit_pct)

    def _build_metrics(
        self,
        signal: str,
        action: str,
        bias: str,
        sub_strategy: str,
        tp_calc: float,
        sl_calc: float,
        net_tp: float,
        failures: List[str],
        safeguards: List[str],
        current_price: float,
        vwap_val: float,
    ) -> Dict[str, Any]:
        return {
            "mode": self.id,
            "strategy_id": self.id,
            "sub_strategy": sub_strategy,
            "suggested_signal": signal,
            "signal": signal,
            "action": action,
            "bias": bias,
            "current_price": round(current_price, 4),
            "vwap": round(vwap_val, 4),
            "tp_gross_pct": tp_calc,
            "sl_gross_pct": sl_calc,
            "tp_net_pct": net_tp,
            "candidate_eligible": False,
            "filter_failures": failures,
            "applied_safeguards": safeguards,
            "peluqueo_active": False,
        }
