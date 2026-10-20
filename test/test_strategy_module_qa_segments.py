"""Segment coverage QA for the /strategy module.

The other suites in this module test one layer against fakes. This one drives
the two strategy kinds across every segment the module claims to support, with
the real validator, the real symbol resolver, the real store and the real run
state, and only the final broker call replaced:

    validate_strategy_config -> store -> engine.start_run / signals.handle_signal
        -> symbol_resolver (real) -> order_dispatch.dispatch_order (mocked)
        -> sm_strategy_order + run state

Segments covered: NSE and BSE cash, NFO index options (NIFTY, BANKNIFTY), BFO
index options (SENSEX), NFO stock options (RELIANCE, VEDL), NFO stock futures,
MCX commodity futures and options (CRUDEOIL), and CDS currency futures and
options (USDINR).

What is asserted for each: the leg resolves to a symbol in the format
docs/prompt/symbol-format.md documents, the quantity is the lot count times the
lot size the master contract actually carries, the order payload carries the
right action, exchange, product and price type, an order row is written, and
the run state records the leg with a side.

The market below is in memory. The dates are in 2030 so the resolver's
"not expired" filtering cannot make the suite go stale, and the lot sizes are
the real ones (NIFTY 65, BANKNIFTY 30, SENSEX 20, RELIANCE 500, CRUDEOIL 1,
USDINR 1000) rather than round numbers that would hide an arithmetic error.

Tests marked xfail pin a defect. Each names it in its reason string and its
docstring says what the module does and what it should do instead. They are
strict, so fixing the defect turns the marker red rather than passing silently.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

# restx_api first: see the note in test_strategy_module_order_dispatch.py.
import restx_api  # noqa: F401
from blueprints.strategy_module import validate_strategy_config
from database import strategy_module_db as store
from services import expiry_service, option_symbol_service, quotes_service
from services.strategy_module import engine, signals, state
from services.strategy_module.order_dispatch import DispatchResult
from services.strategy_module.symbol_resolver import lot_size_for, resolve_leg, resolve_quantity

USER = "qa_segment_user"

# ---------------------------------------------------------------------------
# The market: master contract, expiry calendars and tape, all in memory
# ---------------------------------------------------------------------------

NIFTY_EXPIRIES = [
    "03-JAN-30",
    "10-JAN-30",
    "17-JAN-30",
    "24-JAN-30",
    "31-JAN-30",
    "07-FEB-30",
    "28-FEB-30",
]
#: NFO futures list monthlies only, which is why the resolver asks for the
#: options and the futures calendar separately.
NIFTY_FUTURE_EXPIRIES = ["31-JAN-30", "28-FEB-30"]
NIFTY_STRIKES = [23400.0, 23450.0, 23500.0, 23550.0, 23600.0, 23650.0, 23700.0, 23750.0]
NIFTY_LTP = 23587.50
NIFTY_LOT = 65

BANKNIFTY_EXPIRIES = ["31-JAN-30", "28-FEB-30"]
BANKNIFTY_STRIKES = [51800.0, 51900.0, 52000.0, 52100.0, 52200.0]
BANKNIFTY_LTP = 52040.0
BANKNIFTY_LOT = 30

#: BFO runs its own index family on its own calendar, and a different lot size.
SENSEX_EXPIRIES = ["04-JAN-30", "11-JAN-30", "25-JAN-30"]
SENSEX_FUTURE_EXPIRIES = ["25-JAN-30"]
SENSEX_STRIKES = [77800.0, 77900.0, 78000.0, 78100.0, 78200.0]
SENSEX_LTP = 78040.0
SENSEX_LOT = 20

#: Stock options are monthly only. A leg that asks for "weekly" gets the
#: nearest live expiry, which here is a monthly.
RELIANCE_EXPIRIES = ["31-JAN-30", "28-FEB-30"]
RELIANCE_STRIKES = [2900.0, 2950.0, 3000.0, 3050.0, 3100.0]
RELIANCE_LTP = 2987.0
RELIANCE_LOT = 500

#: The fractional ladder. VEDL really does list 292.5.
VEDL_EXPIRIES = ["25-APR-30"]
VEDL_STRIKES = [287.5, 290.0, 292.5, 295.0]
VEDL_LTP = 292.30
VEDL_LOT = 1150

#: MCX: no spot at all, two calendars that do not line up, lot size 1.
CRUDEOIL_OPTION_EXPIRIES = ["16-AUG-30", "16-SEP-30"]
CRUDEOIL_FUTURE_EXPIRIES = ["19-AUG-30", "19-SEP-30"]
CRUDEOIL_STRIKES = [6650.0, 6700.0, 6750.0, 6800.0, 6850.0]
CRUDEOIL_LTP = 6743.0
CRUDEOIL_LOT = 1

#: CDS: no spot either, and a quarter-rupee strike ladder.
USDINR_OPTION_EXPIRIES = ["26-MAY-30", "26-JUN-30"]
USDINR_FUTURE_EXPIRIES = ["26-MAY-30", "26-JUN-30"]
USDINR_STRIKES = [87.75, 88.0, 88.25, 88.5]
USDINR_LTP = 88.19
USDINR_LOT = 1000

#: Which products each exchange actually accepts. Mirrors
#: blueprints/scalping.py, which is the one surface in this codebase that
#: states the rule directly: a derivative venue takes MIS or NRML, a cash
#: venue MIS or CNC.
DERIVATIVE_VENUES = frozenset({"NFO", "BFO", "MCX", "CDS", "BCD", "NCDEX", "NCO"})


def legal_products(exchange: str) -> set[str]:
    return {"MIS", "NRML"} if exchange in DERIVATIVE_VENUES else {"MIS", "CNC"}


def symbol_expiry(stored: str) -> str:
    """``31-JAN-30`` as a symbol embeds it: ``31JAN30``."""
    return datetime.strptime(stored, "%d-%b-%y").strftime("%d%b%y").upper()


class FakeMarket:
    """The master contract, the expiry calendars and the tape.

    Nothing is listed by default. A symbol the resolver builds and this class
    does not know is refused, which is the point: a wrongly constructed symbol
    must fail the lookup rather than be waved through.
    """

    def __init__(self):
        self.expiries: dict[tuple[str, str, str], list[str]] = {}
        self.strikes: dict[tuple[str, str, str, str], list[float]] = {}
        self.contracts: dict[tuple[str, str], dict] = {}
        self.near_futures: dict[tuple[str, str], dict] = {}
        self.prices: dict[tuple[str, str], float] = {}
        self.expiry_calls: list[tuple[str, str, str]] = []
        self.strike_calls: list[tuple[str, str, str, str]] = []
        self.quote_calls: list[tuple[str, str]] = []
        self.lookups: list[tuple[str, str]] = []

    # -- registration ---------------------------------------------------------

    def list_contract(self, symbol, exchange, lotsize, tick_size=0.05):
        self.contracts[(symbol, exchange)] = {
            "symbol": symbol,
            "exchange": exchange,
            "lotsize": lotsize,
            "tick_size": tick_size,
        }

    def list_cash(self, symbol, exchange, lotsize=1, tick_size=0.05):
        self.list_contract(symbol, exchange, lotsize, tick_size)

    def list_futures(self, base, exchange, expiries, lotsize, tick_size=0.05, nearest=None):
        self.expiries[(base, exchange, "futures")] = list(expiries)
        for stored in expiries:
            symbol = f"{base}{symbol_expiry(stored)}FUT"
            self.list_contract(symbol, exchange, lotsize, tick_size)
        if nearest:
            symbol = f"{base}{symbol_expiry(nearest)}FUT"
            self.near_futures[(base, exchange)] = {
                "symbol": symbol,
                "exchange": exchange,
                "expiry": nearest,
            }

    def list_option_chain(self, base, exchange, expiries, strikes, lotsize, tick_size=0.05):
        self.expiries[(base, exchange, "options")] = list(expiries)
        for stored in expiries:
            embedded = symbol_expiry(stored)
            for option_type in ("CE", "PE"):
                self.strikes[(base, embedded, option_type, exchange)] = list(strikes)
                for strike in strikes:
                    text = str(int(strike)) if float(strike).is_integer() else str(strike)
                    self.list_contract(
                        f"{base}{embedded}{text}{option_type}", exchange, lotsize, tick_size
                    )

    def set_price(self, symbol, exchange, ltp):
        self.prices[(symbol, exchange)] = ltp

    # -- the stubs the resolver actually calls ---------------------------------

    def get_expiry_dates(self, symbol, exchange, instrumenttype, api_key=None):
        self.expiry_calls.append((symbol, exchange, instrumenttype))
        dates = self.expiries.get((symbol, exchange, instrumenttype))
        if dates is None:
            return False, {"status": "error", "message": f"No expiries for {symbol}"}, 404
        return True, {"status": "success", "data": list(dates)}, 200

    def get_available_strikes(self, base_symbol, expiry_date, option_type, exchange):
        key = (base_symbol, expiry_date, option_type, exchange)
        self.strike_calls.append(key)
        return list(self.strikes.get(key, []))

    def find_option_in_database(self, symbol, exchange):
        self.lookups.append((symbol, exchange))
        return self.contracts.get((symbol, exchange))

    def find_near_month_futures(self, base_symbol, exchange):
        return self.near_futures.get(((base_symbol or "").upper(), (exchange or "").upper()))

    def get_quotes(self, symbol, exchange, api_key=None, **kwargs):
        self.quote_calls.append((symbol, exchange))
        price = self.prices.get((symbol, exchange))
        if price is None:
            return False, {"status": "error", "message": f"No quote for {symbol}"}, 404
        return True, {"status": "success", "data": {"ltp": price}}, 200


@pytest.fixture
def market(monkeypatch):
    """Every segment listed, and the resolver's collaborators pointed at it."""
    fake = FakeMarket()

    # Equity cash.
    fake.list_cash("RELIANCE", "NSE", lotsize=1)
    fake.list_cash("SBIN", "NSE", lotsize=1)
    fake.list_cash("TATAMOTORS", "BSE", lotsize=1)
    fake.set_price("RELIANCE", "NSE", RELIANCE_LTP)

    # NFO index options and futures.
    fake.list_option_chain("NIFTY", "NFO", NIFTY_EXPIRIES, NIFTY_STRIKES, NIFTY_LOT)
    fake.list_futures("NIFTY", "NFO", NIFTY_FUTURE_EXPIRIES, NIFTY_LOT)
    fake.set_price("NIFTY", "NSE_INDEX", NIFTY_LTP)
    fake.list_option_chain("BANKNIFTY", "NFO", BANKNIFTY_EXPIRIES, BANKNIFTY_STRIKES, BANKNIFTY_LOT)
    fake.set_price("BANKNIFTY", "NSE_INDEX", BANKNIFTY_LTP)

    # BFO index options and futures.
    fake.list_option_chain("SENSEX", "BFO", SENSEX_EXPIRIES, SENSEX_STRIKES, SENSEX_LOT)
    fake.list_futures("SENSEX", "BFO", SENSEX_FUTURE_EXPIRIES, SENSEX_LOT)
    fake.set_price("SENSEX", "BSE_INDEX", SENSEX_LTP)

    # NFO stock options and futures.
    fake.list_option_chain("RELIANCE", "NFO", RELIANCE_EXPIRIES, RELIANCE_STRIKES, RELIANCE_LOT)
    fake.list_futures("RELIANCE", "NFO", RELIANCE_EXPIRIES, RELIANCE_LOT)
    fake.list_option_chain("VEDL", "NFO", VEDL_EXPIRIES, VEDL_STRIKES, VEDL_LOT)
    fake.set_price("VEDL", "NSE", VEDL_LTP)

    # MCX: the underlying is a FUT contract, and the two calendars differ.
    fake.list_option_chain(
        "CRUDEOIL", "MCX", CRUDEOIL_OPTION_EXPIRIES, CRUDEOIL_STRIKES, CRUDEOIL_LOT
    )
    fake.list_futures(
        "CRUDEOIL", "MCX", CRUDEOIL_FUTURE_EXPIRIES, CRUDEOIL_LOT, nearest="19-AUG-30"
    )
    fake.set_price("CRUDEOIL19AUG30FUT", "MCX", CRUDEOIL_LTP)

    # CDS currency, same shape as MCX.
    fake.list_option_chain("USDINR", "CDS", USDINR_OPTION_EXPIRIES, USDINR_STRIKES, USDINR_LOT)
    fake.list_futures("USDINR", "CDS", USDINR_FUTURE_EXPIRIES, USDINR_LOT, nearest="26-MAY-30")
    fake.set_price("USDINR26MAY30FUT", "CDS", USDINR_LTP)

    monkeypatch.setattr(expiry_service, "get_expiry_dates", fake.get_expiry_dates)
    monkeypatch.setattr(option_symbol_service, "get_available_strikes", fake.get_available_strikes)
    monkeypatch.setattr(
        option_symbol_service, "find_option_in_database", fake.find_option_in_database
    )
    monkeypatch.setattr(
        option_symbol_service, "find_near_month_futures", fake.find_near_month_futures
    )
    monkeypatch.setattr(quotes_service, "get_quotes", fake.get_quotes)
    return fake


