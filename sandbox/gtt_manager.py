# sandbox/gtt_manager.py
"""Sandbox GTT (Good Till Triggered) manager.

Analyze-mode counterpart to the broker GTT APIs. A GTT is a resting trigger: it
holds one leg (``single``) or two mutually exclusive legs (``two-leg`` OCO), and
when the market crosses a leg's trigger price that leg's order is placed for
real in the sandbox book.

Three independent evaluators can observe the same crossed trigger at the same
instant - the polling engine, the WebSocket engine, and the boot-time catch-up
scan. Firing must happen exactly once, so every evaluator goes through
``try_claim_trigger()``, a single conditional UPDATE that moves a leg from
``pending`` to ``triggering``. The database decides the winner; losers see
``rowcount == 0`` and return quietly. Nothing else in this module may place an
order for a leg it did not win.

The ``triggering`` state is a claim, not a durable one: a process that dies
between claiming and firing would strand the leg there forever. Legs whose
claim is older than ``gtt_claim_timeout_sec`` are reverted to ``pending`` by
``reclaim_stranded_legs()``, which runs on every poll tick and again at startup.

Margin is blocked at placement so a GTT cannot promise an order the account
cannot afford when it fires. For OCO, only one leg can ever execute, so
``gtt_oco_margin_mode='max'`` (the default) blocks the larger leg rather than
both; ``sum`` blocks both for users who prefer the conservative reading.
"""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import update

from database.sandbox_db import (
    SandboxGTT,
    SandboxGTTLeg,
    db_session,
    get_config,
)
from sandbox.fund_manager import FundManager
from sandbox.order_manager import OrderManager
from utils.logging import get_logger

logger = get_logger(__name__)

#: Zerodha parity: a GTT with no explicit expiry rests for a year.
DEFAULT_EXPIRY_DAYS = 365

#: Fallback when the config row is missing or unparseable. Matches the seeded
#: default in database/sandbox_db.py.
DEFAULT_CLAIM_TIMEOUT_SEC = 60


def _now() -> datetime:
    return datetime.now()


def _generate_gtt_id() -> str:
    """``GTT-YYMMDD-<8hex>`` - prefixed so origin is obvious in logs."""
    return f"GTT-{_now().strftime('%y%m%d')}-{uuid.uuid4().hex[:8]}"


def _claim_timeout_seconds() -> int:
    try:
        return int(get_config("gtt_claim_timeout_sec", DEFAULT_CLAIM_TIMEOUT_SEC))
    except (TypeError, ValueError):
        logger.warning(
            "gtt_claim_timeout_sec is not an integer; using "
            f"{DEFAULT_CLAIM_TIMEOUT_SEC}s"
        )
        return DEFAULT_CLAIM_TIMEOUT_SEC


def _oco_margin_mode() -> str:
    mode = (get_config("gtt_oco_margin_mode", "max") or "max").strip().lower()
    return mode if mode in ("max", "sum") else "max"


def leg_is_triggered_by(action: str, trigger_price, ltp) -> bool:
    """Whether ``ltp`` has crossed ``trigger_price`` for a leg of ``action``.

    A BUY leg is a breakout above its trigger; a SELL leg is a breakdown below
    it. Both comparisons are inclusive, matching how the regular sandbox
    SL/SL-M book treats a trigger touched exactly.
    """
    if trigger_price is None or ltp is None:
        return False
    trigger = Decimal(str(trigger_price))
    price = Decimal(str(ltp))
    if (action or "").upper() == "BUY":
        return price >= trigger
    return price <= trigger


