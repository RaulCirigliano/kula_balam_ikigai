"""
Suite de Pruebas Automatizadas: Arquitectura de Ejecución Multimercado Paralelo
Valida la estrategia Donchian Breakout + Salida Estructural MID_EXIT y persistencia de estado.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch
import pandas as pd
import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.state_manager import PortfolioStateManager, get_default_state
from src.strategy_donchian_mid import calcular_indicadores_donchian_mid, evaluar_senal_vela
from src.crypto_module import CryptoWorker
from src.stocks_module import StocksWorker


class TestPortfolioStateManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_file = os.path.join(self.temp_dir.name, "state_portfolio.json")
        self.csv_file = os.path.join(self.temp_dir.name, "trades.csv")
        self.mgr = PortfolioStateManager(
            filepath=self.state_file,
            trades_csv_path=self.csv_file,
            stock_symbol="NVDA",
            initial_capital=100.0,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_initial_state_structure(self):
        state = self.mgr.get_state()
        self.assertEqual(state["capital_total"], 100.0)
        self.assertIn("ETH_USDT", state["assets"])
        self.assertIn("NVDA", state["assets"])

        eth = state["assets"]["ETH_USDT"]
        self.assertEqual(eth["market"], "crypto")
        self.assertEqual(eth["timeframe"], "1h")
        self.assertEqual(eth["allocated_usd"], 50.0)
        self.assertFalse(eth["in_position"])
        self.assertIsNone(eth["entry_price"])
        self.assertEqual(eth["amount"], 0.0)

        nvda = state["assets"]["NVDA"]
        self.assertEqual(nvda["market"], "stocks")
        self.assertEqual(nvda["timeframe"], "1d")
        self.assertEqual(nvda["allocated_usd"], 50.0)
        self.assertFalse(nvda["in_position"])
        self.assertIsNone(nvda["entry_price"])
        self.assertEqual(nvda["shares"], 0.0)

    def test_open_and_close_position_crypto(self):
        # 1. Abrir posición en ETH
        entry_price = 2000.0
        initial_sl = entry_price * 0.985  # 1970.0
        size_amount = 50.0 / entry_price  # 0.025 ETH
        pos = self.mgr.open_position(
            asset_key="ETH_USDT",
            entry_price=entry_price,
            entry_time="2026-11-04 10:00:00 UTC",
            initial_sl=initial_sl,
            size=size_amount,
        )
        self.assertTrue(pos["in_position"])
        self.assertEqual(pos["entry_price"], 2000.0)
        self.assertEqual(pos["initial_sl"], 1970.0)
        self.assertEqual(pos["amount"], 0.025)

        # 2. Verificar persistencia en disco tras reapertura de manager
        mgr_reloaded = PortfolioStateManager(
            filepath=self.state_file,
            trades_csv_path=self.csv_file,
        )
        eth_state = mgr_reloaded.get_asset("ETH_USDT")
        self.assertTrue(eth_state["in_position"])
        self.assertEqual(eth_state["entry_price"], 2000.0)

        # 3. Cerrar posición con ganancia (salida en 2100.0)
        exit_price = 2100.0  # +5% bruto
        trade = self.mgr.close_position(
            asset_key="ETH_USDT",
            exit_price=exit_price,
            exit_time="2026-11-04 15:00:00 UTC",
            exit_reason="EXIT_MID",
            fee_rate=0.0015,
        )
        self.assertEqual(trade["exit_reason"], "EXIT_MID")
        self.assertGreater(trade["pnl_usd"], 2.0)

        # Estado reseteado
        eth_after = self.mgr.get_asset("ETH_USDT")
        self.assertFalse(eth_after["in_position"])
        self.assertIsNone(eth_after["entry_price"])
        self.assertGreater(self.mgr.get_state()["capital_total"], 100.0)
        self.assertTrue(os.path.exists(self.csv_file))

    def test_parallel_positions_independence(self):
        # Ambas posiciones activas al mismo tiempo
        self.mgr.open_position("ETH_USDT", 2500.0, "2026-11-04 10:00", 2462.5, 0.02)
        self.mgr.open_position("NVDA", 140.0, "2026-11-04 17:05", 137.9, 0.3571)

        eth = self.mgr.get_asset("ETH_USDT")
        nvda = self.mgr.get_asset("NVDA")
        self.assertTrue(eth["in_position"])
        self.assertTrue(nvda["in_position"])
        self.assertEqual(eth["amount"], 0.02)
        self.assertEqual(nvda["shares"], 0.3571)


class TestStrategyDonchianMid(unittest.TestCase):
    def _crear_datos_sinteticos(self, n=250):
        # Serie con tendencia alcista sobre EMA 200
        fechas = pd.date_range("2026-01-01", periods=n, freq="h")
        precios = np.linspace(100.0, 200.0, n)
        df = pd.DataFrame({
            "timestamp": [int(f.timestamp() * 1000) for f in fechas],
            "datetime": fechas,
            "open": precios - 0.5,
            "high": precios + 2.0,
            "low": precios - 1.0,
            "close": precios,
            "volume": np.full(n, 1000.0),
        })
        return df

    def test_indicators_strict_shift1(self):
        df = self._crear_datos_sinteticos(220)
        df_ind = calcular_indicadores_donchian_mid(df, donchian_period=20, ema_period=200)

        # Donchian High de la fila i debe ser exactamente el max de las 20 filas anteriores (i-20 a i-1)
        i = 210
        expected_high = df["high"].iloc[i-20:i].max()
        expected_low = df["low"].iloc[i-20:i].min()
        expected_mid = (expected_high + expected_low) / 2.0

        self.assertAlmostEqual(df_ind["donchian_high"].iloc[i], expected_high, places=5)
        self.assertAlmostEqual(df_ind["donchian_low"].iloc[i], expected_low, places=5)
        self.assertAlmostEqual(df_ind["donchian_mid"].iloc[i], expected_mid, places=5)

    def test_entry_long_signal(self):
        df = self._crear_datos_sinteticos(220)
        df_ind = calcular_indicadores_donchian_mid(df)

        # Modificar última vela para forzar ruptura
        row = df_ind.iloc[-1].copy()
        row["close"] = float(row["donchian_high"]) + 5.0  # Ruptura alcista sobre canal y sobre EMA200

        accion, px, motivo = evaluar_senal_vela(row, in_position=False)
        self.assertEqual(accion, "BUY")
        self.assertEqual(px, row["close"])
        self.assertIn("Ruptura Donchian", motivo)

    def test_structural_exit_mid(self):
        df = self._crear_datos_sinteticos(220)
        df_ind = calcular_indicadores_donchian_mid(df)

        row = df_ind.iloc[-1].copy()
        entry_price = 190.0
        initial_sl = entry_price * 0.985  # 187.15
        # Vela cierra por debajo de la media pero encima del SL de emergencia
        row["close"] = float(row["donchian_mid"]) - 1.0
        row["open"] = float(row["donchian_mid"]) + 0.5
        row["low"] = 188.0  # > initial_sl

        accion, px, motivo = evaluar_senal_vela(
            row, in_position=True, entry_price=entry_price, initial_sl=initial_sl
        )
        self.assertEqual(accion, "EXIT_MID")
        self.assertEqual(px, row["close"])
        self.assertIn("MID_EXIT", motivo)

    def test_emergency_sl_exit(self):
        df = self._crear_datos_sinteticos(220)
        df_ind = calcular_indicadores_donchian_mid(df)

        row = df_ind.iloc[-1].copy()
        entry_price = 200.0
        initial_sl = 200.0 * 0.985  # 197.0

        # Caso 1: Caída intradía perfora SL de emergencia
        row["open"] = 199.0
        row["low"] = 196.5  # < initial_sl
        row["close"] = 197.5

        accion, px, motivo = evaluar_senal_vela(
            row, in_position=True, entry_price=entry_price, initial_sl=initial_sl
        )
        self.assertEqual(accion, "EXIT_SL")
        self.assertEqual(px, 197.0)

        # Caso 2: Gap bajista en apertura
        row["open"] = 195.0  # Gap down
        row["low"] = 194.0
        row["close"] = 196.0

        accion_gap, px_gap, _ = evaluar_senal_vela(
            row, in_position=True, entry_price=entry_price, initial_sl=initial_sl
        )
        self.assertEqual(accion_gap, "EXIT_GAP_SL")
        self.assertEqual(px_gap, 195.0)

    def test_no_rigid_take_profit_or_trailing(self):
        """Verifica que un avance masivo (ej: +10%) no liquide por TP ni por trailing rígido."""
        df = self._crear_datos_sinteticos(220)
        df_ind = calcular_indicadores_donchian_mid(df)

        row = df_ind.iloc[-1].copy()
        entry_price = 100.0
        initial_sl = 98.5
        # Precio vuela a 120.0 (+20%) y Donchian Mid está en 110.0
        row["open"] = 118.0
        row["low"] = 117.0
        row["close"] = 120.0
        row["donchian_mid"] = 110.0

        accion, px, motivo = evaluar_senal_vela(
            row, in_position=True, entry_price=entry_price, initial_sl=initial_sl
        )
        self.assertEqual(accion, "HOLD")
        self.assertIsNone(px)
        self.assertIn("Mantener posición activa", motivo)


class TestWorkersSimulation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_file = os.path.join(self.temp_dir.name, "state_portfolio.json")
        self.csv_file = os.path.join(self.temp_dir.name, "trades.csv")
        self.mgr = PortfolioStateManager(
            filepath=self.state_file,
            trades_csv_path=self.csv_file,
            stock_symbol="NVDA",
            initial_capital=100.0,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_crypto_worker_buy_and_mid_exit_flow(self):
        worker = CryptoWorker(self.mgr, symbol="ETH/USDT")

        # Mockear velas de Binance
        fechas = pd.date_range("2026-01-01", periods=220, freq="h")
        precios = np.linspace(2000.0, 3000.0, 220)
        candles = []
        for i, f in enumerate(fechas):
            c = precios[i]
            candles.append([int(f.timestamp() * 1000), c - 5, c + 10, c - 10, c, 500.0])

        # Forzar que la vela cerrada[-2] quiebre Donchian High previo
        candles[-2][4] = 3100.0  # Close > Donchian High (3010.0) y > EMA200
        candles[-2][2] = 3110.0  # High

        with patch.object(worker.exchange, "fetch_ohlcv", return_value=candles):
            # 1. Velas en subida constante con quiebre -> debe gatillar BUY en vela cerrada
            accion, metrics = worker.audit_closed_candle()
            self.assertEqual(accion, "BUY")
            self.assertTrue(self.mgr.get_asset("ETH_USDT")["in_position"])

        # 2. Simular desarrollo tendencial: precio sube a 2500 y mid sube a 2400
        # Luego vela cierra en 2350 (< mid 2400, pero Low 2300 > initial_sl 1970)
        # Re-setear estado con entrada en 2000.0
        self.mgr.close_position("ETH_USDT", 2000.0, "2026-01-01", "RESET", fee_rate=0.0)
        self.mgr.open_position("ETH_USDT", 2000.0, "2026-01-01", 1970.0, 0.025)

        # Configurar vela cerrada[-2] con Mid ~2400, Close 2350, Low 2300 (> 1970)
        candles[-2] = [
            candles[-2][0] + 3600000,
            2420.0,  # Open (> initial_sl)
            2450.0,  # High
            2300.0,  # Low (> initial_sl 1970.0)
            2350.0,  # Close (< donchian_mid ~2500.0)
            500.0
        ]
        with patch.object(worker.exchange, "fetch_ohlcv", return_value=candles):
            accion2, metrics2 = worker.audit_closed_candle()
            self.assertEqual(accion2, "EXIT_MID")
            self.assertFalse(self.mgr.get_asset("ETH_USDT")["in_position"])

    def test_stocks_worker_window_and_audit(self):
        worker = StocksWorker(self.mgr, ticker="NVDA")

        # Comprobar control de horario:
        # Lunes 17:06 hs -> Ventana activa
        dt_in = datetime(2026, 11, 2, 17, 6, 0)  # Lunes
        self.assertTrue(worker.is_post_close_window(dt_in))

        # Lunes 16:50 hs -> Ventana inactiva
        dt_out = datetime(2026, 11, 2, 16, 50, 0)
        self.assertFalse(worker.is_post_close_window(dt_out))

        # Sábado 17:10 hs -> Fin de semana inactivo
        dt_sat = datetime(2026, 11, 7, 17, 10, 0)
        self.assertFalse(worker.is_post_close_window(dt_sat))


if __name__ == "__main__":
    unittest.main()
