"""
Intraday Order Flow Options Strategy
=====================================
Designed for prop-trading use on an intraday timeframe.

Concept
-------
1. **Volume Profile (VP)** — Built from 1-minute bars during the session.
   Key levels computed every bar:
   - POC  : Point of Control (highest-volume price)
   - VAH  : Value Area High  (upper bound of 70 % volume)
   - VAL  : Value Area Low   (lower bound of 70 % volume)

2. **Market Flow (Cumulative Delta)** — Bar-level delta approximated via the
   Close-Location Value:
       delta ≈ (2*(close - low) / range - 1) * volume
   Tracks net buying/selling pressure across the session.

3. **Order-Flow Setups at VP Levels** (trigger option trades)
   - Imbalance  : Cumulative delta strongly skewed at a key level →
                  expect directional continuation.
   - Absorption : High volume + small-body bar at key level →
                  one side being absorbed; potential reversal or strong hold.
   - Expansion  : High volume + large-body bar breaking through a key level →
                  momentum continuation trade.

4. **Options execution** — Calls on bullish signals, puts on bearish signals,
   always selecting the closest-to-ATM contract in the chain.

Prop-Trading Risk Rules
-----------------------
- Max daily loss guard  : halt trading once daily P&L falls 2 % below open equity.
- Per-trade risk        : size contracts so that paying full premium = 0.5 % of equity.
- Premium stop-out      : exit if the option loses 50 % of entry premium.
- Profit target         : exit at 2× the entry premium.
- End-of-day exit       : liquidate all options 15 min before close.
- Signal cooldown       : 15 bar minimum between entries.
"""

from math import floor

from AlgorithmImports import (
    BrokerageName,
    OptionRight,
    QCAlgorithm,
    Resolution,
    Slice,
    TradeBar,
)


# ════════════════════════════════════════════════════════════════════════════════
# Helper: Volume Profile
# ════════════════════════════════════════════════════════════════════════════════

class VolumeProfile:
    """Maintains a price-bucketed volume histogram for the current session."""

    def __init__(self, bucket_size: float = 0.50):
        self.bucket_size = bucket_size
        self._profile: dict[float, float] = {}

    def reset(self):
        self._profile.clear()

    def update(self, bar: TradeBar):
        """Distribute bar volume evenly across price buckets between low and high."""
        low_b = self._snap(bar.low)
        high_b = self._snap(bar.high)
        num_buckets = max(1, round((high_b - low_b) / self.bucket_size) + 1)
        vol_each = bar.volume / num_buckets
        price = low_b
        while price <= high_b + 1e-9:
            key = round(price, 2)
            self._profile[key] = self._profile.get(key, 0.0) + vol_each
            price = round(price + self.bucket_size, 2)

    def levels(self) -> dict | None:
        """Return POC, VAH, VAL and total volume; None if not enough data."""
        if len(self._profile) < 3:
            return None

        sorted_lvls = sorted(self._profile.items())          # [(price, vol), ...]
        total_vol = sum(v for _, v in sorted_lvls)
        if total_vol <= 0:
            return None

        # POC — price level with the most volume
        poc = max(self._profile, key=self._profile.__getitem__)
        poc_idx = next(i for i, (p, _) in enumerate(sorted_lvls) if p == poc)

        # Value Area — expand from POC until 70 % of volume is captured
        target = total_vol * 0.70
        lo_idx = hi_idx = poc_idx
        captured = self._profile[poc]

        while captured < target:
            can_lo = lo_idx > 0
            can_hi = hi_idx < len(sorted_lvls) - 1
            if not (can_lo or can_hi):
                break
            lo_vol = sorted_lvls[lo_idx - 1][1] if can_lo else 0.0
            hi_vol = sorted_lvls[hi_idx + 1][1] if can_hi else 0.0
            if hi_vol >= lo_vol:
                hi_idx += 1
                captured += hi_vol
            else:
                lo_idx -= 1
                captured += lo_vol

        return {
            "poc": poc,
            "vah": sorted_lvls[hi_idx][0],
            "val": sorted_lvls[lo_idx][0],
            "total_vol": total_vol,
        }

    # ── internals ──────────────────────────────────────────────────────────────

    def _snap(self, price: float) -> float:
        return floor(price / self.bucket_size) * self.bucket_size


# ════════════════════════════════════════════════════════════════════════════════
# Helper: Order Flow Analyzer
# ════════════════════════════════════════════════════════════════════════════════