# ---------------------------------------------------------------------------
# The master contract rows signal mode reads its lot sizes from
#
# symbol_resolver.lot_size_for queries database.symbol directly rather than
# going through the option service, so the fake market above cannot answer it.
# These rows are seeded into the test database instead, which is what makes the
# signal-mode quantity assertions real rather than a restatement of a mock.
# ---------------------------------------------------------------------------

_SEED_ROWS = [
    # (symbol, name, exchange, expiry, lotsize, instrumenttype)
    # The cash contracts FakeMarket lists, seeded for real so a signal cash leg
    # can be checked against the master contract the way a derivative one is.
    # Without rows on the venue, contract_exists takes its "master contract not
    # downloaded yet" path and answers True for anything.
    ("RELIANCE", "RELIANCE", "NSE", "", 1, "EQ"),
    ("SBIN", "SBIN", "NSE", "", 1, "EQ"),
    ("TATAMOTORS", "TATAMOTORS", "BSE", "", 1, "EQ"),
    ("NIFTY03JAN3023600CE", "NIFTY", "NFO", "03-JAN-30", NIFTY_LOT, "CE"),
    ("NIFTY31JAN30FUT", "NIFTY", "NFO", "31-JAN-30", NIFTY_LOT, "FUT"),
    ("BANKNIFTY31JAN3052000CE", "BANKNIFTY", "NFO", "31-JAN-30", BANKNIFTY_LOT, "CE"),
    ("SENSEX04JAN3078000CE", "SENSEX", "BFO", "04-JAN-30", SENSEX_LOT, "CE"),
    ("RELIANCE31JAN303000CE", "RELIANCE", "NFO", "31-JAN-30", RELIANCE_LOT, "CE"),
    ("CRUDEOIL16AUG306750CE", "CRUDEOIL", "MCX", "16-AUG-30", CRUDEOIL_LOT, "CE"),
    ("USDINR26MAY3088.25CE", "USDINR", "CDS", "26-MAY-30", USDINR_LOT, "CE"),
    # A broker master that puts a description in `name` rather than the base,
    # for a product whose base is a prefix of another one. The real family is
    # GOLD / GOLDM / GOLDPETAL; the names here are namespaced so this suite
    # cannot collide with rows another suite seeds into the shared test
    # database. There is deliberately no ZZGOLD contract at all.
    ("ZZGOLDM04JUN30FUT", "ZZ GOLD MINI JUN 2030", "MCX", "04-JUN-30", 10, "FUT"),
]


@pytest.fixture(scope="module", autouse=True)
def seed_master_contract():
    """Seed, then remove exactly what was seeded.

    The test database is shared with every other suite, so only rows this
    fixture actually inserted are deleted afterwards.
    """
    from database.symbol import SymToken, db_session, init_db

    init_db()
    inserted = []
    for symbol, name, exchange, expiry, lotsize, instrumenttype in _SEED_ROWS:
        if SymToken.query.filter_by(symbol=symbol, exchange=exchange).first() is not None:
            continue
        db_session.add(
            SymToken(
                symbol=symbol,
                brsymbol=symbol,
                name=name,
                exchange=exchange,
                brexchange=exchange,
                token=symbol,
                expiry=expiry,
                strike=-1.0,
                lotsize=lotsize,
                instrumenttype=instrumenttype,
                tick_size=0.05,
            )
        )
        inserted.append((symbol, exchange))
    db_session.commit()

    yield

    for symbol, exchange in inserted:
        SymToken.query.filter_by(symbol=symbol, exchange=exchange).delete()
    db_session.commit()
    db_session.remove()


# ---------------------------------------------------------------------------
# Store, engine and broker harness
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_slate():
    # This scoped_session is shared with every other suite in the run, so start
    # from a clean one: a sibling that deleted rows underneath it leaves stale
    # objects in the identity map here.
    store.db_session.remove()
    store.init_db()

    def purge():
        for row in store.list_strategies(USER):
            if row["current_run_id"]:
                state.clear_run_state(row["current_run_id"])
            store.set_strategy_status(row["id"], "stopped", None)
            store.delete_strategy(row["id"], USER)
        # Every registered run, not only this suite's. Run state is keyed by
        # run id, SQLite reuses a rowid after a delete, and a sibling suite
        # that left state behind therefore hands this one a run that is
        # already populated with somebody else's legs.
        for run_id in list(state.active_run_ids()):
            state.clear_run_state(run_id)
        store.clear_strategy_module_cache()

    purge()
    yield
    purge()


@pytest.fixture
def broker():
    """Records every order that would have reached a broker, and accepts them.

    Only the final call is replaced. The validator, the resolver, the store and
    the run state are all real.
    """
    placed = []

    def record(**kwargs):
        placed.append(kwargs["order"])
        return DispatchResult(ok=True, broker_order_id=f"QA-{len(placed)}", response={})

    with (
        patch("services.strategy_module.order_dispatch.dispatch_order", side_effect=record),
        patch("database.auth_db.get_api_key_for_tradingview", return_value="qa-api-key"),
        # The tick feed opens sockets and threads and has its own suite. Only
        # its interface matters here.
        patch("services.strategy_module.tick_feed.get_risk_tick_feed", return_value=MagicMock()),
    ):
        yield placed


_names = (f"QA segment strategy {n}" for n in range(1, 10_000))


def _config(underlying, underlying_exchange, legs, **overrides):
    config = {
        "name": next(_names),
        "underlying": underlying,
        "underlying_exchange": underlying_exchange,
        # No universe_tab on purpose. It is a grouping the wizard sets, and the
        # validator derives it from the legs when a caller does not, so pinning
        # one here would have every cash and commodity strategy in this file
        # claim to be an index one.
        "strategy_type": "positional",
        "legs": legs,
    }
    config.update(overrides)
    return config


def _make(config):
    """Validate exactly as the HTTP surface does, then store it."""
    validated, error = validate_strategy_config(config)
    assert error is None, error
    created, store_error = store.create_strategy(USER, validated)
    assert store_error is None, store_error
    return created["id"]


def _refused(config) -> str:
    """The message the API answers for a configuration it will not accept."""
    validated, error = validate_strategy_config(config)
    assert validated is None, "expected this configuration to be refused"
    return error


def _start(sid):
    return engine.start_run(sid, USER, "sandbox")


def _signal_strategy(legs, **overrides):
    overrides.setdefault("product", "MIS")
    sid = _make(
        _config("MULTI", "NSE", legs, strategy_kind="signal", direction="both", **overrides)
    )
    return store.get_strategy(sid, USER)


def _cash_leg(**overrides):
    """A batch cash leg. Its "lots" is a share count: cash lot size is 1."""
    leg = {"id": 1, "segment": "cash", "position": "B", "lots": 10}
    leg.update(overrides)
    return leg


