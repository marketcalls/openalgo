"""
SPX 0DTE order-flow/profile spread strategy.

Signals are built from SPY minute bars because SPY usually has better live
volume for local order-flow approximations. Execution is in SPXW 0DTE index
options using bull call spreads for long signals and bear put spreads for
short signals.

This strategy uses bar-level order-flow proxies. True footprint stacked
imbalance requires bid/ask-at-price or tick/market-depth data from the live
feed. The proxy here looks for consecutive aggressive delta bars, expansion,
absorption, and value-area level interaction.
"""

from datetime import timedelta
from math import floor

from AlgorithmImports import (
    BrokerageName,
    OptionRight,
    OptionStrategies,
    OrderStatus,
    QCAlgorithm,
    Resolution,
    Slice,
    TradeBar,
)


class PriceProfile:
    def __init__(self, bucket_size: float = 0.25):
        self.bucket_size = bucket_size
        self.volume_by_price = {}
        self.tpo_by_price = {}

    def reset(self):
        self.volume_by_price.clear()
        self.tpo_by_price.clear()

    def update(self, bar: TradeBar):
        low_bucket = self._snap(bar.low)
        high_bucket = self._snap(bar.high)
        bucket_count = max(1, round((high_bucket - low_bucket) / self.bucket_size) + 1)
        volume_each = float(bar.volume) / bucket_count if bucket_count else 0.0

        price = low_bucket
        while price <= high_bucket + 1e-9:
            key = round(price, 2)
            self.volume_by_price[key] = self.volume_by_price.get(key, 0.0) + volume_each
            self.tpo_by_price[key] = self.tpo_by_price.get(key, 0) + 1
            price = round(price + self.bucket_size, 2)

    def merge(self, other: "PriceProfile"):
        for price, volume in other.volume_by_price.items():
            self.volume_by_price[price] = self.volume_by_price.get(price, 0.0) + volume
        for price, count in other.tpo_by_price.items():
            self.tpo_by_price[price] = self.tpo_by_price.get(price, 0) + count

    def levels(self):
        volume_levels = self._levels_from_distribution(self.volume_by_price)
        tpo_levels = self._levels_from_distribution(self.tpo_by_price)
        if volume_levels is None:
            return None

        return {
            "vah": volume_levels["vah"],
            "poc": volume_levels["poc"],
            "val": volume_levels["val"],
            "volume": volume_levels["total"],
            "tpo_vah": tpo_levels["vah"] if tpo_levels else volume_levels["vah"],
            "tpo_poc": tpo_levels["poc"] if tpo_levels else volume_levels["poc"],
            "tpo_val": tpo_levels["val"] if tpo_levels else volume_levels["val"],
        }

    def _levels_from_distribution(self, distribution):
        if len(distribution) < 3:
            return None

        sorted_levels = sorted(distribution.items())
        total = sum(value for _, value in sorted_levels)
        if total <= 0:
            return None

        poc = max(distribution, key=distribution.__getitem__)
        poc_index = next(i for i, (price, _) in enumerate(sorted_levels) if price == poc)

        target = total * 0.70
        low_index = high_index = poc_index
        captured = distribution[poc]

        while captured < target:
            can_expand_low = low_index > 0
            can_expand_high = high_index < len(sorted_levels) - 1
            if not can_expand_low and not can_expand_high:
                break

            low_value = sorted_levels[low_index - 1][1] if can_expand_low else -1
            high_value = sorted_levels[high_index + 1][1] if can_expand_high else -1
            if high_value >= low_value:
                high_index += 1
                captured += high_value
            else:
                low_index -= 1
                captured += low_value

        return {
            "vah": sorted_levels[high_index][0],
            "poc": poc,
            "val": sorted_levels[low_index][0],
            "total": total,
        }

    def _snap(self, price: float) -> float:
        return floor(float(price) / self.bucket_size) * self.bucket_size


