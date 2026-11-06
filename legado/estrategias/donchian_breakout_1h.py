"""
===============================================================================
ESTRATEGIA CUANTITATIVA: DONCHIAN BREAKOUT 1H (FÓRMULA EMPÍRICA VALIDADA)
===============================================================================
Ecosistema: KULA · BALAM
Basado en: Especificación Técnica de Motor Matemático Validado sobre BTC/USDT 1H.
Ventaja estadística: Profit Factor 1.43 base / 1.72 con filtro de compresión y volumen.

Mecánica Operativa:
1. Canal Donchian de 20 períodos sobre velas cerradas previas (shift 1 para evitar sesgo del futuro).
   - donchian_high = high.shift(1).rolling(20).max()
   - donchian_low = low.shift(1).rolling(20).min()
   - donchian_mid = (donchian_high + donchian_low) / 2.0
   - donchian_width = donchian_high - donchian_low
2. Filtros Obligatorios de Entrada (TODAS en confluencia estricta):
   - cond_quiebre: close > donchian_high (Ruptura alcista real)
   - cond_tendencia: close > EMA_100 (Tendencia institucional a favor)
   - cond_compresion: donchian_width <= (4.5 * atr_14) (Descarta canales sobre-extendidos / agotados)
   - cond_volumen: volume > (SMA20_volume * 1.25) (Expansión de volumen institucional)
3. Reglas de Salida Estricta:
   - Stop Loss Inicial: precio_entrada - (1.5 * atr_14)
   - Salida Dinámica (MID_EXIT): Si close < donchian_mid (corte por mitad de canal)
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

DONCHIAN_STRATEGY_TIMEFRAMES: Set[str] = {"1h", "4h"}


class DonchianBreakout1H(EstrategiaBase):
    """
    Motor Matemático Validado Donchian 1H (Breakout + EMA100 + Compresión ATR + Volumen SMA20)
    con salida dinámica por mitad de canal (Donchian Mid).
    """

    id: str = "donchian_breakout_1h"
    nombre: str = "🛡️ Donchian Breakout 1H (EMA 100 + Compresión ATR + Mid-Exit)"
    descripcion: str = (
        "Motor matemático validado empíricamente sobre BTC/USDT en 1H con ventaja estadística comprobada "
        "(Profit Factor 1.43 a 1.72). Exige ruptura del canal Donchian de 20 períodos con shift 1, alineación "
        "sobre EMA 100, filtro de compresión previa Donchian Width <= 4.5 x ATR y volumen expansivo > 1.25 x SMA20. "
        "Aplica Stop Loss inicial en 1.5 x ATR y salida dinámica por mitad de canal (Donchian Mid)."
    )
    autor: str = "Arquitectura Cuantitativa Kula-Balam (Validación Empírica)"
    activos_recomendados: List[str] = [
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "QQQ", "SPY"
    ]
    temporalidades_permitidas: Set[str] = DONCHIAN_STRATEGY_TIMEFRAMES
    horario_operativo: str = "Swing / Intradía 1H (24/7 Cripto / Rueda bursátil)"

    parametros_por_defecto: Dict[str, Any] = {
        "timeframe": "1h",
        "donchian_period": 20,
        "ema_trend_period": 100,
        "compression_atr_mult": 4.5,
        "volume_ma_mult": 1.25,
        "atr_sl_mult": 1.5,
        "min_rr_ratio": 2.0,
        "target_tp_atr_mult": 3.0,
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
        latest = ind.get("latest", {})
        current_price = float(ind.get("live_price") or latest.get("close") or 0.0)
        tf_label = str(ind.get("timeframe") or "1h").lower()

        # Inyectar configuración desde StrategyConfigManager
        cfg_mgr = StrategyConfigManager()
        cfg = cfg_mgr.get_strategy_config(self.id)
        params = cfg.get("parameters", self.parametros_por_defecto)
        sub_strats = cfg.get("sub_strategies", {})

        allow_long = sub_strats.get("operar_long", {}).get("enabled", True)
        require_ema_trend = sub_strats.get("filtro_ema100", {}).get("enabled", True)
        require_compression = sub_strats.get("filtro_compresion_atr", {}).get("enabled", True)
        require_volume = sub_strats.get("filtro_volumen_expansion", {}).get("enabled", True)
        require_mid_exit = sub_strats.get("salida_donchian_mid", {}).get("enabled", True)

        donchian_period = int(params.get("donchian_period", 20))
        ema_trend_period = int(params.get("ema_trend_period", 100))
        compression_mult = float(params.get("compression_atr_mult", 4.5))
        vol_mult = float(params.get("volume_ma_mult", 1.25))
        atr_sl_mult = float(params.get("atr_sl_mult", 1.5))
        target_tp_mult = float(params.get("target_tp_atr_mult", 3.0))
        min_rr_target = float(params.get("min_rr_ratio", 2.0))

        filter_failures: List[str] = []

        # Variables de cálculo
        donchian_high = None
        donchian_low = None
        donchian_mid = None
        donchian_width = None
        ema_100 = None
        vol_ma20 = None
        atr_14 = float(ind.get("atr_14") or 0.0)
        cur_volume = float(latest.get("volume") or 0.0)

        if df is not None and isinstance(df, pd.DataFrame) and len(df) >= max(donchian_period + 2, 25):
            try:
                # 1. Donchian con shift(1) estricto (velas cerradas previas sin sesgo)
                high_shift = df["high"].shift(1)
                low_shift = df["low"].shift(1)
                dh_series = high_shift.rolling(donchian_period).max()
                dl_series = low_shift.rolling(donchian_period).min()
                dm_series = (dh_series + dl_series) / 2.0
                dw_series = dh_series - dl_series

                donchian_high = float(dh_series.iloc[-1])
                donchian_low = float(dl_series.iloc[-1])
                donchian_mid = float(dm_series.iloc[-1])
                donchian_width = float(dw_series.iloc[-1])

                # 2. Rango Verdadero Medio (ATR 14)
                tr1 = df["high"] - df["low"]
                tr2 = (df["high"] - df["close"].shift(1)).abs()
                tr3 = (df["low"] - df["close"].shift(1)).abs()
                tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
                atr_series = tr.rolling(14).mean()
                if not pd.isna(atr_series.iloc[-1]):
                    atr_14 = float(atr_series.iloc[-1])

                # 3. Filtro de Tendencia (EMA 100)
                span_ema = min(ema_trend_period, len(df))
                ema_100_series = df["close"].ewm(span=span_ema, adjust=False).mean()
                ema_100 = float(ema_100_series.iloc[-1])

                # 4. Filtro de Volumen (SMA 20)
                vol_ma20_series = df["volume"].rolling(20).mean()
                if not pd.isna(vol_ma20_series.iloc[-1]):
                    vol_ma20 = float(vol_ma20_series.iloc[-1])
                cur_volume = float(df["volume"].iloc[-1])
            except Exception:
                pass

        # Fallbacks si no se cuenta con serie histórica completa
        if donchian_high is None:
            donchian_high = current_price * 1.01
        if donchian_low is None:
            donchian_low = current_price * 0.99
        if donchian_mid is None:
            donchian_mid = (donchian_high + donchian_low) / 2.0
        if donchian_width is None:
            donchian_width = donchian_high - donchian_low
        if ema_100 is None:
            ema_100 = float(ind.get("ema_200_value") or current_price * 0.98)
        if vol_ma20 is None or vol_ma20 <= 0:
            vol_ma20 = cur_volume if cur_volume > 0 else 1.0

        # Verificación de condiciones de entrada obligatorias:
        # Condición 1: Quiebre alcista Donchian (close > donchian_high)
        cond_quiebre = current_price > donchian_high
        if not cond_quiebre:
            filter_failures.append(
                f"Sin ruptura Donchian: Precio actual (${current_price:.2f}) <= Donchian High (${donchian_high:.2f})."
            )

        # Condición 2: Tendencia institucional (close > ema_100)
        cond_tendencia = current_price > ema_100
        if require_ema_trend and not cond_tendencia:
            filter_failures.append(
                f"Filtro Tendencia violado: Precio (${current_price:.2f}) <= EMA 100 (${ema_100:.2f})."
            )

        # Condición 3: Compresión de canal previa (donchian_width <= 4.5 * atr_14)
        max_allowed_width = compression_mult * atr_14 if atr_14 > 0 else donchian_width
        cond_compresion = donchian_width <= max_allowed_width
        if require_compression and not cond_compresion:
            filter_failures.append(
                f"Canal sobre-extendido: Ancho ({donchian_width:.2f}) > 4.5x ATR ({max_allowed_width:.2f}). Sin compresión previa."
            )

        # Condición 4: Expansión de volumen institucional (volume > vol_ma20 * 1.25)
        min_required_vol = vol_ma20 * vol_mult
        cond_volumen = cur_volume > min_required_vol
        if require_volume and not cond_volumen:
            filter_failures.append(
                f"Volumen insuficiente: Volumen actual ({cur_volume:.1f}) <= 1.25x SMA20 ({min_required_vol:.1f})."
            )

        if not allow_long:
            filter_failures.append("Operativa en Largo (LONG) desactivada en subestrategias.")

        # Cálculo de Stop Loss Inicial y Take Profit Objetivo
        if atr_14 > 0 and current_price > 0:
            atr_pct = (atr_14 / current_price) * 100.0
            sl_calc = round(max(1.0, atr_sl_mult * atr_pct), 2)
            tp_raw = target_tp_mult * atr_pct
        else:
            sl_calc = 1.5
            tp_raw = 3.5

        min_tp_for_rr = required_tp_gross_for_rr(sl_calc, fee, spread, target_rr=min_rr_target)
        tp_calc = round(max(tp_raw, min_tp_for_rr + 0.005), 2)

        net_tp = round(net_return_after_costs(tp_calc, fee, spread), 4)
        net_sl = round(net_return_after_costs(-sl_calc, fee, spread), 4)
        rr_info = net_rr_metrics(tp_calc, sl_calc, fee, spread)
        calc_net_rr = round(float(rr_info.get("net_rr") or 0.0), 2)

        if not rr_info.get("valid") or calc_net_rr < min_rr_target:
            filter_failures.append(
                f"Asimetría insuficiente: R:R neto {calc_net_rr:.2f} < {min_rr_target:.2f} tras costos."
            )

        candidate_eligible = len(filter_failures) == 0 and allow_long
        suggested_signal = "COMPRAR" if candidate_eligible else "MANTENER"
        effective_net_tp = net_tp if candidate_eligible else 0.0

        strategy_metrics = {
            "mode": self.id,
            "side": "LONG" if candidate_eligible else "MANTENER",
            "current_price": round(current_price, 2),
            "donchian_high": round(donchian_high, 2),
            "donchian_low": round(donchian_low, 2),
            "donchian_mid": round(donchian_mid, 2),
            "donchian_width": round(donchian_width, 2),
            "ema_100": round(ema_100, 2),
            "atr_14": round(atr_14, 4),
            "volume": round(cur_volume, 2),
            "volume_sma20": round(vol_ma20, 2),
            "compression_ok": cond_compresion,
            "volume_ok": cond_volumen,
            "cond_quiebre": cond_quiebre,
            "cond_tendencia": cond_tendencia,
            "cond_compresion": cond_compresion,
            "cond_volumen": cond_volumen,
            "tp_gross_pct": tp_calc,
            "sl_gross_pct": sl_calc,
            "tp_net_pct": net_tp,
            "sl_net_pct": net_sl,
            "net_rr": round(float(rr_info.get("net_rr") or 0.0), 2),
            "mid_exit_price": round(donchian_mid, 2),
            "require_mid_exit": require_mid_exit,
            "candidate_eligible": candidate_eligible,
            "suggested_signal": suggested_signal,
            "filter_failures": filter_failures,
            "policy": (
                "Donchian Breakout 1H: Ruptura de Donchian High con shift(1) sobre EMA 100, "
                "compresión previa Donchian Width <= 4.5x ATR y volumen > 1.25x SMA20. Salida MID_EXIT en donchian_mid."
            ),
        }

        return (
            strategy_metrics,
            effective_net_tp,
            candidate_eligible,
            filter_failures,
            max(0.50, min_profit_pct),
        )
