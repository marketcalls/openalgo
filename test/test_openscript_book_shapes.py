"""The three books, against the shapes the three services actually answer.

**Why this file exists beside the other one.** The tests in
``test_openscript_books.py`` were written against fakes shaped the way the author
believed a book was shaped: ``data`` as an object with the rows under a name.
The orderbook is that shape. The tradebook and the positionbook answer ``data``
as the list of rows itself. So two of the three books filtered an empty object,
answered success with nothing in it, and every test agreed, because every fake
had the shape the code expected rather than the shape the platform sends.

The constants below are copied from the services, with the line each came from,
and the first test holds them against the real modules. That is the part a fake
cannot do: agree with something that is not itself.
"""

import pytest

from services import openscript_books as books

TAG = "openscript_probe"


@pytest.fixture(autouse=True)
def tagged(monkeypatch):
    """Every order in these tests belongs to one strategy."""
    monkeypatch.setattr(books, "tag_for", lambda script: TAG)


def mine(**over):
    row = {"symbol": "TCS", "exchange": "NSE", "strategy": TAG, "quantity": 1}
    row.update(over)
    return row


def theirs(**over):
    return mine(strategy="someone_else", **over)


# ---------------------------------------------------------------------------
# The shapes, as the services really write them
# ---------------------------------------------------------------------------


def test_the_services_still_answer_the_shapes_these_tests_assume():
    """THE GUARD THE OTHER FILE DID NOT HAVE.

    Reads the service modules and checks each still writes ``data`` the way the
    tests below fake it. A fake cannot notice a service changing shape, which is
    exactly how two of these books came to return nothing: the shape was assumed
    once and never checked against the thing it was assuming about.
    """
    import inspect

    from services import orderbook_service, positionbook_service, tradebook_service

    orders = inspect.getsource(orderbook_service)
    trades = inspect.getsource(tradebook_service)
    positions = inspect.getsource(positionbook_service)

    # The orderbook wraps its rows in an object beside a statistics block.
    assert '"data": {"orders": formatted_orders' in orders

    # These two answer the list itself.
    assert '"data": formatted_trades' in trades
    assert '"data": formatted_positions' in positions


# ---------------------------------------------------------------------------
# The orderbook: rows under a name, beside statistics
# ---------------------------------------------------------------------------


def test_the_orderbook_keeps_its_object_shape_and_recounts(monkeypatch):
    answered = {
        "status": "success",
        "data": {
            "orders": [mine(orderid="1"), theirs(orderid="2"), mine(orderid="3")],
            "statistics": {"total_orders": 3, "open_orders": 3},
        },
    }
    monkeypatch.setattr(books, "_fetch", lambda *a: (True, answered))

    out = books.orderbook("probe.oscript", "key", "sandbox")

    assert [row["orderid"] for row in out["data"]["orders"]] == ["1", "3"]
    assert out["data"]["statistics"]["total_orders"] == 2


# ---------------------------------------------------------------------------
# The tradebook and the positionbook: a bare list
# ---------------------------------------------------------------------------


def test_the_tradebook_reads_a_bare_list_and_answers_one(monkeypatch):
    """THE DEFECT. Read as an object this filtered nothing and answered nothing.

    A trader reads an empty tradebook as a strategy that has not filled, which
    is the one answer that must never be given by mistake.
    """
    answered = {
        "status": "success",
        "data": [mine(orderid="1"), theirs(orderid="2"), mine(orderid="3")],
    }
    monkeypatch.setattr(books, "_fetch", lambda *a: (True, answered))

    out = books.tradebook("probe.oscript", "key", "sandbox")

    assert isinstance(out["data"], list), "a bare list must come back a bare list"
    assert [row["orderid"] for row in out["data"]] == ["1", "3"]


def test_the_positionbook_reads_a_bare_list_and_answers_one(monkeypatch):
    """The same defect, and the one the trader actually reported.

    The strategy was holding a position, the envelope carried its profit, and
    the rows were dropped on the way through.
    """
    calls = []

    def fetch(book, mode, api_key):
        calls.append(book)
        if book == "orderbook":
            return True, {"status": "success", "data": {"orders": [mine(orderid="1")]}}
        return True, {
            "status": "success",
            "total_pnl": 0.9,
            "data": [
                mine(quantity=1, pnl=0.5),
                {"symbol": "RELIANCE", "exchange": "NSE", "quantity": 4},
            ],
        }

    monkeypatch.setattr(books, "_fetch", fetch)

    out = books.positions("probe.oscript", "key", "sandbox")

    assert isinstance(out["data"], list)
    assert [row["symbol"] for row in out["data"]] == ["TCS"]
    # And the account's own figure is not carried through as this strategy's.
    # See the test below: that is a different and worse defect.
    assert "total_pnl" not in out


