#!/usr/bin/env python3
"""
Punto de Entrada Principal del Sistema Multimercado Paralelo (Kula Balam Ikigai).
Implementa la estrategia validada Donchian Breakout con salida estructural pura (MID_EXIT)
sobre Módulo Cripto (ETH/USDT 1H 24/7) y Módulo Wall Street (NVDA 1D 17:05 hs).
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time

# Configurar path local
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.multimarket_orchestrator import MultimarketOrchestrator
from src.state_manager import PortfolioStateManager

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main_multimercado")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Kula Balam Ikigai: Motor Multimercado Paralelo (Cripto 1H + Wall Street 1D)."
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Muestra el estado actual del portfolio persistido (state_portfolio.json) y sale.",
    )
    parser.add_argument(
        "--check-now",
        action="store_true",
        help="Ejecuta una inspección y auditoría cuantitativa inmediata de ambos mercados y sale.",
    )
    parser.add_argument(
        "--stock",
        type=str,
        default="NVDA",
        help="Símbolo del activo para el módulo de Wall Street (ej: NVDA, AAPL). Default: NVDA",
    )
    parser.add_argument(
        "--crypto",
        type=str,
        default="ETH/USDT",
        help="Símbolo del par para el módulo Cripto. Default: ETH/USDT",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=100.0,
        help="Capital total del portfolio en USD para inicialización. Default: 100.0",
    )
    parser.add_argument(
        "--state-file",
        type=str,
        default=os.path.join(PROJECT_ROOT, "state_portfolio.json"),
        help="Ruta al archivo JSON de estado del portfolio.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_arguments()

    state_mgr = PortfolioStateManager(
        filepath=args.state_file,
        trades_csv_path=os.path.join(PROJECT_ROOT, "registro_trades_multimercado.csv"),
        stock_symbol=args.stock.upper(),
        initial_capital=args.capital,
    )

    orchestrator = MultimarketOrchestrator(
        state_mgr=state_mgr,
        stock_ticker=args.stock.upper(),
        crypto_symbol=args.crypto,
    )

    if args.status:
        orchestrator.print_status()
        sys.exit(0)

    if args.check_now:
        orchestrator.run_single_check()
        sys.exit(0)

    # Modo continuo
    orchestrator.start()

    # Manejo de señales de parada limpia
    def handle_exit(sig, frame):
        print("\n[!] Señal de interrupción recibida. Deteniendo sistema...")
        orchestrator.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        handle_exit(None, None)


if __name__ == "__main__":
    main()
