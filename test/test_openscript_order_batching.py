"""One position change, one broker order.

**The defect this file is about.** The engine never sends an order across zero:
an instruction taking a position from long to short is two intents, one closing
the outgoing position and one opening its replacement, each with its own
position reference so a late fill can say which it settled. That is the engine's
bookkeeping and it is correct.

It is not the broker's. A broker holds one net position in one instrument, and
being told to buy one and then buy one again is being told to buy two, in two
orders, at two commissions and two spreads, for a position change a trader asked
for once. A live run was observed sending exactly that: one signal, two
identical market orders at the same instant.

So the runner nets them. The engine keeps its two positions, the broker gets the
one order it would have netted anyway, and the fill is handed back to the two
intents afterwards. The tests below are in two halves: what may be merged, which
is the half that could send a quantity nobody wrote, and how a fill is split,
which is the half that could leave a run believing it holds double.
"""

from types import SimpleNamespace

import pytest

from openscript_host import openscript_runner as runner


def intent(intent_id=1, side="buy", qty=1, kind="place", order_type="market",
           limit=None, trigger=None, symbol="TCS", exchange="NSE", product="MIS", tag=""):
    return SimpleNamespace(
        intent_id=intent_id,
        kind=kind,
        side=side,
        qty=qty,
        qty_type="units",
        product=product,
        instrument=SimpleNamespace(symbol=symbol, exchange=exchange),
        placement=SimpleNamespace(order_type=order_type, limit=limit, trigger=trigger, tag=tag),
    )


@pytest.fixture
def session():
    """A session with only the bookkeeping these tests touch."""
    held = object.__new__(runner.Session)
    held._orders = {}
    held._open = set()
    held._shares = {}
    return held


# ---------------------------------------------------------------------------
# What may be merged
# ---------------------------------------------------------------------------


def test_a_reversal_becomes_one_order(session):
    """THE DEFECT. Two buys of one for a flip is two brokerages for one change."""
    batches = session._batches([
        intent(1, "buy", 1, tag="closing"),
        intent(2, "buy", 1, tag="opening"),
    ])

    assert len(batches) == 1
    assert [one.intent_id for one in batches[0]] == [1, 2]


def test_two_sides_are_never_netted(session):
    """Catches a merge on instrument alone.

    A buy and a sell net to a quantity nobody wrote, and on a bar that meant to
    close one position and open another the other way, netting them would send
    nothing at all.
    """
    batches = session._batches([intent(1, "buy", 1), intent(2, "sell", 1)])

    assert len(batches) == 2


def test_a_limit_is_never_merged_with_a_market(session):
    """Catches a merge that ignores the placement.

    They are different instructions: one is matched at a price and the other is
    taken at whatever is there. One order cannot be both.
    """
    batches = session._batches([
        intent(1, "buy", 1),
        intent(2, "buy", 1, order_type="limit", limit=100.0),
    ])

    assert len(batches) == 2


def test_a_stop_is_never_merged(session):
    batches = session._batches([
        intent(1, "buy", 1),
        intent(2, "buy", 1, order_type="stop", trigger=99.0),
    ])

    assert len(batches) == 2


def test_a_cancellation_is_not_an_order_and_joins_nothing(session):
    batches = session._batches([
        intent(1, "buy", 1),
        intent(2, "buy", 1, kind="cancel"),
        intent(3, "buy", 1),
    ])

    assert [len(one) for one in batches] == [1, 1, 1]


def test_two_instruments_are_never_one_order(session):
    """Catches the day a leg arrives.

    Every order one run sends today is in one instrument, so this is equal by
    construction. It is compared anyway: this is the line that would otherwise
    net two instruments into a single order the moment a strategy holds legs.
    """
    batches = session._batches([
        intent(1, "buy", 1, symbol="TCS"),
        intent(2, "buy", 1, symbol="INFY"),
    ])

    assert len(batches) == 2


def test_two_products_are_never_one_order(session):
    batches = session._batches([
        intent(1, "buy", 1, product="MIS"),
        intent(2, "buy", 1, product="NRML"),
    ])

    assert len(batches) == 2


def test_a_quantity_that_is_not_whole_is_left_alone(session):
    """It is refused when routed, and must not be summed into a batch first."""
    batches = session._batches([intent(1, "buy", 1), intent(2, "buy", 1.5)])

    assert len(batches) == 2