class GTTManager:
    """Owns the sandbox GTT lifecycle for one user."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.fund_manager = FundManager(user_id)

    # -- placement ---------------------------------------------------------

    def _leg_margin(self, symbol, exchange, product, quantity, price, action):
        """Margin one leg would need if it fired, priced at its limit price."""
        margin, error = self.fund_manager.calculate_margin_required(
            symbol=symbol,
            exchange=exchange,
            product=product,
            quantity=quantity,
            price=price,
            action=action,
        )
        if margin is None:
            return None, error
        return Decimal(str(margin)), None

    def place_gtt(self, gtt_data: dict, last_price) -> tuple[bool, dict, int]:
        """Create a GTT and block its margin.

        Args:
            gtt_data: Flat validated payload (see ``PlaceGTTOrderSchema``):
                trigger_type SINGLE|OCO, symbol, exchange, action, product,
                quantity, pricetype, price, triggerprice_sl, triggerprice_tg,
                stoploss, target, strategy.
            last_price: LTP snapshot at placement, echoed back for broker parity.

        Returns:
            ``(success, response, http_status)``.
        """
        try:
            legs = self._build_legs(gtt_data)
            if not legs:
                return (
                    False,
                    {
                        "status": "error",
                        "mode": "analyze",
                        "message": (
                            "A SINGLE GTT needs exactly one of triggerprice_sl or "
                            "triggerprice_tg; an OCO needs both."
                        ),
                    },
                    400,
                )

            symbol = gtt_data.get("symbol")
            exchange = gtt_data.get("exchange")
            product = gtt_data.get("product")
            trigger_type = "two-leg" if len(legs) == 2 else "single"

            # Price each leg, then decide what the GTT as a whole must reserve.
            for leg in legs:
                margin, error = self._leg_margin(
                    symbol, exchange, product, leg["quantity"], leg["price"], leg["action"]
                )
                if margin is None:
                    return (
                        False,
                        {"status": "error", "mode": "analyze", "message": error},
                        400,
                    )
                leg["margin"] = margin

            margins = [leg["margin"] for leg in legs]
            if trigger_type == "two-leg" and _oco_margin_mode() == "max":
                # Only one OCO leg can ever execute, so reserving both would
                # double-count and reject GTTs the account can actually afford.
                blocked = max(margins)
            else:
                blocked = sum(margins)

            ok, message = self.fund_manager.block_margin(
                blocked, description=f"GTT {symbol} {exchange}"
            )
            if not ok:
                return (
                    False,
                    {"status": "error", "mode": "analyze", "message": message},
                    400,
                )

            gtt_id = _generate_gtt_id()
            gtt = SandboxGTT(
                gtt_id=gtt_id,
                user_id=self.user_id,
                strategy=gtt_data.get("strategy"),
                trigger_type=trigger_type,
                symbol=symbol,
                exchange=exchange,
                last_price=Decimal(str(last_price or 0)),
                gtt_status="active",
                margin_blocked=blocked,
                expires_at=_now() + timedelta(days=DEFAULT_EXPIRY_DAYS),
            )
            db_session.add(gtt)

            for index, leg in enumerate(legs, start=1):
                db_session.add(
                    SandboxGTTLeg(
                        gtt_id=gtt_id,
                        leg_number=index,
                        trigger_price=Decimal(str(leg["trigger_price"])),
                        action=leg["action"],
                        quantity=int(leg["quantity"]),
                        price=Decimal(str(leg["price"])),
                        pricetype=leg["pricetype"],
                        product=product,
                        leg_status="pending",
                        leg_margin=leg["margin"],
                    )
                )

            db_session.commit()
            logger.info(
                f"Sandbox GTT {gtt_id} placed for {self.user_id}: {trigger_type} "
                f"{symbol}/{exchange}, margin blocked {blocked}"
            )
            return True, {"status": "success", "mode": "analyze", "trigger_id": gtt_id}, 200

        except Exception as e:
            db_session.rollback()
            logger.exception(f"Error placing sandbox GTT: {e}")
            return (
                False,
                {"status": "error", "mode": "analyze", "message": f"GTT placement error: {e}"},
                500,
            )

    def _build_legs(self, gtt_data: dict) -> list[dict]:
        """Flat request fields to leg dicts.

        SINGLE carries one trigger and reuses the top-level action/price. OCO
        carries a stoploss and a target leg; both take the same action, which is
        how a protective pair on an existing position behaves - it is the exit
        side that matters, and only one of the two will survive.
        """
        action = (gtt_data.get("action") or "").upper()
        quantity = gtt_data.get("quantity")
        pricetype = (gtt_data.get("pricetype") or "LIMIT").upper()
        price = gtt_data.get("price") or 0

        def as_float(value):
            try:
                return float(value or 0)
            except (TypeError, ValueError):
                return 0.0

        sl_trigger = as_float(gtt_data.get("triggerprice_sl"))
        tg_trigger = as_float(gtt_data.get("triggerprice_tg"))
        is_oco = (gtt_data.get("trigger_type") or "").upper() == "OCO"

        if is_oco:
            if sl_trigger <= 0 or tg_trigger <= 0:
                return []
            return [
                {
                    "trigger_price": sl_trigger,
                    "action": action,
                    "quantity": quantity,
                    "price": as_float(gtt_data.get("stoploss")) or price,
                    "pricetype": pricetype,
                },
                {
                    "trigger_price": tg_trigger,
                    "action": action,
                    "quantity": quantity,
                    "price": as_float(gtt_data.get("target")) or price,
                    "pricetype": pricetype,
                },
            ]

        trigger = sl_trigger or tg_trigger
        # Exactly one, not either-or: a SINGLE carrying both triggers is an OCO
        # the caller forgot to label, and guessing which one they meant would
        # silently drop the other.
        if trigger <= 0 or (sl_trigger > 0 and tg_trigger > 0):
            return []
        return [
            {
                "trigger_price": trigger,
                "action": action,
                "quantity": quantity,
                "price": price,
                "pricetype": pricetype,
            }
        ]

    # -- modify / cancel / list -------------------------------------------

    def modify_gtt(self, trigger_id: str, gtt_data: dict) -> tuple[bool, dict, int]:
        """Re-price an active GTT, reconciling the margin difference."""
        try:
            gtt = self._get_active_gtt(trigger_id)
            if gtt is None:
                return self._not_found(trigger_id)

            legs = self._build_legs(gtt_data)
            if not legs or len(legs) != len(gtt.legs):
                return (
                    False,
                    {
                        "status": "error",
                        "mode": "analyze",
                        "message": (
                            "Modify must keep the same trigger shape: "
                            f"this GTT has {len(gtt.legs)} leg(s)."
                        ),
                    },
                    400,
                )

            for leg in legs:
                margin, error = self._leg_margin(
                    gtt.symbol,
                    gtt.exchange,
                    gtt_data.get("product") or gtt.legs[0].product,
                    leg["quantity"],
                    leg["price"],
                    leg["action"],
                )
                if margin is None:
                    return False, {"status": "error", "mode": "analyze", "message": error}, 400
                leg["margin"] = margin

            margins = [leg["margin"] for leg in legs]
            if gtt.trigger_type == "two-leg" and _oco_margin_mode() == "max":
                new_blocked = max(margins)
            else:
                new_blocked = sum(margins)

            old_blocked = Decimal(str(gtt.margin_blocked or 0))
            delta = new_blocked - old_blocked
            if delta > 0:
                ok, message = self.fund_manager.block_margin(
                    delta, description=f"GTT {trigger_id} modify"
                )
                if not ok:
                    return False, {"status": "error", "mode": "analyze", "message": message}, 400
            elif delta < 0:
                self.fund_manager.release_margin(
                    -delta, description=f"GTT {trigger_id} modify"
                )

            # strict: the length check above guarantees a 1:1 pairing, and a
            # silent truncation here would leave a leg holding stale prices.
            for existing, updated in zip(gtt.legs, legs, strict=True):
                existing.trigger_price = Decimal(str(updated["trigger_price"]))
                existing.quantity = int(updated["quantity"])
                existing.price = Decimal(str(updated["price"]))
                existing.pricetype = updated["pricetype"]
                existing.action = updated["action"]
                existing.leg_margin = updated["margin"]
            gtt.margin_blocked = new_blocked

            db_session.commit()
            logger.info(f"Sandbox GTT {trigger_id} modified; margin now {new_blocked}")
            return True, {"status": "success", "mode": "analyze", "trigger_id": trigger_id}, 200

        except Exception as e:
            db_session.rollback()
            logger.exception(f"Error modifying sandbox GTT {trigger_id}: {e}")
            return (
                False,
                {"status": "error", "mode": "analyze", "message": f"GTT modify error: {e}"},
                500,
            )

    def cancel_gtt(self, trigger_id: str) -> tuple[bool, dict, int]:
        """Cancel an active GTT and release its margin."""
        try:
            gtt = self._get_active_gtt(trigger_id)
            if gtt is None:
                return self._not_found(trigger_id)

            released = Decimal(str(gtt.margin_blocked or 0))
            gtt.gtt_status = "cancelled"
            for leg in gtt.legs:
                if leg.leg_status == "pending":
                    leg.leg_status = "cancelled"
            gtt.margin_blocked = Decimal("0.00")
            db_session.commit()

            if released > 0:
                self.fund_manager.release_margin(
                    released, description=f"GTT {trigger_id} cancelled"
                )

            logger.info(f"Sandbox GTT {trigger_id} cancelled; released {released}")
            return True, {"status": "success", "mode": "analyze", "trigger_id": trigger_id}, 200

        except Exception as e:
            db_session.rollback()
            logger.exception(f"Error cancelling sandbox GTT {trigger_id}: {e}")
            return (
                False,
                {"status": "error", "mode": "analyze", "message": f"GTT cancel error: {e}"},
                500,
            )

    def list_gtts(self, status_filter: str | None = None) -> tuple[bool, dict, int]:
        """The user's GTTs, newest first, in broker-orderbook shape."""
        try:
            query = SandboxGTT.query.filter_by(user_id=self.user_id)
            if status_filter:
                query = query.filter_by(gtt_status=status_filter)
            rows = query.order_by(SandboxGTT.created_at.desc()).all()
            return (
                True,
                {
                    "status": "success",
                    "mode": "analyze",
                    "data": [self._serialize(gtt) for gtt in rows],
                },
                200,
            )
        except Exception as e:
            logger.exception(f"Error listing sandbox GTTs: {e}")
            return (
                False,
                {"status": "error", "mode": "analyze", "message": f"GTT orderbook error: {e}"},
                500,
            )

    def _serialize(self, gtt: SandboxGTT) -> dict:
        return {
            "trigger_id": gtt.gtt_id,
            "strategy": gtt.strategy,
            "trigger_type": gtt.trigger_type,
            "symbol": gtt.symbol,
            "exchange": gtt.exchange,
            "last_price": float(gtt.last_price or 0),
            "status": gtt.gtt_status,
            "margin_blocked": float(gtt.margin_blocked or 0),
            "created_at": gtt.created_at.isoformat() if gtt.created_at else None,
            "expires_at": gtt.expires_at.isoformat() if gtt.expires_at else None,
            "legs": [
                {
                    "leg_number": leg.leg_number,
                    "trigger_price": float(leg.trigger_price or 0),
                    "action": leg.action,
                    "quantity": leg.quantity,
                    "price": float(leg.price or 0),
                    "pricetype": leg.pricetype,
                    "product": leg.product,
                    "status": leg.leg_status,
                    "triggered_order_id": leg.triggered_order_id,
                }
                for leg in gtt.legs
            ],
        }

    def _get_active_gtt(self, trigger_id: str):
        return SandboxGTT.query.filter_by(
            gtt_id=trigger_id, user_id=self.user_id, gtt_status="active"
        ).first()

    def _not_found(self, trigger_id: str) -> tuple[bool, dict, int]:
        return (
            False,
            {
                "status": "error",
                "mode": "analyze",
                "message": f"No active GTT with trigger_id '{trigger_id}'",
            },
            404,
        )


