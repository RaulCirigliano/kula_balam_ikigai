"""

Motor de simulación cuantitativa para Donchian Breakout 1H con filtro de días (Martes a Jueves).

Deduce comisiones de exchange (0.15% round-trip).

"""

import os

import pandas as pd

import numpy as np

from indicators import agregar\_indicadores\_breakout

from strategy import generar\_senales\_breakout



def ejecutar\_backtest\_breakout\_dinamico(

&#x20;   df: pd.DataFrame,

&#x20;   capital\_inicial: float = 100.0,

&#x20;   comision\_pct: float = 0.00075

) -> dict:

&#x20;   posicion\_abierta = False

&#x20;   precio\_entrada = 0.0

&#x20;   sl = 0.0

&#x20;   tiempo\_entrada = None



&#x20;   historial\_trades = \[]

&#x20;   capital = capital\_inicial



&#x20;   for i in range(len(df)):

&#x20;       fila = df.iloc\[i]



&#x20;       if not posicion\_abierta:

&#x20;           if fila\['signal'] == 1:

&#x20;               posicion\_abierta = True

&#x20;               precio\_entrada = fila\['close']

&#x20;               sl = fila\['sl\_price']

&#x20;               tiempo\_entrada = fila\['datetime']

&#x20;               continue



&#x20;       if posicion\_abierta:

&#x20;           salida\_ejecutada = False

&#x20;           precio\_salida = 0.0

&#x20;           motivo = ""



&#x20;           if fila\['low'] <= sl:

&#x20;               salida\_ejecutada = True

&#x20;               precio\_salida = sl

&#x20;               motivo = "SL"

&#x20;           elif fila\['close'] < fila\['donchian\_mid']:

&#x20;               salida\_ejecutada = True

&#x20;               precio\_salida = fila\['close']

&#x20;               motivo = "MID\_EXIT"



&#x20;           if salida\_ejecutada:

&#x20;               retorno\_bruto = (precio\_salida - precio\_entrada) / precio\_entrada

&#x20;               costo\_comision = comision\_pct \* 2

&#x20;               retorno\_neto = retorno\_bruto - costo\_comision



&#x20;               pnl\_usd = capital \* retorno\_neto

&#x20;               capital += pnl\_usd



&#x20;               historial\_trades.append({

&#x20;                   "entrada\_tiempo": tiempo\_entrada,

&#x20;                   "salida\_tiempo": fila\['datetime'],

&#x20;                   "precio\_entrada": precio\_entrada,

&#x20;                   "precio\_salida": precio\_salida,

&#x20;                   "motivo": motivo,

&#x20;                   "retorno\_neto\_pct": retorno\_neto \* 100,

&#x20;                   "pnl\_usd": pnl\_usd,

&#x20;                   "capital\_acumulado": capital

&#x20;               })



&#x20;               posicion\_abierta = False



&#x20;   df\_trades = pd.DataFrame(historial\_trades)



&#x20;   if len(df\_trades) > 0:

&#x20;       trades\_ganadores = df\_trades\[df\_trades\['pnl\_usd'] > 0]

&#x20;       trades\_perdedores = df\_trades\[df\_trades\['pnl\_usd'] <= 0]



&#x20;       win\_rate = (len(trades\_ganadores) / len(df\_trades)) \* 100

&#x20;       ganancia\_bruta = trades\_ganadores\['pnl\_usd'].sum()

&#x20;       perdida\_bruta = abs(trades\_perdedores\['pnl\_usd'].sum())

&#x20;       profit\_factor = (ganancia\_bruta / perdida\_bruta) if perdida\_bruta > 0 else np.nan



&#x20;       df\_trades\['max\_capital'] = df\_trades\['capital\_acumulado'].cummax()

&#x20;       df\_trades\['drawdown'] = (df\_trades\['capital\_acumulado'] - df\_trades\['max\_capital']) / df\_trades\['max\_capital']

&#x20;       max\_drawdown = df\_trades\['drawdown'].min() \* 100



&#x20;       retorno\_total\_pct = ((capital - capital\_inicial) / capital\_inicial) \* 100

&#x20;   else:

&#x20;       win\_rate = 0.0

&#x20;       profit\_factor = 0.0

&#x20;       max\_drawdown = 0.0

&#x20;       retorno\_total\_pct = 0.0



&#x20;   return {

&#x20;       "capital\_final": capital,

&#x20;       "retorno\_total\_pct": retorno\_total\_pct,

&#x20;       "total\_trades": len(df\_trades),

&#x20;       "win\_rate": win\_rate,

&#x20;       "profit\_factor": profit\_factor,

&#x20;       "max\_drawdown\_pct": max\_drawdown,

&#x20;       "detalle\_trades": df\_trades

&#x20;   }



if \_\_name\_\_ == "\_\_main\_\_":

&#x20;   ruta\_csv = os.path.join("data", "btc\_usdt\_1h.csv")

&#x20;   if os.path.exists(ruta\_csv):

&#x20;       raw\_df = pd.read\_csv(ruta\_csv)

&#x20;       df\_ind = agregar\_indicadores\_breakout(raw\_df)

&#x20;       

&#x20;       # Filtro activado: solo martes, miércoles y jueves

&#x20;       df\_strat = generar\_senales\_breakout(

&#x20;           df\_ind, mult\_sl=1.5, max\_ancho\_atr=4.5, mult\_vol=1.25, solo\_martes\_a\_jueves=True

&#x20;       )



&#x20;       print("Ejecutando backtest: Donchian 1H (Solo Martes a Jueves)...")

&#x20;       resultados = ejecutar\_backtest\_breakout\_dinamico(df\_strat, capital\_inicial=100.0)



&#x20;       print("\\n" + "="\*45)

&#x20;       print("  RESULTADOS: DONCHIAN 1H (MARTES A JUEVES)")

&#x20;       print("="\*45)

&#x20;       print(f"Capital Inicial:     $100.00 USD")

&#x20;       print(f"Capital Final:       ${resultados\['capital\_final']:.2f} USD")

&#x20;       print(f"Retorno Neto:        {resultados\['retorno\_total\_pct']:.2f}%")

&#x20;       print(f"Total Operaciones:   {resultados\['total\_trades']}")

&#x20;       print(f"Tasa de Acierto:     {resultados\['win\_rate']:.2f}%")

&#x20;       print(f"Profit Factor:       {resultados\['profit\_factor']:.2f}")

&#x20;       print(f"Drawdown Maximo:     {resultados\['max\_drawdown\_pct']:.2f}%")

&#x20;       print("="\*45)



&#x20;       df\_t = resultados\['detalle\_trades']

&#x20;       if len(df\_t) > 0:

&#x20;           print("\\nDistribución por motivo de salida:")

&#x20;           print(df\_t\['motivo'].value\_counts())

&#x20;           print("\\nÚltimos 5 trades ejecutados:")

&#x20;           cols = \['entrada\_tiempo', 'salida\_tiempo', 'motivo', 'retorno\_neto\_pct', 'capital\_acumulado']

&#x20;           print(df\_t\[cols].tail())

&#x20;   else:

&#x20;       print("No se encontró data/btc\_usdt\_1h.csv")