def _option_leg(**overrides):
    leg = {
        "id": 1,
        "segment": "options",
        "position": "S",
        "lots": 1,
        "option_type": "CE",
        "strike_mode": "atm",
        "atm_offset": "ATM",
        "expiry": "monthly",
    }
    leg.update(overrides)
    return leg


def _leg_state(run_id, leg_id=1):
    live = state.get_run_state(run_id)
    assert live is not None, "the run has no live state"
    return live["legs"][str(leg_id)]


# ---------------------------------------------------------------------------
# The segment matrix, batch mode
# ---------------------------------------------------------------------------

#: (id, underlying, underlying exchange, leg, product, symbol, exchange, qty)
SEGMENTS = [
    (
        "nse_cash",
        "RELIANCE",
        "NSE",
        {"id": 1, "segment": "cash", "position": "B", "lots": 10},
        "CNC",
        "RELIANCE",
        "NSE",
        10,
    ),
    (
        "bse_cash",
        "TATAMOTORS",
        "BSE",
        {"id": 1, "segment": "cash", "position": "B", "lots": 5},
        "CNC",
        "TATAMOTORS",
        "BSE",
        5,
    ),
    (
        "nfo_index_option_weekly",
        "NIFTY",
        "NSE_INDEX",
        {
            "id": 1,
            "segment": "options",
            "position": "S",
            "lots": 2,
            "option_type": "CE",
            "expiry": "weekly",
        },
        "NRML",
        "NIFTY03JAN3023600CE",
        "NFO",
        2 * NIFTY_LOT,
    ),
    (
        "nfo_index_option_monthly",
        "NIFTY",
        "NSE_INDEX",
        {
            "id": 1,
            "segment": "options",
            "position": "B",
            "lots": 1,
            "option_type": "PE",
            "expiry": "monthly",
        },
        "NRML",
        "NIFTY31JAN3023600PE",
        "NFO",
        NIFTY_LOT,
    ),
    (
        "nfo_index_option_banknifty",
        "BANKNIFTY",
        "NSE_INDEX",
        {
            "id": 1,
            "segment": "options",
            "position": "S",
            "lots": 1,
            "option_type": "CE",
            "expiry": "monthly",
        },
        "MIS",
        "BANKNIFTY31JAN3052000CE",
        "NFO",
        BANKNIFTY_LOT,
    ),
    (
        "bfo_index_option",
        "SENSEX",
        "BSE_INDEX",
        {
            "id": 1,
            "segment": "options",
            "position": "S",
            "lots": 3,
            "option_type": "CE",
            "expiry": "weekly",
        },
        "NRML",
        "SENSEX04JAN3078000CE",
        "BFO",
        3 * SENSEX_LOT,
    ),
    (
        "nfo_stock_option",
        "RELIANCE",
        "NSE",
        {
            "id": 1,
            "segment": "options",
            "position": "S",
            "lots": 1,
            "option_type": "CE",
            "expiry": "monthly",
        },
        "NRML",
        "RELIANCE31JAN303000CE",
        "NFO",
        RELIANCE_LOT,
    ),
    (
        "nfo_stock_option_fractional_strike",
        "VEDL",
        "NSE",
        {
            "id": 1,
            "segment": "options",
            "position": "B",
            "lots": 1,
            "option_type": "CE",
            "expiry": "current",
        },
        "NRML",
        "VEDL25APR30292.5CE",
        "NFO",
        VEDL_LOT,
    ),
    (
        "nfo_stock_future",
        "RELIANCE",
        "NSE",
        {"id": 1, "segment": "futures", "position": "B", "lots": 2, "expiry": "current"},
        "NRML",
        "RELIANCE31JAN30FUT",
        "NFO",
        2 * RELIANCE_LOT,
    ),
    (
        "mcx_commodity_future",
        "CRUDEOIL",
        "MCX",
        {"id": 1, "segment": "futures", "position": "B", "lots": 3, "expiry": "current"},
        "NRML",
        "CRUDEOIL19AUG30FUT",
        "MCX",
        3 * CRUDEOIL_LOT,
    ),
    (
        "mcx_commodity_option",
        "CRUDEOIL",
        "MCX",
        {
            "id": 1,
            "segment": "options",
            "position": "S",
            "lots": 2,
            "option_type": "CE",
            "expiry": "current",
        },
        "NRML",
        "CRUDEOIL16AUG306750CE",
        "MCX",
        2 * CRUDEOIL_LOT,
    ),
    (
        "cds_currency_option",
        "USDINR",
        "CDS",
        {
            "id": 1,
            "segment": "options",
            "position": "S",
            "lots": 1,
            "option_type": "CE",
            "expiry": "current",
        },
        "NRML",
        "USDINR26MAY3088.25CE",
        "CDS",
        USDINR_LOT,
    ),
    (
        "cds_currency_future",
        "USDINR",
        "CDS",
        {"id": 1, "segment": "futures", "position": "B", "lots": 1, "expiry": "current"},
        "NRML",
        "USDINR26MAY30FUT",
        "CDS",
        USDINR_LOT,
    ),
]


@pytest.mark.parametrize(
    ("underlying", "underlying_exchange", "leg", "product", "symbol", "exchange", "quantity"),
    [case[1:] for case in SEGMENTS],
    ids=[case[0] for case in SEGMENTS],
)
def test_a_batch_leg_reaches_the_broker_correctly_for_its_segment(
    market, broker, underlying, underlying_exchange, leg, product, symbol, exchange, quantity
):
    """The whole chain for one segment: symbol, quantity, payload, row, state."""
    sid = _make(_config(underlying, underlying_exchange, [leg], product=product))

    result = _start(sid)

    assert result.ok is True, result.error

    # The contract.
    assert len(broker) == 1
    order = broker[0]
    assert order["symbol"] == symbol
    assert order["exchange"] == exchange

    # The quantity, which is the lot count times the lot size the master
    # contract carries, never an assumed one.
    assert order["quantity"] == str(quantity)

    # The payload.
    assert order["action"] == ("BUY" if leg["position"] == "B" else "SELL")
    assert order["product"] == product
    assert order["pricetype"] == "MARKET"
    assert order["price"] == "0"

    # The audit row.
    rows = store.list_orders(result.run_id)
    assert [row["kind"] for row in rows] == ["entry"]
    assert (rows[0]["symbol"], rows[0]["exchange"], rows[0]["qty"]) == (symbol, exchange, quantity)
    assert rows[0]["status"] == "open"

    # The run state, which is what every later exit and every risk rule reads.
    live = _leg_state(result.run_id)
    assert live["position"] == leg["position"]
    assert live["symbol"] == symbol
    assert live["exchange"] == exchange
    assert live["qty"] == quantity
    assert live["lots"] == leg["lots"]
    assert live["status"] == "open"


@pytest.mark.parametrize(
    ("exchange", "product"),
    [(case[6], case[4]) for case in SEGMENTS],
    ids=[case[0] for case in SEGMENTS],
)
def test_each_segment_in_the_matrix_uses_a_product_its_exchange_accepts(exchange, product):
    """The matrix itself must not smuggle an illegal product past the module.

    CNC is equity only and NRML is for derivatives, the same split
    blueprints/scalping.py enforces per exchange.
    """
    assert product in legal_products(exchange)


# ---------------------------------------------------------------------------
# Equity cash
# ---------------------------------------------------------------------------


def test_a_cash_leg_quantity_is_the_lot_count_times_the_equity_rows_lot_size(market, broker):
    """Cash is counted in "lots" too, and an equity row carries a lot size of 1.

    Pinned because the multiplication is unconditional: nothing checks that a
    cash contract's lot size is 1, so a broker master that fills the equity row
    with the F&O lot size would multiply every cash order by it.
    """
    market.list_cash("RELIANCE", "NSE", lotsize=1)
    sid = _make(
        _config(
            "RELIANCE",
            "NSE",
            [{"id": 1, "segment": "cash", "position": "B", "lots": 7}],
            product="CNC",
        )
    )

    result = _start(sid)

    assert result.ok is True, result.error
    assert broker[0]["quantity"] == "7"


def test_a_cash_leg_on_an_index_underlying_is_refused_before_anything_is_claimed(market, broker):
    """An index has no cash instrument of its own and cannot be traded."""
    sid = _make(
        _config(
            "NIFTY",
            "NSE_INDEX",
            [{"id": 1, "segment": "cash", "position": "B", "lots": 1}],
            product="CNC",
        )
    )

    result = _start(sid)

    assert result.ok is False
    assert "No cash contract found for NIFTY on NSE" in result.error
    assert not broker
    assert store.list_runs(sid) == []
    assert store.get_strategy(sid, USER).status == "stopped"


def test_a_cash_leg_carries_no_expiry_into_the_run_row(market, broker):
    sid = _make(
        _config(
            "RELIANCE",
            "NSE",
            [{"id": 1, "segment": "cash", "position": "B", "lots": 1}],
            product="CNC",
        )
    )

    result = _start(sid)

    assert store.list_runs(sid)[0]["resolved_expiries"] == {}
    assert _leg_state(result.run_id)["symbol"] == "RELIANCE"


def test_a_cash_leg_refuses_an_expiry(market):
    message = _refused(
        _config(
            "RELIANCE",
            "NSE",
            [{"id": 1, "segment": "cash", "position": "B", "lots": 1, "expiry": "weekly"}],
            product="CNC",
        )
    )
    assert "expiry is not valid on a cash leg" in message


def test_a_cash_leg_can_express_an_ordinary_equity_quantity(market):
    """100 shares of SBIN is an ordinary order and the module cannot express it.

    A batch leg's only quantity field is `lots`, validated at
    blueprints/strategy_module.py:534-537 with maximum=MAX_LOTS (50), and a
    cash contract's lot size is 1, so the largest cash order a batch strategy
    can place is 50 shares. Signal mode counts cash in units up to 1,000,000.
    """
    config = _config(
        "SBIN",
        "NSE",
        [{"id": 1, "segment": "cash", "position": "B", "lots": 100}],
        product="CNC",
    )
    validated, error = validate_strategy_config(config)
    assert error is None, error
    assert validated["legs"][0]["lots"] == 100