# -- claim / fire (module level: evaluators are not per-user) ---------------


def try_claim_trigger(leg_id: int) -> bool:
    """Atomically claim a leg for firing. Exactly one caller can win.

    The polling engine, the WebSocket engine and the boot catch-up scan can all
    see the same crossed trigger within milliseconds of each other. The claim is
    a single conditional UPDATE, so the database - not application ordering -
    decides the winner. Losers get ``rowcount == 0`` and must do nothing.

    Returns:
        True if this caller now owns the leg and must call ``fire_leg``.
    """
    try:
        result = db_session.execute(
            update(SandboxGTTLeg)
            .where(SandboxGTTLeg.id == leg_id, SandboxGTTLeg.leg_status == "pending")
            .values(leg_status="triggering", claimed_at=datetime.now())
        )
        db_session.commit()
        won = result.rowcount == 1
        if not won:
            logger.debug(f"GTT leg {leg_id}: claim lost, another evaluator owns it")
        return won
    except Exception as e:
        db_session.rollback()
        logger.exception(f"Error claiming GTT leg {leg_id}: {e}")
        return False


def _revert_claim(leg_id: int) -> None:
    """Put a claimed leg back to ``pending`` after a failed fire.

    Conditional on still being ``triggering`` so this cannot stamp over a state
    the reaper or another worker has since moved on.
    """
    try:
        db_session.execute(
            update(SandboxGTTLeg)
            .where(SandboxGTTLeg.id == leg_id, SandboxGTTLeg.leg_status == "triggering")
            .values(leg_status="pending", claimed_at=None)
        )
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        logger.exception(f"Error reverting GTT leg {leg_id} claim: {e}")