class OrderFlowAnalyzer:
    """
    Tracks:
    - Bar delta (approximated buying/selling pressure)
    - Cumulative delta (session-running total)
    - Rolling average bar volume (for absorption/expansion thresholds)
    """

    def __init__(self, vol_window: int = 20):
        self.cumulative_delta = 0.0
        self._bar_volumes: list[float] = []
        self._vol_window = vol_window
        self.avg_bar_volume: float | None = None

    def reset(self):
        self.cumulative_delta = 0.0
        self._bar_volumes.clear()
        self.avg_bar_volume = None

    def update(self, bar: TradeBar) -> float:
        """Feed a bar; returns this bar's delta."""
        delta = self._bar_delta(bar)
        self.cumulative_delta += delta
        self._bar_volumes.append(bar.volume)
        if len(self._bar_volumes) > self._vol_window:
            self._bar_volumes.pop(0)
        if len(self._bar_volumes) >= 5:
            self.avg_bar_volume = sum(self._bar_volumes) / len(self._bar_volumes)
        return delta

    # ── internals ──────────────────────────────────────────────────────────────

    @staticmethod
    def _bar_delta(bar: TradeBar) -> float:
        """
        Close-Location Value delta approximation:
            delta = (2*(close - low) / range - 1) * volume
        Positive → net buying; negative → net selling.
        """
        bar_range = bar.high - bar.low
        if bar_range < 1e-9:
            return 0.0
        return (2.0 * (bar.close - bar.low) / bar_range - 1.0) * bar.volume


# ════════════════════════════════════════════════════════════════════════════════
# Main Strategy
# ════════════════════════════════════════════════════════════════════════════════