# ---------------------------------------------------------------------------
# Index options: NFO against BFO
# ---------------------------------------------------------------------------


def test_bfo_and_nfo_take_different_index_families_and_different_lot_sizes(market, broker):
    """One lot of SENSEX is 20 and one lot of NIFTY is 65, on different venues."""
    nifty = _make(
        _config(
            "NIFTY",
            "NSE_INDEX",
            [
                {
                    "id": 1,
                    "segment": "options",
                    "position": "S",
                    "lots": 1,
                    "option_type": "CE",
                    "expiry": "weekly",
                }
            ],
        )
    )
    sensex = _make(
        _config(
            "SENSEX",
            "BSE_INDEX",
            [
                {
                    "id": 1,
                    "segment": "options",
                    "position": "S",
                    "lots": 1,
                    "option_type": "CE",
                    "expiry": "weekly",
                }
            ],
        )
    )

    assert _start(nifty).ok is True
    assert _start(sensex).ok is True

    assert [(o["exchange"], o["quantity"]) for o in broker] == [("NFO", "65"), ("BFO", "20")]


def test_a_bse_index_named_on_the_nse_side_is_refused_rather_than_traded(market, broker):
    """SENSEX has no NFO chain. The lookup must refuse rather than invent one."""
    sid = _make(
        _config(
            "SENSEX",
            "NSE_INDEX",
            [
                {
                    "id": 1,
                    "segment": "options",
                    "position": "S",
                    "lots": 1,
                    "option_type": "CE",
                    "expiry": "weekly",
                }
            ],
        )
    )

    result = _start(sid)

    assert result.ok is False
    assert not broker
    assert store.list_runs(sid) == []


def test_both_legs_of_a_basket_are_priced_off_one_quote(market, broker):
    """Two legs quoted separately can settle around different ATM strikes."""
    sid = _make(
        _config(
            "NIFTY",
            "NSE_INDEX",
            [
                {
                    "id": 1,
                    "segment": "options",
                    "position": "S",
                    "lots": 1,
                    "option_type": "CE",
                    "expiry": "weekly",
                },
                {
                    "id": 2,
                    "segment": "options",
                    "position": "S",
                    "lots": 1,
                    "option_type": "PE",
                    "expiry": "weekly",
                },
            ],
        )
    )

    result = _start(sid)

    assert result.ok is True, result.error
    assert market.quote_calls == [("NIFTY", "NSE_INDEX")]
    assert sorted(o["symbol"] for o in broker) == [
        "NIFTY03JAN3023600CE",
        "NIFTY03JAN3023600PE",
    ]


def test_an_offset_leg_names_the_strike_the_chain_actually_lists(market, broker):
    """ITM and OTM run in opposite directions for a call and a put."""
    sid = _make(
        _config(
            "NIFTY",
            "NSE_INDEX",
            [
                {
                    "id": 1,
                    "segment": "options",
                    "position": "B",
                    "lots": 1,
                    "option_type": "CE",
                    "strike_mode": "atm",
                    "atm_offset": "OTM2",
                    "expiry": "weekly",
                },
                {
                    "id": 2,
                    "segment": "options",
                    "position": "B",
                    "lots": 1,
                    "option_type": "PE",
                    "strike_mode": "atm",
                    "atm_offset": "OTM2",
                    "expiry": "weekly",
                },
            ],
        )
    )

    assert _start(sid).ok is True
    symbols = sorted(o["symbol"] for o in broker)
    assert symbols == ["NIFTY03JAN3023500PE", "NIFTY03JAN3023700CE"]


# ---------------------------------------------------------------------------
# Stock options, including the fractional strike
# ---------------------------------------------------------------------------


def test_a_fractional_strike_survives_into_the_symbol_and_the_order(market, broker):
    """VEDL25APR24292.5CE is a real contract. Rounding names a different one."""
    sid = _make(
        _config(
            "VEDL",
            "NSE",
            [
                {
                    "id": 1,
                    "segment": "options",
                    "position": "B",
                    "lots": 1,
                    "option_type": "CE",
                    "expiry": "current",
                }
            ],
        )
    )

    result = _start(sid)

    assert result.ok is True, result.error
    assert broker[0]["symbol"] == "VEDL25APR30292.5CE"
    assert "292.5" in store.list_orders(result.run_id)[0]["symbol"]
    assert _leg_state(result.run_id)["symbol"].endswith("292.5CE")


def test_a_fractional_strike_named_outright_is_not_rounded(market, broker):
    sid = _make(
        _config(
            "VEDL",
            "NSE",
            [
                {
                    "id": 1,
                    "segment": "options",
                    "position": "B",
                    "lots": 1,
                    "option_type": "PE",
                    "strike_mode": "strike",
                    "strike": 292.5,
                    "expiry": "current",
                }
            ],
        )
    )

    assert _start(sid).ok is True
    assert broker[0]["symbol"] == "VEDL25APR30292.5PE"


def test_a_whole_strike_on_a_fractional_ladder_carries_no_trailing_zero(market, broker):
    sid = _make(
        _config(
            "VEDL",
            "NSE",
            [
                {
                    "id": 1,
                    "segment": "options",
                    "position": "B",
                    "lots": 1,
                    "option_type": "CE",
                    "strike_mode": "atm",
                    "atm_offset": "OTM1",
                    "expiry": "current",
                }
            ],
        )
    )

    assert _start(sid).ok is True
    assert broker[0]["symbol"] == "VEDL25APR30295CE"


def test_a_lot_size_that_is_not_a_round_number_is_multiplied_exactly(market, broker):
    """VEDL trades in lots of 1150. Three lots is 3450, not a rounded 3500."""
    sid = _make(
        _config(
            "VEDL",
            "NSE",
            [
                {
                    "id": 1,
                    "segment": "options",
                    "position": "B",
                    "lots": 3,
                    "option_type": "CE",
                    "expiry": "current",
                }
            ],
        )
    )

    assert _start(sid).ok is True
    assert broker[0]["quantity"] == str(3 * VEDL_LOT)


def test_a_stock_option_leg_asking_for_weekly_gets_the_nearest_monthly(market, broker):
    """Stock options are monthly only, and the ranks are positional."""
    sid = _make(
        _config(
            "RELIANCE",
            "NSE",
            [
                {
                    "id": 1,
                    "segment": "options",
                    "position": "S",
                    "lots": 1,
                    "option_type": "CE",
                    "expiry": "weekly",
                }
            ],
        )
    )

    assert _start(sid).ok is True
    assert broker[0]["symbol"] == "RELIANCE31JAN303000CE"


def test_a_stale_lot_size_is_refused_rather_than_treated_as_one(market, broker):
    """A silent 1 would send an order 500 times too small."""
    market.list_contract("RELIANCE31JAN303000CE", "NFO", lotsize=0)
    sid = _make(
        _config(
            "RELIANCE",
            "NSE",
            [
                {
                    "id": 1,
                    "segment": "options",
                    "position": "S",
                    "lots": 1,
                    "option_type": "CE",
                    "expiry": "monthly",
                }
            ],
        )
    )

    result = _start(sid)

    assert result.ok is False
    assert "lot size" in result.error
    assert not broker
    assert store.list_runs(sid) == []


# ---------------------------------------------------------------------------
# MCX: the underlying is a future, and the calendars do not line up
# ---------------------------------------------------------------------------


def test_an_mcx_option_leg_prices_off_the_nearest_unexpired_future(market, broker):
    """MCX lists CRUDEOIL19AUG30FUT and no plain CRUDEOIL to quote at all."""
    sid = _make(
        _config(
            "CRUDEOIL",
            "MCX",
            [
                {
                    "id": 1,
                    "segment": "options",
                    "position": "S",
                    "lots": 1,
                    "option_type": "CE",
                    "expiry": "current",
                }
            ],
        )
    )

    result = _start(sid)

    assert result.ok is True, result.error
    assert market.quote_calls == [("CRUDEOIL19AUG30FUT", "MCX")]
    assert ("CRUDEOIL", "MCX") not in market.quote_calls
    assert broker[0]["symbol"] == "CRUDEOIL16AUG306750CE"


def test_an_mcx_option_uses_the_options_calendar_not_the_futures_one(market, broker):
    """The quote comes off the 19th; the contract expires on the 16th."""
    sid = _make(
        _config(
            "CRUDEOIL",
            "MCX",
            [
                {
                    "id": 1,
                    "segment": "options",
                    "position": "S",
                    "lots": 1,
                    "option_type": "CE",
                    "expiry": "current",
                },
                {"id": 2, "segment": "futures", "position": "B", "lots": 1, "expiry": "current"},
            ],
        )
    )

    result = _start(sid)

    assert result.ok is True, result.error
    assert ("CRUDEOIL", "MCX", "options") in market.expiry_calls
    assert ("CRUDEOIL", "MCX", "futures") in market.expiry_calls
    assert store.list_runs(sid)[0]["resolved_expiries"] == {"1": "16-AUG-30", "2": "19-AUG-30"}


def test_lots_still_mean_lots_on_mcx_where_the_lot_size_is_one(market, broker):
    """CRUDEOIL has a lot size of 1, so three lots is a quantity of three."""
    sid = _make(
        _config(
            "CRUDEOIL",
            "MCX",
            [
                {
                    "id": 1,
                    "segment": "options",
                    "position": "S",
                    "lots": 3,
                    "option_type": "PE",
                    "expiry": "current",
                }
            ],
        )
    )

    result = _start(sid)

    assert result.ok is True, result.error
    assert broker[0]["quantity"] == "3"
    assert _leg_state(result.run_id)["lots"] == 3
    assert _leg_state(result.run_id)["qty"] == 3


def test_a_commodity_with_no_unexpired_future_cannot_price_its_options(market, broker):
    """Refusing is right: there is no reference price for the ATM strike."""
    market.near_futures.pop(("CRUDEOIL", "MCX"))
    sid = _make(
        _config(
            "CRUDEOIL",
            "MCX",
            [
                {
                    "id": 1,
                    "segment": "options",
                    "position": "S",
                    "lots": 1,
                    "option_type": "CE",
                    "expiry": "current",
                }
            ],
        )
    )

    result = _start(sid)

    assert result.ok is False
    assert "CRUDEOIL" in result.error
    assert not broker
    assert store.list_runs(sid) == []


