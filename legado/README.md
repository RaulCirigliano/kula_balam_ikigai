# Legado Cuantitativo Kula-Balam (Biblioteca Estática)

Esta carpeta constituye una biblioteca estática de consulta limpia y libre de dependencias operativas.
**NO contiene:** Servidores web (FastAPI/Uvicorn), bases de datos (SQLite), llamadas a LLMs (Ollama/Gemini), ni notificadores externos.

---

## Estructura de Módulos Matemáticos

### 1. Riesgo, Dimensionamiento y Fricción
* **`quant_risk.py`**:
  * Ecuaciones de retorno neto tras comisiones y spread (`net_return_after_costs`).
  * Objetivo de ganancia bruta para alcanzar retorno neto objetivo (`gross_target_for_net`).
  * Asimetría matemática estricta ($R:R \ge 1:2.0$) con `required_tp_gross_for_rr` y `net_rr_metrics`.
  * Modelo de fricción por activo y tipo de mercado (`get_asset_friction_costs`).
  * Dimensionamiento de orden basado en presupuesto de riesgo (`risk_sized_qty`).
  * Criterio fraccional Quarter-Kelly (`kelly_fraction_sizing`).

### 2. Indicadores y Series Temporales
* **`quant_analysis.py`**:
  * Funciones vectorizadas para cálculo de medias móviles (EMA, SMA), ATR, RSI y Bandas de Bollinger.
  * Niveles de retroceso y extensión Fibonacci.
  * Indicadores de volumen y confluencia técnica sin llamadas a sockets.

### 3. Lógica Algorítmica de Estrategias (`estrategias/`)
* **`base.py`**: Interfaz abstracta pura (`EstrategiaBase`).
* **`kula_balam_cava_ruiz.py`**: Reglas de tríada temporal (1D-1H-5M), retrocesos a Zona Dorada Fibo (0.50-0.75), fallo de MACD y secado de volumen institucional.
* **`alex_ruiz_triada_3velas.py`**: Lógica de gatillos en 5M y vetos de estructura rota.
* **`nasdaq_araujo_vwap.py`**: Confluencia temporal y rechazo contra VWAP de parqué.
* **`mean_reversion_atr.py`**: Reversión estadística basada en desvíos y bandas de volatilidad ATR.
* **`donchian_breakout_1h.py`**: Motor validado de ruptura de rango Donchian (20 períodos con `shift(1)`), filtro de tendencia EMA 100, compresión ATR $\le 4.5 \times ATR$, volumen institucional y salida dinámica `MID_EXIT`.

---
*Propósito:* Servir como repositorio de referencia determinista para extraer funciones puras hacia `src/` conforme al desarrollo modular de `kula_balam_ikigai`.
