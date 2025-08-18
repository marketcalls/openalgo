import os
import pandas as pd
from datetime import datetime
import uuid

class TradeJournal:
    """
    Manages the trade journal for a strategy, writing all trades to a mode-specific CSV file.
    """

    def __init__(self, strategy_name: str, trades_path: str, mode: str):
        """
        Initializes the TradeJournal.

        Args:
            strategy_name (str): The name of the strategy.
            trades_path (str): The directory where trade CSV files should be stored.
            mode (str): The trading mode ('LIVE' or 'PAPER').
        """
        self.strategy_name = strategy_name
        self.trades_path = trades_path
        self.mode = mode
        os.makedirs(self.trades_path, exist_ok=True)
        self.csv_path = os.path.join(self.trades_path, f"{self.strategy_name}_{self.mode.lower()}_trades.csv")
        self.columns = [
            'trade_id', 'order_id', 'timestamp_ist', 'action', 'symbol',
            'quantity', 'price', 'leg_type', 'is_adjustment', 'mode'
        ]

    def generate_trade_id(self) -> str:
        """Generates a new, unique trade ID."""
        return str(uuid.uuid4())

    def record_trade(self, trade_id: str, order_id: str, action: str, symbol: str,
                     quantity: int, price: float, leg_type: str,
                     is_adjustment: bool, mode: str):
        """
        Records a single trade event to the CSV journal.

        Args:
            trade_id (str): The unique ID for the entire trade lifecycle.
            order_id (str): The order ID from the broker or paper trading.
            action (str): 'BUY' or 'SELL'.
            symbol (str): The trading symbol.
            quantity (int): The number of shares.
            price (float): The execution price.
            leg_type (str): e.g., 'CALL_SHORT', 'PUT_SHORT'.
            is_adjustment (bool): True if this trade is part of an adjustment.
            mode (str): 'LIVE' or 'PAPER'.
        """
        trade_data = {
            'trade_id': trade_id,
            'order_id': order_id,
            'timestamp_ist': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'action': action,
            'symbol': symbol,
            'quantity': quantity,
            'price': price,
            'leg_type': leg_type,
            'is_adjustment': is_adjustment,
            'mode': mode
        }

        log_df = pd.DataFrame([trade_data], columns=self.columns)

        # Check if file exists to determine if we need to write the header
        file_exists = os.path.isfile(self.csv_path)
        log_df.to_csv(self.csv_path, mode='a', header=not file_exists, index=False)