# ---------------------------------------------------------------------------
# Currency: CDS is claimed by UNDERLYING_EXCHANGES, so it is covered
# ---------------------------------------------------------------------------


def test_a_cds_option_leg_prices_off_its_own_future_and_keeps_a_quarter_strike(market, broker):
    sid = _make(
        _config(
            "USDINR",
            "CDS",
            [
                {
                    "id": 1,
                    "segment": "options",
                    "position": "S",
                    "lots": 2,
                    "option_type": "CE",
                    "expiry": "current",
                }
            ],
        )
    )

    result = _start(sid)

    assert result.ok is True, result.error
    assert market.quote_calls == [("USDINR26MAY30FUT", "CDS")]
    assert broker[0]["symbol"] == "USDINR26MAY3088.25CE"
    assert broker[0]["exchange"] == "CDS"
    assert broker[0]["quantity"] == str(2 * USDINR_LOT)


def test_a_cds_cash_leg_is_refused_in_plain_words(market, broker):
    """There is no cash instrument on the currency segment."""
    sid = _make(
        _config(
            "USDINR",
            "CDS",
            [{"id": 1, "segment": "cash", "position": "B", "lots": 1}],
            product="MIS",
        )
    )

    result = _start(sid)

    assert result.ok is False
    assert "No cash contract found for USDINR on CDS" in result.error
    assert not broker


# ---------------------------------------------------------------------------
# Expiry ranks
# ---------------------------------------------------------------------------


def test_the_monthly_rank_skips_a_month_whose_monthly_has_already_gone(market, broker):
    """Mid-February, January's monthly is behind us and February's is next."""
    market.list_option_chain(
        "NIFTY",
        "NFO",
        ["14-FEB-30", "21-FEB-30", "28-FEB-30", "07-MAR-30", "28-MAR-30"],
        NIFTY_STRIKES,
        NIFTY_LOT,
    )

    sid = _make(
        _config(
            "NIFTY",
            "NSE_INDEX",
            [
                {
                    "id": 1,
                    "segment": "options",
                    "position": "S",
                    "lots": 1,
                    "option_type": "CE",
                    "expiry": "monthly",
                },
                {
                    "id": 2,
                    "segment": "options",
                    "position": "B",
                    "lots": 1,
                    "option_type": "CE",
                    "expiry": "next_month",
                },
            ],
        )
    )

    result = _start(sid)

    assert result.ok is True, result.error
    assert store.list_runs(sid)[0]["resolved_expiries"] == {"1": "28-FEB-30", "2": "28-MAR-30"}
    assert sorted(o["symbol"] for o in broker) == [
        "NIFTY28FEB3023600CE",
        "NIFTY28MAR3023600CE",
    ]


def test_a_monthly_only_underlying_answers_every_rank_from_its_own_calendar(market, broker):
    """RELIANCE lists no weeklies, so weekly and monthly are the same contract."""
    weekly = resolve_leg(
        {"segment": "options", "option_type": "CE", "expiry": "weekly", "lots": 1},
        "RELIANCE",
        "NSE",
    )
    monthly = resolve_leg(
        {"segment": "options", "option_type": "CE", "expiry": "monthly", "lots": 1},
        "RELIANCE",
        "NSE",
    )
    next_week = resolve_leg(
        {"segment": "options", "option_type": "CE", "expiry": "next_week", "lots": 1},
        "RELIANCE",
        "NSE",
    )

    assert weekly.symbol == monthly.symbol == "RELIANCE31JAN303000CE"
    # Positional, by design: "next" means the next listed expiry, which on a
    # monthly-only underlying is a month away rather than a week.
    assert next_week.symbol == "RELIANCE28FEB303000CE"
    assert next_week.detail["expiry_fallback"] is False


def test_the_resolver_reports_that_a_rank_fell_back_to_the_only_expiry(market):
    """A single listed expiry answers next_week, and says that it did."""
    market.expiries[("NIFTY", "NFO", "options")] = ["31-JAN-30"]

    leg = resolve_leg(
        {"segment": "options", "option_type": "CE", "expiry": "next_week", "lots": 1},
        "NIFTY",
        "NSE_INDEX",
    )

    assert leg.ok, leg.error
    assert leg.symbol == "NIFTY31JAN3023600CE"
    assert leg.detail["expiry_fallback"] is True


def test_a_run_records_that_an_expiry_rank_fell_back(market, broker):
    """next_week silently becomes the current week and nothing says so.

    symbol_resolver.ExpiryResult.fallback exists so a caller "can say so", and
    _resolve_options_leg puts it in detail["expiry_fallback"]. engine.py's
    _resolve_all_legs keeps only leg_id, position, symbol, exchange, lots,
    quantity, expiry and the risk fields, so the flag is discarded and the
    operator sees a leg on an expiry they did not ask for with no explanation.
    """
    market.expiries[("NIFTY", "NFO", "options")] = ["31-JAN-30"]
    sid = _make(
        _config(
            "NIFTY",
            "NSE_INDEX",
            [
                {
                    "id": 1,
                    "segment": "options",
                    "position": "S",
                    "lots": 1,
                    "option_type": "CE",
                    "expiry": "next_week",
                }
            ],
        )
    )

    result = _start(sid)
    assert result.ok is True, result.error

    trail = (
        str(store.list_events(sid))
        + str(store.list_runs(sid))
        + str(state.get_run_state(result.run_id))
    )
    assert "fallback" in trail.lower()


def test_the_run_row_records_the_expiry_each_leg_resolved_to(market, broker):
    """The database spelling, so it can be used as a query filter later."""
    sid = _make(
        _config(
            "NIFTY",
            "NSE_INDEX",
            [
                {
                    "id": 1,
                    "segment": "options",
                    "position": "S",
                    "lots": 1,
                    "option_type": "CE",
                    "expiry": "weekly",
                },
                {
                    "id": 2,
                    "segment": "options",
                    "position": "B",
                    "lots": 1,
                    "option_type": "CE",
                    "expiry": "next_week",
                },
            ],
        )
    )

    _start(sid)

    assert store.list_runs(sid)[0]["resolved_expiries"] == {"1": "03-JAN-30", "2": "10-JAN-30"}


# ---------------------------------------------------------------------------
# Product rules
# ---------------------------------------------------------------------------


def test_a_derivative_leg_is_never_sent_cnc(market, broker):
    """CNC is equity only. An index option is never CNC.

    blueprints/strategy_module.py:780 validates product against
    ("CNC", "NRML", "MIS") and stops there; engine.py:412 passes
    strategy["product"] to every leg whatever its exchange. Nothing downstream
    refuses it either: restx_api/account_schema.py only checks the value is one
    of the three, and the sandbox does not check the pairing at all, so the
    order reaches the live broker as CNC on NFO.
    """
    sid = _make(
        _config(
            "NIFTY",
            "NSE_INDEX",
            [
                {
                    "id": 1,
                    "segment": "options",
                    "position": "S",
                    "lots": 1,
                    "option_type": "CE",
                    "expiry": "weekly",
                }
            ],
            product="CNC",
        )
    )

    result = _start(sid)

    assert result.ok is True, result.error
    assert broker[0]["product"] in legal_products(broker[0]["exchange"])


def test_a_cash_only_strategy_defaults_to_a_product_equity_accepts(market, broker):
    """A strategy that names no product gets NRML, and cash takes CNC or MIS."""
    sid = _make(
        _config("RELIANCE", "NSE", [{"id": 1, "segment": "cash", "position": "B", "lots": 1}])
    )

    result = _start(sid)

    assert result.ok is True, result.error
    assert broker[0]["exchange"] == "NSE"
    assert broker[0]["product"] in legal_products("NSE")


def test_a_basket_mixing_cash_and_options_can_be_given_a_legal_product(market, broker):
    """A covered call is cash plus an option, and the two take different products.

    The leg vocabulary (blueprints/strategy_module.py:LEG_FIELDS) has no
    per-leg product, so whichever of the three is chosen, one leg of this
    strategy is sent a product its exchange refuses.
    """
    legs = [
        {"id": 1, "segment": "cash", "position": "B", "lots": 1},
        {
            "id": 2,
            "segment": "options",
            "position": "S",
            "lots": 1,
            "option_type": "CE",
            "expiry": "monthly",
        },
    ]
    sid = _make(_config("RELIANCE", "NSE", legs, product="CNC"))

    result = _start(sid)

    assert result.ok is True, result.error
    for order in broker:
        assert order["product"] in legal_products(order["exchange"]), order


def test_the_order_row_records_the_product_that_was_sent(market, broker):
    """The orders table is described as audit grade and omits the product.

    database/strategy_module_db.py:SmStrategyOrder stores symbol, exchange,
    action, qty, pricetype, price and trigger_price. With F4 above, an order
    placed with an illegal product leaves no record of which product it was.
    """
    sid = _make(
        _config(
            "NIFTY",
            "NSE_INDEX",
            [
                {
                    "id": 1,
                    "segment": "options",
                    "position": "S",
                    "lots": 1,
                    "option_type": "CE",
                    "expiry": "weekly",
                }
            ],
            product="NRML",
        )
    )

    result = _start(sid)

    assert store.list_orders(result.run_id)[0]["product"] == "NRML"


# ---------------------------------------------------------------------------
# Price type
# ---------------------------------------------------------------------------


