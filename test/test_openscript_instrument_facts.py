"""The instrument facts /trading hands the OpenScript engine.

The engine derives every session fact a script reads (``session.isFirstBar``,
``session.isLastBar``, the bar ``vwap`` restarts on) from one session record and
one zone, and a host that states neither gets all of them absent with nothing on
the chart to say why. These tests hold that record to the platform's own data:

- the session comes from the market calendar's timing table, and an admin edit
  to that table is what the record states, so no time is written anywhere but
  the calendar;
- today's window is the calendar's effective window, so a special session, an
  evening window on an equity holiday, a holiday and a weekend each come out
  the way the calendar resolves them;
- the weekday rule stated in the record agrees with the calendar's own answer
  for every day of a week;
- an exchange the calendar does not know gets no session rather than a
  borrowed one;
- volume and open interest follow what the instrument is.

The calendar is a real one: its own tables, created in a temporary SQLite file
and filled by its own seed functions. Only the master contract lookup is
replaced, because it reads a broker's download.
"""

from datetime import date, timedelta

import pytest
from flask import Blueprint, Flask
from sqlalchemy.orm import scoped_session, sessionmaker

import services.openscript_instrument_service as facts_service
import utils.session
from blueprints import openscript as openscript_blueprint
from database.engine_factory import create_db_engine

REGULAR_WEDNESDAY = date(2026, 9, 23)
PLAIN_SATURDAY = date(2026, 9, 19)
MUHURAT_SUNDAY = date(2026, 11, 8)  # SPECIAL_SESSION in the 2026 seed
AMBEDKAR_JAYANTI = date(2026, 4, 14)  # equity closed, MCX evening in the seed
GANDHI_JAYANTI = date(2026, 10, 2)  # every exchange closed in the seed
HOLIDAY_FREE_WEEK = [date(2026, 9, 21) + timedelta(days=n) for n in range(7)]


@pytest.fixture
def calendar(tmp_path, monkeypatch):
    """The market calendar on its own tables, seeded by its own functions."""
    import database.market_calendar_db as mc

    engine = create_db_engine(f"sqlite:///{(tmp_path / 'calendar.db').as_posix()}")
    session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
    monkeypatch.setattr(mc, "engine", engine)
    monkeypatch.setattr(mc, "db_session", session)
    # Swapped by hand: monkeypatch reads the old value with getattr, and a
    # query property read on the declarative base itself raises.
    previous_query = mc.Base.__dict__["query"]
    mc.Base.query = session.query_property()
    try:
        mc.Base.metadata.create_all(engine)
        mc.clear_market_calendar_cache()
        mc.seed_holidays_2026()
        mc.seed_market_timings()
        facts_service.clear_instrument_facts_cache()

        yield mc
    finally:
        facts_service.clear_instrument_facts_cache()
        mc.clear_market_calendar_cache()
        mc.Base.query = previous_query
        session.remove()
        engine.dispose()


class MasterContract:
    """Stands in for the /api/v1/symbol lookup, counting what it is asked."""

    def __init__(self):
        self.rows: dict[tuple[str, str], dict] = {}
        self.failing = False
        self.calls: list[tuple[str, str]] = []

    def add(self, symbol, exchange, instrumenttype, lotsize=1, tick_size=0.05):
        self.rows[(symbol, exchange)] = {
            "symbol": symbol,
            "exchange": exchange,
            "instrumenttype": instrumenttype,
            "lotsize": lotsize,
            "tick_size": tick_size,
        }

    def __call__(self, symbol, exchange, **_ignored):
        self.calls.append((symbol, exchange))
        if self.failing:
            return False, {"status": "error", "message": "database is locked"}, 500
        row = self.rows.get((symbol, exchange))
        if row is None:
            return False, {"status": "error", "message": "not found"}, 404
        return True, {"status": "success", "data": dict(row)}, 200


@pytest.fixture
def contracts(monkeypatch):
    master = MasterContract()
    monkeypatch.setattr(facts_service, "get_symbol_info", master)
    return master


def facts(symbol, exchange, on_date=REGULAR_WEDNESDAY):
    return facts_service.get_instrument_facts(symbol, exchange, on_date=on_date)


# ---------------------------------------------------------------------------
# The session comes from the calendar
# ---------------------------------------------------------------------------


