import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timezone

def fetch_data(symbol="BTC/USDT"):
    exchange = ccxt.binance({'enableRateLimit': True})
    print(f"Descargando datos históricos para {symbol}...")
    
    # Descargar ~1000 velas de 5M (~3.5 días de microestructura)
    # y suficiente historial de 1H y 1D para cubrir ese período
    ohlcv_5m = exchange.fetch_ohlcv(symbol, timeframe='5m', limit=1000)
    ohlcv_1h = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=500)
    ohlcv_1d = exchange.fetch_ohlcv(symbol, timeframe='1d', limit=150)
    
    def to_df(data):
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        return df

    return to_df(ohlcv_5m), to_df(ohlcv_1h), to_df(ohlcv_1d)

def run_multitimeframe_backtest():
    df_5m, df_1h, df_1d = fetch_data()

    # 1. Indicadores Macro 1D (EMA 50 sobre velas cerradas previas)
    df_1d['ema_50'] = df_1d['close'].ewm(span=50, adjust=False).mean()
    df_1d['macro_bias'] = np.where(df_1d['close'] > df_1d['ema_50'], 'LONG', 'SHORT')
    # Desplazamos 1 período: el día de hoy solo conoce el cierre de ayer
    df_1d['macro_bias_closed'] = df_1d['macro_bias'].shift(1)

    # 2. Indicadores Estructura 1H (Swing High/Low de 48h previas cerradas)
    # Usamos shift(1) para evitar lookahead bias
    df_1h['swing_high'] = df_1h['high'].shift(1).rolling(48).max()
    df_1h['swing_low'] = df_1h['low'].shift(1).rolling(48).min()
    df_1h['prev_1h_close'] = df_1h['close'].shift(1)

    # 3. Sincronización Temporal Estricta con merge_asof (Lookahead-Free)
    # Cada vela de 5M solo se aparea con la última vela CERRADA disponible
    df = pd.merge_asof(
        df_5m.sort_values('timestamp'),
        df_1h[['timestamp', 'swing_high', 'swing_low', 'prev_1h_close']].sort_values('timestamp'),
        on='timestamp',
        direction='backward'
    )
    df = pd.merge_asof(
        df.sort_values('timestamp'),
        df_1d[['timestamp', 'macro_bias_closed']].sort_values('timestamp'),
        on='timestamp',
        direction='backward'
    )

    df = df.dropna().reset_index(drop=True)

    # Variables de simulación
    fee = 0.00075  # 0.075% comisión spot Binance con BNB
    trades = []
    in_position = False
    pos_side = None
    entry_price = 0.0
    sl_price = 0.0
    tp_price = 0.0

    print("Simulando ejecución vela a vela en 5M...")

    for i in range(3, len(df)):
        row = df.iloc[i]
        prev1 = df.iloc[i-1] # V3 (confirmación)
        prev2 = df.iloc[i-2] # V2 (pausa)
        
        # Gestión de posición abierta
        if in_position:
            if pos_side == 'LONG':
                if row['low'] <= sl_price:
                    pnl = ((sl_price - entry_price) / entry_price) - (2 * fee)
                    trades.append({'side': 'LONG', 'pnl': pnl, 'type': 'SL'})
                    in_position = False
                elif row['high'] >= tp_price:
                    pnl = ((tp_price - entry_price) / entry_price) - (2 * fee)
                    trades.append({'side': 'LONG', 'pnl': pnl, 'type': 'TP'})
                    in_position = False
            elif pos_side == 'SHORT':
                if row['high'] >= sl_price:
                    pnl = ((entry_price - sl_price) / entry_price) - (2 * fee)
                    trades.append({'side': 'SHORT', 'pnl': pnl, 'type': 'SL'})
                    in_position = False
                elif row['low'] <= tp_price:
                    pnl = ((entry_price - tp_price) / entry_price) - (2 * fee)
                    trades.append({'side': 'SHORT', 'pnl': pnl, 'type': 'TP'})
                    in_position = False
            continue

        # Evaluación de Entrada (Embudo 3 Pantallas)
        bias = row['macro_bias_closed']
        s_high = row['swing_high']
        s_low = row['swing_low']
        s_range = max(0.0001, s_high - s_low)
        last_1h_close = row['prev_1h_close']

        if bias == 'LONG':
            fibo = (s_high - last_1h_close) / s_range
            in_zone = 0.50 <= fibo <= 0.75
            # Gatillo 3 Velas en 5M: V3 supera máximo de V2
            trigger = prev1['close'] > prev2['high']
            
            if in_zone and trigger:
                entry_price = row['open']
                sl_price = min(prev1['low'], prev2['low'])
                risk = entry_price - sl_price
                if risk > 0 and (risk / entry_price) <= 0.025: # Filtro anti-anomalías
                    tp_price = entry_price + (risk * 2.0) # R:R 1:2.0 limpio
                    in_position = True
                    pos_side = 'LONG'

        elif bias == 'SHORT':
            fibo = (last_1h_close - s_low) / s_range
            in_zone = 0.50 <= fibo <= 0.75
            # Gatillo 3 Velas en 5M: V3 perfora mínimo de V2
            trigger = prev1['close'] < prev2['low']
            
            if in_zone and trigger:
                entry_price = row['open']
                sl_price = max(prev1['high'], prev2['high'])
                risk = sl_price - entry_price
                if risk > 0 and (risk / entry_price) <= 0.025:
                    tp_price = entry_price - (risk * 2.0) # R:R 1:2.0 limpio
                    in_position = True
                    pos_side = 'SHORT'

    # Consolidación de Métricas Cuantitativas
    if not trades:
        print("No se generaron operaciones en la ventana analizada.")
        return

    df_trades = pd.DataFrame(trades)
    wins = df_trades[df_trades['pnl'] > 0]
    losses = df_trades[df_trades['pnl'] <= 0]
    
    total_gain = wins['pnl'].sum() if not wins.empty else 0.0
    total_loss = abs(losses['pnl'].sum()) if not losses.empty else 0.0
    
    profit_factor = round(total_gain / total_loss, 2) if total_loss > 0 else (999.0 if total_gain > 0 else 0.0)
    win_rate = round((len(wins) / len(df_trades)) * 100, 2)
    net_cum_return = round(df_trades['pnl'].sum() * 100, 2)

    print("\n" + "=" * 55)
    print("📊 RESULTADOS DEL BACKTEST MULTITEMPORAL (1D-1H-5M)")
    print("=" * 55)
    print(f"Total Operaciones:   {len(df_trades)}")
    print(f"Win Rate:            {win_rate}% ({len(wins)}W / {len(losses)}L)")
    print(f"Ganancia Bruta:      +{total_gain*100:.2f}%")
    print(f"Pérdida Bruta:       -{total_loss*100:.2f}%")
    print(f"Retorno Neto:        {net_cum_return:+.2f}%")
    print(f"PROFIT FACTOR (PF):  {profit_factor}")
    print("=" * 55 + "\n")

if __name__ == '__main__':
    run_multitimeframe_backtest()
