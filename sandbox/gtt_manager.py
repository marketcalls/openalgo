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

from sqlalchemy import select, update

from database.sandbox_db import (
    SandboxGTT,
    SandboxGTTLeg,
    SandboxOrders,
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
            f"gtt_claim_timeout_sec is not an integer; using {DEFAULT_CLAIM_TIMEOUT_SEC}s"
        )
        return DEFAULT_CLAIM_TIMEOUT_SEC


def _oco_margin_mode() -> str:
    mode = (get_config("gtt_oco_margin_mode", "max") or "max").strip().lower()
    return mode if mode in ("max", "sum") else "max"


def _resolve_expiry(supplied) -> datetime:
    """When this GTT stops resting.

    A caller-supplied ``expires_at`` is honoured; overwriting it with the
    default silently rests a GTT for a year the user asked to expire sooner.
    Anything unparseable falls back to the Zerodha-parity default rather than
    being rejected, since expiry is not what the request is about.
    """
    if supplied:
        for parse in (
            lambda v: datetime.fromisoformat(str(v)),
            lambda v: datetime.strptime(str(v), "%Y-%m-%d %H:%M:%S"),
            lambda v: datetime.strptime(str(v), "%Y-%m-%d"),
        ):
            try:
                parsed = parse(supplied)
            except (TypeError, ValueError):
                continue
            if parsed.tzinfo is not None:
                # The column is a naive DateTime compared against
                # datetime.now(), so an offset-carrying value must be converted
                # to local time first. Storing the wall-clock digits unchanged
                # would treat 13:00Z and 13:00+05:30 as the same instant when
                # they are five and a half hours apart.
                parsed = parsed.astimezone().replace(tzinfo=None)
            return parsed
        logger.warning(f"Unparseable GTT expires_at {supplied!r}; using the default")
    return _now() + timedelta(days=DEFAULT_EXPIRY_DAYS)


def _pricing_basis(leg: dict, last_price) -> float:
    """Price to size a leg's margin against.

    A LIMIT leg is sized at its limit. A MARKET leg has no limit price, and
    sizing it at 0 reserves nothing - the GTT would be accepted, then fail to
    fund its order the moment it fired. The trigger price is the best estimate
    available for a MARKET leg, since that is roughly where it will execute;
    the placement LTP is the fallback if even that is missing.
    """
    price = float(leg.get("price") or 0)
    if price > 0:
        return price
    trigger = float(leg.get("trigger_price") or 0)
    if trigger > 0:
        return trigger
    return float(last_price or 0)


def leg_is_triggered_by(direction: str, trigger_price, ltp) -> bool:
    """Whether ``ltp`` has crossed ``trigger_price`` in ``direction``.

    Direction is a property of the trigger's role, not of the leg's action.
    ``triggerprice_sl`` sits below the LTP at placement and fires on a fall;
    ``triggerprice_tg`` sits above it and fires on a rise. Deriving this from
    BUY/SELL inverts two of the four documented cases - a BUY-on-dip fires
    falling and a SELL-at-target fires rising - which would trigger every such
    GTT immediately on the first tick.

    Comparisons are inclusive, matching how the regular sandbox SL/SL-M book
    treats a trigger touched exactly.
    """
    if trigger_price is None or ltp is None:
        return False
    trigger = Decimal(str(trigger_price))
    price = Decimal(str(ltp))
    if (direction or "").lower() == "above":
        return price >= trigger
    return price <= trigger


