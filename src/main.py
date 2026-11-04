"""
Pipeline de Ejecución Kula-Balam para BTC/USDT.
Estrategia Validada: Donchian Breakout 1H (Variante 3.2 - Salida Dinámica MID).

Roles:
- Balam: Detección táctica cuantitativa sobre velas horarias cerradas.
- Kula: Auditoría de riesgo, capital y control de órdenes.
"""
from datetime import datetime, timezone
import os
import time
import ccxt
import pandas as pd
from indicators import agregar_indicadores_breakout


class KulaBalamEngine:

    def __init__(
        self,
        symbol: str = "BTC/USDT",
        capital_asignado: float = 100.0,
        modo_paper: bool = True,
    ):
        self.symbol = symbol
        self.timeframe = "1h"
        self.capital = capital_asignado
        self.modo_paper = modo_paper

        # Estado de la posición activa
        self.en_posicion = False
        self.precio_entrada = 0.0
        self.sl_precio = 0.0
        self.ultimo_timestamp_auditado = None

        # Inicialización del exchange con ccxt
        self.exchange = ccxt.binance({
            "enableRateLimit": True,
            # Si pasas a real, aquí se inyectan api_key y secret
        })
        print(f"=== MOTOR KULA-BALAM INICIALIZADO ===")
        print(f"Activo: {self.symbol} | Timeframe: {self.timeframe}")
        print(f"Modo: {'PAPER TRADING' if self.modo_paper else 'REAL TRADING'}")
        print(f"Capital Asignado: ${self.capital:.2f} USD\n")

    def obtener_ultimas_velas(self, limite: int = 150) -> pd.DataFrame:
        """Descarga las velas más recientes de Binance."""
        ohlcv = self.exchange.fetch_ohlcv(
            self.symbol, timeframe=self.timeframe, limit=limite
        )
        df = pd.DataFrame(
            ohlcv,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        return df

    def balam_auditar_senales(
        self, df_ind: pd.DataFrame
    ) -> tuple[str, dict | None]:
        """
        Balam evalúa tácticamente la ÚLTIMA VELA CERRADA (índice -2 para descartar la que está en curso).
        """
        vela_cerrada = df_ind.iloc[-2]
        datos = {
            "datetime": vela_cerrada["datetime"],
            "close": vela_cerrada["close"],
            "high": vela_cerrada["high"],
            "low": vela_cerrada["low"],
            "donchian_high": vela_cerrada["donchian_high"],
            "donchian_low": vela_cerrada["donchian_low"],
            "donchian_mid": vela_cerrada["donchian_mid"],
            "donchian_width": vela_cerrada["donchian_width"],
            "atr_14": vela_cerrada["atr_14"],
            "ema_100": vela_cerrada["ema_100"],
            "volume": vela_cerrada["volume"],
            "vol_ma20": vela_cerrada["vol_ma20"],
        }

        # 1. Si no hay posición activa, buscar ENTRADA LONG
        if not self.en_posicion:
            quiebre_maximo = datos["close"] > datos["donchian_high"]
            tendencia_alcista = datos["close"] > datos["ema_100"]
            canal_comprimido = datos["donchian_width"] <= (
                4.5 * datos["atr_14"]
            )
            volumen_fuerte = datos["volume"] > (datos["vol_ma20"] * 1.25)

            if (
                quiebre_maximo
                and tendencia_alcista
                and canal_comprimido
                and volumen_fuerte
            ):
                return "COMPRAR", datos

        # 2. Si hay posición activa, evaluar SALIDA DINÁMICA
        if self.en_posicion:
            # Salida 1: Si tocó Stop Loss
            if datos["low"] <= self.sl_precio:
                return "SALIDA_SL", datos
            # Salida 2: Salida tendencial dinámica por canal medio
            elif datos["close"] < datos["donchian_mid"]:
                return "SALIDA_MID", datos

        return "ESPERAR", datos

    def kula_ejecutar_orden(self, accion: str, datos: dict):
        """
        Kula valida el riesgo y ejecuta la orden (paper o real).
        """
        tiempo = datos["datetime"].strftime("%Y-%m-%d %H:%M:%S UTC")

        if accion == "COMPRAR":
            self.en_posicion = True
            self.precio_entrada = datos["close"]
            self.sl_precio = datos["close"] - (1.5 * datos["atr_14"])

            print(f"\n[KULA ALERTA] >>> ORDEN DE COMPRA EJECUTADA ({tiempo})")
            print(f"Precio Entrada: ${self.precio_entrada:.2f} USDT")
            print(f"Stop Loss:      ${self.sl_precio:.2f} USDT")
            print(
                f"Donchian High:  ${datos['donchian_high']:.2f} | Canal Mid:"
                f" ${datos['donchian_mid']:.2f}"
            )
            print(
                f"Volumen:        {datos['volume']:.2f} (Promedio:"
                f" {datos['vol_ma20']:.2f})"
            )

        elif accion in ["SALIDA_SL", "SALIDA_MID"]:
            precio_salida = (
                self.sl_precio if accion == "SALIDA_SL" else datos["close"]
            )
            retorno_bruto = (
                precio_salida - self.precio_entrada
            ) / self.precio_entrada
            comision_roundtrip = 0.0015  # 0.15% ida y vuelta
            retorno_neto = retorno_bruto - comision_roundtrip
            pnl_usd = self.capital * retorno_neto
            self.capital += pnl_usd

            print(
                f"\n[KULA ALERTA] <<< ORDEN DE SALIDA ({accion}) - {tiempo}"
            )
            print(f"Precio Salida:  ${precio_salida:.2f} USDT")
            print(f"Retorno Neto:   {retorno_neto * 100:.2f}%")
            print(f"PnL Trade:      ${pnl_usd:.2f} USD")
            print(f"Capital Actual: ${self.capital:.2f} USD\n")

            self.en_posicion = False
            self.precio_entrada = 0.0
            self.sl_precio = 0.0

    def ciclo_monitoreo(self):
        """Ejecuta una ronda de inspección táctica."""
        df_raw = self.obtener_ultimas_velas(limite=150)
        df_ind = agregar_indicadores_breakout(df_raw)

        timestamp_ultima_vela = df_ind.iloc[-2]["timestamp"]

        # Evitar procesar dos veces la misma vela cerrada
        if timestamp_ultima_vela == self.ultimo_timestamp_auditado:
            return

        self.ultimo_timestamp_auditado = timestamp_ultima_vela
        accion, datos = self.balam_auditar_senales(df_ind)

        tiempo_str = datos["datetime"].strftime("%Y-%m-%d %H:%M:%S")
        print(
            f"[{datetime.now().strftime('%H:%M:%S')}] Vela Auditada:"
            f" {tiempo_str} | Close: ${datos['close']:.2f} | Donchian High:"
            f" ${datos['donchian_high']:.2f} | Mid: ${datos['donchian_mid']:.2f}"
            f" | Estado: {'EN POSICION' if self.en_posicion else 'LIQUIDEZ'} |"
            f" Dictamen: {accion}"
        )

        if accion != "ESPERAR":
            self.kula_ejecutar_orden(accion, datos)


if __name__ == "__main__":
    bot = KulaBalamEngine(
        symbol="BTC/USDT", capital_asignado=100.0, modo_paper=True
    )

    print("Iniciando monitoreo de mercado en vivo...")
    print(
        "Balam audita al cierre de cada vela horaria. Presiona Ctrl + C para"
        " detener.\n"
    )

    # Primera comprobación inmediata
    bot.ciclo_monitoreo()

    try:
        while True:
            # Inspección cada 60 segundos
            time.sleep(60)
            bot.ciclo_monitoreo()
    except KeyboardInterrupt:
        print("\nMonitoreo detenido por el operador.")