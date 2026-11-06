import ccxt
import pandas as pd
import numpy as np

def to_df(data):
    df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    return df

def calcular_indicadores(df):
    df['ema_20'] = df['close'].ewm(span=20, adjust=False).mean().shift(1)
    df['vol_sma20'] = df['volume'].rolling(window=20).mean().shift(1)

    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift(1)).abs()
    low_close = (df['low'] - df['close'].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(window=14).mean().shift(1)

    # Tamaño del cuerpo
    df['body'] = (df['close'] - df['open']).abs()
    df['prev_max_body_10'] = df['body'].rolling(window=10).max().shift(1)

    return df

def auditar_simbolo(symbol, exchange):
    print(f"  -> Descargando 1000 velas 4H para {symbol}...")
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe='4h', limit=1000)
    df = to_df(ohlcv)
    df = calcular_indicadores(df)

    balance = 100.0
    risk_usd = 1.00
    fee_rate = 0.00075

    in_pos = False
    pos_side = None
    entry_price = 0.0
    sl_price = 0.0
    tp_price = 0.0
    pos_size_usd = 0.0

    trades = []

    print(f"  -> Auditando lógica en {len(df)} velas...")
    for i in range(30, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]

        # 1. Monitoreo de posición activa
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
                    continue

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
                    continue

        # 2. Gatillo de entrada si no hay posición
        if not in_pos:
            atr_val = prev['atr']
            vol_mean = prev['vol_sma20']
            body_val = prev['body']
            prev_max = prev['prev_max_body_10']

            if pd.isna(atr_val) or atr_val <= 0 or pd.isna(vol_mean) or vol_mean <= 0:
                continue

            # Condiciones de Vela Elefante:
            # - Cuerpo >= 1.8 * ATR
            # - Cuerpo mayor a las últimas 10 velas
            # - Volumen >= 1.4 * media de 20
            is_elephant = (body_val >= 1.8 * atr_val) and (body_val >= prev_max) and (prev['volume'] >= 1.4 * vol_mean)

            if is_elephant:
                # Caso LONG: Vela elefante verde
                if prev['close'] > prev['open'] and prev['close'] > row['ema_20']:
                    entry_price = row['open']
                    # SL al 50% del cuerpo de la vela elefante
                    sl_price = prev['open'] + (body_val * 0.50)
                    risk_pct = (entry_price - sl_price) / entry_price

                    if 0.01 <= risk_pct <= 0.06:
                        tp_price = entry_price + ((entry_price - sl_price) * 2.0)
                        pos_size_usd = min(balance, risk_usd / risk_pct)
                        in_pos = True
                        pos_side = 'LONG'

                # Caso SHORT: Vela elefante roja
                elif prev['close'] < prev['open'] and prev['close'] < row['ema_20']:
                    entry_price = row['open']
                    # SL al 50% del cuerpo de la vela elefante
                    sl_price = prev['open'] - (body_val * 0.50)
                    risk_pct = (sl_price - entry_price) / entry_price

                    if 0.01 <= risk_pct <= 0.06:
                        tp_price = entry_price - ((sl_price - entry_price) * 2.0)
                        pos_size_usd = min(balance, risk_usd / risk_pct)
                        in_pos = True
                        pos_side = 'SHORT'

    return trades, balance

def run():
    exchange = ccxt.binance({
        'enableRateLimit': True,
        'timeout': 10000
    })
    symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
    all_trades = []

    print("==========================================================")
    print("  AUDITORÍA: HYENUK CHU - SWING MULTIBAGGER 4H")
    print("  Vela Elefante, Stop 50% Cuerpo, TP 1:2.0 | 1000 velas 4H")
    print("==========================================================")

    for sym in symbols:
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
