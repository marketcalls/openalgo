"""SPX 1:45 PM Sandwich: a paper-first 0DTE short iron condor.

The rules are derived from the Option Alpha bot's visible scanner and closed
positions. Paper-mode order placement is enabled by default; an explicit
decision-only parameter remains available for diagnostics.
"""

from datetime import date, datetime, time
import json
import re
import uuid

from AlgorithmImports import *

from rules import build_strikes, calculate_credit_metrics
from strategies.python.common.strategy_state import StrategyStateStore


class Spx1_45PmSandwichStrategy(QCAlgorithm):
    STATE_KEY_PREFIX = "ib-ownership/v1/spx-1-45pm-sandwich"
    TAG_PREFIX = "SPX145"
    ENTRY_START = time(13, 45)
    ENTRY_END = time(14, 0)
    ALLOWED_WEEKDAYS = {0, 1, 3, 4}  # Mon/Tue/Thu/Fri

    def initialize(self):
        self.set_start_date(2024, 1, 2)
        self.set_cash(50_000)
        self.set_brokerage_model(BrokerageName.INTERACTIVE_BROKERS_BROKERAGE)

        self.min_vix = self._float_parameter("sandwich-min-vix", 0.0)
        self.max_vix = self._float_parameter("sandwich-max-vix", 24.0)
        self.min_reward_risk = self._float_parameter("sandwich-min-reward-risk", 1.0)
        self.wing_width = self._float_parameter("sandwich-wing-width", 5.0)
        self.max_allocation = self._float_parameter("sandwich-max-allocation", 2500.0)
        self.place_orders = self._bool_parameter("sandwich-place-orders", True)
        self.force_exit_before_close = self._bool_parameter("sandwich-force-exit", False)
        self.state_scope = self.get_parameter("sandwich-state-scope") or "paper"
        self._legacy_state_key = f"{self.STATE_KEY_PREFIX}/{self.state_scope}/ledger.json"
        self._state_store = StrategyStateStore(
            self.object_store,
            "spx-1-45pm-sandwich",
            self.state_scope,
            1,
            self._default_ledger,
        )
        self._state_reconciliation_required = False
        self._ledger = self._load_ledger()
        self._ledger_reconciled = False

        self.spx = self.add_index("SPX", Resolution.MINUTE).symbol
        self.vix = self.add_index("VIX", Resolution.MINUTE).symbol
        option = self.add_index_option(self.spx, "SPXW", Resolution.MINUTE)
        option.set_filter(lambda universe: universe.weeklys_only().strikes(-20, 20).expiration(0, 0))
        self.spxw = option.symbol

        self._entry_attempted_date = None
        self._entry_tickets = []
        self._last_decision_date = None

        if self.force_exit_before_close:
            self.schedule.on(
                self.date_rules.every_day(self.spx),
                self.time_rules.at(15, 55),
                self._emergency_exit,
            )

        self.set_warm_up(1, Resolution.MINUTE)

    def on_data(self, slice: Slice) -> None:
        if self.is_warming_up:
            return

        if self._state_reconciliation_required:
            self._log_decision("blocked: state reconciliation required")
            return

        if not self._ledger_reconciled:
            self._reconcile_ledger()

        now = self.time
        if now.weekday() not in self.ALLOWED_WEEKDAYS:
            return
        if not (self.ENTRY_START <= now.time() <= self.ENTRY_END):
            return
        if self._entry_attempted_date == now.date():
            return
        if self._has_owned_open_trade() or self._has_pending_orders():
            self._log_decision("blocked: existing position or pending order")
            self._entry_attempted_date = now.date()
            return

        vix_price = float(self.securities[self.vix].price)
        if vix_price <= self.min_vix or vix_price >= self.max_vix:
            self._log_decision(f"blocked: VIX={vix_price:.2f} outside ({self.min_vix}, {self.max_vix})")
            return

        reference_price = float(self.securities[self.spx].price)
        if reference_price <= 0:
            self._log_decision("blocked: SPX reference price unavailable")
            return

        chain = slice.option_chains.get(self.spxw)
        if not chain:
            self._log_decision("blocked: SPXW option chain unavailable")
            return

        today = now.date()
        contracts = [contract for contract in chain if contract.expiry.date() == today]
        if not contracts:
            self._log_decision("blocked: no SPXW 0DTE contracts")
            return

        strikes = build_strikes(reference_price, wing=self.wing_width)
        selected = self._select_contracts(contracts, strikes)
        if selected is None:
            self._log_decision(f"blocked: missing quoted contracts for {strikes}")
            return

        long_put, short_put, short_call, long_call = selected
        metrics = calculate_credit_metrics(
            short_put.bid_price,
            short_call.bid_price,
            long_put.ask_price,
            long_call.ask_price,
            wing_width=self.wing_width,
        )
        if metrics is None:
            self._log_decision("blocked: non-positive executable credit or risk")
            return
        if metrics.reward_risk_ratio < self.min_reward_risk:
            self._log_decision(
                f"blocked: credit={metrics.credit:.2f} ROR={metrics.reward_risk_ratio:.3f} "
                f"minimum={self.min_reward_risk:.3f}"
            )
            return
        if metrics.max_loss_dollars > self.max_allocation:
            self._log_decision(f"blocked: max loss ${metrics.max_loss_dollars:.2f} exceeds allocation")
            return

        self._entry_attempted_date = today
        self._log_decision(
            f"eligible: SPX={reference_price:.2f} VIX={vix_price:.2f} "
            f"strikes={strikes} credit={metrics.credit:.2f} risk=${metrics.max_loss_dollars:.2f} "
            f"ROR={metrics.reward_risk_ratio:.3f} place_orders={self.place_orders}"
        )
        if not self.place_orders:
            return

        trade_id = uuid.uuid4().hex[:16]
        entry_tag = self._order_tag(trade_id, "ENTRY")
        self._ledger["trades"][trade_id] = {
            "status": "ENTRY_SUBMITTED",
            "entry_order_ids": [],
            "entry_brokerage_ids": [],
            "entry_execution_ids": [],
            "exit_order_ids": [],
            "exit_execution_ids": [],
            "legs": [
                {"symbol": str(long_put.symbol), "expected_quantity": 1},
                {"symbol": str(short_put.symbol), "expected_quantity": -1},
                {"symbol": str(short_call.symbol), "expected_quantity": -1},
                {"symbol": str(long_call.symbol), "expected_quantity": 1},
            ],
            "created_at": self.time.isoformat(),
            "last_event_at": self.time.isoformat(),
        }
        self._save_ledger()

        strategy = OptionStrategies.iron_condor(
            self.spxw,
            strikes.long_put,
            strikes.short_put,
            strikes.short_call,
            strikes.long_call,
            min(contract.expiry for contract in selected),
        )
        self._entry_tickets = list(self.sell(strategy, 1, tag=entry_tag))
        trade = self._ledger["trades"][trade_id]
        for ticket in self._entry_tickets:
            trade["entry_order_ids"].append(int(ticket.order_id))
            brokerage_id = getattr(ticket.order, "brokerage_id", None)
            if brokerage_id:
                trade["entry_brokerage_ids"].append(str(brokerage_id))
        self._save_ledger()
        self.debug(f"submitted short iron condor trade={trade_id} tickets={len(self._entry_tickets)}")

    def on_order_event(self, order_event: OrderEvent) -> None:
        order = self.transactions.get_order_by_id(order_event.order_id)
        tag = getattr(order, "tag", "") if order else ""
        trade_id = self._trade_id_from_tag(tag)
        if trade_id and trade_id in self._ledger["trades"]:
            trade = self._ledger["trades"][trade_id]
            execution_id = getattr(order_event, "brokerage_execution_id", None)
            if execution_id and execution_id not in self._ledger["seen_execution_ids"]:
                self._ledger["seen_execution_ids"].append(str(execution_id))
                trade["entry_execution_ids"].append(str(execution_id))
            if order_event.status == OrderStatus.FILLED:
                trade["status"] = "OPEN"
            elif order_event.status == OrderStatus.PARTIALLY_FILLED:
                trade["status"] = "PARTIALLY_FILLED"
            elif order_event.status in {OrderStatus.CANCELED, OrderStatus.INVALID}:
                trade["status"] = "RECONCILIATION_REQUIRED"
            trade["last_event_at"] = self.time.isoformat()
            self._save_ledger()
        self.debug(
            f"order event id={order_event.order_id} status={order_event.status} "
            f"symbol={order_event.symbol} fill={order_event.fill_quantity} price={order_event.fill_price} "
            f"ib_exec_id={getattr(order_event, 'brokerage_execution_id', None)}"
        )

    def _select_contracts(self, contracts, strikes):
        def find(right, strike):
            matches = [
                contract
                for contract in contracts
                if contract.right == right
                and abs(float(contract.strike) - float(strike)) < 1e-9
                and float(contract.bid_price) > 0
                and float(contract.ask_price) > 0
            ]
            return matches[0] if matches else None

        selected = (
            find(OptionRight.PUT, strikes.long_put),
            find(OptionRight.PUT, strikes.short_put),
            find(OptionRight.CALL, strikes.short_call),
            find(OptionRight.CALL, strikes.long_call),
        )
        return selected if all(selected) else None

    def _has_pending_orders(self):
        return any(
            ticket.status in {OrderStatus.NEW, OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED}
            for ticket in self._entry_tickets
        )

    def _has_owned_open_trade(self):
        active = {"ENTRY_SUBMITTED", "PARTIALLY_FILLED", "OPEN", "EXIT_SUBMITTED", "RECONCILIATION_REQUIRED"}
        return any(trade.get("status") in active for trade in self._ledger["trades"].values())

    def _order_tag(self, trade_id, role):
        return f"{self.TAG_PREFIX}|v1|trade={trade_id}|role={role}"

    def _trade_id_from_tag(self, tag):
        match = re.search(r"(?:^|\|)trade=([^|]+)", str(tag or ""))
        return match.group(1) if match else None

    def _load_ledger(self):
        result = self._state_store.load()
        if result.is_valid:
            ledger = result.payload
        elif result.status == "missing":
            ledger = self._load_legacy_ledger()
            if ledger is None:
                return self._default_ledger()
            self._state_store.save(ledger, self.time.isoformat())
            self.debug("ownership ledger migrated into shared storage.")
        else:
            self._state_reconciliation_required = True
            self.error(
                f"Unable to restore ownership ledger: {result.status}; "
                "new entries are blocked pending reconciliation."
            )
            return self._default_ledger()

        ledger.setdefault("trades", {})
        ledger.setdefault("seen_execution_ids", [])
        return ledger

    def _default_ledger(self):
        return {
            "schema_version": 1,
            "strategy_id": "spx-1-45pm-sandwich",
            "trades": {},
            "seen_execution_ids": [],
        }

    def _load_legacy_ledger(self):
        try:
            if not self.object_store.contains_key(self._legacy_state_key):
                return None
            loaded = json.loads(self.object_store.read(self._legacy_state_key))
        except Exception as error:
            self._state_reconciliation_required = True
            self.error(
                f"Unable to load legacy ownership ledger: {error}; "
                "new entries are blocked pending reconciliation."
            )
            return None

        if (not isinstance(loaded, dict)
                or loaded.get("schema_version") != 1
                or loaded.get("strategy_id") != "spx-1-45pm-sandwich"):
            self._state_reconciliation_required = True
            self.error(
                "Incompatible legacy ownership ledger; "
                "new entries are blocked pending reconciliation."
            )
            return None
        return loaded

    def _save_ledger(self):
        self._ledger["updated_at"] = self.time.isoformat()
        self._state_store.save(self._ledger, self.time.isoformat())

    def _reconcile_ledger(self):
        # IB/LEAN account synchronization has completed before the first live
        # OnData call. Existing active ledger trades are intentionally retained
        # and block new entries until their ownership is resolved.
        self._ledger_reconciled = True
        if self._has_owned_open_trade():
            self.debug("ownership ledger restored; new entries remain blocked until the owned trade is closed.")

    def _emergency_exit(self):
        if self.portfolio.invested:
            self.liquidate(tag="emergency exit before settlement")

    def _log_decision(self, message):
        if self._last_decision_date != self.time.date() or message.startswith("eligible"):
            self.debug(f"{self.time.isoformat()} sandwich {message}")
            self._last_decision_date = self.time.date()

    def _bool_parameter(self, name, default):
        value = str(self.get_parameter(name) or str(default)).lower()
        return value in {"1", "true", "yes", "on"}

    def _float_parameter(self, name, default):
        try:
            value = self.get_parameter(name)
            return float(value) if value else float(default)
        except (TypeError, ValueError):
            return float(default)
