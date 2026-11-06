import pandas as pd, numpy as np
df = pd.read_csv('data/btc_usdt_1h.csv')
df['dh'] = df['high'].shift(1).rolling(20).max()
df['dl'] = df['low'].shift(1).rolling(20).min()
df['dmid'] = (df['dh'] + df['dl']) / 2.0
df['dw'] = df['dh'] - df['dl']
tr = pd.concat([df['high'] - df['low'], (df['high'] - df['close'].shift(1)).abs(), (df['low'] - df['close'].shift(1)).abs()], axis=1).max(axis=1)
df['atr'] = tr.rolling(14).mean()
df['ema100'] = df['close'].ewm(span=100, adjust=False).mean()
df['slope'] = (df['ema100'] - df['ema100'].shift(5)) / df['ema100'] * 100
df['vma'] = df['volume'].rolling(20).mean()
c_buy = (df['close'] > df['dh']) & (df['close'] > df['ema100']) & (df['dw'] <= 4.5 * df['atr']) & (df['volume'] > 1.25 * df['vma']) & (df['slope'] > 0)
closes, highs, lows, dmids, atrs = df['close'].to_numpy(), df['high'].to_numpy(), df['low'].to_numpy(), df['dmid'].to_numpy(), df['atr'].to_numpy()
sigs = np.where(c_buy, 1, 0)
n = len(df)

# 1. MID_EXIT puro (100%)
cap1, pos1, ent1, sl1 = 100.0, False, 0.0, 0.0
t1 = []
for i in range(n):
    if not pos1 and sigs[i] == 1:
        pos1, ent1, sl1 = True, closes[i], closes[i] - 1.5 * atrs[i]
        continue
    if pos1:
        out, pout = False, 0.0
        if lows[i] <= sl1: out, pout = True, sl1
        elif closes[i] < dmids[i]: out, pout = True, closes[i]
        if out:
            ret = ((pout - ent1) / ent1) - 0.0015
            cap1 += cap1 * ret
            t1.append(ret)
            pos1 = False

# 2. Parcial 50% (+2 ATR) + BreakEven (+0.25% bruto)
cap2, pos2, ent2, sl2, tp2, parc = 100.0, False, 0.0, 0.0, 0.0, False
t2 = []
for i in range(n):
    if not pos2 and sigs[i] == 1:
        pos2, ent2, sl2, tp2, parc = True, closes[i], closes[i] - 1.5 * atrs[i], closes[i] + 2.0 * atrs[i], False
        continue
    if pos2:
        pnl = 0.0
        if not parc and highs[i] >= tp2:
            pnl += 0.5 * (((tp2 - ent2) / ent2) - 0.0015)
            parc = True
            sl2 = ent2 * 1.0025
        out, pout = False, 0.0
        if lows[i] <= sl2: out, pout = True, sl2
        elif closes[i] < dmids[i]: out, pout = True, closes[i]
        if out:
            frac = 0.5 if parc else 1.0
            pnl += frac * (((pout - ent2) / ent2) - 0.0015)
            cap2 += cap2 * pnl
            t2.append(pnl)
            pos2 = False

def stats(t, cap, label):
    s = pd.Series(t)
    g, p = s[s > 0].sum(), abs(s[s <= 0].sum())
    pf = (g / p) if p > 0 else 0
    wr = (len(s[s > 0]) / len(s) * 100) if len(s) > 0 else 0
    print(f'{label} -> Trades: {len(s)} | WinRate: {wr:.1f}% | PF: {pf:.2f} | Capital: {cap:.2f} USDT')

print('=' * 68)
print('  AUDITORIA DE SALIDAS (PASO 3: MID_EXIT vs PARCIAL + BE)')
print('=' * 68)
stats(t1, cap1, '1. MID_EXIT Puro (100%)    ')
stats(t2, cap2, '2. Parcial 50% (+2 ATR)+BE ')
print('=' * 68)