def test_a_regular_day_states_the_calendar_window_and_the_zone(calendar, contracts):
    contracts.add("BHEL", "NSE", "EQ", lotsize=1, tick_size=0.05)
    timing = calendar.get_market_timing("NSE")

    result = facts("BHEL", "NSE")

    assert result["contractFound"] is True
    record = result["instrument"]
    assert record["exchange"] == "NSE"
    # The name of the zone the calendar itself uses, not one written here.
    assert record["timezone"] == calendar.IST.zone
    assert record["tickSize"] == 0.05
    assert record["lotSize"] == 1
    assert record["session"] == {
        "start": timing["start_time"],
        "end": timing["end_time"],
        "days": [1, 2, 3, 4, 5],
    }
    assert result["today"] == {
        "date": "2026-09-23",
        "open": True,
        "isSpecial": False,
        "session": {"start": timing["start_time"], "end": timing["end_time"], "days": [3]},
    }


def test_an_admin_edit_to_the_timing_table_is_what_the_record_states(
    calendar, contracts, monkeypatch
):
    """The proof that no time is written in the service: move it and it moves."""
    contracts.add("BHEL", "NSE", "EQ")
    # update_market_timing also rewrites the module's defaults for the process.
    # Recorded here so the teardown puts back whatever was there.
    monkeypatch.setitem(
        calendar.DEFAULT_MARKET_TIMINGS, "NSE", calendar.DEFAULT_MARKET_TIMINGS["NSE"]
    )
    assert calendar.update_market_timing("NSE", "10:05", "14:50")

    result = facts("BHEL", "NSE")

    assert result["instrument"]["session"]["start"] == "10:05"
    assert result["instrument"]["session"]["end"] == "14:50"
    assert result["today"]["session"]["start"] == "10:05"


def test_the_weekday_rule_agrees_with_the_calendar_on_every_day(calendar, contracts):
    for exchange in ("NSE", "MCX", "CRYPTO"):
        days = facts("ANY", exchange)["instrument"]["session"]["days"]
        for day in HOLIDAY_FREE_WEEK:
            calendar_open = calendar.get_effective_session_window(day, exchange) is not None
            assert (day.isoweekday() in days) is calendar_open, (exchange, day)


def test_a_special_session_day_keeps_the_regular_window_and_states_the_day_apart(
    calendar, contracts
):
    contracts.add("BHEL", "NSE", "EQ")
    regular = calendar.get_market_timing("NSE")

    result = facts("BHEL", "NSE", on_date=MUHURAT_SUNDAY)

    # History on the chart is still read against the regular window.
    assert result["instrument"]["session"]["start"] == regular["start_time"]
    assert result["instrument"]["session"]["days"] == [1, 2, 3, 4, 5]
    # And today is the calendar's special window, on the Sunday it is held.
    assert result["today"] == {
        "date": "2026-11-08",
        "open": True,
        "isSpecial": True,
        "session": {"start": "18:00", "end": "19:15", "days": [7]},
    }


def test_a_window_that_runs_past_midnight_is_written_as_the_clock_reads_it(calendar, contracts):
    """MCX Muhurat closes at 00:15 the next morning; the record reads end < start."""
    today = facts("CRUDEOIL", "MCX", on_date=MUHURAT_SUNDAY)["today"]
    assert today["session"] == {"start": "18:00", "end": "00:15", "days": [7]}
    assert today["isSpecial"] is True


def test_a_holiday_closes_the_exchanges_the_calendar_closes(calendar, contracts):
    closed = facts("BHEL", "NSE", on_date=GANDHI_JAYANTI)["today"]
    assert closed == {"date": "2026-10-02", "open": False, "isSpecial": False}

    equity = facts("BHEL", "NSE", on_date=AMBEDKAR_JAYANTI)["today"]
    assert equity["open"] is False

    # The same day, MCX trades its evening session.
    evening = facts("CRUDEOIL", "MCX", on_date=AMBEDKAR_JAYANTI)["today"]
    assert evening["open"] is True
    assert evening["isSpecial"] is True
    assert evening["session"] == {"start": "17:00", "end": "23:55", "days": [2]}


def test_a_weekend_is_closed_except_for_crypto(calendar, contracts):
    assert facts("BHEL", "NSE", on_date=PLAIN_SATURDAY)["today"]["open"] is False

    crypto = facts("BTCUSD", "CRYPTO", on_date=PLAIN_SATURDAY)
    # The calendar's crypto day runs to 23:59:59 inclusive, which is the whole
    # day, and the record spells the end of the day 24:00.
    assert crypto["instrument"]["session"] == {
        "start": "00:00",
        "end": "24:00",
        "days": [1, 2, 3, 4, 5, 6, 7],
    }
    assert crypto["today"] == {
        "date": "2026-09-19",
        "open": True,
        "isSpecial": False,
        "session": {"start": "00:00", "end": "24:00", "days": [6]},
    }


