# services/backtest_client.py
"""
BacktestClient — Drop-in replacement for openalgo.api

Mirrors the openalgo SDK interface exactly so that strategies written for
live trading work in backtest mode with zero code changes.

The engine swaps `api()` with this client. All order execution is simulated
on historical OHLCV bars. Look-ahead bias is prevented by only exposing
data up to the current bar via history().
"""

import pandas as pd


class BacktestClient:
    """
    SDK-compatible mock client for backtesting.

    All public methods match the openalgo Python SDK signatures.
    """

    def __init__(self, config):
        self.initial_capital = float(config["initial_capital"])
        self.capital = float(config["initial_capital"])
        self.slippage_pct = float(config.get("slippage_pct", 0.05))
        self.commission_per_order = float(config.get("commission_per_order", 20.0))
        self.commission_pct = float(config.get("commission_pct", 0.0))

        # Data store — populated by engine before run
        self.data = {}  # {symbol:exchange -> DataFrame}
        self.current_bar_index = {}  # {symbol:exchange -> int}
        self.current_timestamp = None

        # State
        self.positions = {}  # {symbol:exchange -> {qty, avg_price, product}}
        self.orders = []  # all orders placed
        self.trades = []  # completed round-trip trades
        self.open_entries = {}  # {symbol:exchange -> entry info}
        self.pending_orders = []  # LIMIT/SL/SL-M waiting
        self.equity_curve = []  # [{timestamp, equity, drawdown}]
        self.peak_equity = float(config["initial_capital"])
        self._order_counter = 0
        self._trade_counter = 0

    # ─── SDK-Compatible Methods ──────────────────────────────────────

    def history(self, symbol="", exchange="", interval="", start_date="",
                end_date="", source="db"):
        """
        Returns historical data UP TO current bar only.
        This prevents look-ahead bias — the single most critical requirement.
        """
        key = f"{symbol}:{exchange}"
        if key not in self.data:
            return pd.DataFrame()
        df = self.data[key]
        # CRITICAL: Default to -1 (no data visible) if bar index not set.
        # Using len(df)-1 would expose ALL future data — a look-ahead bias leak.
        current_idx = self.current_bar_index.get(key, -1)
        if current_idx < 0:
            return pd.DataFrame()
        return df.iloc[: current_idx + 1].copy()

    def quotes(self, symbol="", exchange=""):
        """Returns current bar's data as a quote snapshot."""
        bar = self._get_current_bar(symbol, exchange)
        if bar is None:
            return {"status": "error", "message": "No data available"}
        prev_close = self._get_prev_close(symbol, exchange)
        return {
            "status": "success",
            "data": {
                "ltp": float(bar["close"]),
                "open": float(bar["open"]),
                "high": float(bar["high"]),
                "low": float(bar["low"]),
                "close": float(bar["close"]),
                "volume": int(bar.get("volume", 0)),
                "bid": float(bar["close"]),
                "ask": float(bar["close"]),
                "prev_close": float(prev_close) if prev_close is not None else float(bar["open"]),
                "oi": int(bar.get("oi", 0)),
            },
        }

    def multiquotes(self, symbols=None):
        """Returns quotes for multiple symbols."""
        if symbols is None:
            symbols = []
        results = {}
        for sym in symbols:
            q = self.quotes(sym.get("symbol", ""), sym.get("exchange", ""))
            if q["status"] == "success":
                results[f"{sym['symbol']}:{sym['exchange']}"] = q["data"]
        return {"status": "success", "data": results}

    def placeorder(self, strategy="", symbol="", action="", exchange="",
                   price_type="MARKET", product="MIS", quantity=1,
                   price=0, trigger_price=0, **kwargs):
        """Simulate order execution."""
        bar = self._get_current_bar(symbol, exchange)
        if bar is None:
            return {"status": "error", "message": f"No data for {symbol}:{exchange}"}

        quantity = int(quantity)
        if quantity <= 0:
            return {"status": "error", "message": "Quantity must be positive"}

        self._order_counter += 1
        order_id = f"BT-{self._order_counter:06d}"

        if price_type == "MARKET":
            exec_price = self._apply_slippage(float(bar["close"]), action)
            self._execute_fill(
                symbol, exchange, action, quantity,
                exec_price, product, strategy, bar,
            )
            self.orders.append({
                "orderid": order_id, "symbol": symbol, "exchange": exchange,
                "action": action, "quantity": quantity, "price": exec_price,
                "price_type": "MARKET", "product": product, "strategy": strategy,
                "status": "complete", "timestamp": self.current_timestamp,
            })
            return {"orderid": order_id, "status": "success"}

        if price_type in ("LIMIT", "SL", "SL-M"):
            self.pending_orders.append({
                "order_id": order_id,
                "symbol": symbol,
                "exchange": exchange,
                "action": action,
                "quantity": quantity,
                "price_type": price_type,
                "price": float(price),
                "trigger_price": float(trigger_price),
                "product": product,
                "strategy": strategy,
                "placed_bar": self.current_bar_index.get(f"{symbol}:{exchange}", 0),
            })
            self.orders.append({
                "orderid": order_id, "symbol": symbol, "exchange": exchange,
                "action": action, "quantity": quantity, "price": float(price),
                "price_type": price_type, "product": product, "strategy": strategy,
                "status": "open", "timestamp": self.current_timestamp,
            })
            return {"orderid": order_id, "status": "success"}

        return {"status": "error", "message": f"Unknown price_type: {price_type}"}

    def placesmartorder(self, strategy="", symbol="", action="", exchange="",
                        price_type="MARKET", product="MIS", quantity=1,
                        position_size=0, **kwargs):
        """Position-aware order placement."""
        key = f"{symbol}:{exchange}"
        current_qty = self.positions.get(key, {}).get("qty", 0)
        target = int(position_size)

        if action == "BUY":
            needed = target - current_qty
        else:  # SELL
            needed = current_qty - target

        if needed > 0:
            actual_action = "BUY" if action == "BUY" else "SELL"
            return self.placeorder(
                strategy=strategy, symbol=symbol, action=actual_action,
                exchange=exchange, price_type=price_type, product=product,
                quantity=abs(needed), **kwargs,
            )
        elif needed < 0:
            actual_action = "SELL" if action == "BUY" else "BUY"
            return self.placeorder(
                strategy=strategy, symbol=symbol, action=actual_action,
                exchange=exchange, price_type=price_type, product=product,
                quantity=abs(needed), **kwargs,
            )

        return {"status": "success", "message": "No action needed"}

    def cancelorder(self, order_id="", **kwargs):
        """Cancel a pending order by ID."""
        before = len(self.pending_orders)
        self.pending_orders = [
            o for o in self.pending_orders if o["order_id"] != order_id
        ]
        # Update order status in orders list
        for o in self.orders:
            if o.get("orderid") == order_id and o.get("status") == "open":
                o["status"] = "cancelled"
        if len(self.pending_orders) < before:
            return {"status": "success"}
        return {"status": "error", "message": "Order not found"}

    def cancelallorder(self, strategy="", **kwargs):
        """Cancel all pending orders, optionally filtered by strategy."""
        if strategy:
            self.pending_orders = [
                o for o in self.pending_orders if o.get("strategy") != strategy
            ]
        else:
            self.pending_orders.clear()
        for o in self.orders:
            if o.get("status") == "open":
                if not strategy or o.get("strategy") == strategy:
                    o["status"] = "cancelled"
        return {"status": "success"}

    def closeposition(self, strategy="", **kwargs):
        """Close all open positions."""
        for key, pos in list(self.positions.items()):
            if pos["qty"] != 0:
                symbol, exchange = key.split(":")
                action = "SELL" if pos["qty"] > 0 else "BUY"
                self.placeorder(
                    strategy=strategy, symbol=symbol, action=action,
                    exchange=exchange, price_type="MARKET",
                    product=pos.get("product", "MIS"),
                    quantity=abs(pos["qty"]),
                )
        return {"status": "success"}

    def positionbook(self):
        """Return current open positions."""
        positions = []
        for key, pos in self.positions.items():
            if pos["qty"] != 0:
                symbol, exchange = key.split(":")
                bar = self._get_current_bar(symbol, exchange)
                ltp = float(bar["close"]) if bar is not None else pos["avg_price"]
                if pos["qty"] > 0:
                    pnl = (ltp - pos["avg_price"]) * pos["qty"]
                else:
                    pnl = (pos["avg_price"] - ltp) * abs(pos["qty"])
                positions.append({
                    "symbol": symbol, "exchange": exchange,
                    "product": pos.get("product", "MIS"),
                    "quantity": str(pos["qty"]),
                    "average_price": str(round(pos["avg_price"], 2)),
                    "ltp": str(round(ltp, 2)),
                    "pnl": str(round(pnl, 2)),
                })
        return {"status": "success", "data": positions}

    def orderbook(self):
        """Return all orders."""
        return {"status": "success", "data": self.orders}

    def tradebook(self):
        """Return all executed trades."""
        return {
            "status": "success",
            "data": [
                {
                    "symbol": t["symbol"],
                    "exchange": t["exchange"],
                    "action": t["action"],
                    "quantity": t["quantity"],
                    "price": t["entry_price"],
                    "strategy": t.get("strategy_tag", ""),
                }
                for t in self.trades
            ],
        }

    def funds(self):
        """Return fund balances."""
        unrealized = self._total_unrealized()
        realized = self.capital - self.initial_capital
        return {
            "status": "success",
            "data": {
                "availablecash": str(round(self.capital, 2)),
                "collateral": "0",
                "m2mrealized": str(round(realized, 2)),
                "m2munrealized": str(round(unrealized, 2)),
            },
        }

    def openposition(self, strategy="", symbol="", exchange="", product="MIS"):
        """Check if a position exists for a symbol."""
        key = f"{symbol}:{exchange}"
        pos = self.positions.get(key, {})
        qty = pos.get("qty", 0)
        return {"status": "success", "quantity": str(qty)}

    def holdings(self):
        """No holdings in backtest mode."""
        return {"status": "success", "data": []}

    def orderstatus(self, order_id="", strategy=""):
        """Get status of a specific order."""
        for o in self.orders:
            if o.get("orderid") == order_id:
                return {"status": "success", "data": o}
        return {"status": "error", "message": "Order not found"}

    def search(self, query="", exchange=""):
        """Stub — not applicable in backtest."""
        return {"status": "success", "data": []}

    def intervals(self):
        """Return supported intervals."""
        return {
            "status": "success",
            "data": {
                "minutes": ["1m", "3m", "5m", "10m", "15m", "30m"],
                "hours": ["1h"],
                "days": ["D"],
            },
        }

    # ─── Internal Methods ────────────────────────────────────────────

    def _get_current_bar(self, symbol, exchange):
        """Get the current bar for a symbol."""
        key = f"{symbol}:{exchange}"
        if key not in self.data:
            return None
        idx = self.current_bar_index.get(key, 0)
        df = self.data[key]
        if idx >= len(df):
            return None
        return df.iloc[idx]

    def _get_prev_close(self, symbol, exchange):
        """Get previous bar's close price."""
        key = f"{symbol}:{exchange}"
        idx = self.current_bar_index.get(key, 0)
        if idx <= 0:
            return None
        return float(self.data[key].iloc[idx - 1]["close"])

    def _apply_slippage(self, price, action):
        """Apply slippage percentage to execution price."""
        pct = self.slippage_pct / 100.0
        if action == "BUY":
            return round(price * (1 + pct), 2)
        return round(price * (1 - pct), 2)

    def _calculate_commission(self, trade_value):
        """Calculate commission for a trade."""
        if self.commission_pct > 0:
            return round(trade_value * self.commission_pct / 100.0, 2)
        return self.commission_per_order

    def _execute_fill(self, symbol, exchange, action, qty, exec_price,
                      product, strategy, bar):
        """
        Execute a fill: update positions, deduct commission, record trade.
        Handles: new position, add to position, partial close, full close, reversal.
        """
        key = f"{symbol}:{exchange}"
        trade_value = qty * exec_price
        slippage_cost = abs(exec_price - float(bar["close"])) * qty

        # Get or create position
        pos = self.positions.get(key, {"qty": 0, "avg_price": 0.0, "product": product})
        old_qty = pos["qty"]

        if action == "BUY":
            new_qty = old_qty + qty
        else:
            new_qty = old_qty - qty

        # Case 1: New position (was flat)
        if old_qty == 0:
            commission = self._calculate_commission(trade_value)
            self.capital -= commission
            pos["avg_price"] = exec_price
            pos["qty"] = new_qty
            pos["product"] = product
            self.open_entries[key] = {
                "entry_price": exec_price,
                "entry_time": self.current_timestamp,
                "entry_bar": self.current_bar_index.get(key, 0),
                "qty": abs(new_qty),
                "action": action,
                "strategy": strategy,
            }

        # Case 2: Adding to existing position (same direction)
        elif (old_qty > 0 and action == "BUY") or (old_qty < 0 and action == "SELL"):
            commission = self._calculate_commission(trade_value)
            self.capital -= commission
            total_cost = abs(old_qty) * pos["avg_price"] + qty * exec_price
            pos["qty"] = new_qty
            if abs(new_qty) > 0:
                pos["avg_price"] = round(total_cost / abs(new_qty), 2)

        # Case 3: Reducing, closing, or reversing
        else:
            close_qty = min(abs(old_qty), qty)
            excess_qty = qty - close_qty  # >0 only for reversals

            # Commission for the CLOSE portion only (proportional to close_qty)
            close_value = close_qty * exec_price
            close_commission = self._calculate_commission(close_value)
            close_slippage = abs(exec_price - float(bar["close"])) * close_qty

            # Deduct close commission
            self.capital -= close_commission

            # P&L for closed portion
            if old_qty > 0:
                pnl = (exec_price - pos["avg_price"]) * close_qty
            else:
                pnl = (pos["avg_price"] - exec_price) * close_qty

            self.capital += pnl

            # Record completed trade
            entry = self.open_entries.get(key, {})
            self._trade_counter += 1
            entry_bar = entry.get("entry_bar", 0)
            current_bar = self.current_bar_index.get(key, 0)

            self.trades.append({
                "trade_num": self._trade_counter,
                "symbol": symbol,
                "exchange": exchange,
                "action": "LONG" if old_qty > 0 else "SHORT",
                "quantity": close_qty,
                "entry_price": round(pos["avg_price"], 2),
                "exit_price": round(exec_price, 2),
                "entry_time": entry.get("entry_time"),
                "exit_time": self.current_timestamp,
                "pnl": round(pnl, 2),
                "pnl_pct": round(
                    pnl / (pos["avg_price"] * close_qty) * 100, 4
                ) if pos["avg_price"] > 0 and close_qty > 0 else 0.0,
                "commission": round(close_commission, 2),
                "slippage_cost": round(close_slippage, 2),
                "net_pnl": round(pnl - close_commission, 2),
                "bars_held": max(current_bar - entry_bar, 0),
                "product": product,
                "strategy_tag": strategy,
            })

            pos["qty"] = new_qty

            if new_qty == 0:
                # Fully closed
                pos["avg_price"] = 0.0
                self.open_entries.pop(key, None)
            elif (old_qty > 0 and new_qty < 0) or (old_qty < 0 and new_qty > 0):
                # Reversed — open new entry for excess, charge separate commission
                reversal_value = excess_qty * exec_price
                reversal_commission = self._calculate_commission(reversal_value)
                self.capital -= reversal_commission

                pos["avg_price"] = exec_price
                self.open_entries[key] = {
                    "entry_price": exec_price,
                    "entry_time": self.current_timestamp,
                    "entry_bar": self.current_bar_index.get(key, 0),
                    "qty": abs(new_qty),
                    "action": action,
                    "strategy": strategy,
                }
            # else: partial close — keep existing avg_price

        self.positions[key] = pos

    def process_pending_orders(self):
        """
        Check all pending SL/LIMIT orders against current bar's OHLC.
        Called by the engine at the start of each bar.
        """
        remaining = []
        for order in self.pending_orders:
            key = f"{order['symbol']}:{order['exchange']}"
            bar = self._get_current_bar(order["symbol"], order["exchange"])
            if bar is None:
                remaining.append(order)
                continue

            triggered = False
            exec_price = 0.0
            bar_high = float(bar["high"])
            bar_low = float(bar["low"])
            bar_close = float(bar["close"])

            if order["price_type"] == "LIMIT":
                if order["action"] == "BUY" and bar_low <= order["price"]:
                    exec_price = order["price"]
                    triggered = True
                elif order["action"] == "SELL" and bar_high >= order["price"]:
                    exec_price = order["price"]
                    triggered = True

            elif order["price_type"] == "SL":
                if order["action"] == "BUY" and bar_high >= order["trigger_price"]:
                    exec_price = min(order["price"], bar_high)
                    triggered = True
                elif order["action"] == "SELL" and bar_low <= order["trigger_price"]:
                    exec_price = max(order["price"], bar_low)
                    triggered = True

            elif order["price_type"] == "SL-M":
                if order["action"] == "BUY" and bar_high >= order["trigger_price"]:
                    exec_price = self._apply_slippage(bar_close, "BUY")
                    triggered = True
                elif order["action"] == "SELL" and bar_low <= order["trigger_price"]:
                    exec_price = self._apply_slippage(bar_close, "SELL")
                    triggered = True

            if triggered:
                self._execute_fill(
                    order["symbol"], order["exchange"], order["action"],
                    order["quantity"], exec_price, order["product"],
                    order["strategy"], bar,
                )
                # Update order status
                for o in self.orders:
                    if o.get("orderid") == order["order_id"] and o.get("status") == "open":
                        o["status"] = "complete"
                        o["price"] = exec_price
            else:
                remaining.append(order)

        self.pending_orders = remaining

    def record_equity(self, timestamp):
        """Snapshot equity for curve generation."""
        unrealized = self._total_unrealized()
        equity = self.capital + unrealized
        self.peak_equity = max(self.peak_equity, equity)
        drawdown = 0.0
        if self.peak_equity > 0:
            drawdown = (self.peak_equity - equity) / self.peak_equity
        self.equity_curve.append({
            "timestamp": int(timestamp) if not isinstance(timestamp, int) else timestamp,
            "equity": round(equity, 2),
            "drawdown": round(drawdown, 6),
        })

    def close_all_positions_at_end(self):
        """Force-close all open positions at last bar price."""
        for key, pos in list(self.positions.items()):
            if pos["qty"] != 0:
                symbol, exchange = key.split(":")
                bar = self._get_current_bar(symbol, exchange)
                if bar is not None:
                    action = "SELL" if pos["qty"] > 0 else "BUY"
                    exec_price = self._apply_slippage(float(bar["close"]), action)
                    self._execute_fill(
                        symbol, exchange, action, abs(pos["qty"]),
                        exec_price, pos.get("product", "MIS"),
                        "_backtest_close", bar,
                    )

    def advance_to(self, timestamp):
        """Advance all symbol cursors to the given timestamp."""
        self.current_timestamp = timestamp
        for key, df in self.data.items():
            if "timestamp" in df.columns:
                ts_values = df["timestamp"].values
            else:
                ts_values = df.index.values
            # Find the latest bar at or before this timestamp
            mask = ts_values <= timestamp
            if mask.any():
                self.current_bar_index[key] = int(mask.sum()) - 1
            else:
                self.current_bar_index[key] = -1

    def _total_unrealized(self):
        """Calculate total unrealized P&L across all positions."""
        total = 0.0
        for key, pos in self.positions.items():
            if pos["qty"] != 0:
                symbol, exchange = key.split(":")
                bar = self._get_current_bar(symbol, exchange)
                if bar is not None:
                    ltp = float(bar["close"])
                    if pos["qty"] > 0:
                        total += (ltp - pos["avg_price"]) * pos["qty"]
                    else:
                        total += (pos["avg_price"] - ltp) * abs(pos["qty"])
        return total
