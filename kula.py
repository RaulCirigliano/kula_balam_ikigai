import os
import pandas as pd

class KulaRisk:
    def __init__(self, initial_balance=100.0, risk_usd=1.00, fee_rate=0.00075):
        self.balance = initial_balance
        self.risk_per_trade_usd = risk_usd
        self.fee_rate = fee_rate
        self.active_positions = {}
        self.csv_path = '/home/raul/Escritorio/proyectos/kula_balam_ikigai/registro_trades.csv'

    def auditar_y_ejecutar(self, senal):
        symbol = senal['symbol']
        side = senal['side']

        # 1. Filtro: activo ya posicionado
        if symbol in self.active_positions:
            return False, "Activo ya tiene posición abierta"

        # 2. Filtro Anti-Correlación: no duplicar dirección en la canasta
        for pos in self.active_positions.values():
            if pos['side'] == side:
                return False, f"Veto Anti-Correlación: ya existe posición {side} activa"

        # 3. Position Sizing por Volatilidad ($1.00 USD de pérdida máxima)
        pos_size_usd = min(self.balance, self.risk_per_trade_usd / senal['risk_pct'])

        self.active_positions[symbol] = {
            'side': side,
            'entry_price': senal['entry'],
            'sl_price': senal['sl'],
            'tp_price': senal['tp'],
            'pos_size_usd': pos_size_usd,
            'entry_time': senal['datetime']
        }
        return True, f"Posición abierta: {side} en {symbol} | Sizing: ${pos_size_usd:.2f} USD"

    def monitorear_salidas(self, symbol, current_high, current_low, current_time):
        if symbol not in self.active_positions:
            return None

        pos = self.active_positions[symbol]
        entry = pos['entry_price']
        sl = pos['sl_price']
        tp = pos['tp_price']
        size = pos['pos_size_usd']
        side = pos['side']
        trade_out = None

        if side == 'LONG':
            if current_low <= sl:
                raw_pnl = (sl - entry) / entry
                net_pnl = (size * raw_pnl) - (size * 2 * self.fee_rate)
                self.balance += net_pnl
                trade_out = {'symbol': symbol, 'side': side, 'type': 'SL', 'pnl': net_pnl, 'exit_time': current_time}
            elif current_high >= tp:
                raw_pnl = (tp - entry) / entry
                net_pnl = (size * raw_pnl) - (size * 2 * self.fee_rate)
                self.balance += net_pnl
                trade_out = {'symbol': symbol, 'side': side, 'type': 'TP', 'pnl': net_pnl, 'exit_time': current_time}

        elif side == 'SHORT':
            if current_high >= sl:
                raw_pnl = (entry - sl) / entry
                net_pnl = (size * raw_pnl) - (size * 2 * self.fee_rate)
                self.balance += net_pnl
                trade_out = {'symbol': symbol, 'side': side, 'type': 'SL', 'pnl': net_pnl, 'exit_time': current_time}
            elif current_low <= tp:
                raw_pnl = (entry - tp) / entry
                net_pnl = (size * raw_pnl) - (size * 2 * self.fee_rate)
                self.balance += net_pnl
                trade_out = {'symbol': symbol, 'side': side, 'type': 'TP', 'pnl': net_pnl, 'exit_time': current_time}

        if trade_out:
            trade_out['balance_actual'] = self.balance
            trade_out['entry_time'] = pos['entry_time']
            del self.active_positions[symbol]
            self._guardar_csv(trade_out)
            return trade_out

        return None

    def _guardar_csv(self, trade):
        df = pd.DataFrame([trade])
        header = not os.path.exists(self.csv_path)
        df.to_csv(self.csv_path, mode='a', header=header, index=False)