class OrderFlowProxy:
    def __init__(self, volume_window: int = 20, stack_window: int = 4):
        self.volume_window = volume_window
        self.stack_window = stack_window
        self.cumulative_delta = 0.0
        self.recent_volumes = []
        self.recent_deltas = []
        self.last_delta = 0.0

    def reset(self):
        self.cumulative_delta = 0.0
        self.recent_volumes.clear()
        self.recent_deltas.clear()
        self.last_delta = 0.0

    def update(self, bar: TradeBar):
        self.last_delta = self._bar_delta(bar)
        self.cumulative_delta += self.last_delta
        self.recent_deltas.append(self.last_delta)
        self.recent_volumes.append(float(bar.volume))
        if len(self.recent_deltas) > self.stack_window:
            self.recent_deltas.pop(0)
        if len(self.recent_volumes) > self.volume_window:
            self.recent_volumes.pop(0)

    @property
    def average_volume(self):
        if len(self.recent_volumes) < 5:
            return None
        return sum(self.recent_volumes) / len(self.recent_volumes)

    def stacked_imbalance(self, direction: str, min_delta_per_bar: float):
        if len(self.recent_deltas) < self.stack_window:
            return False
        if direction == "long":
            return all(delta >= min_delta_per_bar for delta in self.recent_deltas)
        return all(delta <= -min_delta_per_bar for delta in self.recent_deltas)

    @staticmethod
    def _bar_delta(bar: TradeBar):
        bar_range = float(bar.high - bar.low)
        if bar_range <= 1e-9:
            return 0.0
        close_location = (2.0 * float(bar.close - bar.low) / bar_range) - 1.0
        return close_location * float(bar.volume)


