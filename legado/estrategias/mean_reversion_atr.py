"""
Estrategia Cuantitativa: Reversión a la Media + ATR (Plan Argon).
Reglas deterministas centralizadas: Z-Score <= -2.0, EMA200 alcista, absorción, RVOL y costos cubiertos.
"""

from typing import Any, Dict, List, Optional, Set, Tuple
from backend.estrategias.base import EstrategiaBase
from backend.quant_risk import MIN_NET_RR, net_return_after_costs, net_rr_metrics

ATR_STRATEGY_TIMEFRAMES: Set[str] = {"15m", "1h"}
ATR_Z_SCORE_THRESHOLD: float = -2.0
ATR_LOWER_WICK_RATIO_MIN: float = 0.25
ATR_RELATIVE_VOLUME_MAX: float = 3.5
ATR_TP_ATR_MULTIPLIER: float = 4.0
ATR_SL_ATR_MULTIPLIER: float = 1.5
ATR_COST_COVERAGE_MULTIPLIER: float = 3.5
ATR_MIN_NET_TP_PCT: float = 0.5


# Parámetros para Camino A: Pullback en Tendencia Alcista
ATR_PULLBACK_Z_MIN: float = -1.2
ATR_PULLBACK_Z_MAX: float = -0.4
ATR_PULLBACK_LOWER_WICK_MIN: float = 0.20