def test_only_neighbours_merge(session):
    """Catches a merge gathered from across the bar.

    The sequence is what a half moved position is reported against and what the
    fill allocation counts on, so a batch is neighbours or it is nothing.
    """
    batches = session._batches([
        intent(1, "buy", 1),
        intent(2, "sell", 1),
        intent(3, "buy", 1),
    ])

    assert [len(one) for one in batches] == [1, 1, 1]


def test_an_ordinary_bar_is_unchanged(session):
    """One order call is one order, which is almost every bar."""
    batches = session._batches([intent(1, "buy", 1)])

    assert [len(one) for one in batches] == [1]


# ---------------------------------------------------------------------------
# Splitting the fill back
# ---------------------------------------------------------------------------


def filled(session, intent_id, order_quantity, price=2111.1):
    """The frame the runner builds for one intent of a shared order."""
    session.engine = SimpleNamespace(OrderFrame=lambda **fields: fields)
    session.options = SimpleNamespace(strategy_name="openscript_probe")
    session.client = SimpleNamespace(
        orderstatus=lambda order_id, strategy: {
            "status": "success",
            "data": {
                "order_status": "complete",
                "quantity": order_quantity,
                "average_price": price,
            },
        }
    )
    return session._frame_for(intent_id, "ORDER-1")


def test_each_intent_gets_its_own_part_of_a_shared_order(session):
    """THE ONE THAT MATTERS MOST.

    The order's whole quantity reported against each intent folds twice what
    traded, and the run then believes it holds double what the broker has. That
    is a wrong position, arrived at silently, on a strategy that is trading.
    """
    session._shares = {1: (0, 1), 2: (1, 1)}

    first = filled(session, 1, order_quantity=2)
    second = filled(session, 2, order_quantity=2)

    assert first["filled_qty"] == 1
    assert second["filled_qty"] == 1
    assert first["avg_fill_price"] == second["avg_fill_price"]


def test_the_parts_add_up_to_what_the_order_filled(session):
    """Catches an allocation that loses or invents a unit."""
    session._shares = {1: (0, 3), 2: (3, 2)}

    total = filled(session, 1, 5)["filled_qty"] + filled(session, 2, 5)["filled_qty"]

    assert total == 5


def test_an_order_that_only_partly_filled_settles_the_earlier_intent(session):
    """The truthful reading of one order that traded in part.

    Handing each a share of it would settle two positions on a fill that opened
    one. The earlier intent fills first and the later one stays open.
    """
    session._shares = {1: (0, 1), 2: (1, 1)}

    assert filled(session, 1, order_quantity=1)["filled_qty"] == 1
    assert filled(session, 2, order_quantity=1)["filled_qty"] == 0


def test_an_intent_with_an_order_to_itself_is_untouched(session):
    """Almost every order. A share is only recorded where one is shared."""
    session._shares = {}

    assert filled(session, 7, order_quantity=4)["filled_qty"] == 4


def test_a_share_never_goes_negative_or_past_its_own_size(session):
    session._shares = {1: (0, 1), 2: (1, 1), 3: (2, 1)}

    for intent_id in (1, 2, 3):
        for reported in (0, 1, 2, 3, 9):
            answered = filled(session, intent_id, reported)["filled_qty"]
            assert 0 <= answered <= 1


# ---------------------------------------------------------------------------
# Against the engine's own shape, not a stand-in
# ---------------------------------------------------------------------------


def test_the_engine_real_intent_is_one_this_merges(session):
    """THE TEST A STAND-IN CANNOT DO.

    Every case above builds its own object, so all of them would keep passing
    if the field this reads were renamed or were never there: the merge would
    simply never fire, in production only, and the saving this file exists for
    would quietly not happen. So this builds the engine's own intent and asserts
    the two halves of a reversal merge.
    """
    from openscript.strategy.intents import Identity, IntentBar, OrderIntent, Placement

    def real(intent_id, side):
        return OrderIntent(
            intent_id=intent_id,
            placement=Placement(kind="place", side=side, qty=1.0, order_type="market"),
            instrument=Identity(symbol="TCS", exchange="NSE"),
            product="intraday",
            bar=IntentBar(index=7, time=1_700_000_000_000.0),
        )

    batches = session._batches([real(1, "buy"), real(2, "buy")])

    assert len(batches) == 1, "a real reversal did not merge, so nothing here fires live"
    assert [one.intent_id for one in batches[0]] == [1, 2]

    # And the two sides of a real pair still do not.
    assert len(session._batches([real(1, "buy"), real(2, "sell")])) == 2
