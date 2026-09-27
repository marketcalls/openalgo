"""One OpenScript strategy's books, and what they must never do.

A trader running several strategies asks which of them did this. Every test
below names the wrong implementation it catches, and the ones that matter most
are about attribution: a book showing another strategy's orders, or showing none
of its own, is read as fact and acted on.
"""

import pytest

from services import openscript_books as books


def order(oid, strategy, symbol="TCS", exchange="NSE", status="complete"):
    return {
        "orderid": oid,
        "strategy": strategy,
        "symbol": symbol,
        "exchange": exchange,
        "order_status": status,
    }


SCRIPT = "supertrend-strategy.oscript"

#: The deployment whose book these read. A book belongs to a deployment and not
#: to a file, because one file is deployed on several instruments at once and an
#: order's tag is what says which of them placed it.
MINE = "openscript_supertrend-strategy_SYM1_EXCH1_1m"

#: The same script deployed on a second instrument. Its orders are in the same
#: global book and must never appear in the first one's.
SIBLING = "openscript_supertrend-strategy_SYM2_EXCH1_1m"


class TestTheTag:
    def test_the_tag_is_the_run_id_the_service_mints(self):
        # Catches the two drifting apart. The runner writes this value onto every
        # order and this reads it back: a book keyed on anything else answers an
        # empty list for a strategy that is trading, which reads as "it has done
        # nothing" rather than as a bug.
        from services.openscript_runner_service import run_id_for

        assert books.tag_for(MINE) == run_id_for(SCRIPT, "SYM1", "EXCH1", "1m")
        assert books.tag_for(MINE).startswith(books.PREFIX)

    def test_a_file_name_is_not_a_deployment_and_takes_no_book(self):
        """THE ONE THE DEPLOYMENT CHANGE IS FOR.

        A file name names no instrument, and one file is deployed on several at
        once. The tag was minted from the file alone, so two deployments shared
        it and each one's book listed the other's orders: the panel showed a run
        on a commodity future listing the stock orders the same file had placed
        that morning, and a trader could not tell which position they were
        reading.
        """
        assert books.tag_for(SCRIPT) == ""

    def test_no_tag_shows_no_rows_and_never_every_untagged_row(self):
        """Catches an empty tag used as a filter.

        Comparing against an empty string matches exactly the orders carrying no
        strategy at all, which is every order the trader placed by hand. A book
        that could not be identified would show somebody else's trades.
        """
        rows = [order("1", ""), order("2", None), order("3", MINE)]

        assert books._mine(rows, SCRIPT) == []

    def test_two_deployments_of_one_script_do_not_share_a_book(self):
        rows = [order("1", MINE), order("2", SIBLING), order("3", MINE)]

        assert [row["orderid"] for row in books._mine(rows, MINE)] == ["1", "3"]
        assert [row["orderid"] for row in books._mine(rows, SIBLING)] == ["2"]


class TestAttribution:
    def test_only_this_strategy_rows_survive(self):
        rows = [
            order("1", MINE),
            order("2", "chart-trading"),
            order("3", MINE, status="open"),
            order("4", "openscript_ema-crossover", symbol="RELIANCE"),
        ]
        assert [r["orderid"] for r in books._mine(rows, MINE)] == ["1", "3"]

    def test_another_openscript_strategy_is_not_mine(self):
        # Catches a prefix match. Every OpenScript run's tag starts the same way,
        # so matching on the prefix rather than the whole tag puts every
        # strategy's orders in every strategy's book.
        rows = [order("1", "openscript_ema-crossover")]
        assert books._mine(rows, SCRIPT) == []

    def test_an_untagged_row_is_nobody_and_never_mine(self):
        # Catches an empty tag treated as a wildcard, which would hand a
        # strategy every manual order on the account.
        rows = [order("1", ""), order("2", None), {"orderid": "3"}]
        assert books._mine(rows, SCRIPT) == []

    def test_whitespace_around_a_tag_does_not_hide_a_row(self):
        assert len(books._mine([order("1", f"  {MINE} ")], MINE)) == 1

    def test_a_book_that_is_not_a_list_is_empty_rather_than_a_crash(self):
        for shape in (None, {}, "orders", 7):
            assert books._mine(shape, SCRIPT) == []


class TestStatistics:
    def test_counted_over_what_survived_and_never_carried_over(self):
        # THE ONE THAT MATTERS HERE. A global statistic over a filtered list is
        # wrong: passing the platform's own totals through would tell a trader
        # their strategy placed every order on the account.
        mine = [order("1", MINE), order("2", MINE, status="open"), order("3", MINE, status="rejected")]
        counted = books._statistics(mine)
        assert counted["total_orders"] == 3
        assert counted["completed_orders"] == 1
        assert counted["open_orders"] == 1
        assert counted["rejected_orders"] == 1

    def test_an_unknown_status_counts_as_open_rather_than_vanishing(self):
        # Catches rows dropped by a status nobody listed: the totals would then
        # not add up to the rows shown, which is worse than one being wrong.
        counted = books._statistics([order("1", MINE, status="something-new")])
        assert counted["total_orders"] == 1
        assert counted["open_orders"] == 1