class MeanReversionATR(EstrategiaBase):
    id: str = "mean_reversion_atr"
    long_entries_suspended: bool = True  # Medida Inmediata 1: Suspensión preventiva de compras Long
    nombre: str = "Reversión a la Media + ATR"
    descripcion: str = (
        "Estrategia estadística con doble camino cuantitativo (OR): "
        "Camino 1: Pullback saludable en tendencia alcista (Precio > EMA200, Z-Score entre -1.2 y -0.4). "
        "Camino 2: Rebote de pánico extremo / capitulación (Z-Score ≤ -2.0 con absorción institucional). "
        "Ambos caminos exigen mecha de absorción y cobertura estricta de costos con múltiplos ATR."
    )
    autor: str = "Algoritmo Cuantitativo"
    activos_recomendados: List[str] = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "SPY", "QQQ"]
    temporalidades_permitidas: Set[str] = ATR_STRATEGY_TIMEFRAMES
    horario_operativo: str = "24/7 (Mercados Cripto y Horario Bursátil)"
    parametros_por_defecto: Dict[str, Any] = {
        "z_score_threshold": ATR_Z_SCORE_THRESHOLD,
        "pullback_z_range": [ATR_PULLBACK_Z_MIN, ATR_PULLBACK_Z_MAX],
        "tp_multiplier": ATR_TP_ATR_MULTIPLIER,
        "sl_multiplier": ATR_SL_ATR_MULTIPLIER,
        "cost_coverage_multiplier": ATR_COST_COVERAGE_MULTIPLIER,
    }

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
        latest = ind["latest"]
        atr_14 = ind["atr_14"]
        z_score = ind["z_score"]
        ema_200_value = ind["ema_200_value"]
        ema_200_slope_pct = ind["ema_200_slope_pct"]
        lower_wick_ratio = ind["lower_wick_ratio"]
        relative_volume = ind["relative_volume"]
        tf_label = ind.get("timeframe") or "15m"
        live_px = ind.get("live_price")
        live_txt = f" [Tick vivo: ${live_px:.2f}]" if (live_px is not None and live_px > 0) else ""

        if atr_14 is None or atr_14 <= 0:
            tp_gross_pct = None
            sl_gross_pct = None
            strategy_net_tp = None
            strategy_net_sl = None
        else:
            tp_gross_pct = (ATR_TP_ATR_MULTIPLIER * atr_14 / float(latest["close"])) * 100
            sl_gross_pct = (ATR_SL_ATR_MULTIPLIER * atr_14 / float(latest["close"])) * 100
            strategy_net_tp = round(net_return_after_costs(tp_gross_pct, fee, spread), 4)
            strategy_net_sl = round(net_return_after_costs(-sl_gross_pct, fee, spread), 4)

        minimum_strategy_net_tp = max(ATR_MIN_NET_TP_PCT, min_profit_pct)

        # 1. Compuertas comunes innegociables (gestión de peajes, asimetría y viabilidad de capital)
        common_failures: List[str] = []
        if self.long_entries_suspended:
            common_failures.append(
                "Entradas en LONG suspendidas de inmediato en 'mean_reversion_atr': "
                "Prohibido comprar reversión a la media en marcos de 15m durante tendencias bajistas (Medida Inmediata 1)."
            )
        if tp_gross_pct is None or tp_gross_pct < round_trip_cost * ATR_COST_COVERAGE_MULTIPLIER:
            common_failures.append(
                f"Recorrido bruto al TP no cubre {ATR_COST_COVERAGE_MULTIPLIER}x los costos ida/vuelta"
            )
        if strategy_net_tp is None or strategy_net_tp < minimum_strategy_net_tp:
            common_failures.append(
                f"TP neto no alcanza el mínimo de {minimum_strategy_net_tp:.3f}%"
            )
        if tp_gross_pct is not None and sl_gross_pct is not None:
            rr_info = net_rr_metrics(tp_gross_pct, sl_gross_pct, fee, spread)
            if not rr_info["valid"] or rr_info["net_rr"] < MIN_NET_RR:
                common_failures.append(
                    f"R:R neto {rr_info['net_rr']:.2f} < {MIN_NET_RR:.2f} tras costos (acierto de equilibrio {rr_info['breakeven_win_rate'] * 100:.0f}%)"
                )

        # 2. Bifurcación en Dos Caminos Cuantitativos (OR Lógico)
        # Camino A: Pullback en Tendencia Alcista Sólida
        es_tendencia = (
            ema_200_value is not None
            and float(latest["close"]) > ema_200_value
            and ema_200_slope_pct is not None
            and ema_200_slope_pct >= 0
        )
        es_pullback = (z_score is not None and ATR_PULLBACK_Z_MIN <= z_score <= ATR_PULLBACK_Z_MAX)
        mecha_pullback = (lower_wick_ratio is not None and lower_wick_ratio >= ATR_PULLBACK_LOWER_WICK_MIN)
        volumen_tranquilo = (relative_volume is not None and relative_volume <= ATR_RELATIVE_VOLUME_MAX)
        setup_tendencia = es_tendencia and es_pullback and mecha_pullback and volumen_tranquilo

        # Camino B: Rebote por Pánico Extremo / Capitulación
        # En pánico extremo el precio suele perforar la EMA200 y el volumen explota por liquidaciones;
        # NO se limita el volumen máximo (libertad total para absorber flash crashes con alto RVOL).
        es_panico = (z_score is not None and z_score <= ATR_Z_SCORE_THRESHOLD)
        mecha_panico = (lower_wick_ratio is not None and lower_wick_ratio >= ATR_LOWER_WICK_RATIO_MIN)
        volumen_panico = (relative_volume is not None)
        setup_panico = es_panico and mecha_panico and volumen_panico

        setup_valido = setup_tendencia or setup_panico

        if setup_valido and not common_failures:
            quant_candidate_eligible = True
            quant_filter_failures: List[str] = []
            setup_name = "Pullback en Tendencia Alcista" if setup_tendencia else "Rebote de Pánico Extremo (Z ≤ -2.0)"
        else:
            quant_candidate_eligible = False
            quant_filter_failures = list(common_failures)
            setup_name = None
            if not setup_valido:
                if z_score is None:
                    quant_filter_failures.append("Z-Score no disponible")
                elif relative_volume is None:
                    quant_filter_failures.append("Volumen relativo no disponible")
                elif z_score > ATR_PULLBACK_Z_MAX:
                    quant_filter_failures.append(
                        f"Z-Score ({z_score:.2f}) sin retroceso ni pánico (requiere Pullback [{ATR_PULLBACK_Z_MIN}, {ATR_PULLBACK_Z_MAX}] o Pánico ≤ {ATR_Z_SCORE_THRESHOLD})"
                    )
                elif -2.0 < z_score < ATR_PULLBACK_Z_MIN:
                    if not es_tendencia:
                        quant_filter_failures.append(
                            f"Z-Score ({z_score:.2f}) bajo EMA200 sin pánico extremo (≤ {ATR_Z_SCORE_THRESHOLD})"
                        )
                    elif not mecha_pullback:
                        quant_filter_failures.append(
                            f"Mecha inferior ({lower_wick_ratio if lower_wick_ratio is not None else 'N/A'}) menor a {ATR_PULLBACK_LOWER_WICK_MIN}"
                        )
                    elif not volumen_tranquilo:
                        quant_filter_failures.append(
                            f"Volumen en retroceso excesivo ({relative_volume:.2f} > {ATR_RELATIVE_VOLUME_MAX})"
                        )
                elif es_panico and not mecha_panico:
                    quant_filter_failures.append(
                        f"Pánico extremo (Z={z_score:.2f}) sin mecha de absorción suficiente ({lower_wick_ratio if lower_wick_ratio is not None else 'N/A'} < {ATR_LOWER_WICK_RATIO_MIN})"
                    )
                elif not es_tendencia:
                    quant_filter_failures.append(f"Cierre de vela {tf_label} bajo EMA200 o pendiente negativa (sin pánico extremo){live_txt}")
                elif not volumen_tranquilo:
                    quant_filter_failures.append(
                        f"Volumen en retroceso excesivo ({relative_volume:.2f} > {ATR_RELATIVE_VOLUME_MAX})"
                    )

        effective_net_tp = strategy_net_tp if strategy_net_tp is not None else 0.0

        strategy_metrics = {
            "mode": self.id,
            "z_score": round(z_score, 4) if z_score is not None else None,
            "z_score_threshold": ATR_Z_SCORE_THRESHOLD,
            "ema_200": round(ema_200_value, 6) if ema_200_value is not None else None,
            "ema_200_slope_pct": round(ema_200_slope_pct, 6) if ema_200_slope_pct is not None else None,
            "atr_14": round(atr_14, 8) if atr_14 is not None else None,
            "relative_volume": round(relative_volume, 4) if relative_volume is not None else None,
            "lower_wick_ratio": round(lower_wick_ratio, 4) if lower_wick_ratio is not None else None,
            "tp_gross_pct": round(tp_gross_pct, 6) if tp_gross_pct is not None else None,
            "sl_gross_pct": round(sl_gross_pct, 6) if sl_gross_pct is not None else None,
            "tp_net_pct": strategy_net_tp,
            "sl_net_pct": strategy_net_sl,
            "minimum_net_tp_pct": round(minimum_strategy_net_tp, 4),
            "setup": setup_name,
            "candidate_eligible": quant_candidate_eligible,
            "filter_failures": quant_filter_failures,
        }

        return (
            strategy_metrics,
            effective_net_tp,
            quant_candidate_eligible,
            quant_filter_failures,
            minimum_strategy_net_tp,
        )