def fire_leg(leg_id: int, execution_price=None) -> bool:
    """Place the order for a leg this caller has already claimed.

    Must only be called after ``try_claim_trigger(leg_id)`` returned True.

    On success the leg becomes ``triggered``, its sibling (OCO) is cancelled,
    the parent becomes ``triggered`` and the GTT's margin is released - the
    placed order blocks its own margin, so leaving the GTT's reservation in
    place would double-count it.

    On any failure the claim is reverted to ``pending`` so the next evaluator
    tick retries, rather than the leg being lost in ``triggering``.
    """
    leg = SandboxGTTLeg.query.filter_by(id=leg_id).first()
    if leg is None:
        logger.error(f"GTT leg {leg_id} vanished between claim and fire")
        return False

    gtt = SandboxGTT.query.filter_by(gtt_id=leg.gtt_id).first()
    if gtt is None:
        logger.error(f"GTT parent {leg.gtt_id} missing for leg {leg_id}")
        _revert_claim(leg_id)
        return False

    try:
        order_manager = OrderManager(gtt.user_id)
        order_payload = {
            "symbol": gtt.symbol,
            "exchange": gtt.exchange,
            "action": leg.action,
            "quantity": leg.quantity,
            "price": float(leg.price or 0),
            "trigger_price": 0,
            "price_type": leg.pricetype,
            "product": leg.product,
            "strategy": gtt.strategy or "GTT",
        }

        # Release the GTT's reservation first: place_order blocks margin for the
        # order it creates, and holding both at once would reject a leg the
        # account can afford.
        released = Decimal(str(gtt.margin_blocked or 0))
        if released > 0:
            FundManager(gtt.user_id).release_margin(
                released, description=f"GTT {gtt.gtt_id} triggered"
            )
            gtt.margin_blocked = Decimal("0.00")
            db_session.commit()

        success, response, _status = order_manager.place_order(order_payload)

        if not success:
            message = response.get("message") if isinstance(response, dict) else response
            logger.error(f"GTT leg {leg_id} order rejected: {message}")
            # Put the reservation back so the retry has funds to work with.
            if released > 0:
                FundManager(gtt.user_id).block_margin(
                    released, description=f"GTT {gtt.gtt_id} fire failed"
                )
                gtt.margin_blocked = released
                db_session.commit()
            _revert_claim(leg_id)
            return False

        orderid = response.get("orderid") if isinstance(response, dict) else None
        leg.triggered_order_id = orderid
        leg.leg_status = "triggered"
        leg.claimed_at = None

        # OCO: the sibling can never fire now. Claim-and-cancel so a sibling
        # mid-claim on another thread cannot also place an order.
        if gtt.trigger_type == "two-leg":
            result = db_session.execute(
                update(SandboxGTTLeg)
                .where(
                    SandboxGTTLeg.gtt_id == gtt.gtt_id,
                    SandboxGTTLeg.id != leg_id,
                    SandboxGTTLeg.leg_status.in_(["pending", "triggering"]),
                )
                .values(leg_status="cancelled", claimed_at=None)
            )
            if result.rowcount == 0:
                logger.debug(
                    f"GTT {gtt.gtt_id}: sibling of leg {leg_id} already resolved elsewhere"
                )

        gtt.gtt_status = "triggered"
        db_session.commit()

        logger.info(
            f"Sandbox GTT {gtt.gtt_id} leg {leg.leg_number} triggered at "
            f"{execution_price}; order {orderid}"
        )
        _publish_triggered(gtt, orderid)
        return True

    except Exception as e:
        db_session.rollback()
        logger.exception(f"Error firing GTT leg {leg_id}: {e}")
        _revert_claim(leg_id)
        return False


