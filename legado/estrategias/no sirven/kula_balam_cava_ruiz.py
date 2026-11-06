"""
Estrategia Cuantitativa: Kula Balam · Alex Ruiz & José Luis Cava.
Módulo oficial integrado en el catálogo de estrategias de Kula Balam.

Doctrina y Fundamentos Cuantitativos:
1. Módulo Kula (Estructura Fractal de Alex Ruiz):
   - Jerarquía de temporalidades: 1D (Contexto) -> 1H (Zona) -> 5M (Gatillo).
   - Zona Dorada de Fibonacci: Retrocesos del 0.50 al 0.75 del impulso previo.
   - Quiebre y cierre sobre la EMA 50 al cierre de vela.
2. Doctrina de Parqué de José Luis Cava:
   - Clúster de Volumen Horizontal a la izquierda (nodo de alta densidad / punto medio institucional).
   - Agotamiento de la Onda C de Elliott (quiebre de directriz 2-4 y entrada en micro-quinta onda).
   - Gatillo de Fallo de MACD (mínimo decreciente o barrida en precio con suelos crecientes en MACD / histograma).
   - Divergencia de RSI con secado de volumen (RVOL < 0.80 en la corrección).
   - Inviolabilidad del Stop: Mínimo técnico restando margen dinámico de invalidación (2 ticks adaptativos).
   - Gestión de Salida: Peluqueo del 50% en TP1 (R:R >= 1:2.0) + Pase a Breakeven ($0 riesgo) + Trailing del remanente.
3. 5 Compuertas de Veto Inmediato ("Si no veo lo que quiero ver, NO VOY").
"""

from typing import Any, Dict, List, Optional, Set, Tuple
import pandas as pd
from backend.estrategias.base import EstrategiaBase
from backend.estrategias.config_manager import StrategyConfigManager
from backend.quant_risk import MIN_NET_RR, net_return_after_costs, net_rr_metrics, required_tp_gross_for_rr

KULA_BALAM_TIMEFRAMES: Set[str] = {"1m", "5m", "15m", "1h", "4h", "1d"}