class GTTManager:
    """Owns the sandbox GTT lifecycle for one user."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.fund_manager = FundManager(user_id)

    # -- placement ---------------------------------------------------------

    def _leg_margin(self, symbol, exchange, product, quantity, price, action):
        """Margin one leg would need if it fired.

        ``price`` must already be a realistic execution price. A MARKET leg
        carries no limit price, so pricing it at 0 reserves nothing and the GTT
        promises an order it cannot fund - see ``_pricing_basis``.
        """
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
                    symbol,
                    exchange,
                    product,
                    leg["quantity"],
                    _pricing_basis(leg, last_price),
                    leg["action"],
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

            # Staged, so the reservation and the GTT rows land in one commit.
            # Blocking first and persisting after meant a failed insert left the
            # money reserved against a GTT that does not exist, recoverable only
            # by a compensating release that could itself fail.
            ok, message = self.fund_manager.stage_margin_delta(
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
                expires_at=_resolve_expiry(gtt_data.get("expires_at")),
            )
            db_session.add(gtt)

            for index, leg in enumerate(legs, start=1):
                db_session.add(
                    SandboxGTTLeg(
                        gtt_id=gtt_id,
                        leg_number=index,
                        trigger_price=Decimal(str(leg["trigger_price"])),
                        trigger_direction=leg["direction"],
                        action=leg["action"],
                        quantity=int(leg["quantity"]),
                        price=Decimal(str(leg["price"])),
                        pricetype=leg["pricetype"],
                        product=product,
                        leg_status="pending",
                        leg_margin=leg["margin"],
                    )
                )

            try:
                db_session.commit()
            except Exception:
                # One transaction now, so the rollback takes the reservation
                # with it - no compensating release to get wrong.
                db_session.rollback()
                db_session.expire_all()
                raise

            logger.info(
                f"Sandbox GTT {gtt_id} placed for {self.user_id}: {trigger_type} "
                f"{symbol}/{exchange}, margin blocked {blocked}"
            )
            _notify_websocket_engine(gtt)
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
                    "direction": "below",  # stoploss leg: the lower trigger
                    "action": action,
                    "quantity": quantity,
                    "price": as_float(gtt_data.get("stoploss")) or price,
                    "pricetype": pricetype,
                },
                {
                    "trigger_price": tg_trigger,
                    "direction": "above",  # target leg: the higher trigger
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
                # The suffix is the directional hint: _sl sits below the LTP,
                # _tg above it. SINGLE has no stoploss/target roles.
                "direction": "below" if sl_trigger > 0 else "above",
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

            immutable = self._immutable_violation(gtt, gtt_data)
            if immutable:
                return False, {"status": "error", "mode": "analyze", "message": immutable}, 400

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
                    _pricing_basis(leg, gtt.last_price),
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

            # One transaction: the funds move, the parent is re-priced and the
            # legs are rewritten, then a single commit. Two commits meant a
            # failure between them left the ledger and the row disagreeing
            # about the same money, in either direction depending on which way
            # the margin went.
            #
            # The parent update is also conditional on 'active'. The read above
            # can be stale - a fire can claim the GTT while this request is in
            # flight - and a plain assignment would report a successful modify
            # against a GTT that had already triggered.
            claimed = db_session.execute(
                update(SandboxGTT)
                .where(
                    SandboxGTT.gtt_id == trigger_id,
                    SandboxGTT.user_id == self.user_id,
                    SandboxGTT.gtt_status == "active",
                )
                .values(margin_blocked=new_blocked)
            )
            if claimed.rowcount != 1:
                db_session.rollback()
                db_session.expire_all()
                logger.info(
                    f"GTT {trigger_id}: no longer active when the modify was applied"
                )
                return self._not_found(trigger_id)

            staged, message = self.fund_manager.stage_margin_delta(
                delta, description=f"GTT {trigger_id} modify"
            )
            if not staged:
                db_session.rollback()
                db_session.expire_all()
                return (
                    False,
                    {
                        "status": "error",
                        "mode": "analyze",
                        "trigger_id": trigger_id,
                        "message": f"{message}. The GTT is unchanged.",
                    },
                    400 if delta > 0 else 500,
                )

            # strict: the length check above guarantees a 1:1 pairing, and a
            # silent truncation here would leave a leg holding stale prices.
            for existing, updated in zip(gtt.legs, legs, strict=True):
                existing.trigger_price = Decimal(str(updated["trigger_price"]))
                existing.trigger_direction = updated["direction"]
                existing.quantity = int(updated["quantity"])
                existing.price = Decimal(str(updated["price"]))
                existing.pricetype = updated["pricetype"]
                existing.action = updated["action"]
                existing.leg_margin = updated["margin"]

            try:
                db_session.commit()
            except Exception:
                # Nothing was committed, so the funds change unwinds with it.
                db_session.rollback()
                db_session.expire_all()
                raise

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

    @staticmethod
    def _immutable_violation(gtt, gtt_data: dict) -> str | None:
        """Reject a modify that changes something the contract fixes.

        modifygttorder documents action, symbol/exchange and trigger_type as
        not modifiable. Silently applying an action flip would turn a resting
        buy into a sell, and silently ignoring an instrument change would leave
        the user believing a trigger now watches a symbol it does not.
        """
        requested_action = (gtt_data.get("action") or "").upper()
        if requested_action and gtt.legs and requested_action != gtt.legs[0].action.upper():
            return (
                "action cannot be changed on an existing GTT "
                f"({gtt.legs[0].action} -> {requested_action}). Cancel and re-place."
            )

        symbol = (gtt_data.get("symbol") or "").upper()
        if symbol and symbol != (gtt.symbol or "").upper():
            return (
                f"symbol cannot be changed on an existing GTT ({gtt.symbol} -> {symbol}). "
                "Cancel and re-place."
            )

        exchange = (gtt_data.get("exchange") or "").upper()
        if exchange and exchange != (gtt.exchange or "").upper():
            return (
                f"exchange cannot be changed on an existing GTT ({gtt.exchange} -> "
                f"{exchange}). Cancel and re-place."
            )

        requested_type = (gtt_data.get("trigger_type") or "").upper()
        current_type = "OCO" if gtt.trigger_type == "two-leg" else "SINGLE"
        if requested_type and requested_type != current_type:
            return (
                f"trigger_type cannot be changed ({current_type} -> {requested_type}). "
                "Cancel and re-place."
            )
        return None

    def cancel_gtt(self, trigger_id: str) -> tuple[bool, dict, int]:
        """Cancel an active GTT and release its margin.

        The status change is a conditional UPDATE, not a read followed by a
        write. Reading an active GTT and then assigning ``cancelled`` is
        check-then-act: fire_leg can claim the parent in between, and the stale
        object would then overwrite 'triggered' with 'cancelled' while the child
        order was already on its way - cancel reporting success for an order
        that got placed anyway, with the margin released twice.

        Only the caller whose UPDATE matched may touch the legs or the funds.
        """
        try:
            gtt = self._get_active_gtt(trigger_id)
            if gtt is None:
                return self._not_found(trigger_id)

            # Captured before the claim. Only fire_leg changes this, and it can
            # only do so after winning the same row, so if our UPDATE matches
            # then this value was still current.
            released = Decimal(str(gtt.margin_blocked or 0))

            # Parent claim, leg cancellation and the fund release are one
            # transaction. Committing the parent first meant a later failure
            # left the GTT terminally cancelled with the money still blocked and
            # no way to retry - the row was already 'cancelled', so a second
            # attempt could not claim it.
            won = db_session.execute(
                update(SandboxGTT)
                .where(
                    SandboxGTT.gtt_id == trigger_id,
                    SandboxGTT.user_id == self.user_id,
                    SandboxGTT.gtt_status == "active",
                )
                .values(gtt_status="cancelled", margin_blocked=Decimal("0.00"))
            )
            if won.rowcount != 1:
                # Someone else resolved it between the read and here.
                db_session.rollback()
                db_session.expire_all()
                return self._not_found(trigger_id)

            # 'triggering' too: a leg claimed a moment ago has placed nothing
            # yet, and fire_leg revalidates the parent before it does, so
            # cancelling the leg here stops it.
            db_session.execute(
                update(SandboxGTTLeg)
                .where(
                    SandboxGTTLeg.gtt_id == trigger_id,
                    SandboxGTTLeg.leg_status.in_(["pending", "triggering"]),
                )
                .values(leg_status="cancelled", claimed_at=None)
            )

            if released > 0:
                staged, reason = self.fund_manager.stage_margin_delta(
                    -released, description=f"GTT {trigger_id} cancelled"
                )
                if not staged:
                    db_session.rollback()
                    db_session.expire_all()
                    logger.error(
                        f"GTT {trigger_id}: could not release its {released} margin "
                        f"({reason}); the GTT is unchanged and can be cancelled again"
                    )
                    return (
                        False,
                        {
                            "status": "error",
                            "mode": "analyze",
                            "trigger_id": trigger_id,
                            "message": (
                                f"Could not release {released} margin ({reason}). The "
                                "GTT is unchanged - retry the cancel."
                            ),
                        },
                        500,
                    )

            try:
                db_session.commit()
            except Exception:
                # Nothing landed, so the GTT is still active and cancellable.
                db_session.rollback()
                db_session.expire_all()
                raise

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

    def list_gtts(self, status_filter: str | None = "active") -> tuple[bool, dict, int]:
        """The user's GTTs, newest first, in the canonical orderbook shape.

        Active-only by default, matching the broker mappers: the orderbook UI
        lists triggers that can still fire, so returning cancelled and expired
        rows would show the user GTTs that no longer exist. Pass
        ``status_filter=None`` for the full history.
        """
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
        """One orderbook entry, shaped exactly like the broker mappers produce.

        ``trigger_prices`` is not optional: the frontend's GttOrder type
        requires it and GttTab renders it directly, so an entry without it
        breaks the GTT tab rather than merely looking different.
        """
        return {
            "trigger_id": gtt.gtt_id,
            "trigger_type": gtt.trigger_type,
            "status": gtt.gtt_status,
            "symbol": gtt.symbol,
            "exchange": gtt.exchange,
            "trigger_prices": [float(leg.trigger_price or 0) for leg in gtt.legs],
            "last_price": float(gtt.last_price or 0),
            "legs": [
                {
                    "action": leg.action,
                    "quantity": leg.quantity,
                    "price": float(leg.price or 0),
                    "pricetype": leg.pricetype,
                    "product": leg.product,
                }
                for leg in gtt.legs
            ],
            "created_at": gtt.created_at.isoformat() if gtt.created_at else "",
            "updated_at": gtt.updated_at.isoformat() if gtt.updated_at else "",
            "expires_at": gtt.expires_at.isoformat() if gtt.expires_at else "",
            # Sandbox-only extras, additive so the shared shape is unaffected.
            "strategy": gtt.strategy,
            "margin_blocked": float(gtt.margin_blocked or 0),
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
        # Exclusivity is per GTT, not per leg. Claiming only on
        # leg_status='pending' lets both legs of an OCO be claimed at once by
        # two evaluators - each wins its own leg - and both then place an
        # order, which is precisely what OCO must never do. The predicate also
        # requires the parent to still be active, so a GTT cancelled or expired
        # between evaluation and claim cannot fire.
        parent = select(SandboxGTTLeg.gtt_id).where(SandboxGTTLeg.id == leg_id).scalar_subquery()

        sibling_busy = (
            select(SandboxGTTLeg.id)
            .where(
                SandboxGTTLeg.gtt_id == parent,
                SandboxGTTLeg.id != leg_id,
                SandboxGTTLeg.leg_status.in_(["triggering", "triggered"]),
            )
            .exists()
        )
        parent_active = (
            select(SandboxGTT.id)
            .where(SandboxGTT.gtt_id == parent, SandboxGTT.gtt_status == "active")
            .exists()
        )

        result = db_session.execute(
            update(SandboxGTTLeg)
            .where(
                SandboxGTTLeg.id == leg_id,
                SandboxGTTLeg.leg_status == "pending",
                ~sibling_busy,
                parent_active,
            )
            .values(leg_status="triggering", claimed_at=datetime.now())
        )
        db_session.commit()
        won = result.rowcount == 1
        if not won:
            logger.debug(
                f"GTT leg {leg_id}: claim lost - another evaluator owns this GTT, "
                "or it is no longer active"
            )
        return won
    except Exception as e:
        db_session.rollback()
        logger.exception(f"Error claiming GTT leg {leg_id}: {e}")
        return False


def _compensate_failed_fire(gtt, leg_id: int, released: Decimal, order_committed: bool) -> None:
    """Undo a fire that did not complete, on every failure path.

    Both a rejected order and a raised exception land here, because they leave
    the same wreckage: the GTT's reservation has already been released so the
    child order could be funded, and the parent has already been claimed. A
    rejection used to restore the margin while an exception did not, so a raised
    error left the GTT back on 'active' holding nothing - it would fire again on
    the next tick and be rejected for want of funds.

    If the reservation cannot be restored, the GTT is marked 'rejected' rather
    than returned to 'active'. An active GTT with no margin is a trap: it looks
    armed and fails the moment it matters.
    """
    if order_committed:
        # The child order exists. Undoing the parent now would double-fire.
        logger.error(
            f"GTT {gtt.gtt_id}: fire failed after the child order was committed; "
            "leaving it triggered so the order is not duplicated"
        )
        return

    restored = True
    if released > 0:
        try:
            restored, reason = FundManager(gtt.user_id).block_margin(
                released, description=f"GTT {gtt.gtt_id} fire failed"
            )
        except Exception:
            restored = False
            reason = "block_margin raised"
            logger.exception(f"GTT {gtt.gtt_id}: restoring margin raised")

        try:
            gtt.margin_blocked = released if restored else Decimal("0.00")
            db_session.commit()
        except Exception:
            db_session.rollback()
            logger.exception(f"GTT {gtt.gtt_id}: could not persist the restored margin")

        if not restored:
            logger.error(
                f"GTT {gtt.gtt_id}: could not restore {released} margin after a failed "
                f"fire ({reason}). Marking it rejected rather than leaving it armed "
                "and unfunded."
            )
            try:
                db_session.execute(
                    update(SandboxGTT)
                    .where(SandboxGTT.gtt_id == gtt.gtt_id)
                    .values(gtt_status="rejected")
                )
                db_session.commit()
            except Exception:
                db_session.rollback()
                logger.exception(f"GTT {gtt.gtt_id}: could not mark it rejected")
            _revert_claim(leg_id)
            return

    _revert_parent(gtt.gtt_id)
    _revert_claim(leg_id)


def self_release(gtt, amount: Decimal) -> tuple[bool, str]:
    """Stage a GTT's margin release inside the caller's transaction."""
    if amount <= 0:
        return True, ""
    try:
        return FundManager(gtt.user_id).stage_margin_delta(
            -amount, description=f"GTT {gtt.gtt_id} expired"
        )
    except Exception:
        logger.exception(f"GTT {gtt.gtt_id}: staging the expiry release raised")
        return False, "stage_margin_delta raised"


def _release_margin(user_id: str, amount: Decimal, description: str) -> tuple[bool, str]:
    """Release margin and report whether it actually happened.

    Every caller here publishes a state change - expired, cancelled, modified,
    triggered - and each of those is a lie if the funds did not move. Wrapping
    the call means no caller can forget to look at the result, and a raised
    exception reads the same as a refusal.
    """
    if amount <= 0:
        return True, ""
    try:
        return FundManager(user_id).release_margin(amount, description=description)
    except Exception:
        logger.exception(f"{description}: release_margin raised")
        return False, "release_margin raised"


def _revert_parent(gtt_id: str) -> None:
    """Hand a GTT back to 'active' after a fire that did not complete.

    Conditional on it still being 'triggered', so this cannot resurrect a GTT
    that another path has since cancelled or expired.
    """
    try:
        db_session.execute(
            update(SandboxGTT)
            .where(SandboxGTT.gtt_id == gtt_id, SandboxGTT.gtt_status == "triggered")
            .values(gtt_status="active")
        )
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        logger.exception(f"Error reverting GTT {gtt_id} to active: {e}")


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

    if leg.leg_status != "triggering":
        logger.info(f"GTT leg {leg_id} is '{leg.leg_status}', not 'triggering' - not firing")
        return False

    # Take the parent atomically, before any irreversible step. Reading
    # gtt_status here would be check-then-act: a cancel landing between the read
    # and place_order returns success while the order still goes in, and both
    # paths then release the same margin. Flipping active -> triggered in one
    # conditional UPDATE means whoever wins that row owns the outcome, and
    # cancel - which only matches gtt_status='active' - can no longer succeed.
    claimed_parent = db_session.execute(
        update(SandboxGTT)
        .where(SandboxGTT.gtt_id == gtt.gtt_id, SandboxGTT.gtt_status == "active")
        .values(gtt_status="triggered")
    )
    db_session.commit()
    if claimed_parent.rowcount != 1:
        db_session.refresh(gtt)
        logger.info(
            f"GTT {gtt.gtt_id} is no longer active ('{gtt.gtt_status}') - "
            f"not firing leg {leg_id}"
        )
        _revert_claim(leg_id)
        return False

    released = Decimal("0.00")
    released_ok = False
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
            # Written in the same INSERT as the order. This is what makes
            # recovery correct: leg.triggered_order_id is a later commit, so a
            # crash between the two would otherwise hide a placed order.
            "gtt_leg_id": leg.id,
        }

        # Release the GTT's reservation before placing: place_order blocks
        # margin for the order it creates, and holding both at once would
        # reject a leg the account can afford.
        #
        # The release and the margin_blocked=0 that records it are one
        # transaction. Committing them separately meant a crash in between left
        # the money returned while the row still claimed it, and recovery reads
        # margin_blocked > 0 as proof the funds were never released - so it
        # would re-arm the GTT without restoring anything, leaving it active and
        # unfunded.
        released = Decimal(str(gtt.margin_blocked or 0))
        if released > 0:
            staged, reason = FundManager(gtt.user_id).stage_margin_delta(
                -released, description=f"GTT {gtt.gtt_id} triggered"
            )
            if not staged:
                # Placing now would block a second reservation on top of one
                # that was never returned - the account charged twice for a
                # single trigger. Stand down and let the next tick retry.
                db_session.rollback()
                logger.error(
                    f"GTT {gtt.gtt_id}: could not release its {released} margin "
                    f"({reason}); not placing the order"
                )
                _revert_parent(gtt.gtt_id)
                _revert_claim(leg_id)
                return False

            gtt.margin_blocked = Decimal("0.00")
            try:
                db_session.commit()
            except Exception:
                # Neither the funds nor the row moved; nothing to compensate.
                db_session.rollback()
                logger.exception(
                    f"GTT {gtt.gtt_id}: releasing its margin failed to commit; "
                    "not placing the order"
                )
                _revert_parent(gtt.gtt_id)
                _revert_claim(leg_id)
                return False
            released_ok = True

        success, response, _status = order_manager.place_order(order_payload)

        if not success:
            message = response.get("message") if isinstance(response, dict) else response
            logger.error(f"GTT leg {leg_id} order rejected: {message}")
            _compensate_failed_fire(
                gtt, leg_id, released if released_ok else Decimal('0.00'), order_committed=False
            )
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

        # gtt_status was already set to 'triggered' by the parent claim above.
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
        # Same compensation as a rejection: an exception after the release left
        # the GTT armed with no reservation, which is the worse of the two.
        _compensate_failed_fire(
            gtt,
            leg_id,
            released if locals().get("released_ok") else Decimal("0.00"),
            order_committed=bool(locals().get("orderid")),
        )
        return False


def _notify_websocket_engine(gtt: SandboxGTT) -> None:
    """Ask the running WebSocket engine to start watching this GTT.

    The engine's index is built at startup, so a GTT placed while it runs would
    otherwise never be ticked - inert until a restart or a fallback to polling.
    A no-op when the polling engine is active, which scans the table directly.
    """
    try:
        from sandbox.websocket_execution_engine import (
            get_websocket_execution_engine,
            is_websocket_execution_engine_running,
        )

        if not is_websocket_execution_engine_running():
            return
        engine = get_websocket_execution_engine()
        if engine is not None:
            engine.notify_gtt_placed(gtt)
    except Exception as e:
        # Never fail a placement because the watcher could not be told: the
        # polling fallback and the boot rebuild both still find this GTT.
        logger.exception(f"Could not notify the WebSocket engine of GTT {gtt.gtt_id}: {e}")


def _api_key_for(user_id: str) -> str:
    """The user's API key, needed by the alert subscribers to identify them.

    A trigger fires from a background thread with no request context, so there
    is no key to carry through - it has to be looked up. Returns "" on failure:
    a missing key costs an alert, and must not cost the order.
    """
    try:
        from database.auth_db import ApiKeys, decrypt_token

        row = ApiKeys.query.filter_by(user_id=user_id).first() or ApiKeys.query.first()
        return decrypt_token(row.api_key_encrypted) if row else ""
    except Exception:
        logger.exception(f"Could not resolve an API key for {user_id}")
        return ""


def _publish_triggered(gtt: SandboxGTT, orderid) -> None:
    """Announce a fired GTT. A publish failure must not undo a placed order.

    request_data/response_data are populated because the log and alert
    subscribers read them: without a payload the row would land in the log with
    nothing in it, which is worse than useless when reconstructing why an order
    appeared unprompted.
    """
    try:
        from events.order_events import GTTTriggeredEvent
        from utils.event_bus import bus

        request_data = {
            "api_type": "gtttriggered",
            "trigger_id": gtt.gtt_id,
            "symbol": gtt.symbol,
            "exchange": gtt.exchange,
            "strategy": gtt.strategy or "",
            "trigger_prices": [float(leg.trigger_price or 0) for leg in gtt.legs],
        }
        response_data = {
            "status": "success",
            "mode": "analyze",
            "trigger_id": gtt.gtt_id,
            "orderid": orderid or "",
        }
        bus.publish(
            GTTTriggeredEvent(
                mode="analyze",
                api_type="gtttriggered",
                symbol=gtt.symbol,
                exchange=gtt.exchange,
                trigger_id=gtt.gtt_id,
                triggered_order_id=orderid or "",
                request_data=request_data,
                response_data=response_data,
                api_key=_api_key_for(gtt.user_id),
            )
        )
    except Exception as e:
        logger.exception(f"Error publishing GTTTriggeredEvent for {gtt.gtt_id}: {e}")


def _publish_expired(gtt: SandboxGTT) -> None:
    """Announce an expired GTT. A publish failure must not undo the expiry."""
    try:
        from events.order_events import GTTExpiredEvent
        from utils.event_bus import bus

        request_data = {
            "api_type": "gttexpired",
            "trigger_id": gtt.gtt_id,
            "symbol": gtt.symbol,
            "exchange": gtt.exchange,
            "strategy": gtt.strategy or "",
        }
        response_data = {
            "status": "success",
            "mode": "analyze",
            "trigger_id": gtt.gtt_id,
            "message": "GTT expired without firing",
        }
        bus.publish(
            GTTExpiredEvent(
                mode="analyze",
                api_type="gttexpired",
                symbol=gtt.symbol,
                exchange=gtt.exchange,
                trigger_id=gtt.gtt_id,
                request_data=request_data,
                response_data=response_data,
                api_key=_api_key_for(gtt.user_id),
            )
        )
    except Exception as e:
        logger.exception(f"Error publishing GTTExpiredEvent for {gtt.gtt_id}: {e}")


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
        # A crashed fire strands the parent as well as the leg, and a parent
        # left on 'triggered' with a pending leg is invisible to every
        # evaluator - so the leg reclaim alone would not bring the GTT back.
        reclaim_stranded_parents()
        return result.rowcount
    except Exception as e:
        db_session.rollback()
        logger.exception(f"Error reclaiming stranded GTT legs: {e}")
        return 0


def reclaim_stranded_parents() -> int:
    """Recover GTTs whose fire died between claiming the parent and placing.

    fire_leg flips the parent to 'triggered' before the child order exists, so
    that a cancel cannot slip in. If the worker dies in that window the leg
    reaper puts the leg back to 'pending' but nothing touches the parent, and
    the GTT is left 'triggered' with a pending leg: invisible to every
    evaluator, and unable to fire, cancel or expire.

    Recovery is decided by whether the child order actually exists, which is the
    only durable evidence of how far the fire got:

    * no leg carries a triggered_order_id -> the order was never placed, so the
      GTT goes back to 'active' and its reservation is restored;
    * some leg does -> the order is real, so the GTT stays 'triggered' and is
      simply finalised.

    Restoring the reservation matters as much as the status: the crash happened
    after the margin was released, so a GTT returned to 'active' without it
    would be armed and unfunded. If the funds cannot be restored the GTT is
    marked 'rejected' instead.
    """
    recovered = 0
    try:
        stranded = (
            SandboxGTT.query.filter(SandboxGTT.gtt_status == "triggered").all()
        )
        for gtt in stranded:
            legs = gtt.legs or []
            if any(leg.triggered_order_id for leg in legs):
                continue  # marker present; the order exists

            # The marker is written after the order, so its absence proves
            # nothing. Ask the order table directly - a row correlated to one of
            # these legs means the child order was committed and this GTT has
            # already fired, whatever the leg says. Re-arming it here would
            # place a second order for a single trigger.
            leg_ids = [leg.id for leg in legs]
            # Rejected attempts are not evidence the GTT fired - the broker
            # refused, nothing was bought, and the GTT should be re-armed.
            placed = (
                SandboxOrders.query.filter(
                    SandboxOrders.gtt_leg_id.in_(leg_ids),
                    SandboxOrders.order_status != "rejected",
                ).first()
                if leg_ids
                else None
            )
            if placed is not None:
                logger.warning(
                    f"GTT {gtt.gtt_id}: interrupted after its child order "
                    f"{placed.orderid} was committed but before the leg was marked; "
                    "finalising rather than re-arming"
                )
                db_session.execute(
                    update(SandboxGTTLeg)
                    .where(SandboxGTTLeg.id == placed.gtt_leg_id)
                    .values(
                        leg_status="triggered",
                        triggered_order_id=placed.orderid,
                        claimed_at=None,
                    )
                )
                db_session.commit()
                recovered += 1
                continue
            if not any(leg.leg_status in ("pending", "triggering") for leg in legs):
                continue  # fully resolved (cancelled sibling etc), not stranded

            still_reserved = Decimal(str(gtt.margin_blocked or 0))
            if still_reserved > 0:
                # The crash happened before the release, so the funds were never
                # given back. Blocking again here would reserve the same money
                # twice - the GTT is already funded, so only its status needs
                # putting right.
                required = Decimal("0.00")
                logger.info(
                    f"GTT {gtt.gtt_id}: interrupted before its margin was released; "
                    f"the existing {still_reserved} reservation stands"
                )
            else:
                # Released during the fire and never restored - put back what
                # the legs say the GTT needs.
                required = max(
                    (Decimal(str(leg.leg_margin or 0)) for leg in legs),
                    default=Decimal("0.00"),
                )

            restored = True
            if required > 0:
                try:
                    restored, reason = FundManager(gtt.user_id).block_margin(
                        required, description=f"GTT {gtt.gtt_id} crash recovery"
                    )
                except Exception:
                    restored, reason = False, "block_margin raised"
                    logger.exception(f"GTT {gtt.gtt_id}: recovery re-block raised")

            if not restored:
                logger.error(
                    f"GTT {gtt.gtt_id}: stranded by an interrupted fire and its "
                    f"{required} margin could not be restored ({reason}). Marking it "
                    "rejected rather than re-arming it unfunded."
                )
                db_session.execute(
                    update(SandboxGTT)
                    .where(SandboxGTT.gtt_id == gtt.gtt_id)
                    .values(gtt_status="rejected")
                )
                db_session.commit()
                recovered += 1
                continue

            db_session.execute(
                update(SandboxGTT)
                .where(SandboxGTT.gtt_id == gtt.gtt_id, SandboxGTT.gtt_status == "triggered")
                .values(
                    gtt_status="active",
                    margin_blocked=still_reserved if still_reserved > 0 else required,
                )
            )
            db_session.execute(
                update(SandboxGTTLeg)
                .where(
                    SandboxGTTLeg.gtt_id == gtt.gtt_id,
                    SandboxGTTLeg.leg_status == "triggering",
                )
                .values(leg_status="pending", claimed_at=None)
            )
            db_session.commit()
            recovered += 1
            logger.warning(
                f"GTT {gtt.gtt_id}: recovered from an interrupted fire - back to "
                f"active with {required} margin restored"
            )
        return recovered
    except Exception as e:
        db_session.rollback()
        logger.exception(f"Error reclaiming stranded GTT parents: {e}")
        return recovered


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
        due = SandboxGTT.query.filter(
            SandboxGTT.gtt_status == "active",
            SandboxGTT.expires_at.isnot(None),
            SandboxGTT.expires_at < datetime.now(),
        ).all()
        for gtt in due:
            released = Decimal(str(gtt.margin_blocked or 0))

            # Claim the parent conditionally, exactly as firing does. The query
            # above is a stale read by the time we act on it: a GTT can be
            # fired, cancelled or expired by another path in between, and
            # assigning 'expired' over a fire would strand a real child order
            # and release the margin that order now needs.
            claimed = db_session.execute(
                update(SandboxGTT)
                .where(
                    SandboxGTT.gtt_id == gtt.gtt_id,
                    SandboxGTT.gtt_status == "active",
                )
                .values(gtt_status="expired", margin_blocked=Decimal("0.00"))
            )
            if claimed.rowcount != 1:
                db_session.rollback()
                logger.debug(
                    f"GTT {gtt.gtt_id}: resolved by another path before it expired"
                )
                continue

            db_session.execute(
                update(SandboxGTTLeg)
                .where(
                    SandboxGTTLeg.gtt_id == gtt.gtt_id,
                    SandboxGTTLeg.leg_status == "pending",
                )
                .values(leg_status="cancelled", claimed_at=None)
            )

            # Staged, not committed: the funds move and the expiry land in the
            # same transaction. Releasing first and committing after meant a
            # failed commit left the money returned while the GTT stayed
            # active - and the next sweep would release the same reservation
            # again.
            staged, reason = self_release(gtt, released)
            if not staged:
                db_session.rollback()
                logger.error(
                    f"GTT {gtt.gtt_id}: past expiry but its {released} margin could "
                    f"not be released ({reason}); leaving it active to retry"
                )
                continue

            try:
                db_session.commit()
            except Exception:
                db_session.rollback()
                logger.exception(
                    f"GTT {gtt.gtt_id}: expiry commit failed; nothing was applied"
                )
                continue

            expired += 1
            logger.info(f"Sandbox GTT {gtt.gtt_id} expired; released {released}")
            _publish_expired(gtt)
        return expired
    except Exception as e:
        db_session.rollback()
        logger.exception(f"Error expiring GTTs: {e}")
        return expired