@pytest.mark.parametrize("exchange", ["NCDEX", "GLOBAL_INDEX", "SOMEWHERE"])
def test_an_exchange_the_calendar_does_not_know_gets_no_session(calendar, contracts, exchange):
    result = facts("ANY", exchange)

    assert "session" not in result["instrument"]
    assert result["today"] is None
    # Still stated: the zone the platform reads every clock in, and volume.
    assert result["instrument"]["timezone"] == calendar.IST.zone
    assert isinstance(result["instrument"]["hasVolume"], bool)


def test_an_index_exchange_follows_its_cash_exchange_calendar(calendar, contracts):
    contracts.add("NIFTY", "NSE_INDEX", "INDEX", lotsize=0, tick_size=0)
    cash = facts("BHEL", "NSE", on_date=MUHURAT_SUNDAY)

    index = facts("NIFTY", "NSE_INDEX", on_date=MUHURAT_SUNDAY)

    assert index["instrument"]["session"] == cash["instrument"]["session"]
    assert index["today"] == cash["today"]


# ---------------------------------------------------------------------------
# What the instrument is
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("symbol", "exchange", "code", "kind", "volume", "open_interest"),
    [
        ("BHEL", "NSE", "EQ", "equity", True, False),
        # Some brokers write no code on a cash row; that is the cash segment.
        ("BHEL", "BSE", "", "equity", True, False),
        ("NIFTY", "NSE_INDEX", "INDEX", "index", False, False),
        ("SENSEX", "BSE_INDEX", "AMXIDX", "index", False, False),
        ("NIFTY28OCT26FUT", "NFO", "FUTIDX", "future", True, True),
        ("NIFTY28OCT2625000CE", "NFO", "CE", "option", True, True),
        ("BANKNIFTY28OCT2650000PE", "NFO", "OPTIDX", "option", True, True),
        ("BTCUSD", "CRYPTO", "PERPFUT", "future", True, True),
        ("CRUDEOIL19NOV26FUT", "MCX", "COM", "commodity", True, True),
        ("USDINR28OCT26FUT", "CDS", "CUR", "currency", True, True),
        # A code none of the seven words fits is stated as nothing.
        ("BTC_USDT", "CRYPTO", "SPOT", None, True, False),
    ],
)
def test_index_equity_and_derivative_facts(
    calendar, contracts, symbol, exchange, code, kind, volume, open_interest
):
    contracts.add(symbol, exchange, code)

    record = facts(symbol, exchange)["instrument"]

    assert record.get("instrumentType") == kind
    assert record["hasVolume"] is volume
    assert record["hasOpenInterest"] is open_interest


def test_a_size_of_zero_is_not_stated(calendar, contracts):
    contracts.add("NIFTY", "NSE_INDEX", "INDEX", lotsize=0, tick_size=0)

    record = facts("NIFTY", "NSE_INDEX")["instrument"]

    assert "lotSize" not in record
    assert "tickSize" not in record


@pytest.mark.parametrize(
    ("exchange", "kind", "volume", "open_interest"),
    [
        ("NSE", None, True, False),
        ("NFO", None, True, True),
        ("NSE_INDEX", "index", False, False),
    ],
)
def test_an_unknown_symbol_gets_what_the_exchange_alone_says(
    calendar, contracts, exchange, kind, volume, open_interest
):
    result = facts("NOSUCHTHING", exchange)

    assert result["contractFound"] is False
    record = result["instrument"]
    assert record.get("instrumentType") == kind
    assert record["hasVolume"] is volume
    assert record["hasOpenInterest"] is open_interest
    assert "lotSize" not in record and "tickSize" not in record
    assert record["timezone"] == calendar.IST.zone
    assert "session" in record


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


def test_one_answer_per_symbol_exchange_and_date(calendar, contracts):
    contracts.add("BHEL", "NSE", "EQ")

    first = facts("BHEL", "NSE")
    first["instrument"]["lotSize"] = 999  # a caller changing its copy
    second = facts("BHEL", "nse")
    facts("BHEL", "NSE", on_date=PLAIN_SATURDAY)

    assert contracts.calls == [("BHEL", "NSE"), ("BHEL", "NSE")]
    assert second["instrument"]["lotSize"] == 1