def test_an_exit_is_always_market_whatever_the_entry_price_type(market, broker):
    """A limit exit that does not fill is not an exit."""
    sid = _make(
        _config(
            "NIFTY",
            "NSE_INDEX",
            [
                {
                    "id": 1,
                    "segment": "options",
                    "position": "S",
                    "lots": 1,
                    "option_type": "CE",
                    "expiry": "weekly",
                }
            ],
        )
    )
    run_id = _start(sid).run_id
    engine.apply_fill(run_id, 1, 100.0, is_entry=True)

    engine.stop_run(run_id, USER, reason="manual")

    assert broker[-1]["pricetype"] == "MARKET"
    assert broker[-1]["action"] == "BUY"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "NOT BUILT: a limit entry needs a price, and neither the strategy "
        "configuration nor a leg carries one. PRICETYPES is now MARKET only, "
        "so the defect this was written for, a limit order priced at zero, "
        "cannot happen; the capability is what is missing. Adding a price to "
        "the configuration is what turns this green"
    ),
)
def test_a_limit_strategy_carries_a_limit_price(market, broker):
    """LIMIT was offered by the validator with nothing to fill it with.

    blueprints/strategy_module.py:781 accepts PRICETYPES =
    ("MARKET", "LIMIT", "SL", "SL-M"), but neither CONFIG_FIELDS nor LEG_FIELDS
    carries a price, and engine.py:405-413 calls build_order without price or
    trigger_price, so both default to 0. Every entry of a LIMIT strategy is a
    limit order at zero.
    """
    sid = _make(
        _config(
            "NIFTY",
            "NSE_INDEX",
            [
                {
                    "id": 1,
                    "segment": "options",
                    "position": "S",
                    "lots": 1,
                    "option_type": "CE",
                    "expiry": "weekly",
                }
            ],
            pricetype="LIMIT",
        )
    )

    result = _start(sid)

    assert result.ok is True, result.error
    assert broker[0]["pricetype"] == "LIMIT"
    assert float(broker[0]["price"]) > 0, "a limit order at zero cannot be filled"


# ---------------------------------------------------------------------------
# Lot sizes, read from the master contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("symbol", "exchange", "expected"),
    [
        ("NIFTY", "NFO", NIFTY_LOT),
        ("BANKNIFTY", "NFO", BANKNIFTY_LOT),
        ("SENSEX", "BFO", SENSEX_LOT),
        ("RELIANCE", "NFO", RELIANCE_LOT),
        ("CRUDEOIL", "MCX", CRUDEOIL_LOT),
        ("USDINR", "CDS", USDINR_LOT),
        ("NIFTY03JAN3023600CE", "NFO", NIFTY_LOT),
        ("USDINR26MAY3088.25CE", "CDS", USDINR_LOT),
    ],
)
def test_a_lot_size_is_read_per_underlying_and_per_exchange(symbol, exchange, expected):
    assert lot_size_for(symbol, exchange) == expected


@pytest.mark.parametrize("exchange", ["NSE", "BSE"])
def test_cash_exchanges_have_no_lot_size_to_report(exchange):
    """None means "cannot say", and for cash it means "counted in units"."""
    assert lot_size_for("RELIANCE", exchange) is None


def test_an_unlisted_base_cannot_borrow_a_sibling_products_lot_size():
    """ZZGOLD has no contract. The answer must be None, not ZZGOLDM's 10.

    symbol_resolver.py:276 falls back to SymToken.symbol.like(f"{root}%") when
    the name column does not match, which it does not on the brokers whose
    master contract puts a description in `name` - the very case the fallback
    exists for. option_symbol_service.find_near_month_futures anchors the same
    kind of lookup with a regex, and says why: GOLD, GOLDM, GOLDGUINEA,
    GOLDPETAL and GOLDTEN are different contracts in different sizes. Here the
    unanchored match makes lot_size_for answer 10 for a product it has never
    seen, and signals._resolve_signal_leg multiplies the user's lot count by it.
    """
    assert lot_size_for("ZZGOLD", "MCX") is None


def test_lots_mode_refuses_rather_than_fabricating_an_unknown_lot_size():
    quantity, _lot_size, error = resolve_quantity(5, "lots", "NOSUCHTHING", "NFO")

    assert quantity is None
    assert "lot size" in error


def test_units_mode_on_a_derivative_must_land_on_a_lot_boundary():
    quantity, lot_size, error = resolve_quantity(60, "units", "SENSEX", "BFO")
    assert (quantity, lot_size, error) == (60, SENSEX_LOT, None)

    quantity, lot_size, error = resolve_quantity(25, "units", "SENSEX", "BFO")
    assert quantity is None
    assert "whole number of lots" in error


def test_units_mode_on_cash_passes_the_quantity_through():
    assert resolve_quantity(137, "units", "RELIANCE", "NSE") == (137, None, None)


def test_lots_and_units_agree_on_mcx_where_the_lot_size_is_one():
    assert resolve_quantity(3, "lots", "CRUDEOIL", "MCX") == (3, 1, None)
    assert resolve_quantity(3, "units", "CRUDEOIL", "MCX") == (3, 1, None)


# ---------------------------------------------------------------------------
# Signal mode, across the same segments
# ---------------------------------------------------------------------------


def test_a_signal_cash_leg_places_the_quantity_as_written(market, broker):
    strategy = _signal_strategy(
        [{"id": 1, "symbol": "RELIANCE", "exchange": "NSE", "qty": 137, "segment": "cash"}]
    )

    result = signals.handle_signal(strategy, "long_entry", leg_id=1)

    assert result.ok is True, result.error
    assert broker[0]["symbol"] == "RELIANCE"
    assert broker[0]["exchange"] == "NSE"
    assert broker[0]["quantity"] == "137"
    assert broker[0]["action"] == "BUY"
    assert broker[0]["product"] == "MIS"

    run_id = store.get_strategy(strategy.id, USER).current_run_id
    assert _leg_state(run_id)["position"] == "B"
    assert _leg_state(run_id)["qty"] == 137
    assert [o["kind"] for o in store.list_orders(run_id)] == ["entry"]


@pytest.mark.parametrize(
    ("symbol", "exchange", "lots", "lot_size"),
    [
        ("NIFTY03JAN3023600CE", "NFO", 5, NIFTY_LOT),
        ("BANKNIFTY31JAN3052000CE", "NFO", 2, BANKNIFTY_LOT),
        ("SENSEX04JAN3078000CE", "BFO", 3, SENSEX_LOT),
        ("RELIANCE31JAN303000CE", "NFO", 1, RELIANCE_LOT),
        ("CRUDEOIL16AUG306750CE", "MCX", 4, CRUDEOIL_LOT),
        ("USDINR26MAY3088.25CE", "CDS", 2, USDINR_LOT),
    ],
)
def test_a_signal_leg_in_lots_multiplies_by_the_master_contract_lot_size(
    market, broker, symbol, exchange, lots, lot_size
):
    """Five lots of NIFTY is 325 because the master contract says 65."""
    strategy = _signal_strategy(
        [
            {
                "id": 1,
                "symbol": symbol,
                "exchange": exchange,
                "qty": lots,
                "qty_mode": "lots",
                "segment": "futures",
                "expiry": "current",
            }
        ]
    )

    result = signals.handle_signal(strategy, "short_entry", leg_id=1)

    assert result.ok is True, result.error
    assert broker[0]["symbol"] == symbol
    assert broker[0]["exchange"] == exchange
    assert broker[0]["quantity"] == str(lots * lot_size)
    assert broker[0]["action"] == "SELL"

    run_id = store.get_strategy(strategy.id, USER).current_run_id
    leg = _leg_state(run_id)
    assert leg["position"] == "S"
    assert leg["lots"] == lots
    assert leg["qty"] == lots * lot_size


def test_a_signal_leg_in_lots_is_refused_on_a_cash_exchange():
    """Cash has no lot size, so a lot count means nothing there."""
    message = _refused(
        _config(
            "MULTI",
            "NSE",
            [
                {
                    "id": 1,
                    "symbol": "RELIANCE",
                    "exchange": "NSE",
                    "qty": 5,
                    "qty_mode": "lots",
                    "segment": "cash",
                }
            ],
            strategy_kind="signal",
            product="MIS",
        )
    )
    assert "no lot size" in message


def test_a_signal_leg_in_units_must_land_on_a_lot_boundary():
    """The broker would refuse 25 SENSEX rather than round it."""
    message = _refused(
        _config(
            "MULTI",
            "NSE",
            [
                {
                    "id": 1,
                    "symbol": "SENSEX04JAN3078000CE",
                    "exchange": "BFO",
                    "qty": 25,
                    "qty_mode": "units",
                    "segment": "futures",
                }
            ],
            strategy_kind="signal",
            product="MIS",
        )
    )
    assert "whole number of lots" in message


def test_a_signal_leg_in_units_on_a_lot_boundary_is_accepted(market, broker):
    strategy = _signal_strategy(
        [
            {
                "id": 1,
                "symbol": "SENSEX04JAN3078000CE",
                "exchange": "BFO",
                "qty": 60,
                "qty_mode": "units",
                "segment": "futures",
            }
        ]
    )

    result = signals.handle_signal(strategy, "long_entry", leg_id=1)

    assert result.ok is True, result.error
    assert broker[0]["quantity"] == "60"


def test_a_signal_exit_covers_the_side_actually_held_on_a_derivative(market, broker):
    strategy = _signal_strategy(
        [
            {
                "id": 1,
                "symbol": "CRUDEOIL16AUG306750CE",
                "exchange": "MCX",
                "qty": 2,
                "qty_mode": "lots",
                "segment": "futures",
            }
        ]
    )
    signals.handle_signal(strategy, "short_entry", leg_id=1)
    # An exit closes a confirmed quantity, so the entry has to have filled.
    engine.apply_fill(store.get_strategy(strategy.id, USER).current_run_id, 1, 100.0, is_entry=True)

    result = signals.handle_signal(strategy, "short_exit", leg_id=1)

    assert result.ok is True, result.error
    assert [o["action"] for o in broker] == ["SELL", "BUY"]
    run_id = store.get_strategy(strategy.id, USER).current_run_id
    assert {o["kind"] for o in store.list_orders(run_id)} == {"entry", "exit_signal"}


