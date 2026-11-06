import ccxt
import pandas as pd
import numpy as np

def to_df(data):
    df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    return df

def calcular_indicadores(df):
    df['ema_20'] = df['close'].ewm(span=20, adjust=False).mean().shift(1)
    df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean().shift(1)
    df['vol_sma20'] = df['volume'].rolling(window=20).mean().shift(1)
    df['trail_low_3'] = df['low'].rolling(window=3).min().shift(1)
    df['trail_high_3'] = df['high'].rolling(window=3).max().shift(1)
    return df

def auditar_simbolo(symbol, exchange):
    print(f"  -> Descargando 1000 velas 1H para {symbol}...")
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=1000)
    df = to_df(ohlcv)
    df = calcular_indicadores(df)

    balance = 100.0
    risk_usd = 1.00
    fee_rate = 0.00075

    in_pos = False
    pos_side = None
    entry_price = 0.0
    current_sl = 0.0
    pos_size_usd = 0.0

    trades = []

    print(f"  -> Auditando lógica en {len(df)} velas...")
    for i in range(50, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]

        if in_pos:
            hit_exit = False
            exit_price = 0.0

            if pos_side == 'LONG':
                if row['low'] <= current_sl:
                    exit_price = current_sl
                    hit_exit = True
                else:
                    new_sl = row['trail_low_3']
                    if not pd.isna(new_sl) and new_sl > current_sl:
                        current_sl = new_sl

                if hit_exit:
                    raw_pnl = (exit_price - entry_price) / entry_price
                    net_pnl = (pos_size_usd * raw_pnl) - (pos_size_usd * 2 * fee_rate)
                    balance += net_pnl
                    trades.append({'symbol': symbol, 'side': pos_side, 'type': 'Trailing_SL', 'pnl': net_pnl})
                    in_pos = False
                    continue

            elif pos_side == 'SHORT':
                if row['high'] >= current_sl:
                    exit_price = current_sl
                    hit_exit = True
                else:
                    new_sl = row['trail_high_3']
                    if not pd.isna(new_sl) and new_sl < current_sl:
                        current_sl = new_sl

                if hit_exit:
                    raw_pnl = (entry_price - exit_price) / entry_price
                    net_pnl = (pos_size_usd * raw_pnl) - (pos_size_usd * 2 * fee_rate)
                    balance += net_pnl
                    trades.append({'symbol': symbol, 'side': pos_side, 'type': 'Trailing_SL', 'pnl': net_pnl})
                    in_pos = False
                    continue

        if not in_pos:
            vol_ok = prev['volume'] > prev['vol_sma20']

            if (prev['close'] > prev['ema_20']) and (prev['ema_20'] > prev['ema_50']) and vol_ok:
                entry_price = row['open']
                initial_sl = row['trail_low_3']
                if not pd.isna(initial_sl) and initial_sl < entry_price:
                    risk_pct = (entry_price - initial_sl) / entry_price
                    if 0.008 <= risk_pct <= 0.045:
                        pos_size_usd = min(balance, risk_usd / risk_pct)
                        current_sl = initial_sl
                        in_pos = True
                        pos_side = 'LONG'

            elif (prev['close'] < prev['ema_20']) and (prev['ema_20'] < prev['ema_50']) and vol_ok:
                entry_price = row['open']
                initial_sl = row['trail_high_3']
                if not pd.isna(initial_sl) and initial_sl > entry_price:
                    risk_pct = (initial_sl - entry_price) / entry_price
                    if 0.008 <= risk_pct <= 0.045:
                        pos_size_usd = min(balance, risk_usd / risk_pct)
                        current_sl = initial_sl
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
    print("  AUDITORÍA: TRAILING DINÁMICO - TENDENCIA SIN TECHO (1H)")
    print("  Sin TP Fijo, Trailing SL 3 Velas | 1000 velas 1H")
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
