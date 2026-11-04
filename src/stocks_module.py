"""
Módulo Wall Street (NVDA o AAPL en 1D) para Kula Balam Ikigai.
Monitorea cierres diarios de lunes a viernes a las 17:05 hora local (post-cierre NYSE) vía yfinance.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional, Tuple
import pandas as pd
import yfinance as yf

from src.state_manager import PortfolioStateManager
from src.strategy_donchian_mid import calcular_indicadores_donchian_mid, evaluar_senal_vela

logger = logging.getLogger("stocks_module")


class StocksWorker:
    """Worker para el módulo de Wall Street (Acciones en 1D)."""

    def __init__(
        self,
        state_mgr: PortfolioStateManager,
        ticker: str = "NVDA",
        fee_rate: float = 0.0005,  # 0.05% por lado (0.10% round-trip)
    ):
        self.state_mgr = state_mgr
        self.ticker = ticker.upper()
        self.asset_key = self.ticker
        self.fee_rate = fee_rate
        self.last_audited_date: Optional[str] = None

    def fetch_daily_data(self, period: str = "2y") -> pd.DataFrame:
        """Descarga velas diarias consolidadas desde yfinance."""
        df = yf.download(self.ticker, period=period, interval="1d", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0].lower() for col in df.columns]
        else:
            df.columns = [col.lower() for col in df.columns]
        df = df.dropna().copy()
        df["datetime"] = df.index
        return df

    def is_post_close_window(self, now_dt: Optional[datetime] = None) -> bool:
        """
        Determina si estamos en la ventana post-cierre NYSE (Lunes a Viernes a partir de las 17:05 hora local).
        """
        if now_dt is None:
            now_dt = datetime.now()

        # 0 = Lunes, 4 = Viernes, 5 = Sábado, 6 = Domingo
        is_weekday = now_dt.weekday() < 5
        if not is_weekday:
            return False

        # Post-cierre de Wall Street (17:05 hora local en adelante)
        minutes = now_dt.hour * 60 + now_dt.minute
        return minutes >= (17 * 60 + 5)

    def audit_daily_candle(self, force: bool = False) -> Tuple[str, Dict[str, Any]]:
        """
        Evalúa la vela diaria consolidada más reciente de Wall Street.
        Si force=True, omite el control de horario (útil para auditorías manuales con --check-now).
        """
        now_dt = datetime.now()
        today_str = now_dt.strftime("%Y-%m-%d")

        if not force and not self.is_post_close_window(now_dt):
            return "ESPERAR_HORARIO", {
                "motivo": f"Esperando ventana post-cierre NYSE (17:05 hora local). Hora actual: {now_dt.strftime('%H:%M:%S')}"
            }

        df_raw = self.fetch_daily_data(period="2y")
        if len(df_raw) < 205:
            return "ESPERAR", {"motivo": f"Historial insuficiente ({len(df_raw)} velas < 205)"}

        df_ind = calcular_indicadores_donchian_mid(df_raw)
        candle = df_ind.iloc[-1]
        candle_date_str = str(candle["datetime"]).split(" ")[0].split("T")[0]

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

        metrics = {
            "date": candle_date_str,
            "ticker": self.ticker,
            "open": float(candle["open"]),
            "high": float(candle["high"]),
            "low": float(candle["low"]),
            "close": float(candle["close"]),
            "donchian_high": float(candle["donchian_high"]) if pd.notna(candle["donchian_high"]) else None,
            "donchian_mid": float(candle["donchian_mid"]) if pd.notna(candle["donchian_mid"]) else None,
            "donchian_low": float(candle["donchian_low"]) if pd.notna(candle["donchian_low"]) else None,
            "ema200": float(candle["ema200"]) if pd.notna(candle["ema200"]) else None,
            "in_position": in_pos,
            "motivo": motivo,
        }

        # Si ya auditamos la vela consolidada de hoy y no es forzado, no duplicar
        if not force and candle_date_str == self.last_audited_date:
            return "YA_AUDITADA", metrics

        self.last_audited_date = candle_date_str

        # Ejecución
        if accion == "BUY" and not in_pos:
            allocated = float(asset_state.get("allocated_usd") or 50.0)
            entry_price = float(precio_estimado or candle["close"])
            sl_emergency = entry_price * 0.985  # -1.5%
            shares = allocated / entry_price
            self.state_mgr.open_position(
                asset_key=self.asset_key,
                entry_price=entry_price,
                entry_time=f"{candle_date_str} 17:05:00",
                initial_sl=sl_emergency,
                size=shares,
            )
            return "BUY", metrics

        elif accion in ("EXIT_MID", "EXIT_SL", "EXIT_GAP_SL") and in_pos:
            exit_price = float(precio_estimado or candle["close"])
            self.state_mgr.close_position(
                asset_key=self.asset_key,
                exit_price=exit_price,
                exit_time=f"{candle_date_str} 17:05:00",
                exit_reason=accion,
                fee_rate=self.fee_rate,
            )
            return accion, metrics

        return "HOLD", metrics