def test_signal_mode_has_no_options_segment_to_declare():
    """Multi-leg option spreads stay in batch mode, and the validator says so.

    A signal leg names its instrument literally, so an option contract can
    still be traded by typing its symbol; what cannot be declared is the
    segment, which means no expiry rank and no strike are ever resolved for it.
    """
    message = _refused(
        _config(
            "MULTI",
            "NSE",
            [
                {
                    "id": 1,
                    "symbol": "NIFTY03JAN3023600CE",
                    "exchange": "NFO",
                    "qty": 1,
                    "qty_mode": "lots",
                    "segment": "options",
                }
            ],
            strategy_kind="signal",
            product="MIS",
        )
    )
    assert "segment must be one of: cash, futures" in message


def test_a_signal_futures_leg_named_as_a_base_symbol_places_nothing(market, broker):
    """NIFTY on NFO is not a tradable contract; NIFTY31JAN30FUT is.

    A signal leg names its own instrument, so nothing resolves it from an
    underlying and a rank. That used to mean the symbol went to the broker
    verbatim, with a quantity that looked entirely plausible because
    lot_size_for matches the base against the NIFTY contracts. Batch mode
    refused the same leg with contract_not_found; signal mode placed it.

    The refusal is now the answer, and it names what to do instead. Resolving
    the rank into a contract would be a nicer answer and is not what this
    guards: what it guards is that no order is ever placed for a symbol the
    master contract does not list.
    """
    strategy = _signal_strategy(
        [
            {
                "id": 1,
                "symbol": "NIFTY",
                "exchange": "NFO",
                "qty": 5,
                "qty_mode": "lots",
                "segment": "futures",
                "expiry": "current",
            }
        ]
    )

    result = signals.handle_signal(strategy, "long_entry", leg_id=1)

    assert result.ok is False
    assert "not a contract on NFO" in result.error
    assert broker == [], "nothing reached the broker"


def test_a_signal_leg_exchange_is_checked_against_the_known_exchanges():
    """A batch strategy's exchange is checked against a list; a signal leg's is not.

    blueprints/strategy_module.py:444-447 takes the exchange through _text()
    with no membership check, while underlying_exchange goes through _choice()
    against UNDERLYING_EXCHANGES. With F9 above there is no later lookup to
    catch it either.
    """
    message = _refused(
        _config(
            "MULTI",
            "NSE",
            [{"id": 1, "symbol": "RELIANCE", "exchange": "NSEE", "qty": 1, "segment": "cash"}],
            strategy_kind="signal",
            product="MIS",
        )
    )
    assert "exchange" in message


# ---------------------------------------------------------------------------
# Signal mode: the flip, and what happens to the position it opens
# ---------------------------------------------------------------------------


def test_a_flip_keeps_track_of_the_exit_it_just_placed(market, broker):
    """The exit of the old position is still working when the new one opens.

    signals._enter squares the held side with _exit(), which claims the leg and
    records exit_kind and exit_order_id on it, and then calls state.add_leg with
    the new side. add_leg used to assign a fresh leg state over the old one,
    carrying forward only realized_pnl, so the markers for the exit still in
    flight were lost and order_events, which matches a fill by run id and leg
    id, applied that fill to the position the flip had just opened.

    The outgoing position is now kept under "superseded" until its own fill
    settles it, which is what separates the two positions this one leg id names
    for as long as the squaring order is unfilled.
    """
    strategy = _signal_strategy(
        [{"id": 1, "symbol": "RELIANCE", "exchange": "NSE", "qty": 100, "segment": "cash"}]
    )
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    run_id = store.get_strategy(strategy.id, USER).current_run_id
    engine.apply_fill(run_id, 1, 1400.0, is_entry=True)

    flip = signals.handle_signal(strategy, "short_entry", leg_id=1)

    assert flip.ok is True and flip.flipped is True
    assert [o["action"] for o in broker] == ["BUY", "SELL", "SELL"]
    outgoing = _leg_state(run_id)["superseded"]
    assert outgoing is not None, "the exit placed to square the long is still tracked"
    assert outgoing["exit_order_id"] is not None
    assert outgoing["position"] == "B", "the position being squared was the long"
    assert outgoing["entry_avg"] == 1400.0, "and it is settled against its own entry"


def test_the_exit_fill_of_a_flip_does_not_close_the_position_it_opened(market, broker):
    """The worst outcome in the module: a live position with nothing managing it.

    After the flip the leg state describes the new short. When the fill for the
    long's exit arrives, order_events looks the order row up by broker id, reads
    its leg id and calls engine.apply_fill(..., is_entry=False), which marks
    that leg closed and computes a realized figure from the short's entry. The
    short is then invisible: state.open_legs skips it, so no stop is evaluated,
    engine._exit_legs will not square it off and signals._held_side answers
    "no_matching_position" to any later exit alert, while the broker still holds
    it.
    """
    strategy = _signal_strategy(
        [{"id": 1, "symbol": "RELIANCE", "exchange": "NSE", "qty": 100, "segment": "cash"}]
    )
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    run_id = store.get_strategy(strategy.id, USER).current_run_id
    engine.apply_fill(run_id, 1, 1400.0, is_entry=True)
    signals.handle_signal(strategy, "short_entry", leg_id=1)

    # The exit that squared the long fills. It was placed before the new entry,
    # so its fill can easily arrive first.
    engine.apply_fill(run_id, 1, 1405.0, is_entry=False)

    leg = _leg_state(run_id)
    assert leg["position"] == "S"
    assert leg["status"] == "open", "the short opened by the flip is still held"


def test_a_signal_leg_keeps_its_realized_pnl_across_round_trips(market, broker):
    """The day's realized P&L is what every strategy-level rule is judged against.

    The module documents that a leg returns to configured after an exit, that
    its realized P&L accumulates on the leg, and that run_pnl counts realized
    from any leg that has it. signals._enter calls state.add_leg for the next
    entry, and add_leg builds a fresh leg state, so the figure only survives
    because add_leg carries realized_pnl forward explicitly. Without that, a
    strategy that loses 1000 five times never reaches a 5000 daily limit.
    """
    strategy = _signal_strategy(
        [{"id": 1, "symbol": "RELIANCE", "exchange": "NSE", "qty": 100, "segment": "cash"}]
    )
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    run_id = store.get_strategy(strategy.id, USER).current_run_id
    engine.apply_fill(run_id, 1, 1400.0, is_entry=True)
    signals.handle_signal(strategy, "long_exit", leg_id=1)
    engine.apply_fill(run_id, 1, 1410.0, is_entry=False)
    assert _leg_state(run_id)["realized_pnl"] == pytest.approx(1000.0)

    # The next alert of the day reopens the same leg.
    signals.handle_signal(strategy, "long_entry", leg_id=1)

    assert _leg_state(run_id)["realized_pnl"] == pytest.approx(1000.0)


def test_a_signal_run_survives_a_round_trip(market, broker):
    """A signal run is a trading day, not a basket, so going flat is ordinary."""
    strategy = _signal_strategy(
        [{"id": 1, "symbol": "RELIANCE", "exchange": "NSE", "qty": 10, "segment": "cash"}]
    )
    signals.handle_signal(strategy, "long_entry", leg_id=1)
    run_id = store.get_strategy(strategy.id, USER).current_run_id
    engine.apply_fill(run_id, 1, 1400.0, is_entry=True)
    signals.handle_signal(strategy, "long_exit", leg_id=1)

    engine.apply_fill(run_id, 1, 1410.0, is_entry=False)

    assert store.get_run(run_id).stopped_at is None
    assert store.get_strategy(strategy.id, USER).current_run_id == run_id


# ---------------------------------------------------------------------------
# Signal mode: a rejected exit
# ---------------------------------------------------------------------------


def test_a_leg_whose_signal_exit_was_rejected_can_still_be_squared_off(market):
    """A rejected exit must not strand the position for the rest of the day.

    A leg that looks like it has an exit in flight is skipped by every later
    attempt, so signals._exit has to release its claim when the broker refuses
    the order. Every square-off that matters goes through engine._exit_legs:
    the /stop and /close_all routes, the kill switch (engage_kill_switch) and
    the scheduler's auto square-off (scheduler.run_scheduled_stop). If the
    claim were left standing, all of them would pass over the leg, and stop_run
    would then finalise the run and clear its state, leaving a live position
    with nothing pointing at it.
    """
    placed = []

    def fail_exits(**kwargs):
        order = kwargs["order"]
        placed.append(order)
        if order["action"] == "SELL":
            return DispatchResult(ok=False, error="Broker unreachable")
        return DispatchResult(ok=True, broker_order_id=f"QA-{len(placed)}", response={})

    with (
        patch("services.strategy_module.order_dispatch.dispatch_order", side_effect=fail_exits),
        patch("database.auth_db.get_api_key_for_tradingview", return_value="qa-api-key"),
        patch("services.strategy_module.tick_feed.get_risk_tick_feed", return_value=MagicMock()),
    ):
        strategy = _signal_strategy(
            [{"id": 1, "symbol": "RELIANCE", "exchange": "NSE", "qty": 10, "segment": "cash"}]
        )
        signals.handle_signal(strategy, "long_entry", leg_id=1)
        run_id = store.get_strategy(strategy.id, USER).current_run_id
        engine.apply_fill(run_id, 1, 1400.0, is_entry=True)

        refused = signals.handle_signal(strategy, "long_exit", leg_id=1)
        assert refused.ok is False
        assert _leg_state(run_id)["status"] == "open"

        # The operator now hits the kill switch, which flattens through
        # engine.stop_run.
        engine.stop_run(run_id, USER, reason="manual")

    kinds = [row["kind"] for row in store.list_orders(run_id)]
    assert "exit_close_all" in kinds, f"the leg was never squared off: {kinds}"


# ---------------------------------------------------------------------------
# The universe tab, and the segments it decides a leg may use
#
# The tab is what says cash is tradable on the stocks universe and nowhere
# else, because an index has no cash instrument of its own and an MCX commodity
# has no spot. It used to be validated as free text up to thirty characters,
# with every rule hanging off it living in the browser, so a cash leg on an
# index tab validated here and was refused at run start instead.
# ---------------------------------------------------------------------------


