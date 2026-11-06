import pandas as pd
import numpy as np

class BalamQuant:
    def __init__(self):
        self.atr_config = {
            'BTC/USDT': 0.50,
            'ETH/USDT': 0.50,
            'SOL/USDT': 0.85
        }

    def calcular_indicadores(self, df_1h, df_1d, symbol):
        # 1. Sesgo Macro Diario (1D)
        df_1d['ema_50'] = df_1d['close'].ewm(span=50, adjust=False).mean()
        df_1d['ema_slope'] = df_1d['ema_50'] - df_1d['ema_50'].shift(2)
        df_1d['macro_bias'] = np.where(
            (df_1d['close'] > df_1d['ema_50']) & (df_1d['ema_slope'] >= 0), 'LONG',
            np.where((df_1d['close'] < df_1d['ema_50']) & (df_1d['ema_slope'] <= 0), 'SHORT', 'NEUTRAL')
        )
        df_1d['date'] = df_1d['datetime'].dt.date
        df_1d['macro_bias_closed'] = df_1d['macro_bias'].shift(1)
        macro_map = dict(zip(df_1d['date'], df_1d['macro_bias_closed']))

        # 2. Indicadores en 1H
        high_low = df_1h['high'] - df_1h['low']
        high_close = (df_1h['high'] - df_1h['close'].shift(1)).abs()
        low_close = (df_1h['low'] - df_1h['close'].shift(1)).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df_1h['atr'] = tr.rolling(window=14).mean().shift(1)
        df_1h['vol_sma20'] = df_1h['volume'].rolling(window=20).mean().shift(1)

        # Fractales Williams (5 velas)
        h = df_1h['high']
        l = df_1h['low']
        is_f_high = (h.shift(2) > h.shift(3)) & (h.shift(2) > h.shift(4)) & (h.shift(2) > h.shift(1)) & (h.shift(2) > h)
        is_f_low = (l.shift(2) < l.shift(3)) & (l.shift(2) < l.shift(4)) & (l.shift(2) < l.shift(1)) & (l.shift(2) < l)

        df_1h['fractal_high'] = np.where(is_f_high, h.shift(2), np.nan)
        df_1h['fractal_low'] = np.where(is_f_low, l.shift(2), np.nan)
        df_1h['last_fractal_high'] = df_1h['fractal_high'].ffill().bfill().shift(1)
        df_1h['last_fractal_low'] = df_1h['fractal_low'].ffill().bfill().shift(1)

        df_1h['date'] = df_1h['datetime'].dt.date
        df_1h['macro_bias'] = df_1h['date'].map(macro_map)
        df_1h['atr_mult'] = self.atr_config.get(symbol, 0.50)

        return df_1h

    def escanear_senal(self, df_1h, symbol):
        if len(df_1h) < 5:
            return None

        # Evaluamos las 3 velas cerradas previas
        row = df_1h.iloc[-1]
        v3 = df_1h.iloc[-2] # Vela que gatilla quiebre
        v2 = df_1h.iloc[-3]
        v1 = df_1h.iloc[-4]

        bias = row['macro_bias']
        if bias not in ['LONG', 'SHORT']:
            return None

        s_high = row['last_fractal_high']
        s_low = row['last_fractal_low']
        s_range = max(0.0001, s_high - s_low)
        atr_val = row['atr']
        vol_mean = row['vol_sma20']
        atr_mult = row['atr_mult']

        rvol_trigger = v3['volume'] / max(1.0, vol_mean)
        trigger_vol_ok = rvol_trigger > 1.0
        last_close = v3['close']
        entry_price = row['open']

        if bias == 'LONG':
            fibo = (s_high - last_close) / s_range
            in_zone = 0.45 <= fibo <= 0.75
            bos = (last_close > v2['high']) and (last_close > v1['high'])

            if in_zone and bos and trigger_vol_ok:
                base_low = min(v3['low'], v2['low'], v1['low'])
                sl = base_low - (atr_mult * atr_val)
                risk_pct = (entry_price - sl) / entry_price
                if 0.008 <= risk_pct <= 0.045:
                    tp = entry_price + ((entry_price - sl) * 2.0)
                    return {
                        'symbol': symbol, 'side': 'LONG', 'entry': entry_price,
                        'sl': sl, 'tp': tp, 'risk_pct': risk_pct, 'datetime': row['datetime']
                    }

        elif bias == 'SHORT':
            fibo = (last_close - s_low) / s_range
            in_zone = 0.45 <= fibo <= 0.75
            bos = (last_close < v2['low']) and (last_close < v1['low'])

            if in_zone and bos and trigger_vol_ok:
                base_high = max(v3['high'], v2['high'], v1['high'])
                sl = base_high + (atr_mult * atr_val)
                risk_pct = (sl - entry_price) / entry_price
                if 0.008 <= risk_pct <= 0.045:
                    tp = entry_price - ((sl - entry_price) * 2.0)
                    return {
                        'symbol': symbol, 'side': 'SHORT', 'entry': entry_price,
                        'sl': sl, 'tp': tp, 'risk_pct': risk_pct, 'datetime': row['datetime']
                    }

        return None
