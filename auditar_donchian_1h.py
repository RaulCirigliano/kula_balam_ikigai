import ccxt
import pandas as pd
import numpy as np

def to_df(data):
    df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    return df

def calcular_indicadores(df):
    # Donchian 20 sobre velas cerradas previas (shift 1 para evitar repintado)
    df['donchian_high'] = df['high'].rolling(window=20).max().shift(1)
    df['donchian_low'] = df['low'].rolling(window=20).min().shift(1)
    df['donchian_mid'] = (df['donchian_high'] + df['donchian_low']) / 2.0

    # EMA 100
    df['ema_100'] = df['close'].ewm(span=100, adjust=False).mean().shift(1)

    # ATR 14 y Compresión
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift(1)).abs()
    low_close = (df['low'] - df['close'].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(window=14).mean().shift(1)
    
    # Ancho del canal Donchian relativo al ATR (compresión: canal estrecho)
    channel_width = df['donchian_high'] - df['donchian_low']
    df['compression'] = channel_width / df['atr']
    df['is_compressed'] = df['compression'] < df['compression'].rolling(window=50).mean()

    return df

def auditar_simbolo(symbol, exchange):
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=1000)
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
    pos_size_usd = 0.0

    trades = []

    for i in range(100, len(df)):
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
                elif row['close'] < row['donchian_mid']: # Mid-Exit
                    exit_price = row['close']
                    exit_reason = 'Mid-Exit'
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
                elif row['close'] > row['donchian_mid']: # Mid-Exit
                    exit_price = row['close']
                    exit_reason = 'Mid-Exit'
                    hit_exit = True

                if hit_exit:
                    raw_pnl = (entry_price - exit_price) / entry_price
                    net_pnl = (pos_size_usd * raw_pnl) - (pos_size_usd * 2 * fee_rate)
                    balance += net_pnl
                    trades.append({'symbol': symbol, 'side': pos_side, 'type': exit_reason, 'pnl': net_pnl})
                    in_pos = False

        # Buscar nueva entrada si está libre
        if not in_pos:
            # Condición LONG: Rompe el máximo previo de 20 + Sobre EMA 100 + Venía de compresión
            if (row['close'] > prev['donchian_high']) and (row['close'] > row['ema_100']) and prev['is_compressed']:
                entry_price = row['close']
                sl_price = row['donchian_mid'] # SL inicial en la línea media
                risk_pct = (entry_price - sl_price) / entry_price
                if 0.005 <= risk_pct <= 0.05:
                    pos_size_usd = min(balance, risk_usd / risk_pct)
                    in_pos = True
                    pos_side = 'LONG'

            # Condición SHORT: Rompe el mínimo previo de 20 + Bajo EMA 100 + Venía de compresión
            elif (row['close'] < prev['donchian_low']) and (row['close'] < row['ema_100']) and prev['is_compressed']:
                entry_price = row['close']
                sl_price = row['donchian_mid']
                risk_pct = (sl_price - entry_price) / entry_price
                if 0.005 <= risk_pct <= 0.05:
                    pos_size_usd = min(balance, risk_usd / risk_pct)
                    in_pos = True
                    pos_side = 'SHORT'

    return trades, balance

def run():
    exchange = ccxt.binance()
    symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
    all_trades = []
    
    print("==========================================================")
    print("  AUDITORÍA: DONCHIAN BREAKOUT 1H (BTC, ETH, SOL)")
    print("  Canal 20, EMA 100, Mid-Exit | 1000 velas (~41 días)")
    print("==========================================================")

    for sym in symbols:
        print(f"Descargando y evaluando {sym}...")
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