def test_a_universe_tab_outside_the_four_is_refused():
    message = _refused(_config("NIFTY", "NSE_INDEX", [_option_leg()], universe_tab="delta"))
    assert "universe_tab" in message


def test_a_cash_leg_is_refused_on_a_tab_that_has_no_cash_to_trade():
    message = _refused(_config("NIFTY", "NSE_INDEX", [_cash_leg()], universe_tab="weekly_monthly"))
    assert "cash" in message and "weekly_monthly" in message


def test_a_cash_leg_is_accepted_on_the_stocks_tab():
    config, error = validate_strategy_config(
        _config("RELIANCE", "NSE", [_cash_leg()], universe_tab="stocks_fno")
    )
    assert error is None, error
    assert config["universe_tab"] == "stocks_fno"


def test_an_omitted_tab_is_read_off_the_legs_rather_than_defaulted():
    """A caller that never names a tab must not be refused about one.

    The tab is a grouping the wizard sets. An API caller building a cash
    strategy has no reason to know it exists, and defaulting to the index tab
    and then refusing the cash leg underneath it would be a refusal about a
    field the caller never set.
    """
    cash, error = validate_strategy_config(_config("RELIANCE", "NSE", [_cash_leg()]))
    assert error is None, error
    assert cash["universe_tab"] == "stocks_fno"

    weekly, error = validate_strategy_config(
        _config("NIFTY", "NSE_INDEX", [_option_leg(expiry="weekly")])
    )
    assert error is None, error
    assert weekly["universe_tab"] == "weekly_monthly"

    commodity, error = validate_strategy_config(
        _config("CRUDEOIL", "MCX", [_option_leg(expiry="monthly")])
    )
    assert error is None, error
    assert commodity["universe_tab"] == "mcx"


# ---------------------------------------------------------------------------
# A signal leg's segment and its venue have to describe the same instrument
# ---------------------------------------------------------------------------


def test_a_signal_cash_leg_is_refused_on_a_derivative_venue():
    """The segment was accepted and then ignored, so the leg traded the symbol.

    Nothing downstream reconciles a signal leg's segment against its exchange:
    _resolve_signal_leg reads the symbol and the venue and never looks at the
    segment at all.
    """
    message = _refused(
        _config(
            "MULTI",
            "NSE",
            [
                {
                    "id": 1,
                    "symbol": "NIFTY28MAY2624000CE",
                    "exchange": "NFO",
                    "qty": 1,
                    "segment": "cash",
                }
            ],
            strategy_kind="signal",
            product="MIS",
        )
    )
    assert "cash leg on NFO" in message


def test_a_signal_futures_leg_is_refused_on_a_cash_venue():
    message = _refused(
        _config(
            "MULTI",
            "NSE",
            [{"id": 1, "symbol": "RELIANCE", "exchange": "NSE", "qty": 1, "segment": "futures"}],
            strategy_kind="signal",
            product="MIS",
        )
    )
    assert "futures leg on NSE" in message


# ---------------------------------------------------------------------------
# Cash cannot be carried short
#
# Indian cash equity is sold short intraday and never carried short: a delivery
# sell has to be covered by stock the account holds. The product is read as
# intent everywhere in this module, so anything that is not MIS reaches a cash
# venue as CNC, which makes a short a naked short delivery.
# ---------------------------------------------------------------------------


def test_a_short_cash_batch_leg_is_refused_under_a_carry_product():
    message = _refused(_config("RELIANCE", "NSE", [_cash_leg(position="S")], product="NRML"))
    assert "short" in message and "MIS" in message


def test_a_short_cash_batch_leg_is_accepted_intraday():
    _, error = validate_strategy_config(
        _config("RELIANCE", "NSE", [_cash_leg(position="S")], product="MIS")
    )
    assert error is None, error


def test_a_long_cash_batch_leg_is_untouched_by_the_rule():
    _, error = validate_strategy_config(
        _config("RELIANCE", "NSE", [_cash_leg(position="B")], product="CNC")
    )
    assert error is None, error


def test_a_signal_leg_that_accepts_shorts_is_configurable_under_a_carry_product():
    """Only the signal that actually shorts is refused, not the configuration.

    A leg's side says which signals it accepts. A leg set to accept both is an
    ordinary intraday configuration, and refusing it at save time would block
    the common case to catch a rarer one.
    """
    _, error = validate_strategy_config(
        _config(
            "MULTI",
            "NSE",
            [
                {
                    "id": 1,
                    "symbol": "RELIANCE",
                    "exchange": "NSE",
                    "qty": 10,
                    "segment": "cash",
                    "side": "both",
                }
            ],
            strategy_kind="signal",
            product="NRML",
        )
    )
    assert error is None, error


def test_a_short_entry_on_cash_under_a_carry_product_places_nothing(market, broker):
    """The half the form cannot refuse, refused where the side is known."""
    strategy = _signal_strategy(
        [{"id": 1, "symbol": "RELIANCE", "exchange": "NSE", "qty": 10, "segment": "cash"}],
        product="NRML",
    )

    result = signals.handle_signal(strategy, "short_entry", leg_id=1)

    assert result.ok is False
    assert "short" in (result.error or "")
    assert broker == []


def test_a_long_entry_on_cash_under_a_carry_product_still_places(market, broker):
    strategy = _signal_strategy(
        [{"id": 1, "symbol": "RELIANCE", "exchange": "NSE", "qty": 10, "segment": "cash"}],
        product="NRML",
    )

    result = signals.handle_signal(strategy, "long_entry", leg_id=1)

    assert result.ok is True, result.error
    assert broker[0]["action"] == "BUY"
    # Carry on a cash venue is CNC, which is the whole reason a short is not.
    assert broker[0]["product"] == "CNC"


# ---------------------------------------------------------------------------
# A signal cash symbol is checked against the master contract
# ---------------------------------------------------------------------------


def test_a_signal_cash_leg_naming_a_symbol_that_is_not_listed_places_nothing(market, broker):
    """Batch mode refuses the identical typo with contract_not_found.

    The existence check used to be guarded on a derivative exchange, which left
    a misspelled equity as the one instrument nothing verified: a cash leg is
    not resolved from an underlying either, so it reached the broker verbatim.
    """
    strategy = _signal_strategy(
        [{"id": 1, "symbol": "RELAINCE", "exchange": "NSE", "qty": 10, "segment": "cash"}]
    )

    result = signals.handle_signal(strategy, "long_entry", leg_id=1)

    assert result.ok is False
    assert "RELAINCE is not a contract on NSE" in (result.error or "")
    assert broker == []


# ---------------------------------------------------------------------------
# A signal strategy has no start
#
# Its run is opened by the first signal after the session boundary. Running the
# batch lifecycle over signal legs reached run-state construction and raised,
# because a signal leg carries the side it accepts and not a position to be
# entered at, and the failure then left the run open and the strategy claimed
# with no live state for any later stop to work from.
# ---------------------------------------------------------------------------


def test_starting_a_signal_strategy_is_refused_by_name(market, broker):
    strategy = _signal_strategy(
        [{"id": 1, "symbol": "RELIANCE", "exchange": "NSE", "qty": 10, "segment": "cash"}]
    )

    result = engine.start_run(strategy.id, USER, "sandbox")

    assert result.ok is False
    assert "has no start" in (result.error or "")
    assert broker == []


def test_a_refused_start_leaves_the_signal_strategy_startable_by_signal(market, broker):
    """It must not strand the strategy the way the batch lifecycle did."""
    strategy = _signal_strategy(
        [{"id": 1, "symbol": "RELIANCE", "exchange": "NSE", "qty": 10, "segment": "cash"}]
    )

    engine.start_run(strategy.id, USER, "sandbox")

    row = store.get_strategy(strategy.id, USER)
    assert row.status == "stopped", "the refused start claimed the strategy"
    assert row.current_run_id is None, "the refused start left a run behind"

    # And the real entry point still works.
    result = signals.handle_signal(row, "long_entry", leg_id=1)
    assert result.ok is True, result.error


def test_a_start_that_fails_before_any_dispatch_finalises_its_run(market, broker):
    """Nothing sent is provable flatness, even with no run state to inspect.

    `dispatch_attempted` is written immediately before each dispatch, so an
    empty set proves no order left. The run must close rather than stay open
    with a strategy stuck reading "running".
    """
    sid = _make(_config("RELIANCE", "NSE", [_cash_leg()], product="MIS"))

    with patch(
        "services.strategy_module.state.init_run_state",
        side_effect=ValueError("run state could not be built"),
    ):
        result = engine.start_run(sid, USER, "sandbox")

    assert result.ok is False
    assert broker == [], "nothing should have been dispatched"

    row = store.get_strategy(sid, USER)
    assert row.status == "stopped", "the strategy is still claimed by a dead run"
    assert row.current_run_id is None

    runs = store.list_runs(sid)
    assert runs and runs[0]["stopped_at"] is not None, "the run was left open"


def test_a_refused_short_does_not_liquidate_the_long_it_would_have_flipped(market, broker):
    """A refusal must cost nothing.

    The uncarryable-short check used to run after the flip, so a short_entry on
    a leg held long squared that long and only then refused the short: a signal
    that was never going to open anything liquidated a position instead.
    """
    strategy = _signal_strategy(
        [{"id": 1, "symbol": "RELIANCE", "exchange": "NSE", "qty": 4, "segment": "cash"}],
        product="NRML",
    )

    opened = signals.handle_signal(strategy, "long_entry", leg_id=1)
    assert opened.ok is True, opened.error
    run_id = store.get_strategy(strategy.id, USER).current_run_id
    assert _leg_state(run_id)["position"] == "B"
    placed_before = len(broker)

    refused = signals.handle_signal(store.get_strategy(strategy.id, USER), "short_entry", leg_id=1)

    assert refused.ok is False
    assert "short" in (refused.error or "")
    assert len(broker) == placed_before, "the refused short still sent an order"
    assert _leg_state(run_id)["position"] == "B", "the long was squared by a refused signal"
    assert _leg_state(run_id)["status"] == "open"