def _publish_triggered(gtt: SandboxGTT, orderid) -> None:
    """Announce a fired GTT. A publish failure must not undo a placed order."""
    try:
        from events import bus
        from events.order_events import GTTTriggeredEvent

        bus.publish(
            GTTTriggeredEvent(
                mode="analyze",
                api_type="placegttorder",
                symbol=gtt.symbol,
                exchange=gtt.exchange,
                trigger_id=gtt.gtt_id,
                triggered_order_id=orderid or "",
            )
        )
    except Exception as e:
        logger.exception(f"Error publishing GTTTriggeredEvent for {gtt.gtt_id}: {e}")


def reclaim_stranded_legs() -> int:
    """Revert legs stuck in ``triggering`` past the claim timeout.

    A process that dies between claiming a leg and firing it leaves the leg
    unclaimable forever, because the claim UPDATE only matches ``pending``.
    This is the safety net. The timeout comparison is part of the predicate, so
    a worker that is legitimately slow - a claim made one second ago - is not
    yanked out from under itself.

    Returns:
        How many legs were reverted.
    """
    try:
        cutoff = datetime.now() - timedelta(seconds=_claim_timeout_seconds())
        result = db_session.execute(
            update(SandboxGTTLeg)
            .where(
                SandboxGTTLeg.leg_status == "triggering",
                SandboxGTTLeg.claimed_at.isnot(None),
                SandboxGTTLeg.claimed_at < cutoff,
            )
            .values(leg_status="pending", claimed_at=None)
        )
        db_session.commit()
        if result.rowcount:
            logger.warning(
                f"Reclaimed {result.rowcount} GTT leg(s) stranded in 'triggering' "
                "by an interrupted worker"
            )
        return result.rowcount
    except Exception as e:
        db_session.rollback()
        logger.exception(f"Error reclaiming stranded GTT legs: {e}")
        return 0


