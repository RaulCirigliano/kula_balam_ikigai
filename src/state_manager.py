"""
Gestor de Persistencia del Estado del Portfolio Multimercado (Kula Balam Ikigai).
Administra 'state_portfolio.json' con acceso thread-safe y escrituras atómicas.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("state_manager")

DEFAULT_STATE_FILE = "state_portfolio.json"
DEFAULT_TRADES_CSV = "registro_trades_multimercado.csv"


def get_default_state(capital_total: float = 100.0, stock_symbol: str = "NVDA") -> Dict[str, Any]:
    half_capital = round(capital_total / 2.0, 2)
    return {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "capital_total": float(capital_total),
        "assets": {
            "ETH_USDT": {
                "market": "crypto",
                "timeframe": "1h",
                "allocated_usd": half_capital,
                "in_position": False,
                "entry_price": None,
                "entry_time": None,
                "initial_sl": None,
                "amount": 0.0,
            },
            stock_symbol: {
                "market": "stocks",
                "timeframe": "1d",
                "allocated_usd": half_capital,
                "in_position": False,
                "entry_price": None,
                "entry_time": None,
                "initial_sl": None,
                "shares": 0.0,
            },
        },
    }


class PortfolioStateManager:
    """Administrador thread-safe del estado persistente del portfolio."""

    def __init__(
        self,
        filepath: str | Path = DEFAULT_STATE_FILE,
        trades_csv_path: str | Path = DEFAULT_TRADES_CSV,
        stock_symbol: str = "NVDA",
        initial_capital: float = 100.0,
    ):
        self.filepath = Path(filepath)
        self.trades_csv_path = Path(trades_csv_path)
        self.stock_symbol = stock_symbol
        self.initial_capital = initial_capital
        self._lock = threading.Lock()
        self._state: Dict[str, Any] = {}
        self.load_or_initialize()

    def load_or_initialize(self) -> Dict[str, Any]:
        """Carga el estado existente o crea uno nuevo con los valores por defecto."""
        with self._lock:
            if not self.filepath.exists():
                logger.info(f"Creando nuevo archivo de estado en {self.filepath}")
                self._state = get_default_state(self.initial_capital, self.stock_symbol)
                self._save_atomic_unlocked()
            else:
                try:
                    with open(self.filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    # Validar estructura mínima
                    if "capital_total" not in data or "assets" not in data:
                        logger.warning("Estructura inválida en estado. Reinicializando defaults.")
                        self._state = get_default_state(self.initial_capital, self.stock_symbol)
                        self._save_atomic_unlocked()
                    else:
                        self._state = data
                        # Asegurar que ambos módulos existan
                        assets = self._state.setdefault("assets", {})
                        half = round(float(self._state.get("capital_total", 100.0)) / 2.0, 2)
                        if "ETH_USDT" not in assets:
                            assets["ETH_USDT"] = {
                                "market": "crypto",
                                "timeframe": "1h",
                                "allocated_usd": half,
                                "in_position": False,
                                "entry_price": None,
                                "entry_time": None,
                                "initial_sl": None,
                                "amount": 0.0,
                            }
                        if self.stock_symbol not in assets:
                            assets[self.stock_symbol] = {
                                "market": "stocks",
                                "timeframe": "1d",
                                "allocated_usd": half,
                                "in_position": False,
                                "entry_price": None,
                                "entry_time": None,
                                "initial_sl": None,
                                "shares": 0.0,
                            }
                        self._save_atomic_unlocked()
                except Exception as e:
                    logger.error(f"Error leyendo {self.filepath}: {e}. Reinicializando defaults.")
                    self._state = get_default_state(self.initial_capital, self.stock_symbol)
                    self._save_atomic_unlocked()
            return dict(self._state)

    def _save_atomic_unlocked(self) -> None:
        """Escritura atómica en disco usando archivo temporal para prevenir corrupción."""
        self._state["last_updated"] = datetime.now(timezone.utc).isoformat()
        tmp_file = self.filepath.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(self._state, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_file, self.filepath)

    def get_state(self) -> Dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._state))

    def get_asset(self, asset_key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            asset = self._state.get("assets", {}).get(asset_key)
            if asset:
                return json.loads(json.dumps(asset))
            return None

    def open_position(
        self,
        asset_key: str,
        entry_price: float,
        entry_time: str,
        initial_sl: float,
        size: float,
    ) -> Dict[str, Any]:
        """Registra la apertura de una posición Long en el activo indicado."""
        with self._lock:
            assets = self._state.setdefault("assets", {})
            if asset_key not in assets:
                raise ValueError(f"Activo {asset_key} no configurado en el portfolio")

            pos = assets[asset_key]
            if pos.get("in_position", False):
                logger.warning(f"Intento de compra en {asset_key} cuando ya está en posición.")
                return dict(pos)

            pos["in_position"] = True
            pos["entry_price"] = float(round(entry_price, 4))
            pos["entry_time"] = str(entry_time)
            pos["initial_sl"] = float(round(initial_sl, 4))

            market = pos.get("market", "crypto")
            if market == "crypto":
                pos["amount"] = float(round(size, 8))
            else:
                pos["shares"] = float(round(size, 6))

            self._save_atomic_unlocked()
            logger.info(
                f"✅ [POSICIÓN ABIERTA] {asset_key} ({market}) | Entrada: ${entry_price:.4f} | "
                f"SL Emergencia (-1.5%): ${initial_sl:.4f} | Tamaño: {size}"
            )
            return dict(pos)

    def close_position(
        self,
        asset_key: str,
        exit_price: float,
        exit_time: str,
        exit_reason: str,
        fee_rate: float = 0.0015,
    ) -> Dict[str, Any]:
        """
        Registra el cierre de una posición, calcula PnL neto de comisiones y actualiza capital.
        """
        with self._lock:
            assets = self._state.setdefault("assets", {})
            if asset_key not in assets:
                raise ValueError(f"Activo {asset_key} no configurado en el portfolio")

            pos = assets[asset_key]
            if not pos.get("in_position", False):
                logger.warning(f"Intento de salida en {asset_key} sin posición activa.")
                return {"pnl_usd": 0.0, "net_return": 0.0, "status": "no_position"}

            entry_price = float(pos.get("entry_price") or exit_price)
            allocated_usd = float(pos.get("allocated_usd") or 50.0)
            market = pos.get("market", "crypto")
            size = pos.get("amount") if market == "crypto" else pos.get("shares")

            raw_return = (exit_price - entry_price) / entry_price if entry_price > 0 else 0.0
            net_return = raw_return - fee_rate
            pnl_usd = round(allocated_usd * net_return, 4)

            # Actualizar capitales
            new_allocated = max(0.0, round(allocated_usd + pnl_usd, 4))
            pos["allocated_usd"] = new_allocated
            current_total = float(self._state.get("capital_total", 100.0))
            self._state["capital_total"] = max(0.0, round(current_total + pnl_usd, 4))

            # Resetear estado de la posición
            pos["in_position"] = False
            pos["entry_price"] = None
            pos["entry_time"] = None
            pos["initial_sl"] = None
            if market == "crypto":
                pos["amount"] = 0.0
            else:
                pos["shares"] = 0.0

            self._save_atomic_unlocked()

            # Guardar en histórico CSV
            trade_summary = {
                "timestamp": exit_time,
                "asset": asset_key,
                "market": market,
                "entry_price": entry_price,
                "exit_price": float(round(exit_price, 4)),
                "size": size,
                "exit_reason": exit_reason,
                "raw_return_pct": round(raw_return * 100.0, 4),
                "fee_rate_pct": round(fee_rate * 100.0, 4),
                "net_return_pct": round(net_return * 100.0, 4),
                "pnl_usd": pnl_usd,
                "asset_capital_usd": new_allocated,
                "portfolio_total_usd": self._state["capital_total"],
            }
            self._append_trade_csv_unlocked(trade_summary)

            logger.info(
                f"🛑 [POSICIÓN CERRADA] {asset_key} ({market}) por {exit_reason} | "
                f"Entrada: ${entry_price:.4f} -> Salida: ${exit_price:.4f} | "
                f"Neto: {net_return * 100:+.2f}% | PnL: ${pnl_usd:+.2f} USD | "
                f"Capital Total: ${self._state['capital_total']:.2f} USD"
            )
            return trade_summary

    def _append_trade_csv_unlocked(self, trade: Dict[str, Any]) -> None:
        """Añade el registro del trade al archivo CSV de auditoría."""
        try:
            import pandas as pd
            df_row = pd.DataFrame([trade])
            header = not self.trades_csv_path.exists()
            df_row.to_csv(self.trades_csv_path, mode="a", header=header, index=False)
        except Exception as e:
            logger.error(f"Error escribiendo en {self.trades_csv_path}: {e}")