class Spx0DteOrderFlowProfileSpreadStrategy(QCAlgorithm):
    PROFILE_BUCKET = 0.25
    LAST_DAYS = 5
    LEVEL_PROXIMITY_PCT = 0.0015
    MIN_SESSION_BARS = 30
    MAX_SPREADS_PER_DAY = 2
    MAX_SPREAD_QUANTITY = 1
    SPREAD_WIDTH = 20
    COOLDOWN_BARS = 20
    STOP_UNDERLYING_PCT = 0.0035
    TARGET_UNDERLYING_PCT = 0.0060
    EOD_EXIT_MINUTES = 15

    ABSORB_VOL_MULT = 1.8
    ABSORB_BODY_RATIO = 0.30
    EXPAND_VOL_MULT = 1.4
    EXPAND_BODY_RATIO = 0.60
    STACK_MIN_VOL_RATIO = 0.55

    def initialize(self):
        self.set_start_date(2024, 1, 2)
        self.set_cash(50_000)
        self.set_brokerage_model(BrokerageName.INTERACTIVE_BROKERS_BROKERAGE)

        self.profile_bucket = self._float_parameter("profile-bucket", self.PROFILE_BUCKET)
        self.spread_width = self._float_parameter("spread-width", self.SPREAD_WIDTH)
        self.max_spread_quantity = self._int_parameter("max-spread-quantity", self.MAX_SPREAD_QUANTITY)
        self.place_test_order = self._bool_parameter("spx-0dte-place-test-order", False)
        self.test_order_submitted_date = None

        self.spy = self.add_equity("SPY", Resolution.MINUTE).symbol
        self.spx = self.add_index("SPX", Resolution.MINUTE).symbol

        option = self.add_index_option(self.spx, "SPXW", Resolution.MINUTE)
        option.set_filter(lambda universe: universe.include_weeklys().strikes(-30, 30).expiration(0, 0))
        self.spxw = option.symbol

        self.session_profile = PriceProfile(self.profile_bucket)
        self.five_day_profile = PriceProfile(self.profile_bucket)
        self.order_flow = OrderFlowProxy(volume_window=20, stack_window=4)

        self.session_bars = 0
        self.cooldown = 0
        self.trades_today = 0
        self.active_tickets = []
        self.active_symbols = set()
        self.active_direction = None
        self.active_entry_spy = 0.0
        self.current_slice = None
        self.last_chain = None
        self.pending_test_order = None

        self.schedule.on(
            self.date_rules.every_day("SPY"),
            self.time_rules.after_market_open("SPY", 1),
            self._on_session_start,
        )
        self.schedule.on(
            self.date_rules.every_day("SPY"),
            self.time_rules.before_market_close("SPY", self.EOD_EXIT_MINUTES),
            self._exit_all_spreads,
        )

        self.set_warm_up(60, Resolution.MINUTE)
        self._rebuild_five_day_profile()

    def _on_session_start(self):
        self.session_profile.reset()
        self.order_flow.reset()
        self.session_bars = 0
        self.cooldown = 0
        self.trades_today = 0
        self.active_tickets = []
        self.active_symbols = set()
        self.active_direction = None
        self.active_entry_spy = 0.0
        self._rebuild_five_day_profile()
        self.debug(f"{self.time} session reset; rebuilt {self.LAST_DAYS}-day profile")

    def on_data(self, data: Slice):
        self.current_slice = data
        if self.is_warming_up or self.spy not in data.bars:
            return

        chain = data.option_chains.get(self.spxw)
        if chain:
            self.last_chain = chain

        bar = data.bars[self.spy]
        self.session_profile.update(bar)
        self.order_flow.update(bar)
        self.session_bars += 1

        if self.cooldown > 0:
            self.cooldown -= 1

        if self.active_symbols:
            self._manage_active_spread(bar)
            return

        if self.pending_test_order is not None:
            self._try_submit_pending_test_order()
            return

        if self.place_test_order and self._needs_test_order():
            self.test_order_submitted_date = self.time.date()
            self._enter_spread("long", "placement test order", test_mode=True)
            return

        if self.session_bars < self.MIN_SESSION_BARS:
            return
        if self.cooldown > 0 or self.trades_today >= self.MAX_SPREADS_PER_DAY:
            return

        signal = self._detect_signal(bar)
        if signal is None:
            return

        direction, reason = signal
        self._enter_spread(direction, reason)

    def _detect_signal(self, bar: TradeBar):
        current_levels = self.session_profile.levels()
        five_day_levels = self.five_day_profile.levels()
        if current_levels is None:
            return None

        avg_volume = self.order_flow.average_volume
        if avg_volume is None or avg_volume <= 0:
            return None

        price = float(bar.close)
        proximity = price * self.LEVEL_PROXIMITY_PCT
        levels = self._combine_levels(current_levels, five_day_levels)
        nearest_name, nearest_level, distance = self._nearest_level(price, levels)
        if nearest_level is None or distance > proximity:
            return None

        bar_range = float(bar.high - bar.low)
        if bar_range <= 1e-9:
            return None

        body_ratio = abs(float(bar.close - bar.open)) / bar_range
        volume_ratio = float(bar.volume) / avg_volume
        delta_threshold = avg_volume * self.STACK_MIN_VOL_RATIO
        oi_bias = self._open_interest_bias(price)

        bullish_context = nearest_name.endswith("val") or nearest_name.endswith("poc")
        bearish_context = nearest_name.endswith("vah") or nearest_name.endswith("poc")

        if volume_ratio >= self.EXPAND_VOL_MULT and body_ratio >= self.EXPAND_BODY_RATIO:
            if bar.close > bar.open and bullish_context and oi_bias >= 0:
                return "long", f"expansion above {nearest_name}"
            if bar.close < bar.open and bearish_context and oi_bias <= 0:
                return "short", f"expansion below {nearest_name}"

        if volume_ratio >= self.ABSORB_VOL_MULT and body_ratio <= self.ABSORB_BODY_RATIO:
            if nearest_name.endswith("val") and self.order_flow.last_delta > 0 and oi_bias >= 0:
                return "long", f"seller absorption at {nearest_name}"
            if nearest_name.endswith("vah") and self.order_flow.last_delta < 0 and oi_bias <= 0:
                return "short", f"buyer absorption at {nearest_name}"

        if self.order_flow.stacked_imbalance("long", delta_threshold) and bullish_context and oi_bias >= 0:
            return "long", f"stacked buy imbalance at {nearest_name}"
        if self.order_flow.stacked_imbalance("short", delta_threshold) and bearish_context and oi_bias <= 0:
            return "short", f"stacked sell imbalance at {nearest_name}"

        return None

    def _enter_spread(self, direction: str, reason: str, test_mode: bool = False):
        today = self.time.date()
        underlying_price = self._spx_price()
        if underlying_price <= 0 and not test_mode:
            return

        right = OptionRight.CALL if direction == "long" else OptionRight.PUT
        contracts = []
        if self.last_chain is not None:
            contracts = [
                contract
                for contract in self.last_chain
                if contract.expiry.date() == today
                and contract.right == right
                and (test_mode or (contract.bid_price > 0 and contract.ask_price > 0))
            ]

        if not contracts and test_mode:
            symbols = self._resolve_test_mode_symbols(right, today)
            if not symbols:
                self.debug(f"{self.time} test order: no 0DTE {right} contracts from chain provider")
                return
            if underlying_price <= 0:
                strikes = sorted(float(symbol.id.strike_price) for symbol in symbols)
                underlying_price = strikes[len(strikes) // 2]
            return self._submit_test_spread(direction, right, symbols, underlying_price, reason)

        if not contracts:
            self.debug(f"{self.time} no 0DTE {right} contracts available")
            return

        strikes = sorted({float(contract.strike) for contract in contracts})
        long_strike = self._nearest_strike(strikes, underlying_price)
        if long_strike is None:
            return
        expiry = min(contract.expiry for contract in contracts if float(contract.strike) == float(long_strike))

        if direction == "long":
            short_strike = self._nearest_strike([strike for strike in strikes if strike > long_strike], long_strike + self.spread_width)
            if short_strike is None:
                return
            strategy = OptionStrategies.bull_call_spread(self.spxw, long_strike, short_strike, expiry)
        else:
            short_strike = self._nearest_strike([strike for strike in strikes if strike < long_strike], long_strike - self.spread_width)
            if short_strike is None:
                return
            strategy = OptionStrategies.bear_put_spread(self.spxw, long_strike, short_strike, expiry)

        tickets = self.buy(strategy, self.max_spread_quantity)
        self.active_tickets = list(tickets)
        self.active_symbols = {ticket.symbol for ticket in self.active_tickets}
        self.active_direction = direction
        self.active_entry_spy = float(self.securities[self.spy].price)
        self.trades_today += 1
        self.cooldown = self.COOLDOWN_BARS

        self.debug(
            f"{self.time} {direction.upper()} SPXW 0DTE spread "
            f"{long_strike}/{short_strike} qty={self.max_spread_quantity} reason={reason}"
        )

    def _manage_active_spread(self, bar: TradeBar):
        if not any(self.portfolio[symbol].invested for symbol in self.active_symbols if self.portfolio.contains_key(symbol)):
            self.active_symbols = set()
            self.active_direction = None
            self.active_entry_spy = 0.0
            return

        if self.active_entry_spy <= 0:
            return

        move = (float(bar.close) - self.active_entry_spy) / self.active_entry_spy
        if self.active_direction == "short":
            move = -move

        if move <= -self.STOP_UNDERLYING_PCT:
            self._exit_all_spreads("underlying stop")
        elif move >= self.TARGET_UNDERLYING_PCT:
            self._exit_all_spreads("underlying target")

    def _exit_all_spreads(self, tag: str = "scheduled exit"):
        for symbol in list(self.active_symbols):
            if self.portfolio.contains_key(symbol) and self.portfolio[symbol].invested:
                self.liquidate(symbol, tag=tag)
        self.active_symbols = set()
        self.active_direction = None
        self.active_entry_spy = 0.0

    def _combine_levels(self, current_levels, five_day_levels):
        levels = {
            "session_vah": current_levels["vah"],
            "session_poc": current_levels["poc"],
            "session_val": current_levels["val"],
            "session_tpo_vah": current_levels["tpo_vah"],
            "session_tpo_poc": current_levels["tpo_poc"],
            "session_tpo_val": current_levels["tpo_val"],
        }
        if five_day_levels:
            levels.update(
                {
                    "five_day_vah": five_day_levels["vah"],
                    "five_day_poc": five_day_levels["poc"],
                    "five_day_val": five_day_levels["val"],
                    "five_day_tpo_vah": five_day_levels["tpo_vah"],
                    "five_day_tpo_poc": five_day_levels["tpo_poc"],
                    "five_day_tpo_val": five_day_levels["tpo_val"],
                }
            )
        return levels

    def _nearest_level(self, price, levels):
        best_name = None
        best_level = None
        best_distance = float("inf")
        for name, level in levels.items():
            distance = abs(price - float(level))
            if distance < best_distance:
                best_name = name
                best_level = float(level)
                best_distance = distance
        return best_name, best_level, best_distance

    def _open_interest_bias(self, spy_price: float):
        if self.last_chain is None:
            return 0

        spx_price = self._spx_price()
        if spx_price <= 0 or spy_price <= 0:
            return 0
        ratio = spx_price / spy_price

        today = self.time.date()
        calls = {}
        puts = {}
        for contract in self.last_chain:
            if contract.expiry.date() != today:
                continue
            open_interest = float(getattr(contract, "open_interest", 0) or 0)
            if open_interest <= 0:
                continue
            strike = float(contract.strike)
            if contract.right == OptionRight.CALL:
                calls[strike] = calls.get(strike, 0.0) + open_interest
            elif contract.right == OptionRight.PUT:
                puts[strike] = puts.get(strike, 0.0) + open_interest

        call_wall = max(calls, key=calls.get) if calls else None
        put_wall = max(puts, key=puts.get) if puts else None
        if call_wall is None and put_wall is None:
            return 0

        spy_call_wall = call_wall / ratio if call_wall else None
        spy_put_wall = put_wall / ratio if put_wall else None
        proximity = spy_price * self.LEVEL_PROXIMITY_PCT * 2.0

        if spy_call_wall is not None and abs(spy_price - spy_call_wall) <= proximity:
            return -1
        if spy_put_wall is not None and abs(spy_price - spy_put_wall) <= proximity:
            return 1
        return 0

    def _rebuild_five_day_profile(self):
        self.five_day_profile.reset()
        try:
            history = self.history[TradeBar](self.spy, timedelta(days=self.LAST_DAYS + 3), Resolution.MINUTE)
            cutoff = self.time.date() - timedelta(days=self.LAST_DAYS + 3)
            for bar in history:
                if bar.end_time.date() >= cutoff and bar.end_time.date() < self.time.date():
                    self.five_day_profile.update(bar)
        except Exception as exc:
            self.debug(f"{self.time} could not rebuild five-day profile: {exc}")

    def _spx_price(self):
        if self.securities.contains_key(self.spx) and self.securities[self.spx].price > 0:
            return float(self.securities[self.spx].price)
        if self.last_chain is not None and self.last_chain.underlying is not None:
            return float(self.last_chain.underlying.price)
        return 0.0

    @staticmethod
    def _nearest_strike(strikes, target):
        if not strikes:
            return None
        return min(strikes, key=lambda strike: abs(float(strike) - float(target)))

    def _float_parameter(self, name: str, default: float):
        value = self.get_parameter(name)
        return float(value) if value else float(default)

    def _int_parameter(self, name: str, default: int):
        value = self.get_parameter(name)
        return int(value) if value else int(default)

    def _bool_parameter(self, name: str, default: bool) -> bool:
        value = self.get_parameter(name)
        if value is None or value == "":
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}

    def _needs_test_order(self) -> bool:
        return self.test_order_submitted_date != self.time.date()

    def _resolve_test_mode_symbols(self, right, today):
        try:
            all_symbols = list(self.option_chain_provider.get_option_contract_list(self.spxw, self.time))
        except Exception as exc:
            self.debug(f"{self.time} option_chain_provider error: {exc}")
            return []

        return [
            symbol
            for symbol in all_symbols
            if symbol.id.date.date() == today and symbol.id.option_right == right
        ]

    def _submit_test_spread(self, direction, right, symbols, underlying_price, reason):
        by_strike = {float(symbol.id.strike_price): symbol for symbol in symbols}
        strikes = sorted(by_strike)
        long_strike = self._nearest_strike(strikes, underlying_price)
        if long_strike is None:
            return

        if direction == "long":
            short_candidates = [strike for strike in strikes if strike > long_strike]
            short_strike = self._nearest_strike(short_candidates, long_strike + self.spread_width)
        else:
            short_candidates = [strike for strike in strikes if strike < long_strike]
            short_strike = self._nearest_strike(short_candidates, long_strike - self.spread_width)
        if short_strike is None:
            self.debug(f"{self.time} test order: only one strike resolvable around {underlying_price}")
            return

        long_symbol = by_strike[long_strike]
        short_symbol = by_strike[short_strike]
        self.add_index_option_contract(long_symbol, Resolution.MINUTE)
        self.add_index_option_contract(short_symbol, Resolution.MINUTE)
        expiry = long_symbol.id.date
        self.pending_test_order = {
            "direction": direction,
            "long_strike": long_strike,
            "short_strike": short_strike,
            "expiry": expiry,
            "long_symbol": long_symbol,
            "short_symbol": short_symbol,
            "reason": reason,
            "attempts": 0,
        }
        self.debug(
            f"{self.time} pending TEST ORDER SPXW {direction.upper()} "
            f"{long_strike}/{short_strike} expiry={expiry:%Y-%m-%d}; waiting for prices"
        )

    def _try_submit_pending_test_order(self):
        order = self.pending_test_order
        order["attempts"] += 1
        long_price = float(self.securities[order["long_symbol"]].price) if order["long_symbol"] in self.securities else 0.0
        short_price = float(self.securities[order["short_symbol"]].price) if order["short_symbol"] in self.securities else 0.0
        if long_price <= 0 or short_price <= 0:
            if order["attempts"] >= 20:
                self.debug(
                    f"{self.time} pending TEST ORDER giving up after {order['attempts']} attempts; "
                    f"long_price={long_price} short_price={short_price}"
                )
                self.pending_test_order = None
            return

        direction = order["direction"]
        long_strike = order["long_strike"]
        short_strike = order["short_strike"]
        expiry = order["expiry"]
        if direction == "long":
            strategy = OptionStrategies.bull_call_spread(self.spxw, long_strike, short_strike, expiry)
        else:
            strategy = OptionStrategies.bear_put_spread(self.spxw, long_strike, short_strike, expiry)

        try:
            tickets = self.buy(strategy, self.max_spread_quantity)
        except Exception as exc:
            self.debug(f"{self.time} TEST ORDER submit error: {exc}")
            self.pending_test_order = None
            return

        self.active_tickets = list(tickets)
        self.active_symbols = {ticket.symbol for ticket in self.active_tickets}
        self.active_direction = direction
        self.active_entry_spy = float(self.securities[self.spy].price)
        self.trades_today += 1
        self.cooldown = self.COOLDOWN_BARS
        self.log(
            f"{self.time} TEST ORDER SPXW {direction.upper()} "
            f"{long_strike}/{short_strike} expiry={expiry:%Y-%m-%d} reason={order['reason']}"
        )
        self.pending_test_order = None

    def on_order_event(self, order_event):
        if order_event.status == OrderStatus.FILLED:
            self.debug(
                f"{self.time} fill {order_event.symbol.value} "
                f"qty={order_event.fill_quantity} price={order_event.fill_price}"
            )
