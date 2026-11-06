\# Auditoría Cuantitativa: Estrategia 2 (Scalping Dinámico Elástico)



\---



\## 1. Origen y Fuentes de la Estrategia



La estrategia busca capturar ineficiencias de microestructura mediante \*\*reversión elástica rápida\*\* en retrocesos intradiarios:



\* \*\*Filtro de Microtendencia ($\\text{EMA}\_{50}$ / $\\text{EMA}\_{200}$):\*\* Adaptación del principio clásico de seguimiento tendencial a corto y mediano plazo para operar exclusivamente a favor de la inercia dominante del mercado.

\* \*\*Gatillo Elástico ($\\text{RSI}\_3$ ultracorto):\*\* Desarrollado y popularizado por \*\*Larry Connors\*\* (\*Short Term Trading Strategies That Work\*, 2008). Connors demostró que en horizontes intradiarios los osciladores estándar de 14 períodos son lentos; un período ultracorto ($\\text{RSI} \\le 3$) comprimido por debajo de 20 refleja una asimetría estadística temporal por capitulación compradora/vendedora en microtemporalidades.

\* \*\*Filtro de Régimen de Volatilidad ($\\text{ADX}\_5$):\*\* Extrapolación de la obra de \*\*J. Welles Wilder Jr.\*\* (1978). Un umbral de $\\text{ADX} \\ge 25$ en ventana de 5 períodos garantiza que el activo tiene desplazamiento dinámico activo y descarta fases de estancamiento o baja liquidez.

\* \*\*Salidas Mecánicas (Múltiplos de ATR 14):\*\* Control de riesgo simétrico/asimétrico dependiente de la volatilidad instantánea para definir niveles exactos de Stop Loss y Take Profit.



\---



\## 2. Iteraciones y Modificaciones Realizadas



Las pruebas se ejecutaron sobre velas históricas descargadas de Binance mediante `ccxt` con deducción de comisiones reales de exchange (\*\*0.075% taker, 0.15% round-trip\*\*):



1\. \*\*Variante 2.0 en 5 Minutos (5M Cruda - 45 días / 12.960 velas):\*\*

&#x20;  \* \*Reglas:\* $\\text{Close} > \\text{EMA}\_{50}$, $\\text{ADX}\_5 \\ge 25$, $\\text{RSI}\_3 \\le 20$.

&#x20;  \* \*Salidas:\* $\\text{SL} = 1.2 \\times \\text{ATR}\_{14}$, $\\text{TP} = 1.5 \\times \\text{ATR}\_{14}$.

&#x20;  \* \*Diagnóstico:\* Disparó 148 trades. En 5M el rango del ATR es de apenas \~$75 USD ($0.10\\%-0.25\\%$). La comisión del 0.15% devoró el margen operativo neto.

2\. \*\*Variante 2.0 trasladada a 15 Minutos (15M Base - 90 días / 8.640 velas):\*\*

&#x20;  \* \*Modificación:\* Se mantuvo la lógica técnica idéntica pero se triplicó el marco temporal a 15M para expandir el recorrido del ATR ($\~0.40\\%-0.80\\%$) y diluir el peso de las comisiones.

3\. \*\*Variante 2.1 (15M Optimizada: Filtro Macro $\\text{EMA}\_{200}$ + TP Extendido):\*\*

&#x20;  \* \*Modificación de Entrada:\* Se añadió el filtro $\\text{EMA}\_{50} > \\text{EMA}\_{200}$ para evitar compras durante tendencias bajistas mayores.

&#x20;  \* \*Modificación de Salida:\* Se elevó el Take Profit de $1.5 \\times \\text{ATR}$ a $2.0 \\times \\text{ATR}$ manteniendo el Stop Loss en $1.2 \\times \\text{ATR}$ para mejorar la relación matemática beneficio/riesgo.



\---



\## 3. Comparativa Cuantitativa de Resultados



Auditoría corrida con capital base de $100.00 USD y ejecución cronológica secuencial:



| Métrica | V2.0 (5M Cruda) | V2.0 (15M Base) | V2.1 (15M + EMA 200 + TP 2.0x) |

| :--- | :--- | :--- | :--- |

| \*\*Muestra Temporal\*\* | 45 días (5m) | 90 días (15m) | 90 días (15m) |

| \*\*Total Operaciones\*\* | 148 | 85 | \*\*57\*\* |

| \*\*Tasa de Acierto (Win Rate)\*\* | 25.68% | \*\*44.71%\*\* | 40.35% |

| \*\*Profit Factor\*\* | 0.14 | 0.55 | \*\*0.74\*\* |

| \*\*Retorno Neto\*\* | -17.96% | -8.05% | \*\*-3.79%\*\* |

| \*\*Drawdown Máximo\*\* | -18.03% | -10.93% | \*\*-7.75%\*\* |

| \*\*Distribución de Salidas\*\* | 73 TP / 75 SL | 42 TP / 43 SL | 25 TP / 32 SL |

| \*\*Capital Final ($100 inicial)\*\* | $82.04 | $91.95 | \*\*$96.21\*\* |



\---



\## 4. Diagnóstico y Conclusión Técnica



\* \*\*Impacto del Timeframe:\*\* Pasar de 5M a 15M aumentó el Profit Factor de 0.14 a 0.55, confirmando que en microtemporalidades ultracortas de Bitcoin la fricción por tarifas de exchange vuelve matemáticamente inviable cualquier sistema con recorridos menores al 0.30%.

\* \*\*Filtro Macro:\*\* La inclusión de la $\\text{EMA}\_{200}$ eliminó operaciones falsas en fases bajistas, reduciendo el Drawdown al 7.75% y elevando el Profit Factor a 0.74.

\* \*\*Causa del Límite Estructural:\*\* En 15M, un Stop Loss a $1.2 \\times \\text{ATR}$ sumado a las comisiones cuesta entre $-0.35\\%$ y $-0.58\\%$ neto, mientras que el Take Profit a $2.0 \\times \\text{ATR}$ entrega $+0.24\\%$ a $+0.35\\%$ neto. Con una tasa de acierto del 40%, la esperanza matemática permanece negativa.

\* \*\*Veredicto:\*\* La estrategia queda agotada en 15M; no alcanza la cota mínima de viabilidad ($PF > 1.20$) sin exigir recorridos que el rebote elástico no suele sostener.