def test_the_account_profit_is_never_reported_as_one_deployment_s(monkeypatch):
    """THE ONE A TRADER WOULD ACT ON.

    A positions answer states its totals beside its rows, and those totals are
    the whole account's. The rows were narrowed to one deployment and the totals
    were not, so every deployment on the server reported the account's profit as
    its own: two brand new deployments, holding nothing and having traded
    nothing, each showed the same several hundred rupees.

    It is the one number a trader is actually watching, and there is nothing on
    the screen that would tell them it belongs to something else.
    """

    def fetch(book, mode, api_key):
        if book == "orderbook":
            return True, {"status": "success", "data": {"orders": []}}
        return True, {
            "status": "success",
            "total_pnl": 2113.4,
            "total_pnl_today": 2113.4,
            "total_unrealized_pnl": 1100.0,
            "total_today_realized_pnl": 1013.4,
            "data": [{"symbol": "RELIANCE", "exchange": "NSE", "quantity": 4, "pnl": 2113.4}],
        }

    monkeypatch.setattr(books, "_fetch", fetch)

    out = books.positions("openscript_probe_TCS_NSE_1m", "key", "sandbox")

    for key in ("total_pnl", "total_pnl_today", "total_unrealized_pnl"):
        assert out.get(key) != 2113.4, f"{key} is the account's and was reported as one strategy's"


def test_a_deployment_s_own_profit_comes_from_the_platform_s_own_book(monkeypatch):
    """Catches the totals simply dropped and never replaced.

    Dropping them is honest and loses the realised half, which for a strategy
    that has been trading all day is most of the number. The platform already
    keeps a leg per order tag with realised profit accumulated across sessions,
    so this is read rather than recomputed or given up on.
    """

    def fetch(book, mode, api_key):
        if book == "orderbook":
            return True, {"status": "success", "data": {"orders": [mine(orderid="1")]}}
        return True, {
            "status": "success",
            "total_pnl": 2113.4,
            "data": [mine(quantity=1, pnl=0.5)],
        }

    monkeypatch.setattr(books, "_fetch", fetch)
    monkeypatch.setattr(books, "tag_for", lambda one: TAG)

    def legs(user_id=None, strategy=None):
        assert strategy == TAG, "the per strategy book was asked about the wrong strategy"
        return [
            {
                "strategy": TAG,
                "symbol": "TCS",
                "exchange": "NSE",
                "product": "MIS",
                "quantity": 0.0,
                "average_price": 0.0,
                "realized_pnl": 17.5,
                "today_realized_pnl": 17.5,
            }
        ]

    import database.strategy_book_db as book_db

    monkeypatch.setattr(book_db, "get_strategy_legs", legs)

    out = books.positions(TAG, "key", "sandbox")

    assert out["total_pnl"] == 17.5
    assert out["total_today_realized_pnl"] == 17.5


def test_a_per_strategy_book_that_cannot_be_read_takes_no_total_with_it(monkeypatch):
    """A figure that could not be worked out is one this answer does not carry.

    Never the account's, which is the number this whole thing exists to stop
    being shown, and never zero, which reads as a strategy that is flat and fine.
    The rows still come back: one unreadable figure must not take a book down.
    """

    def fetch(book, mode, api_key):
        if book == "orderbook":
            return True, {"status": "success", "data": {"orders": [mine(orderid="1")]}}
        return True, {"status": "success", "total_pnl": 2113.4, "data": [mine(quantity=1)]}

    monkeypatch.setattr(books, "_fetch", fetch)
    monkeypatch.setattr(books, "tag_for", lambda one: TAG)

    import database.strategy_book_db as book_db

    def boom(user_id=None, strategy=None):
        raise RuntimeError("the strategy book is not there")

    monkeypatch.setattr(book_db, "get_strategy_legs", boom)

    out = books.positions(TAG, "key", "sandbox")

    assert "total_pnl" not in out
    assert [row["symbol"] for row in out["data"]] == ["TCS"]


def test_a_positionbook_that_names_its_list_is_read_too(monkeypatch):
    """A broker module that wraps its rows must work as well as one that does not.

    Both spellings are in this codebase, so reading one is reading half of them.
    """

    def fetch(book, mode, api_key):
        if book == "orderbook":
            return True, {"status": "success", "data": {"orders": [mine()]}}
        return True, {"status": "success", "data": {"positions": [mine(), theirs(symbol="INFY")]}}

    monkeypatch.setattr(books, "_fetch", fetch)

    out = books.positions("probe.oscript", "key", "sandbox")

    assert isinstance(out["data"], dict)
    assert [row["symbol"] for row in out["data"]["positions"]] == ["TCS"]


# ---------------------------------------------------------------------------
# What must not change
# ---------------------------------------------------------------------------


def test_the_service_own_dict_is_never_narrowed_in_place(monkeypatch):
    """A book service may hold or cache what it returned."""
    answered = {"status": "success", "data": [mine(orderid="1"), theirs(orderid="2")]}
    monkeypatch.setattr(books, "_fetch", lambda *a: (True, answered))

    books.tradebook("probe.oscript", "key", "sandbox")

    assert len(answered["data"]) == 2, "the global tradebook was narrowed for everyone"


def test_a_shape_nobody_writes_answers_nothing_rather_than_raising(monkeypatch):
    for shape in (None, "text", 7, {"data": None}, {"data": "text"}, {}):
        monkeypatch.setattr(books, "_fetch", lambda *a, s=shape: (True, s))

        out = books.tradebook("probe.oscript", "key", "sandbox")

        assert out.get("status") in ("success", "error")
