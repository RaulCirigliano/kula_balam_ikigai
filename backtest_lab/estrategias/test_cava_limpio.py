import pandas as pd
import numpy as np

# 1. Cargar datos
df = pd.read_csv('data/btc_usdt_1h.csv')

# 2. Indicadores base
df['ema100'] = df['close'].ewm(span=100, adjust=False).mean()
df['slope100'] = (df['ema100'] - df['ema100'].shift(5)) / df['ema100'] * 100

df['swing_high'] = df['high'].shift(1).rolling(20).max()
df['swing_low'] = df['low'].shift(1).rolling(20).min()
rango = df['swing_high'] - df['swing_low']

df['fibo_50'] = df['swing_high'] - (rango * 0.50)
df['fibo_75'] = df['swing_high'] - (rango * 0.75)

tr = pd.concat([
    df['high'] - df['low'],
    (df['high'] - df['close'].shift(1)).abs(),
    (df['low'] - df['close'].shift(1)).abs()
], axis=1).max(axis=1)
df['atr'] = tr.rolling(14).mean()

df['vol_ma20'] = df['volume'].rolling(20).mean()

# 3. Condiciones reconstruidas
tendencia_madre = (df['close'] > df['ema100']) & (df['slope100'] > 0)
en_zona_dorada = (df['low'] <= df['fibo_50']) & (df['close'] >= df['fibo_75'])
secado_volumen = df['volume'] < (df['vol_ma20'] * 0.85)
vela_verde_rechazo = df['close'] > df['open']

c_compra = tendencia_madre & en_zona_dorada & secado_volumen & vela_verde_rechazo

# 4. Simulación con comisiones (0.15% round-trip)
closes = df['close'].to_numpy()
lows = df['low'].to_numpy()
atrs = df['atr'].to_numpy()
sigs = np.where(c_compra, 1, 0)
n = len(df)

cap = 100.0
pos = False
ent, sl, tp = 0.0, 0.0, 0.0
trades = []

for i in range(n):
    if not pos and sigs[i] == 1:
        pos = True
        ent = closes[i]
        sl = closes[i] - (1.5 * atrs[i])
        tp = closes[i] + (3.0 * atrs[i])
        continue
    if pos:
        out, pout = False, 0.0
        if lows[i] <= sl:
            out, pout = True, sl
        elif closes[i] >= tp:
            out, pout = True, tp
        elif closes[i] < (ent - 0.5 * atrs[i]):
            out, pout = True, closes[i]

        if out:
            ret = ((pout - ent) / ent) - 0.0015
            cap += cap * ret
            trades.append(ret)
            pos = False

s = pd.Series(trades)
g = s[s > 0].sum()
p = abs(s[s <= 0].sum())
pf = (g / p) if p > 0 else 0
wr = (len(s[s > 0]) / len(s) * 100) if len(s) > 0 else 0

print("=" * 68)
print("  AUDITORIA LIMPIA: CAVA & RUIZ RECONSTRUIDO (BTC 1H)")
print("=" * 68)
print(f"Total Trades:   {len(s)}")
print(f"Win Rate:       {wr:.2f}%")
print(f"Profit Factor:  {pf:.2f}")
print(f"Capital Final:  {cap:.2f} USDT (Inversion inicial: 100.00 USDT)")
print("=" * 68)
