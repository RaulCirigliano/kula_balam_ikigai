"""
Orquestador Multimercado en Paralelo (Kula Balam Ikigai).
Coordina el Módulo Cripto (ETH/USDT 1H 24/7) y el Módulo Wall Street (NVDA/AAPL 1D 17:05 hs).
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional

from src.crypto_module import CryptoWorker
from src.state_manager import PortfolioStateManager
from src.stocks_module import StocksWorker

logger = logging.getLogger("orchestrator")


class MultimarketOrchestrator:
    """Orquestador concurrente de ejecución para Cripto y Wall Street."""

    def __init__(
        self,
        state_mgr: PortfolioStateManager,
        stock_ticker: str = "NVDA",
        crypto_symbol: str = "ETH/USDT",
    ):
        self.state_mgr = state_mgr
        self.stock_ticker = stock_ticker.upper()
        self.crypto_symbol = crypto_symbol

        self.crypto_worker = CryptoWorker(
            state_mgr=self.state_mgr,
            symbol=self.crypto_symbol,
            timeframe="1h",
        )
        self.stocks_worker = StocksWorker(
            state_mgr=self.state_mgr,
            ticker=self.stock_ticker,
        )

        self._stop_event = threading.Event()
        self._crypto_thread: Optional[threading.Thread] = None
        self._stocks_thread: Optional[threading.Thread] = None

    def print_status(self) -> None:
        """Muestra en terminal el estado actual del portfolio y las posiciones."""
        state = self.state_mgr.get_state()
        print("\n" + "=" * 65)
        print("  📊 ESTADO DEL PORTFOLIO MULTIMERCADO (KULA BALAM IKIGAI)")
        print(f"  Última Actualización: {state.get('last_updated')}")
        print(f"  Capital Total:        ${float(state.get('capital_total', 100.0)):.2f} USD")
        print("=" * 65)

        for key, asset in state.get("assets", {}).items():
            market = asset.get("market", "").upper()
            tf = asset.get("timeframe", "")
            alloc = float(asset.get("allocated_usd", 50.0))
            in_pos = asset.get("in_position", False)
            entry = asset.get("entry_price")
            sl = asset.get("initial_sl")
            size = asset.get("amount") if market == "CRYPTO" else asset.get("shares")

            status_str = "🟢 EN POSICIÓN" if in_pos else "⚪ LIQUIDEZ (ESPERANDO RUPTURA)"
            print(f"\n▶ [{key}] Mercado: {market} | Timeframe: {tf} | Asignación: ${alloc:.2f} USD")
            print(f"  Estado:     {status_str}")
            if in_pos:
                print(f"  Entrada:    ${float(entry):.4f} | Tamaño: {size}")
                print(f"  SL Desastre (-1.5%): ${float(sl):.4f}")
                print(f"  Abierta en: {asset.get('entry_time')}")

        print("=" * 65 + "\n")

    def run_single_check(self) -> Dict[str, Any]:
        """
        Ejecuta una inspección inmediata de ambos mercados sin esperar el cronómetro.
        Útil para testing, auditorías de inicio o comandos manuales.
        """
        print("\n" + "=" * 65)
        print(f"  🔍 AUDITORÍA INSTANTÁNEA MULTIMERCADO ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
        print("=" * 65)

        results = {}

        # 1. Inspección Cripto (ETH 1H)
        print("\n[*] Auditando Módulo Cripto (ETH/USDT en 1H)...")
        try:
            # Primero chequeo SL intradía
            sl_res = self.crypto_worker.check_intraday_emergency_sl()
            if sl_res:
                print(f"  -> ALERTA: Posición cerrada de emergencia por SL intradía: {sl_res}")
                results["crypto_emergency_sl"] = sl_res

            # Luego auditoría de vela cerrada 1H
            action_c, metrics_c = self.crypto_worker.audit_closed_candle()
            results["crypto"] = {"action": action_c, "metrics": metrics_c}
            print(f"  Vela 1H: {metrics_c.get('datetime')} | Close: ${metrics_c.get('close', 0):.2f}")
            print(f"  Donchian High: ${metrics_c.get('donchian_high', 0):.2f} | Mid: ${metrics_c.get('donchian_mid', 0):.2f} | EMA200: ${metrics_c.get('ema200', 0):.2f}")
            print(f"  Dictamen Cripto: {action_c} -> {metrics_c.get('motivo')}")
        except Exception as e:
            logger.error(f"Error auditando cripto: {e}", exc_info=True)
            results["crypto"] = {"error": str(e)}

        # 2. Inspección Wall Street (NVDA 1D forzada)
        print(f"\n[*] Auditando Módulo Wall Street ({self.stock_ticker} en 1D)...")
        try:
            action_s, metrics_s = self.stocks_worker.audit_daily_candle(force=True)
            results["stocks"] = {"action": action_s, "metrics": metrics_s}
            print(f"  Vela Diaria: {metrics_s.get('date')} | Close: ${metrics_s.get('close', 0):.2f}")
            print(f"  Donchian High: ${metrics_s.get('donchian_high', 0):.2f} | Mid: ${metrics_s.get('donchian_mid', 0):.2f} | EMA200: ${metrics_s.get('ema200', 0):.2f}")
            print(f"  Dictamen Acciones: {action_s} -> {metrics_s.get('motivo')}")
        except Exception as e:
            logger.error(f"Error auditando Wall Street: {e}", exc_info=True)
            results["stocks"] = {"error": str(e)}

        print("=" * 65 + "\n")
        self.print_status()
        return results

    def _loop_crypto(self) -> None:
        """Loop continuo 24/7 para el módulo Cripto."""
        logger.info("Iniciando hilo de monitoreo Cripto 24/7 (ETH/USDT 1H)...")
        while not self._stop_event.is_set():
            try:
                # 1. Monitoreo intradía continuo de SL de emergencia
                self.crypto_worker.check_intraday_emergency_sl()

                # 2. Auditoría en cada nuevo cierre de vela
                # Revisamos periódicamente la última vela cerrada
                self.crypto_worker.audit_closed_candle()

            except Exception as e:
                logger.error(f"Error en loop cripto: {e}")

            # Duerme en intervalos cortos permitiendo parada limpia
            for _ in range(30):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

    def _loop_stocks(self) -> None:
        """Loop de monitoreo diario para Wall Street (Lunes a Viernes 17:05 hs)."""
        logger.info(f"Iniciando hilo de monitoreo Wall Street ({self.stock_ticker} 1D)...")
        while not self._stop_event.is_set():
            try:
                # Intenta auditar (el worker valida internamente la ventana 17:05 hs Lunes-Viernes)
                self.stocks_worker.audit_daily_candle(force=False)
            except Exception as e:
                logger.error(f"Error en loop Wall Street: {e}")

            # Chequea cada 60 segundos
            for _ in range(60):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

    def start(self) -> None:
        """Inicia los dos módulos en hilos paralelos independientes."""
        self._stop_event.clear()

        print("\n==========================================================")
        print("  🚀 INICIANDO SISTEMA MULTIMERCADO PARALELO")
        print(f"  1. Módulo Cripto:      {self.crypto_symbol} (1H · 24/7 Binance)")
        print(f"  2. Módulo Wall Street: {self.stock_ticker} (1D · Lun-Vie 17:05 hs)")
        print("  Base Nocional: $100 USD (Asignación $50 USD c/u)")
        print("==========================================================\n")

        self.print_status()

        self._crypto_thread = threading.Thread(
            target=self._loop_crypto,
            name="Thread-CryptoWorker",
            daemon=True,
        )
        self._stocks_thread = threading.Thread(
            target=self._loop_stocks,
            name="Thread-StocksWorker",
            daemon=True,
        )

        self._crypto_thread.start()
        self._stocks_thread.start()
        logger.info("Ambos módulos multimercado han sido lanzados en paralelo.")

    def stop(self) -> None:
        """Detiene limpiamente ambos hilos."""
        logger.info("Deteniendo orquestador multimercado...")
        self._stop_event.set()
        if self._crypto_thread and self._crypto_thread.is_alive():
            self._crypto_thread.join(timeout=3.0)
        if self._stocks_thread and self._stocks_thread.is_alive():
            self._stocks_thread.join(timeout=3.0)
        logger.info("Orquestador detenido exitosamente.")