def get_active_legs() -> list:
    """Every pending leg of every active GTT, for the evaluators to scan."""
    try:
        return (
            db_session.query(SandboxGTTLeg, SandboxGTT)
            .join(SandboxGTT, SandboxGTTLeg.gtt_id == SandboxGTT.gtt_id)
            .filter(SandboxGTT.gtt_status == "active", SandboxGTTLeg.leg_status == "pending")
            .all()
        )
    except Exception as e:
        logger.exception(f"Error loading active GTT legs: {e}")
        return []


def expire_due_gtts() -> int:
    """Flip past-expiry active GTTs to ``expired`` and release their margin."""
    expired = 0
    try:
        due = (
            SandboxGTT.query.filter(
                SandboxGTT.gtt_status == "active",
                SandboxGTT.expires_at.isnot(None),
                SandboxGTT.expires_at < datetime.now(),
            ).all()
        )
        for gtt in due:
            released = Decimal(str(gtt.margin_blocked or 0))
            gtt.gtt_status = "expired"
            gtt.margin_blocked = Decimal("0.00")
            for leg in gtt.legs:
                if leg.leg_status == "pending":
                    leg.leg_status = "cancelled"
            db_session.commit()
            if released > 0:
                FundManager(gtt.user_id).release_margin(
                    released, description=f"GTT {gtt.gtt_id} expired"
                )
            expired += 1
            logger.info(f"Sandbox GTT {gtt.gtt_id} expired; released {released}")
        return expired
    except Exception as e:
        db_session.rollback()
        logger.exception(f"Error expiring GTTs: {e}")
        return expired
