# Informe Técnico: Estrategia 1 - Tendencial Multimarcador

- **Proyecto:** `kula_balam_ikigai`
- **Activo evaluado:** BTC/USDT
- **Temporalidad:** 1 Hora (1H)
- **Muestra histórica:** 4.320 velas (~180 días)
- **Comisión simulada:** 0.075% por orden (0.15% round-trip)
- **Capital base de prueba:** $100.00 USD

---

## 1. Fundamentos y Fuentes de la Estrategia

La estrategia toma su base teórica del análisis técnico cuantitativo clásico y la literatura de seguimiento de tendencias:

1. **Estructura de Tendencia (EMA 21 / EMA 89):**
   - **Fuente:** Modelos basados en números de Fibonacci aplicados a medias móviles exponenciales (desarrollados conceptualmente a partir de los trabajos de Bill Williams sobre inercia de mercado y formalizados en trading contemporáneo).
   - **Función:** La EMA 21 mide la inercia dinámica a corto plazo, mientras que la EMA 89 define el sesgo direccional macro.

2. **Filtro de Momentum (RSI 14):**
   - **Fuente:** J. Welles Wilder Jr., *New Concepts in Technical Trading Systems* (1978).
   - **Función:** Identificar si el impulso del precio tiene recorrido sin encontrarse en zonas de sobrecompra exhaustiva ($40 \le \text{RSI} \le 60$).

3. **Gestión de Riesgo y Stop Volátil (ATR 14):**
   - **Fuente:** J. Welles Wilder Jr. (1978) y popularizado por el sistema de las Tortugas (*Turtle Trading System*, Dennis & Eckhardt).
   - **Función:** Fijar límites de pérdidas y tomas de ganancias calibrados a la volatilidad real del mercado en lugar de montos fijos en dólares.

---

## 2. Iteraciones Realizadas y Modificaciones de Código

A lo largo de la fase de desarrollo, se implementaron 4 versiones sucesivas para intentar dotar al sistema de ventaja estadística (*edge*):

### Variante 1.0 (Regla Base Cruda)
- **Condición de entrada:** `ema_21 > ema_89`, `close > ema_21` y `45 <= rsi_14 <= 65`.
- **Salida:** Stop Loss a $2.0 \times \text{ATR}$, Take Profit a $4.0 \times \text{ATR}$ (Ratio 2:1).
- **Problema detectado:** Generó 910 señales en bruto con ejecuciones consecutivas. El TP a 4 ATR resultó inalcanzable para la dinámica de 1H, provocando salidas masivas por SL.

### Variante 1.1 (Filtro Pullback + Salidas Calibradas)
- **Modificación:** Se introdujo la condición de rebote: `low <= ema_21 * 1.002` y `close >= ema_21` con `40 <= rsi_14 <= 60`.
- **Salida:** SL reducido a $1.5 \times \text{ATR}$ y TP a $2.5 \times \text{ATR}$ (Ratio ~1.66:1).
- **Efecto:** Redujo las entradas tardías en máximos y mejoró el porcentaje de aciertos de 24% a 36%.

### Variante 1.2 (Filtro de Pendiente en Media Lenta)
- **Modificación:** Se sumó el control de inercia positiva en la media lenta: `ema_89 > ema_89.shift(5)`.
- **Efecto:** Bloqueó 6 operaciones falsas originadas en zonas de compresión lateral, subiendo el Win Rate a 38.24% y el Profit Factor a 0.69.

### Variante 1.3 (Salida Tendencial Dinámica)
- **Modificación:** Se eliminó el Take Profit estático. Se mantuvo el Stop Loss inicial a $1.5 \times \text{ATR}$ y se implementó salida por vela cerrada bajo la media rápida: `close < ema_21`.
- **Efecto:** Permitió capturar recorridos largos sin cortarlos anticipadamente, llevando el Profit Factor a su valor más alto (0.84) y reduciendo la pérdida neta a -7.50%.

---

## 3. Matriz Comparativa de Resultados

| Parámetro / Métrica | Variante 1.0 (Cruda) | Variante 1.1 (Pullback) | Variante 1.2 (+ Pendiente) | Variante 1.3 (Salida Dinámica) |
| :--- | :---: | :---: | :---: | :---: |
| **Total Operaciones** | 74 | 108 | 102 | **122** |
| **Tasa de Acierto (Win Rate)** | 24.32% | 36.11% | **38.24%** | 19.67% |
| **Profit Factor** | 0.52 | 0.63 | 0.69 | **0.84** |
| **Retorno Neto Total** | -27.69% | -21.37% | -16.70% | **-7.50%** |
| **Drawdown Máximo** | -28.39% | -21.72% | **-17.63%** | -20.14% |
| **Capital Final ($100 base)** | $72.31 | $78.63 | $83.30 | **$92.50** |

---

## 4. Desglose de Salidas en la Variante Más Eficiente (V1.3)

- **Total trades:** 122
- **Salidas por Stop Loss (SL):** 21
- **Salidas por Ruptura de Media (EMA_EXIT):** 101

---

## 5. Veredicto y Conclusiones Cuantitativas

1. **Inviabilidad en 1H:** A pesar de optimizar el gatillo (pullback), filtrar los laterales (pendiente) y liberar los beneficios (salida dinámica), el Profit Factor se estancó en **0.84**, por debajo del umbral mínimo de viabilidad ($PF > 1.20$).
2. **Causa del fallo:** El 82.8% de las operaciones terminaron cerrándose por ruptura de la EMA 21. La volatilidad intra-tendencia de Bitcoin en velas horarias tiende a perforar con frecuencia la media de 21 antes de continuar el impulso alcista, acumulando un goteo constante de pequeñas pérdidas y costos de comisión que anulan la ganancia de las grandes tendencias.
3. **Decisión operativa:** Se da por agotada la **Estrategia 1** sin incurrir en sobreajuste de parámetros (*overfitting*). El código base del backtester e indicadores queda validado y listo para evaluar la **Estrategia 2 (Scalping Dinámico 5M)**.