class IntradayOrderFlowOptionsStrategy(QCAlgorithm):

    # ── parameters ────────────────────────────────────────────────────────────
    VP_BUCKET           = 0.50   # VP bucket width ($)
    LEVEL_PROXIMITY_PCT = 0.002  # 0.2 % proximity for "price at level"
    IMBALANCE_RATIO     = 0.62   # |cumulative_delta| / session_vol threshold
    ABSORB_VOL_MULT     = 2.0    # absorption: bar vol >= N * avg bar vol
    ABSORB_BODY_RATIO   = 0.25   # absorption: body/range <= this
    EXPAND_VOL_MULT     = 1.5    # expansion: bar vol >= N * avg bar vol
    EXPAND_BODY_RATIO   = 0.65   # expansion: body/range >= this
    MAX_DAILY_LOSS_PCT  = 0.02   # stop all trading after 2 % daily drawdown
    RISK_PER_TRADE_PCT  = 0.005  # premium spend per trade = 0.5 % of equity
    MAX_CONTRACTS       = 5      # hard cap on contracts per trade
    STOP_LOSS_PREMIUM   = 0.50   # exit if option down 50 % from entry
    PROFIT_TARGET_MULT  = 2.0    # exit at 2× entry premium
    COOLDOWN_BARS       = 15     # min bars between new entries
    MIN_SESSION_BARS    = 30     # bars before first trade allowed

    # ──────────────────────────────────────────────────────────────────────────

    def initialize(self):
        self.set_start_date(2024, 1, 2)
        self.set_end_date(2024, 6, 28)
        self.set_cash(50_000)
        self.set_brokerage_model(BrokerageName.INTERACTIVE_BROKERS_BROKERAGE)

        # ── Underlying ────────────────────────────────────────────────────────
        equity = self.add_equity("SPY", Resolution.MINUTE)
        self.spy = equity.symbol

        # ── Options chain ─────────────────────────────────────────────────────
        option = self.add_option("SPY", Resolution.MINUTE)
        option.set_filter(lambda u: u.strikes(-5, 5).expiration(0, 7))
        self.option_symbol = option.symbol

        # ── Helpers ───────────────────────────────────────────────────────────
        self._vp = VolumeProfile(self.VP_BUCKET)
        self._of = OrderFlowAnalyzer(vol_window=20)

        # ── Session state (reset each day) ────────────────────────────────────
        self._session_bars       = 0
        self._cooldown           = 0
        self._session_open_value = 0.0
        self._daily_halt         = False
        self._active_option      = None   # Symbol of open option position
        self._option_entry_px    = 0.0
        self._option_direction   = None   # "long" | "short"
        self._current_slice      = None

        # ── Scheduling ────────────────────────────────────────────────────────
        self.schedule.on(
            self.date_rules.every_day("SPY"),
            self.time_rules.after_market_open("SPY", 1),
            self._on_session_start,
        )
        self.schedule.on(
            self.date_rules.every_day("SPY"),
            self.time_rules.before_market_close("SPY", 15),
            self._on_eod_exit,
        )

        self.set_warm_up(60, Resolution.MINUTE)

    # ── Scheduled callbacks ───────────────────────────────────────────────────

    def _on_session_start(self):
        self._vp.reset()
        self._of.reset()
        self._session_bars = 0
        self._cooldown = 0
        self._daily_halt = False
        self._session_open_value = self.portfolio.total_portfolio_value
        self.debug(f"{self.time.date()} Session started — equity {self._session_open_value:,.2f}")

    def _on_eod_exit(self):
        if self._active_option is not None:
            self.liquidate(self._active_option, tag="EOD exit")
            self._active_option = None
            self.debug(f"{self.time} EOD: option position liquidated")

    # ── Main data handler ─────────────────────────────────────────────────────

    def on_data(self, data: Slice):
        self._current_slice = data

        if self.is_warming_up:
            return

        if self.spy not in data.bars:
            return

        bar: TradeBar = data.bars[self.spy]

        # ── Update order flow trackers ─────────────────────────────────────
        self._vp.update(bar)
        self._of.update(bar)
        self._session_bars += 1

        if self._cooldown > 0:
            self._cooldown -= 1

        # ── Manage open option position ────────────────────────────────────
        if self._active_option is not None:
            self._manage_option_position()
            return

        # ── Guard conditions ───────────────────────────────────────────────
        if self._daily_halt:
            return
        if self._session_bars < self.MIN_SESSION_BARS:
            return
        if self._cooldown > 0:
            return

        # ── Check daily loss guard ─────────────────────────────────────────
        current_value = self.portfolio.total_portfolio_value
        if self._session_open_value > 0:
            daily_pnl_pct = (current_value - self._session_open_value) / self._session_open_value
            if daily_pnl_pct <= -self.MAX_DAILY_LOSS_PCT:
                self._daily_halt = True
                self.log(f"{self.time.date()} Daily loss limit hit ({daily_pnl_pct:.2%}) — trading halted")
                return

        # ── Compute VP levels and check for signal ─────────────────────────
        levels = self._vp.levels()
        if levels is None:
            return

        signal = self._detect_signal(bar, levels)
        if signal is None:
            return

        direction, setup_type = signal
        self._enter_option_trade(direction, setup_type, data)

    # ── Option position management ────────────────────────────────────────────

    def _manage_option_position(self):
        """Monitor premium stop-loss and profit target for the open option."""
        if self._active_option not in self.securities:
            return
        if not self.portfolio.contains_key(self._active_option):
            return

        holding = self.portfolio[self._active_option]
        if not holding.invested:
            self._active_option = None
            return

        current_px = self.securities[self._active_option].price
        if current_px <= 0 or self._option_entry_px <= 0:
            return

        pnl_ratio = (current_px - self._option_entry_px) / self._option_entry_px

        if pnl_ratio <= -self.STOP_LOSS_PREMIUM:
            self.liquidate(self._active_option, tag=f"Premium stop: {pnl_ratio:.1%}")
            self._active_option = None
            self._cooldown = self.COOLDOWN_BARS
            return

        if pnl_ratio >= self.PROFIT_TARGET_MULT - 1.0:
            self.liquidate(self._active_option, tag=f"Profit target: {pnl_ratio:.1%}")
            self._active_option = None
            self._cooldown = self.COOLDOWN_BARS

    # ── Signal detection ──────────────────────────────────────────────────────

    def _detect_signal(
        self, bar: TradeBar, levels: dict
    ) -> tuple[str, str] | None:
        """
        Return (direction, setup_type) or None.

        Checks three setups in priority order:
            1. Expansion  — momentum break through VP level
            2. Absorption — high-vol doji at VP level (reversal)
            3. Imbalance  — sustained delta divergence at VP level
        """
        avg_vol = self._of.avg_bar_volume
        if avg_vol is None or avg_vol <= 0:
            return None

        bar_range = bar.high - bar.low
        if bar_range < 1e-9:
            return None

        body       = abs(bar.close - bar.open)
        body_ratio = body / bar_range
        vol_ratio  = bar.volume / avg_vol
        price      = bar.close
        proximity  = price * self.LEVEL_PROXIMITY_PCT

        poc = levels["poc"]
        vah = levels["vah"]
        val = levels["val"]

        # ── 1. Expansion ──────────────────────────────────────────────────
        if vol_ratio >= self.EXPAND_VOL_MULT and body_ratio >= self.EXPAND_BODY_RATIO:
            if bar.close > bar.open:
                # Bullish expansion through VAH
                if bar.low <= vah <= bar.close:
                    return ("long", "expansion")
                # Bullish expansion away from VAL
                if abs(bar.low - val) <= proximity and bar.close > val:
                    return ("long", "expansion")
            else:
                # Bearish expansion through VAL
                if bar.close <= val <= bar.high:
                    return ("short", "expansion")
                # Bearish expansion away from VAH
                if abs(bar.high - vah) <= proximity and bar.close < vah:
                    return ("short", "expansion")

        # ── 2. Absorption ─────────────────────────────────────────────────
        if vol_ratio >= self.ABSORB_VOL_MULT and body_ratio <= self.ABSORB_BODY_RATIO:
            if abs(price - val) <= proximity:
                return ("long", "absorption")   # sellers absorbed at support
            if abs(price - vah) <= proximity:
                return ("short", "absorption")  # buyers absorbed at resistance
            if abs(price - poc) <= proximity:
                # At POC: let cumulative delta decide direction
                return (
                    "long" if self._of.cumulative_delta > 0 else "short",
                    "absorption",
                )

        # ── 3. Imbalance ──────────────────────────────────────────────────
        session_vol = levels["total_vol"]
        delta_ratio = (
            abs(self._of.cumulative_delta) / session_vol
            if session_vol > 0
            else 0.0
        )
        if delta_ratio >= self.IMBALANCE_RATIO:
            if self._of.cumulative_delta > 0:
                # Bullish imbalance: long from VAL or POC
                if abs(price - val) <= proximity and bar.close >= bar.open:
                    return ("long", "imbalance")
                if abs(price - poc) <= proximity and bar.close >= bar.open:
                    return ("long", "imbalance")
            else:
                # Bearish imbalance: short from VAH or POC
                if abs(price - vah) <= proximity and bar.close <= bar.open:
                    return ("short", "imbalance")
                if abs(price - poc) <= proximity and bar.close <= bar.open:
                    return ("short", "imbalance")

        return None

    # ── Option entry ──────────────────────────────────────────────────────────

    def _enter_option_trade(
        self, direction: str, setup_type: str, data: Slice
    ):
        """Select ATM option and size position by premium risk."""
        chain = data.option_chains.get(self.option_symbol)
        if chain is None:
            return

        underlying_price = self.securities[self.spy].price
        right = OptionRight.CALL if direction == "long" else OptionRight.PUT

        contracts = [c for c in chain if c.right == right and c.ask_price > 0]
        if not contracts:
            return

        # Closest-to-ATM, nearest expiry
        best = min(
            contracts,
            key=lambda c: (abs(c.strike - underlying_price), c.expiry),
        )

        premium_per_contract = best.ask_price * 100  # 1 contract = 100 shares
        if premium_per_contract <= 0:
            return

        portfolio_value = self.portfolio.total_portfolio_value
        risk_budget     = portfolio_value * self.RISK_PER_TRADE_PCT
        num_contracts   = max(1, int(risk_budget / premium_per_contract))
        num_contracts   = min(num_contracts, self.MAX_CONTRACTS)

        self.market_order(
            best.symbol,
            num_contracts,
            tag=f"OF|{setup_type}|{direction}",
        )

        self._active_option     = best.symbol
        self._option_entry_px   = best.ask_price
        self._option_direction  = direction
        self._cooldown          = self.COOLDOWN_BARS

        self.debug(
            f"{self.time}  ENTRY {direction.upper()} [{setup_type}]  "
            f"{best.symbol.value} x{num_contracts} @ {best.ask_price:.2f}  "
            f"underlying={underlying_price:.2f}  "
            f"delta={self._of.cumulative_delta:+.0f}  "
            f"bars={self._session_bars}"
        )

    # ── Order events ─────────────────────────────────────────────────────────

    def on_order_event(self, order_event):
        if order_event.status.is_fill():
            self.debug(
                f"Fill: {order_event.symbol.value}  "
                f"qty={order_event.fill_quantity}  "
                f"price={order_event.fill_price:.2f}"
            )
