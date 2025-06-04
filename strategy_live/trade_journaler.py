import csv
import os
import json
from datetime import datetime
import pytz

IST = pytz.timezone('Asia/Kolkata')
# Journal CSV will be in the same directory as this script (strategies folder)
STRATEGIES_DIR = os.path.dirname(os.path.abspath(__file__))
JOURNAL_CSV_PATH = os.path.join(STRATEGIES_DIR, "trading_journal.csv")

JOURNAL_COLUMNS = [
    "TradeID", "OpenTimestamp", "CloseTimestamp", "Symbol", "Exchange",
    "PositionType", "EntryPrice", "ExitPrice", "Quantity",
    "Commission", "SwapFees", "GrossP&L", "NetP&L",
    "AlgorithmID", "Parameters", "SignalName_Exit", "ProductType"
]

def _log_journaler_message(message):
    print(f"{datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S %Z%z')} - TradeJournaler - {message}")

def initialize_journal():
    if not os.path.exists(JOURNAL_CSV_PATH):
        with open(JOURNAL_CSV_PATH, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=JOURNAL_COLUMNS)
            writer.writeheader()
        _log_journaler_message(f"Journal file created: {JOURNAL_CSV_PATH}")

def generate_trade_id(symbol, entry_timestamp_obj):
    ts_aware = entry_timestamp_obj.astimezone(IST) if entry_timestamp_obj.tzinfo else IST.localize(entry_timestamp_obj)
    return f"{ts_aware.strftime('%Y%m%d%H%M%S')}_{symbol.replace('/', '')}"

def _parse_api_timestamp(timestamp_str):
    if not timestamp_str: return None
    try:
        dt_obj_naive = datetime.strptime(timestamp_str, '%d-%b-%Y %H:%M:%S')
        return IST.localize(dt_obj_naive)
    except ValueError as e:
        _log_journaler_message(f"Error parsing API timestamp '{timestamp_str}': {e}")
        return None

def fetch_order_execution_details(openalgo_client, order_id, strategy_name_for_api_call):
    if not openalgo_client or not order_id: return None, None, None
    try:
        response = openalgo_client.orderstatus(order_id=order_id, strategy=strategy_name_for_api_call)
        if response and response.get('status') == 'success' and 'data' in response:
            order_data = response['data']
            if order_data.get('order_status', '').lower() == 'complete':
                price = float(order_data.get('price', 0.0))
                timestamp_obj = _parse_api_timestamp(order_data.get('timestamp'))
                quantity_filled = float(order_data.get('quantity', 0.0))
                if price > 0 and timestamp_obj and quantity_filled > 0:
                    return price, timestamp_obj, quantity_filled
                _log_journaler_message(f"Incomplete execution data from API for OrderID {order_id}: Price={price}, TS='{order_data.get('timestamp')}', Qty={quantity_filled}")
            else:
                _log_journaler_message(f"OrderID {order_id} not 'complete'. Status: {order_data.get('order_status')}")
        else:
            _log_journaler_message(f"Failed to get valid order status for OrderID {order_id}. Response: {response}")
        return None, None, None
    except Exception as e:
        _log_journaler_message(f"Exception fetching order details for {order_id}: {e}\n{traceback.format_exc()}")
        return None, None, None

def process_and_write_completed_trades_to_csv(openalgo_client, raw_completed_trades):
    if not raw_completed_trades:
        _log_journaler_message("No trades to journal.")
        return 0

    initialize_journal()
    journaled_count = 0

    with open(JOURNAL_CSV_PATH, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=JOURNAL_COLUMNS)
        for raw_trade in raw_completed_trades:
            try:
                strategy_name = raw_trade.get('strategy_name', 'UnknownStrategy')
                entry_exec_price, entry_exec_ts, entry_exec_qty = fetch_order_execution_details(
                    openalgo_client, raw_trade['entry_order_id'], strategy_name)
                exit_exec_price, exit_exec_ts, exit_exec_qty = fetch_order_execution_details(
                    openalgo_client, raw_trade['exit_order_id'], strategy_name)

                if not all([entry_exec_price, entry_exec_ts, entry_exec_qty, exit_exec_price, exit_exec_ts, exit_exec_qty]):
                    _log_journaler_message(f"Skipping {raw_trade['symbol']}: missing execution details. EntryOID: {raw_trade['entry_order_id']}, ExitOID: {raw_trade['exit_order_id']}")
                    continue

                quantity = entry_exec_qty
                if entry_exec_qty != exit_exec_qty:
                    _log_journaler_message(f"WARNING: Qty mismatch for {raw_trade['symbol']}. Entry: {entry_exec_qty}, Exit: {exit_exec_qty}. Using entry qty.")

                gross_pnl = (exit_exec_price - entry_exec_price) * quantity if raw_trade['position_type'].upper() == "LONG" else \
                            (entry_exec_price - exit_exec_price) * quantity # For SHORT
                
                commission, swap_fees = 0.0, 0.0 # Placeholders
                net_pnl = gross_pnl - commission - swap_fees
                trade_id = generate_trade_id(raw_trade['symbol'], entry_exec_ts)

                writer.writerow({
                    "TradeID": trade_id,
                    "OpenTimestamp": entry_exec_ts.strftime('%Y-%m-%d %H:%M:%S'),
                    "CloseTimestamp": exit_exec_ts.strftime('%Y-%m-%d %H:%M:%S'),
                    "Symbol": raw_trade['symbol'], "Exchange": raw_trade['exchange'],
                    "PositionType": raw_trade['position_type'],
                    "EntryPrice": round(entry_exec_price, 2), "ExitPrice": round(exit_exec_price, 2),
                    "Quantity": quantity, "Commission": round(commission, 2), "SwapFees": round(swap_fees, 2),
                    "GrossP&L": round(gross_pnl, 2), "NetP&L": round(net_pnl, 2),
                    "AlgorithmID": raw_trade['strategy_name'],
                    "Parameters": json.dumps(raw_trade.get('strategy_parameters', {})),
                    "SignalName_Exit": raw_trade.get('exit_reason', 'N/A'),
                    "ProductType": raw_trade['product_type']
                })
                journaled_count += 1
                _log_journaler_message(f"Successfully journaled trade: {trade_id}")
            except Exception as e:
                _log_journaler_message(f"Error processing raw trade for {raw_trade.get('symbol')}: {e}\n{traceback.format_exc()}")
                continue
    
    _log_journaler_message(f"Journaling finished. Processed {len(raw_completed_trades)} trades, journaled {journaled_count}.")
    return journaled_count

if __name__ == '__main__':
    import traceback # Added for standalone test if needed
    _log_journaler_message("Trade Journaler module. Not for direct full operation.")
    _log_journaler_message(f"Journal will be saved to: {JOURNAL_CSV_PATH}")
    initialize_journal()