class TestTheEnvelope:
    def test_the_service_own_dict_is_never_narrowed_in_place(self, monkeypatch):
        # Catches the global book being mutated. A book service may hold or
        # cache what it returned, and narrowing it in place would narrow the
        # platform's orderbook for whoever read it next.
        #
        # Through the public function rather than the envelope helper. What
        # matters is that a whole read leaves the service's own answer alone,
        # and a helper tested on its own cannot say whether the caller then
        # wrote into the original anyway.
        original = {"status": "success", "data": {"orders": [order("1", MINE), order("2", "other")]}}
        monkeypatch.setattr(books, "_fetch", lambda *a: (True, original))
        monkeypatch.setattr(books, "tag_for", lambda script: MINE)

        answered = books.orderbook("probe.oscript", "key", "sandbox")

        assert len(original["data"]["orders"]) == 2
        assert answered is not original
        assert answered["data"] is not original["data"]

    def test_a_service_refusal_is_passed_through_in_its_own_words(self):
        # Catches a message replaced by a generic one. The book services refuse
        # for reasons a trader can act on, and rewording loses the actionable
        # half.
        answered = books._as_error({"status": "error", "message": "Broker session expired"}, "fallback")
        assert answered["message"] == "Broker session expired"

    def test_a_refusal_with_nothing_to_say_still_gets_a_sentence(self):
        assert books._as_error({}, "Could not read the orderbook")["message"] == (
            "Could not read the orderbook"
        )


class TestFailures:
    @pytest.mark.parametrize("which", [books.orderbook, books.tradebook, books.positions])
    def test_a_book_never_raises_whatever_the_service_does(self, which, monkeypatch):
        # Catches an exception escaping into the page. One failing tab must not
        # take down the surface a trader is using to decide whether to stop
        # something that is trading.
        def explode(*_args, **_kwargs):
            raise RuntimeError("the broker fell over")

        monkeypatch.setattr(books, "_fetch", explode)
        answered = which(SCRIPT, "key", "sandbox")
        assert answered["status"] == "error"
        assert isinstance(answered["message"], str)


class TestThroughTheWholeBook:
    """The three books end to end, with the platform's own service stubbed.

    The tests above exercise the readers. These go through `orderbook`,
    `tradebook` and `positions` themselves, because a helper that is right and a
    book that never calls it is still a book that is wrong: the statistics were
    covered only as a function until a mutation that stopped recounting them
    inside the book passed every test here.
    """

    GLOBAL = {
        "status": "success",
        "data": {
            "orders": [
                order("1", MINE),
                order("2", "chart-trading"),
                order("3", MINE, status="open"),
            ],
            # What the platform counted over everything, which is not ours.
            "statistics": {"total_orders": 99, "open_orders": 40, "completed_orders": 59},
        },
    }

    def test_the_orderbook_recounts_rather_than_passing_the_global_totals(self, monkeypatch):
        monkeypatch.setattr(books, "_fetch", lambda *_a, **_k: (True, self.GLOBAL))

        answered = books.orderbook(MINE, "key", "sandbox")

        assert [o["orderid"] for o in answered["data"]["orders"]] == ["1", "3"]
        counted = answered["data"]["statistics"]
        assert counted["total_orders"] == 2, "the platform's own total reached the page"
        assert counted["open_orders"] == 1
        assert counted["completed_orders"] == 1

    def test_the_tradebook_narrows_to_this_strategy(self, monkeypatch):
        book = {
            "status": "success",
            "data": {"trades": [order("1", MINE), order("2", "OptionChain")]},
        }
        monkeypatch.setattr(books, "_fetch", lambda *_a, **_k: (True, book))

        answered = books.tradebook(MINE, "key", "sandbox")

        assert [t["orderid"] for t in answered["data"]["trades"]] == ["1"]

    def test_positions_keep_only_the_contracts_this_strategy_traded(self, monkeypatch):
        # A position row carries no strategy, so it is narrowed by the contracts
        # this strategy's own orders touched. Catches the filter dropped, which
        # would show a trader every position on the account as this strategy's.
        orders = {"status": "success", "data": {"orders": [order("1", MINE, symbol="TCS")]}}
        held = {
            "status": "success",
            "data": {
                "positions": [
                    {"symbol": "TCS", "exchange": "NSE", "quantity": 1},
                    {"symbol": "INFY", "exchange": "NSE", "quantity": 5},
                ]
            },
        }

        def fetch(book, *_a, **_k):
            return (True, orders) if book == "orderbook" else (True, held)

        monkeypatch.setattr(books, "_fetch", fetch)

        answered = books.positions(MINE, "key", "sandbox")

        assert [p["symbol"] for p in answered["data"]["positions"]] == ["TCS"]

    def test_a_failing_fetch_answers_the_service_own_message(self, monkeypatch):
        monkeypatch.setattr(
            books, "_fetch", lambda *_a, **_k: (False, {"message": "Sandbox is not enabled"})
        )

        answered = books.orderbook(MINE, "key", "sandbox")

        assert answered["status"] == "error"
        assert answered["message"] == "Sandbox is not enabled"
