import yfinance as yf
import pandas as pd
import numpy as np

def fetch_stock_data(ticker, interval, period):
    print(f"[*] Descargando {ticker} en temporalidad {interval} ({period})...")
    df = yf.download(ticker, period=period, interval=interval, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0].lower() for col in df.columns]
    else:
        df.columns = [col.lower() for col in df.columns]
    df = df.dropna().copy()
    return df

def simulate_donchian_stocks(df, fee_rate=0.0005):
    # Donchian 20 y EMA 200 sobre velas cerradas previas (shift 1 sin repainting)
    df = df.copy()
    df['donchian_high'] = df['high'].shift(1).rolling(20).max()
    df['donchian_low'] = df['low'].shift(1).rolling(20).min()
    df['donchian_mid'] = (df['donchian_high'] + df['donchian_low']) / 2.0
    df['ema200'] = df['close'].shift(1).ewm(span=200, adjust=False).mean()

    trades = []
    capital = 100.0
    peak_equity = 100.0
    max_dd = 0.0

    in_pos = False
    entry_price = 0.0

    for i in range(201, len(df)):
        row = df.iloc[i]
        close = float(row['close'])
        low = float(row['low'])
        mid = float(row['donchian_mid'])
        upper = float(row['donchian_high'])
        ema = float(row['ema200'])

        # 1. Monitoreo de posición abierta (Salida Estructural MID_EXIT)
        if in_pos:
            exit_price = None
            exit_reason = None

            initial_sl = entry_price * 0.985  # SL de seguridad al 1.5%
            if low <= initial_sl:
                exit_price = initial_sl
                exit_reason = 'SL'
            elif close < mid:
                exit_price = close
                exit_reason = 'MID_EXIT'

            if exit_price is not None:
                raw_return = (exit_price - entry_price) / entry_price
                net_return = raw_return - fee_rate
                trade_usd = min(capital, 100.0) * net_return
                capital += trade_usd

                if capital > peak_equity:
                    peak_equity = capital
                dd = (peak_equity - capital) / peak_equity * 100.0
                if dd > max_dd:
                    max_dd = dd

                trades.append({
                    'exit_reason': exit_reason,
                    'net_return': net_return,
                    'pnl_usd': trade_usd
                })
                in_pos = False

        # 2. Entrada: Breakout Donchian + Filtro Macro EMA 200
        if not in_pos:
            if close > upper and close > ema:
                in_pos = True
                entry_price = close

    if not trades:
        return {'N': 0, 'WR': 0.0, 'PF': 0.0, 'PnL': 0.0, 'MaxDD': 0.0, 'Salidas': {}}

    df_t = pd.DataFrame(trades)
    wins = df_t[df_t['pnl_usd'] > 0]
    losses = df_t[df_t['pnl_usd'] <= 0]

    wr = (len(wins) / len(df_t)) * 100.0
    gross_profit = wins['pnl_usd'].sum()
    gross_loss = abs(losses['pnl_usd'].sum())
    pf = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)
    pnl_neto = df_t['pnl_usd'].sum()
    salidas = df_t['exit_reason'].value_counts().to_dict()

    return {
        'N': len(df_t),
        'WR': round(wr, 2),
        'PF': round(pf, 2),
        'PnL': round(pnl_neto, 2),
        'MaxDD': round(max_dd, 2),
        'Salidas': salidas
    }

def main():
    tickers = [
        ('SPY', 'S&P 500 ETF (SPY)'),
        ('NVDA', 'NVIDIA Corp (NVDA)')
    ]

    print("=" * 76)
    print(" AUDITORÍA WALL STREET: DONCHIAN + MID_EXIT (1H VS 1D)")
    print("=" * 76)

    for ticker, name in tickers:
        df_1h = fetch_stock_data(ticker, interval='1h', period='700d')
        res_1h = simulate_donchian_stocks(df_1h)

        df_1d = fetch_stock_data(ticker, interval='1d', period='5y')
        res_1d = simulate_donchian_stocks(df_1d)

        print(f"\nResultados para {name}:")
        print("-" * 76)
        print(f"{'Métrica':<22} | {'Horizonte 1H (~2 años)':<23} | {'Horizonte 1D (5 años)':<23}")
        print("-" * 76)
        print(f"{'Trades Totales (N)':<22} | {res_1h['N']:<23} | {res_1d['N']:<23}")
        print(f"{'Win Rate (%)':<22} | {res_1h['WR']:<23} | {res_1d['WR']:<23}")
        print(f"{'Profit Factor (PF)':<22} | {res_1h['PF']:<23} | {res_1d['PF']:<23}")
        print(f"{'PnL Neto (USD)':<22} | ${res_1h['PnL']:<22} | ${res_1d['PnL']:<22}")
        print(f"{'Max Drawdown (%)':<22} | {res_1h['MaxDD']}%{'' :<22} | {res_1d['MaxDD']}%{'' :<22}")
        print(f"{'Desglose Salidas':<22} | {str(res_1h['Salidas']):<23} | {str(res_1d['Salidas']):<23}")
        print("-" * 76)

if __name__ == '__main__':
    main()
