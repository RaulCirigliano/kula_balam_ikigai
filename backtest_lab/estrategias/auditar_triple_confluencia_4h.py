import ccxt
import pandas as pd
import numpy as np

def to_df(data):
    df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    return df

def calcular_indicadores(df):
    # EMAs 21 y 89 en 4H (shift 1 sobre velas cerradas)
    df['ema_21'] = df['close'].ewm(span=21, adjust=False).mean().shift(1)
    df['ema_89'] = df['close'].ewm(span=89, adjust=False).mean().shift(1)

    # ATR 14 y Expansión de Volatilidad
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift(1)).abs()
    low_close = (df['low'] - df['close'].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(window=14).mean().shift(1)
    df['atr_sma20'] = df['atr'].rolling(window=20).mean().shift(1)
    df['atr_expanded'] = df['atr'] > df['atr_sma20']

    return df

def auditar_simbolo(symbol, exchange):
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe='4h', limit=1000)
    df = to_df(ohlcv)
    df = calcular_indicadores(df)

    initial_balance = 100.0
    balance = initial_balance
    risk_usd = 1.00
    fee_rate = 0.00075

    in_pos = False
    pos_side = None
    entry_price = 0.0
    sl_price = 0.0
    tp_price = 0.0
    pos_size_usd = 0.0

    trades = []

    for i in range(90, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]

        # Monitorear posición activa
        if in_pos:
            hit_exit = False
            exit_price = 0.0
            exit_reason = ""

            if pos_side == 'LONG':
                if row['low'] <= sl_price:
                    exit_price = sl_price
                    exit_reason = 'SL'
                    hit_exit = True
                elif row['high'] >= tp_price:
                    exit_price = tp_price
                    exit_reason = 'TP'
                    hit_exit = True

                if hit_exit:
                    raw_pnl = (exit_price - entry_price) / entry_price
                    net_pnl = (pos_size_usd * raw_pnl) - (pos_size_usd * 2 * fee_rate)
                    balance += net_pnl
                    trades.append({'symbol': symbol, 'side': pos_side, 'type': exit_reason, 'pnl': net_pnl})
                    in_pos = False

            elif pos_side == 'SHORT':
                if row['high'] >= sl_price:
                    exit_price = sl_price
                    exit_reason = 'SL'
                    hit_exit = True
                elif row['low'] <= tp_price:
                    exit_price = tp_price
                    exit_reason = 'TP'
                    hit_exit = True

                if hit_exit:
                    raw_pnl = (entry_price - exit_price) / entry_price
                    net_pnl = (pos_size_usd * raw_pnl) - (pos_size_usd * 2 * fee_rate)
                    balance += net_pnl
                    trades.append({'symbol': symbol, 'side': pos_side, 'type': exit_reason, 'pnl': net_pnl})
                    in_pos = False

        # Gatillo de entrada si no hay posición
        if not in_pos:
            atr_val = row['atr']
            if pd.isna(atr_val) or atr_val <= 0:
                continue

            # 1. Condición LONG:
            # - Tendencia: EMA 21 > EMA 89
            # - Volatilidad: ATR expandido
            # - Confluencia: La vela previa testeó la zona entre EMA 21 y 89 y cerró arriba de la EMA 21
            if (row['ema_21'] > row['ema_89']) and row['atr_expanded']:
                tested_zone = prev['low'] <= prev['ema_21'] and prev['low'] >= prev['ema_89']
                bull_bounce = prev['close'] > prev['ema_21'] and prev['close'] > prev['open']
                if tested_zone and bull_bounce:
                    entry_price = row['open']
                    sl_price = entry_price - (1.5 * atr_val)
                    risk_pct = (entry_price - sl_price) / entry_price
                    if 0.01 <= risk_pct <= 0.08:
                        tp_price = entry_price + ((entry_price - sl_price) * 2.0)
                        pos_size_usd = min(balance, risk_usd / risk_pct)
                        in_pos = True
                        pos_side = 'LONG'

            # 2. Condición SHORT:
            # - Tendencia: EMA 21 < EMA 89
            # - Volatilidad: ATR expandido
            # - Confluencia: La vela previa testeó entre EMA 21 y 89 y cerró abajo de la EMA 21
            elif (row['ema_21'] < row['ema_89']) and row['atr_expanded']:
                tested_zone = prev['high'] >= prev['ema_21'] and prev['high'] <= prev['ema_89']
                bear_bounce = prev['close'] < prev['ema_21'] and prev['close'] < prev['open']
                if tested_zone and bear_bounce:
                    entry_price = row['open']
                    sl_price = entry_price + (1.5 * atr_val)
                    risk_pct = (sl_price - entry_price) / entry_price
                    if 0.01 <= risk_pct <= 0.08:
                        tp_price = entry_price - ((sl_price - entry_price) * 2.0)
                        pos_size_usd = min(balance, risk_usd / risk_pct)
                        in_pos = True
                        pos_side = 'SHORT'

    return trades, balance

def run():
    exchange = ccxt.binance()
    symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
    all_trades = []

    print("==========================================================")
    print("  AUDITORÍA: TRIPLE CONFLUENCIA SWING 4H (BTC, ETH, SOL)")
    print("  EMA 21/89, Rebote de Banda, Expansión ATR | 1000 velas 4H")
    print("==========================================================")

    for sym in symbols:
        print(f"Descargando y evaluando {sym} en 4H...")
        trades, _ = auditar_simbolo(sym, exchange)
        all_trades.extend(trades)

    if not all_trades:
        print("No se generaron trades con los filtros aplicados.")
        return

    df_t = pd.DataFrame(all_trades)
    total_trades = len(df_t)
    wins = df_t[df_t['pnl'] > 0]
    losses = df_t[df_t['pnl'] <= 0]

    win_rate = (len(wins) / total_trades) * 100
    gross_profit = wins['pnl'].sum() if not wins.empty else 0.0
    gross_loss = abs(losses['pnl'].sum()) if not losses.empty else 0.0
    net_pnl = df_t['pnl'].sum()
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0.0

    print("\n---------------- RESULTADOS FINALES ----------------")
    print(f"Total Operaciones:    {total_trades}")
    print(f"Operaciones Ganadas:  {len(wins)}")
    print(f"Operaciones Perdidas: {len(losses)}")
    print(f"Win Rate:             {win_rate:.2f}%")
    print(f"Ganancia Bruta:       +${gross_profit:.2f} USD")
    print(f"Pérdida Bruta:        -${gross_loss:.2f} USD")
    print(f"Profit Factor:        {profit_factor:.2f}")
    print(f"PnL Neto:             {net_pnl:+.2f} USD ({net_pnl:+.2f}%)")
    print("----------------------------------------------------\n")

if __name__ == '__main__':
    run()