def test_a_failed_lookup_is_not_kept(calendar, contracts):
    contracts.add("BHEL", "NSE", "EQ")
    contracts.failing = True
    assert facts("BHEL", "NSE")["contractFound"] is False

    contracts.failing = False
    assert facts("BHEL", "NSE")["contractFound"] is True
    assert len(contracts.calls) == 2


# ---------------------------------------------------------------------------
# The route
# ---------------------------------------------------------------------------


def _app():
    application = Flask(__name__)
    application.config["TESTING"] = True
    application.secret_key = "test-only"
    application.register_blueprint(openscript_blueprint.openscript_bp)
    return application


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(utils.session, "is_session_valid", lambda: True)
    return _app().test_client()


def test_the_route_answers_in_the_engine_field_names(calendar, contracts, client):
    contracts.add("BHEL", "NSE", "EQ", lotsize=1, tick_size=0.05)

    response = client.get("/openscript/instrument?symbol=BHEL&exchange=nse")

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "success"
    assert body["symbol"] == "BHEL"
    assert body["contractFound"] is True
    assert set(body["instrument"]) == {
        "exchange",
        "timezone",
        "tickSize",
        "lotSize",
        "instrumentType",
        "hasVolume",
        "hasOpenInterest",
        "session",
    }
    assert body["instrument"]["exchange"] == "NSE"
    assert set(body["today"]) >= {"date", "open", "isSpecial"}


def test_an_unknown_symbol_is_answered_not_refused(calendar, contracts, client):
    response = client.get("/openscript/instrument?symbol=NOSUCHTHING&exchange=NSE")

    assert response.status_code == 200
    body = response.get_json()
    assert body["contractFound"] is False
    assert body["instrument"]["hasVolume"] is True
    assert "session" in body["instrument"]


def test_a_symbol_with_spaces_and_lower_case_is_accepted(calendar, contracts, client):
    contracts.add("NIFTY Alpha 50", "NSE_INDEX", "INDEX")

    response = client.get(
        "/openscript/instrument",
        query_string={
            "symbol": "NIFTY Alpha 50",
            "exchange": "NSE_INDEX",
        },
    )

    assert response.status_code == 200
    assert response.get_json()["contractFound"] is True


@pytest.mark.parametrize(
    "query",
    [
        {"exchange": "NSE"},
        {"symbol": "", "exchange": "NSE"},
        {"symbol": "   ", "exchange": "NSE"},
        {"symbol": "B" * 65, "exchange": "NSE"},
        {"symbol": "BHEL\nX", "exchange": "NSE"},
        {"symbol": "BHEL"},
        {"symbol": "BHEL", "exchange": "N$E"},
        {"symbol": "BHEL", "exchange": "../NSE"},
        {"symbol": "BHEL", "exchange": "X" * 21},
    ],
)
def test_a_malformed_query_is_refused_in_a_sentence(client, contracts, query):
    response = client.get("/openscript/instrument", query_string=query)

    assert response.status_code == 400
    message = response.get_json()["message"]
    assert message.endswith(".")
    assert "400" not in message
    assert contracts.calls == []


def test_a_failure_reads_as_a_sentence(client, monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError("no such table: market_timings")

    monkeypatch.setattr(openscript_blueprint, "get_instrument_facts", broken)

    response = client.get("/openscript/instrument?symbol=BHEL&exchange=NSE")

    assert response.status_code == 500
    message = response.get_json()["message"]
    assert "BHEL" in message
    assert "market_timings" not in message
    assert "RuntimeError" not in message


def test_the_route_is_behind_the_session_guard(monkeypatch, contracts):
    monkeypatch.setattr(utils.session, "is_session_valid", lambda: False)
    monkeypatch.setattr(utils.session, "revoke_user_tokens", lambda: None)
    application = _app()
    auth = Blueprint("auth", __name__)
    auth.add_url_rule("/login", "login", lambda: "login")
    application.register_blueprint(auth)
    guarded = application.test_client()

    fetched = guarded.get(
        "/openscript/instrument?symbol=BHEL&exchange=NSE",
        headers={"Accept": "application/json"},
    )
    navigated = guarded.get("/openscript/instrument?symbol=BHEL&exchange=NSE")

    assert fetched.status_code == 401
    assert navigated.status_code == 302
    assert contracts.calls == []
