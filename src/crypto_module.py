"""
Módulo Cripto 24/7 (ETH/USDT en 1H) para Kula Balam Ikigai.
Monitorea cierres de vela horaria vía ccxt (Binance) y gestiona órdenes con salida MID_EXIT.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import ccxt
import pandas as pd

from src.state_manager import PortfolioStateManager
from src.strategy_donchian_mid import calcular_indicadores_donchian_mid, evaluar_senal_vela

logger = logging.getLogger("crypto_module")


class CryptoWorker:
    """Worker para el módulo de Criptomonedas (ETH/USDT 1H)."""

    def __init__(
        self,
        state_mgr: PortfolioStateManager,
        symbol: str = "ETH/USDT",
        timeframe: str = "1h",
        exchange_id: str = "binance",
        fee_rate: float = 0.0015,  # 0.15% round-trip
    ):
        self.state_mgr = state_mgr
        self.symbol = symbol
        self.asset_key = symbol.replace("/", "_")
        self.timeframe = timeframe
        self.fee_rate = fee_rate
        self.last_audited_timestamp: Optional[int] = None

        # Inicialización de exchange
        exchange_class = getattr(ccxt, exchange_id)
        self.exchange = exchange_class({"enableRateLimit": True})

    def fetch_ohlcv(self, limit: int = 250) -> pd.DataFrame:
        """Descarga velas horarias desde el exchange."""
        raw = self.exchange.fetch_ohlcv(self.symbol, timeframe=self.timeframe, limit=limit)
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        return df

    def get_live_price(self) -> float:
        """Obtiene el último precio tick a mercado."""
        ticker = self.exchange.fetch_ticker(self.symbol)
        return float(ticker.get("last") or ticker.get("close") or 0.0)

    def check_intraday_emergency_sl(self) -> Optional[Dict[str, Any]]:
        """
        Inspecciona el precio tick actual. Si perfora el SL de emergencia (-1.5%),
        ejecuta salida defensiva inmediata sin esperar el cierre de la vela horaria.
        """
        asset_state = self.state_mgr.get_asset(self.asset_key)
        if not asset_state or not asset_state.get("in_position", False):
            return None

        entry_price = asset_state.get("entry_price")
        initial_sl = asset_state.get("initial_sl")
        if not entry_price or not initial_sl:
            return None

        try:
            live_px = self.get_live_price()
        except Exception as e:
            logger.warning(f"Error consultando ticker en vivo para {self.symbol}: {e}")
            return None

        if live_px <= initial_sl:
            exit_time = datetime.now(timezone.utc).isoformat()
            logger.warning(
                f"🚨 [CRIPTO EMERGENCIA SL] {self.symbol} tocó SL de desastre intradía "
                f"(${live_px:.4f} <= ${initial_sl:.4f}). Liquidando..."
            )
            return self.state_mgr.close_position(
                asset_key=self.asset_key,
                exit_price=live_px,
                exit_time=exit_time,
                exit_reason="SL_EMERGENCIA_INTRADIA",
                fee_rate=self.fee_rate,
            )
        return None

    def audit_closed_candle(self) -> Tuple[str, Dict[str, Any]]:
        """
        Evalúa la vela horaria cerrada más reciente y ejecuta compras o salidas estructurales (MID_EXIT).
        """
        df_raw = self.fetch_ohlcv(limit=250)
        if len(df_raw) < 205:
            return "ESPERAR", {"motivo": f"Historial insuficiente ({len(df_raw)} velas < 205)"}

        # La última vela df_raw.iloc[-1] está en curso. La última CERRADA es iloc[-2]
        df_ind = calcular_indicadores_donchian_mid(df_raw)
        candle = df_ind.iloc[-2]
        c_ts = int(candle["timestamp"])

        asset_state = self.state_mgr.get_asset(self.asset_key)
        in_pos = bool(asset_state.get("in_position", False)) if asset_state else False
        entry_p = float(asset_state.get("entry_price") or 0.0) if asset_state else 0.0
        init_sl = float(asset_state.get("initial_sl") or 0.0) if asset_state else 0.0

        accion, precio_estimado, motivo = evaluar_senal_vela(
            row=candle,
            in_position=in_pos,
            entry_price=entry_p,
            initial_sl=init_sl,
        )

        c_time_str = candle["datetime"].strftime("%Y-%m-%d %H:%M:%S UTC")
        metrics = {
            "datetime": c_time_str,
            "timestamp": c_ts,
            "close": float(candle["close"]),
            "donchian_high": float(candle["donchian_high"]) if pd.notna(candle["donchian_high"]) else None,
            "donchian_mid": float(candle["donchian_mid"]) if pd.notna(candle["donchian_mid"]) else None,
            "donchian_low": float(candle["donchian_low"]) if pd.notna(candle["donchian_low"]) else None,
            "ema200": float(candle["ema200"]) if pd.notna(candle["ema200"]) else None,
            "in_position": in_pos,
            "motivo": motivo,
        }

        # Si ya auditamos esta vela horaria cerrada, no duplicar órdenes
        if c_ts == self.last_audited_timestamp:
            return "YA_AUDITADA", metrics

        self.last_audited_timestamp = c_ts

        # Ejecución
        if accion == "BUY" and not in_pos:
            allocated = float(asset_state.get("allocated_usd") or 50.0)
            entry_price = float(precio_estimado or candle["close"])
            sl_emergency = entry_price * 0.985  # -1.5%
            amount = allocated / entry_price
            self.state_mgr.open_position(
                asset_key=self.asset_key,
                entry_price=entry_price,
                entry_time=c_time_str,
                initial_sl=sl_emergency,
                size=amount,
            )
            return "BUY", metrics

        elif accion in ("EXIT_MID", "EXIT_SL", "EXIT_GAP_SL") and in_pos:
            exit_price = float(precio_estimado or candle["close"])
            self.state_mgr.close_position(
                asset_key=self.asset_key,
                exit_price=exit_price,
                exit_time=c_time_str,
                exit_reason=accion,
                fee_rate=self.fee_rate,
            )
            return accion, metrics

        return "HOLD", metrics