class KulaBalamCavaRuiz(EstrategiaBase):
    """
    Estrategia Cuantitativa Táctica: Kula Balam (Alex Ruiz + José Luis Cava).
    """

    id: str = "kula_balam_cava_ruiz"
    nombre: str = "🐅 Kula Balam: Cava & Ruiz (La Tríada 1D-1H-5M & Fallo MACD)"
    descripcion: str = (
        "Fusión cuantitativa del Módulo Kula (Tríada fractal de Alex Ruiz 1D-1H-5M, Zona Dorada Fibonacci "
        "0.50-0.75 y EMA 50) con la doctrina de parqué de José Luis Cava (Clúster de volumen horizontal, "
        "Agotamiento Onda C, Fallo de MACD, secado de volumen RVOL < 0.8, Stop Loss con margen de 2 ticks "
        "adaptativos y salida escalonada con Breakeven y Trailing libre)."
    )
    autor: str = "Alex Ruiz & José Luis Cava (Kula Balam Quant)"
    activos_recomendados: List[str] = [
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "BNB/USDT",
        "SPY", "QQQ", "NVDA", "AAPL", "MSFT"
    ]
    temporalidades_permitidas: Set[str] = KULA_BALAM_TIMEFRAMES
    horario_operativo: str = "24/7 Cripto | 10:30-17:00 ARG / NY Regular"

    parametros_por_defecto: Dict[str, Any] = {
        "direction_mode": "dual",       # "dual" (Long + Short), "long_only", "short_only"
        "min_rr_ratio": 2.0,            # Asimetría obligatoria R:R >= 1:2.0
        "fibo_golden_zone_min": 0.50,   # Zona dorada mínima
        "fibo_golden_zone_max": 0.75,   # Zona dorada máxima (abortar si perfora > 0.75)
        "atr_multiplier_sl": 1.5,       # Distancia mínima al Stop Loss fuera del ruido ATR
        "peluqueo_active": True,        # Cierre parcial del 50% en TP1
        "peluqueo_partial_pct": 50.0,
        "fallo_macd_strict": True,      # Exigir absorción en MACD / histograma
        "rvol_dryout_threshold": 0.85,  # Secado de volumen en la caída previa
        "ema50_filter": True,           # Cierre sobre EMA 50
        "max_sl_pct": 0.85,             # Techo máximo absoluto de Stop Loss intradiario en 5M (blindaje contra ruina)
    }

    @staticmethod
    def _calculate_ema50(series: pd.Series) -> pd.Series:
        return series.ewm(span=50, adjust=False).mean()

    @staticmethod
    def _calculate_macd(series: pd.Series) -> Tuple[pd.Series, pd.Series, pd.Series]:
        exp1 = series.ewm(span=12, adjust=False).mean()
        exp2 = series.ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=9, adjust=False).mean()
        hist = macd - signal
        return macd, signal, hist

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
        Ejecuta el embudo secuencial en 4 fases de Balam:
        Paso 1: Filtro Macro (EMA 50)
        Paso 2: Zona Dorada Fibonacci (0.50-0.75) + Clúster Horizontal de Volumen
        Paso 3: Gatillo de Confirmación (Fallo de MACD + Secado RVOL + Cierre sobre EMA 50)
        Paso 4: Verificación de Asimetría (R:R >= 1:2.0, Margen SL 2 ticks, Peluqueo TP1)
        """
        filter_failures: List[str] = []
        metrics: Dict[str, Any] = {}

        latest_raw = ind.get("latest")
        latest = latest_raw if latest_raw is not None else {}
        close_price = float(ind.get("live_price") or ind.get("price") or (latest.get("close") if hasattr(latest, "get") else 0.0) or 0.0)
        atr = float(ind.get("atr_14") or (latest.get("atr_14") if hasattr(latest, "get") else 0.0) or 0.0)
        rvol = float(ind.get("relative_volume") or (latest.get("relative_volume") if hasattr(latest, "get") else 1.0) or 1.0)
        lower_wick_ratio = float(ind.get("lower_wick_ratio") or 0.0)
        rsi_val = float(ind.get("rsi") or (latest.get("rsi") if hasattr(latest, "get") else 50.0) or 50.0)
        symbol = str(ind.get("symbol") or "BTC/USDT")

        if close_price <= 0:
            return (
                {"mode": self.id, "error": "Precio inválido o nulo"},
                0.0,
                False,
                ["Precio actual inválido para evaluación."],
                min_profit_pct,
            )

        atr_pct = (atr / close_price * 100.0) if close_price > 0 else 1.0

        # --- FASE 1: FILTRO DE CONTEXTO MACRO (EMA 50 & PENDIENTE) ---
        ema_50_val = close_price
        ema_50_prev = close_price
        has_df = df is not None and isinstance(df, pd.DataFrame) and len(df) >= 30
        if has_df:
            ema50_series = self._calculate_ema50(df["close"])
            ema_50_val = float(ema50_series.iloc[-1])
            ema_50_prev = float(ema50_series.iloc[-5]) if len(ema50_series) >= 5 else ema_50_val
        elif ind.get("sma_50"):
            ema_50_val = float(ind["sma_50"])
            ema_50_prev = ema_50_val

        direction_pref = str(self.parametros_por_defecto.get("direction_mode", "dual")).lower()

        # Determinación de dirección operativa (Alex Ruiz: Tríada 1D/1H)
        # La tendencia se define por la pendiente estructural de la EMA 50 y la posición respecto a ella:
        # En series cortas (< 50 velas), la EMA50 inicial oscila con micro-ruido. Usamos una ventana de 15 velas
        # para medir si la tendencia estructural viene subiendo desde la base (swing_high reciente) o bajando.
        is_ema_falling = (ema_50_val < ema_50_prev * 0.995)
        is_ema_rising = (ema_50_val > ema_50_prev * 1.0005)
        
        # Enfoque Alex Ruiz: si el swing general viene de mínimos crecientes (máximo de 60 velas en la 2da mitad),
        # el régimen macro es alcista y cualquier caída profunda es una rotura de soporte en LONG.
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
        else:
            # Modo "dual":
            # Si el swing previo fue alcista (impulso hacia arriba), evaluamos retroceso LONG
            # (para detectar si está en Zona Dorada o si colapsó por Estructura Rota).
            # Solo evaluamos SHORT si el impulso macro previo fue netamente bajista y el precio rebota desde mínimos.
            if is_ema_falling and not swing_bias_long and close_price < (ema_50_val * 0.998):
                target_side = "SHORT"
                macro_bias = "BAJISTA"
            elif swing_bias_long:
                target_side = "LONG"
                macro_bias = "ALCISTA" if close_price >= (ema_50_val * 0.998) else "CORRECCION"
            else:
                target_side = "SHORT" if close_price < ema_50_val else "LONG"
                macro_bias = "TRANSICION"

        metrics["macro_bias_1d"] = macro_bias
        metrics["target_side"] = target_side
        metrics["sub_strategy"] = f"cava_ruiz_{target_side.lower()}"
        metrics["ema_50"] = round(ema_50_val, 2)
        metrics["close_vs_ema50"] = round(((close_price - ema_50_val) / ema_50_val) * 100.0, 2)

        # Validación de subestrategias activas según el panel táctico del operador
        if target_side == "SHORT" and not StrategyConfigManager.is_sub_enabled(self.id, "operar_short"):
            filter_failures.append("Subestrategia deshabilitada: el operador desactivó la operativa en corto (SHORT) en el panel táctico.")
        if target_side == "LONG" and not StrategyConfigManager.is_sub_enabled(self.id, "operar_long"):
            filter_failures.append("Subestrategia deshabilitada: el operador desactivó la operativa en largo (LONG) en el panel táctico.")

        # --- FASE 2: ZONA DORADA FIBONACCI DUAL (0.50 A 0.75) + CLÚSTER HORIZONTAL ---
        swing_high = close_price * 1.03
        swing_low = close_price * 0.97
        cluster_horizontal = close_price * 0.995

        if has_df:
            lookback = min(len(df), 60)
            tail_df = df.tail(lookback)
            swing_high = float(tail_df["high"].max())
            swing_low = float(tail_df["low"].min())

            # Localizar el Clúster de Volumen Horizontal a la izquierda (nodo de mayor volumen)
            if "volume" in tail_df.columns:
                max_vol_row = tail_df.sort_values(by="volume", ascending=False).iloc[0]
                cluster_horizontal = float((max_vol_row["open"] + max_vol_row["close"]) / 2.0)
            else:
                cluster_horizontal = (swing_high + swing_low) / 2.0

        swing_range = max(0.0001, swing_high - swing_low)

        if target_side == "LONG":
            # En largo: retroceso medido desde el máximo hacia abajo
            current_retracement = (swing_high - close_price) / swing_range
            fibo_50 = swing_high - (0.50 * swing_range)
            fibo_618 = swing_high - (0.618 * swing_range)
            fibo_75 = swing_high - (0.75 * swing_range)
            in_golden_zone = bool(0.45 <= current_retracement <= 0.78)
            if current_retracement > 0.78:
                filter_failures.append(
                    f"Estructura rota: retroceso {current_retracement:.2f} perforó el 0.75 de Fibonacci (Fase 2 abortada)."
                )
            elif current_retracement < 0.45:
                filter_failures.append(
                    f"Precio caro: retroceso {current_retracement:.2f} aún no alcanza la Zona Dorada 0.50-0.75."
                )
        else:
            # En corto: rebote correctivo medido desde el mínimo hacia arriba (Alex Ruiz Short)
            current_retracement = (close_price - swing_low) / swing_range
            fibo_50 = swing_low + (0.50 * swing_range)
            fibo_618 = swing_low + (0.618 * swing_range)
            fibo_75 = swing_low + (0.75 * swing_range)
            in_golden_zone = bool(0.45 <= current_retracement <= 0.78)
            if current_retracement > 0.78:
                filter_failures.append(
                    f"Estructura rota: rebote bajista {current_retracement:.2f} superó el 0.75 de Fibonacci (Fase 2 abortada)."
                )
            elif current_retracement < 0.45:
                filter_failures.append(
                    f"Precio en suelo: rebote {current_retracement:.2f} aún no alcanza la Zona Dorada 0.50-0.75 para vender caro."
                )

        metrics["swing_high"] = round(swing_high, 2)
        metrics["swing_low"] = round(swing_low, 2)
        metrics["fibo_retracement_ratio"] = round(current_retracement, 3)
        metrics["fibo_50"] = round(fibo_50, 2)
        metrics["fibo_618"] = round(fibo_618, 2)
        metrics["fibo_75"] = round(fibo_75, 2)
        metrics["cluster_volumen_izq"] = round(cluster_horizontal, 2)
        metrics["in_golden_zone"] = in_golden_zone

        # --- FASE 3: VERIFICACIÓN DEL GATILLO (FALLO DE MACD + SECADO + CIERRE EMA 50) ---
        fallo_macd_detected = False
        secado_volumen_detected = False

        if has_df:
            macd_line, sig_line, hist_line = self._calculate_macd(df["close"])
            if len(hist_line) >= 3:
                h_curr = float(hist_line.iloc[-1])
                h_prev = float(hist_line.iloc[-2])
                h_prev2 = float(hist_line.iloc[-3]) if len(hist_line) >= 4 else h_prev
                if target_side == "LONG":
                    # Fallo de MACD Alcista: histograma sube o MACD se curva hacia arriba en descuento
                    fallo_macd_detected = bool(
                        (h_curr > h_prev)
                        or (h_curr > h_prev2)
                        or (float(macd_line.iloc[-1]) > float(macd_line.iloc[-2]))
                    )
                else:
                    # Fallo de MACD Bajista: agotamiento del rebote, histograma desciende o MACD gira a la baja
                    fallo_macd_detected = bool(
                        (h_curr < h_prev)
                        or (h_curr < h_prev2)
                        or (float(macd_line.iloc[-1]) < float(macd_line.iloc[-2]))
                    )
            else:
                fallo_macd_detected = True

            # Secado de volumen en el movimiento previo (RVOL < 0.85)
            if "volume" in df.columns and len(df) >= 5:
                total_vol_sum = float(df["volume"].tail(20).sum() or 0.0)
                if "=X" in symbol.upper() and total_vol_sum <= 0.0:
                    secado_volumen_detected = True
                else:
                    recent_vol_avg = float(df["volume"].tail(20).mean() or 1.0)
                    if target_side == "LONG":
                        prior_vols = [
                            float(df["volume"].iloc[-i]) / recent_vol_avg
                            for i in range(2, min(5, len(df)))
                            if df["close"].iloc[-i] < df["open"].iloc[-i]
                        ]
                    else:
                        prior_vols = [
                            float(df["volume"].iloc[-i]) / recent_vol_avg
                            for i in range(2, min(5, len(df)))
                            if df["close"].iloc[-i] > df["open"].iloc[-i]
                        ]
                    secado_volumen_detected = bool(any(v < 0.85 for v in prior_vols) if prior_vols else (rvol <= 1.2))
            else:
                secado_volumen_detected = bool(rvol <= 1.2) or ("=X" in symbol.upper())
        else:
            fallo_macd_detected = True
            secado_volumen_detected = True

        metrics["fallo_macd_confirmado"] = fallo_macd_detected
        metrics["secado_volumen_previo"] = secado_volumen_detected

        if self.parametros_por_defecto.get("fallo_macd_strict", True) and not fallo_macd_detected:
            filter_failures.append(
                "Gatillo denegado: Fallo de MACD aún sin confirmar (presión vendedora activa)."
                if target_side == "LONG"
                else "Gatillo denegado: Fallo de MACD bajista sin confirmar (presión compradora aún activa)."
            )

        # Cierre sobre EMA 50 (LONG) o bajo EMA 50 (SHORT) (Regla Alex Ruiz)
        if target_side == "LONG":
            close_ema50_ok = bool(close_price >= (ema_50_val * 0.999))
            if self.parametros_por_defecto.get("ema50_filter", True) and not close_ema50_ok:
                filter_failures.append(f"Vela sin confirmar: precio ({close_price:.2f}) cerró debajo de la EMA 50 ({ema_50_val:.2f}).")
        else:
            close_ema50_ok = bool(close_price <= (ema_50_val * 1.001))
            if self.parametros_por_defecto.get("ema50_filter", True) and not close_ema50_ok:
                filter_failures.append(f"Vela sin confirmar: precio ({close_price:.2f}) cerró por encima de la EMA 50 ({ema_50_val:.2f}).")
        metrics["cruce_ema50_confirmado"] = close_ema50_ok

        # Patrón de 3 Velas en 5M (V1 impulso -> V2 pausa -> V3 confirmación)
        if has_df and len(df) >= 3:
            v2 = df.iloc[-2]
            v3 = df.iloc[-1]
            if target_side == "LONG":
                # V3 supera el máximo de V2
                if not (float(v3["close"]) > float(v2["high"])):
                    filter_failures.append(f"Gatillo 3 Velas incompleto: cierre V3 ({v3['close']:.2f}) no superó máximo de V2 ({v2['high']:.2f}).")
            else:
                # V3 perfora el mínimo de V2
                if not (float(v3["close"]) < float(v2["low"])):
                    filter_failures.append(f"Gatillo 3 Velas incompleto: cierre V3 ({v3['close']:.2f}) no perforó mínimo de V2 ({v2['low']:.2f}).")

        # --- FASE 4: COMPUERTAS DE VETO INMEDIATO (ABSTENCIÓN OBLIGATORIA) ---
        if target_side == "LONG":
            # Veto 1: Cuchillo cayendo (velas rojas sin mecha inferior)
            if lower_wick_ratio < 0.15 and close_price < ema_50_val:
                filter_failures.append("Veto Cuchillo Cayendo: mecha de absorción insuficiente (< 15%).")
            # Veto 2: Bull trap (mecha superior >= 50%)
            if has_df:
                last_candle = df.iloc[-1]
                tot_h_l = float(last_candle["high"] - last_candle["low"])
                if tot_h_l > 0:
                    upper_wick = float(last_candle["high"] - max(last_candle["open"], last_candle["close"]))
                    if (upper_wick / tot_h_l) >= 0.50:
                        filter_failures.append("Veto Bull Trap: mecha superior >= 50% del rango de vela.")
        else:
            # Veto 1: Cohete subiendo sin mecha superior (no venderse contra impulso verde pleno)
            upper_wick_ratio = float(ind.get("upper_wick_ratio") or 0.0)
            if upper_wick_ratio < 0.15 and close_price > ema_50_val:
                filter_failures.append("Veto Cohete Alcista: mecha de rechazo superior insuficiente (< 15%).")
            # Veto 2: Bear trap (mecha inferior >= 50% = absorción compradora)
            if has_df:
                last_candle = df.iloc[-1]
                tot_h_l = float(last_candle["high"] - last_candle["low"])
                if tot_h_l > 0:
                    lower_wick = float(min(last_candle["open"], last_candle["close"]) - last_candle["low"])
                    if (lower_wick / tot_h_l) >= 0.50:
                        filter_failures.append("Veto Bear Trap: mecha inferior >= 50% del rango de vela (trampa de osos).")

        # --- FASE 5: GESTIÓN DE RIESGO ASIMÉTRICA (STOP A MISA -2 TICKS/PIPS & PELUQUEO) ---
        is_forex = "=X" in symbol.upper()
        target_rr = float(self.parametros_por_defecto.get("min_rr_ratio", 2.0))

        if is_forex:
            # Calibración cuantitativa en Pips y ATR para Forex (EURUSD=X, GBPUSD=X, USDJPY=X, etc.)
            pip_size = 0.01 if "JPY" in symbol.upper() else 0.0001
            invalid_margin_pts = max(2.0 * pip_size, 0.20 * atr)
            invalid_margin_pct = (invalid_margin_pts / close_price) * 100.0

            min_fx_sl_pct = 0.12  # ~13 pips piso mínimo anti-ruido
            max_fx_sl_pct = 0.45  # ~48 pips techo intradía razonable
            if target_side == "LONG":
                raw_swing_dist_pct = ((close_price - swing_low) / close_price) * 100.0 if close_price > swing_low else 0.15
            else:
                raw_swing_dist_pct = ((swing_high - close_price) / close_price) * 100.0 if swing_high > close_price else 0.15

            dist_to_swing_pct = max(min_fx_sl_pct, min(max_fx_sl_pct, raw_swing_dist_pct))
            technical_sl_pct = min(max_fx_sl_pct, dist_to_swing_pct + invalid_margin_pct)

            fx_atr_sl_pct = max(min_fx_sl_pct, 1.5 * atr_pct)
            calculated_sl_pct = round(max(fx_atr_sl_pct, technical_sl_pct), 2)

            min_gross_tp_for_rr = required_tp_gross_for_rr(calculated_sl_pct, fee, spread, target_rr=target_rr)
            calculated_tp_pct = round(max(min_gross_tp_for_rr, 3.0 * atr_pct), 2)
            effective_min_profit_pct = min(min_profit_pct, 0.20)

            sl_pips = round((close_price * (calculated_sl_pct / 100.0)) / pip_size, 1)
            tp_pips = round((close_price * (calculated_tp_pct / 100.0)) / pip_size, 1)
            metrics["forex_sl_pips"] = sl_pips
            metrics["forex_tp_pips"] = tp_pips
        else:
            # Margen adaptativo de 2 ticks contra Stop Hunting institucional (Cripto / Acciones)
            tick_size = 0.01
            invalid_margin_pts = max(2.0 * tick_size, 0.20 * atr, 0.0015 * close_price)
            invalid_margin_pct = (invalid_margin_pts / close_price) * 100.0

            # En 5M / Intradía, el Stop a Misa se ancla a la microestructura local (últimas 3 a 7 velas),
            # no al extremo de hace 5 horas (lookback 60), para evitar distancias gigantescas y ruina matemática.
            local_tail = df.tail(min(len(df), 7)) if has_df else None
            if local_tail is not None and len(local_tail) >= 3:
                local_high = float(local_tail["high"].max())
                local_low = float(local_tail["low"].min())
            else:
                local_high = swing_high
                local_low = swing_low

            if target_side == "LONG":
                dist_to_local_pct = max(0.20, ((close_price - local_low) / close_price) * 100.0)
            else:
                dist_to_local_pct = max(0.20, ((local_high - close_price) / close_price) * 100.0)

            technical_sl_pct = dist_to_local_pct + invalid_margin_pct

            # Candado de Riesgo Máximo Intradía: adaptativo a la volatilidad real del activo (tope 3.0x ATR%)
            # En XRP (ATR 0.25%), el tope es 0.85% (bloqueando stops disparatados de 2.10%).
            # En BTC (ATR 1.0%), el tope es ~3.0% (permitiendo volatilidad sana).
            max_intraday_sl = max(float(self.parametros_por_defecto.get("max_sl_pct", 0.85)), 3.0 * atr_pct)
            min_intraday_sl = max(0.20, 1.0 * atr_pct)

            # El Stop Loss queda estrictamente acotado entre el piso anti-ruido y el techo seguro
            calculated_sl_pct = round(min(max_intraday_sl, max(min_intraday_sl, technical_sl_pct)), 2)

            # TP1 calculado para asimetría R:R >= 2.0 tras comisiones
            min_gross_tp_for_rr = required_tp_gross_for_rr(calculated_sl_pct, fee, spread, target_rr=target_rr)
            calculated_tp_pct = round(max(tp, min_gross_tp_for_rr), 2)
            effective_min_profit_pct = min_profit_pct

        net_tp = round(net_return_after_costs(calculated_tp_pct, fee, spread), 4)
        net_sl = round(net_return_after_costs(-calculated_sl_pct, fee, spread), 4)
        minimum_strategy_net_tp = max(effective_min_profit_pct, (calculated_sl_pct * 2.0) - round_trip_cost)

        rr_info = net_rr_metrics(calculated_tp_pct, calculated_sl_pct, fee, spread)
        effective_rr = round(float(rr_info.get("net_rr") or 0.0), 2)

        metrics["sl_margin_2ticks_pct"] = round(invalid_margin_pct, 3)
        metrics["sl_gross_pct"] = calculated_sl_pct
        metrics["tp_gross_pct"] = calculated_tp_pct
        metrics["tp1_cluster_pct"] = round(calculated_sl_pct * target_rr, 2)
        metrics["net_rr"] = effective_rr
        metrics["peluqueo_rule"] = "50% liquidado en TP1 + Stop a Breakeven ($0 riesgo) + Trailing libre del remanente"

        if net_tp < effective_min_profit_pct:
            filter_failures.append(f"Rendimiento neto (+{net_tp:.2f}%) inferior al umbral mínimo (+{effective_min_profit_pct:.2f}%).")

        if not rr_info.get("valid") or effective_rr < MIN_NET_RR:
            filter_failures.append(f"R:R neto {effective_rr:.2f} < {MIN_NET_RR:.2f} tras comisiones y spread.")

        candidate_eligible = (len(filter_failures) == 0)
        signal = ("COMPRAR" if target_side == "LONG" else "SHORT") if candidate_eligible else "MANTENER"
        side = target_side if candidate_eligible else "NEUTRAL"
        effective_net_tp = net_tp if candidate_eligible else 0.0

        strategy_metrics = {
            "mode": self.id,
            "side": side,
            "sub_strategy": f"cava_ruiz_{target_side.lower()}",
            "setup": f"Kula Balam (Tríada 1D-1H-5M + Cava Fallo MACD · {target_side})",
            "current_price": round(close_price, 2),
            "macro_bias_1d": macro_bias,
            "target_side": target_side,
            "ema_50": round(ema_50_val, 2),
            "in_golden_zone": in_golden_zone,
            "fibo_retracement": round(current_retracement, 3),
            "cluster_volumen_izq": round(cluster_horizontal, 2),
            "fallo_macd_confirmado": fallo_macd_detected,
            "secado_volumen_previo": secado_volumen_detected,
            "cruce_ema50_confirmado": close_ema50_ok,
            "sl_margin_2ticks_pct": round(invalid_margin_pct, 3),
            "peluqueo_rule": "50% liquidado en TP1 + Stop a Breakeven ($0 riesgo) + Trailing libre del remanente",
            "sl_gross_pct": calculated_sl_pct,
            "sl_net_pct": net_sl,
            "tp_gross_pct": calculated_tp_pct,
            "tp_net_pct": net_tp,
            "net_rr_ratio": effective_rr,
            "minimum_net_tp_pct": minimum_strategy_net_tp,
            "suggested_signal": signal,
            "policy": f"Tríada Kula {target_side} (1D-1H-5M) + Gatillo Cava con Stop -2 ticks y Peluqueo TP1 (R:R >= 1:2.0)",
        }

        return (strategy_metrics, effective_net_tp, candidate_eligible, filter_failures, minimum_strategy_net_tp)
