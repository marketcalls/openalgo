"""
The chart alert log: what survives the tab being closed.

The failures worth pinning here are not crashes. A log that quietly writes the
wrong time is worse than one that refuses, because the times still look
plausible and still sort correctly, and only somebody holding the log against
the chart would ever catch it. Same for a delivery field that reports a channel
nobody sent to.

The store is deliberately forgiving about its input: a firing arrives from a
browser, and a log that declines to record because one optional field was
absent is a log that is empty exactly when somebody needs it.
"""

import importlib
import math
from datetime import UTC, datetime, timedelta, timezone

import pytest


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A fresh alert log on its own SQLite file, per test."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'alerts.db'}")
    import database.alert_log_db as module

    module = importlib.reload(module)
    module.init_db()
    yield module
    module.db_session.remove()


def fire(**over):
    base = {
        "alertId": "a1",
        "title": "RELIANCE crossing 1264.7",
        "kind": "price",
        "condition": "crossesAbove",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "interval": "1h",
        "price": 1264.7,
        "message": "take the second lot off",
    }
    base.update(over)
    return base


class TestTheTimeItSaysItFired:
    """The bug this class exists for shifted every row by the host's offset."""

    def test_reads_back_the_instant_it_was_written(self, store):
        before = datetime.now(UTC).timestamp()
        row = store.record_fire("trader", fire())
        after = datetime.now(UTC).timestamp()

        # Written as UTC, so it must read back as UTC. A naive .timestamp()
        # assumes the server's local zone, which on an IST host puts every
        # firing 5.5 hours in the past.
        assert before - 1 <= row["firedAt"] <= after + 1

    def test_is_not_shifted_by_the_servers_timezone(self, store):
        row = store.record_fire("trader", fire())
        drift = abs(row["firedAt"] - datetime.now(UTC).timestamp())
        # Any whole-hour or half-hour offset is the local-timezone bug. Allow a
        # minute for a slow machine and nothing like an hour.
        assert drift < 60, f"the log is {drift / 3600:.1f} hours out"

    def test_the_listed_row_agrees_with_the_written_one(self, store):
        written = store.record_fire("trader", fire())
        listed = store.list_fires("trader")[0]
        assert listed["firedAt"] == written["firedAt"]


class TestWhatWentOut:
    def test_records_the_channels_the_page_reported(self, store):
        row = store.record_fire("trader", fire(), ["telegram", "whatsapp"])
        assert row["delivered"] == ["telegram", "whatsapp"]

    def test_an_undelivered_firing_is_still_a_firing(self, store):
        # The distinction the panel needs: reached nobody, versus never happened.
        row = store.record_fire("trader", fire(), [])
        assert row["delivered"] == []
        assert store.list_fires("trader") != []

    def test_never_writes_half_a_channel_name(self, store):
        # Truncating the joined string would leave a badge reading "whats".
        row = store.record_fire("trader", fire(), [f"channel{n:02d}" for n in range(20)])
        assert all(one.startswith("channel") and len(one) == 9 for one in row["delivered"])

    def test_does_not_repeat_a_channel(self, store):
        row = store.record_fire("trader", fire(), ["telegram", "telegram"])
        assert row["delivered"] == ["telegram"]


class TestARecordThatArrivedFromABrowser:
    def test_a_firing_with_no_price_is_still_recorded(self, store):
        # A candle-condition alert has no price of its own: it is true or it is not.
        row = store.record_fire("trader", fire(price=None, kind="barCondition"))
        assert row is not None
        assert row["price"] is None

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), "abc", None, {}])
    def test_a_price_that_is_not_a_number_is_dropped_not_stored(self, store, bad):
        row = store.record_fire("trader", fire(price=bad))
        assert row["price"] is None or math.isfinite(row["price"])

    def test_a_price_sent_as_a_string_is_still_a_price(self, store):
        assert store.record_fire("trader", fire(price="1264.7"))["price"] == pytest.approx(1264.7)

    def test_refuses_only_a_firing_it_cannot_identify(self, store):
        assert store.record_fire("trader", fire(alertId="")) is None
        assert store.record_fire("", fire()) is None

    def test_missing_optional_fields_do_not_lose_the_row(self, store):
        row = store.record_fire("trader", {"alertId": "a1"})
        assert row is not None
        assert row["title"] == ""
        assert row["kind"] == "price"

    def test_an_over_long_field_is_cut_rather_than_refused(self, store):
        row = store.record_fire("trader", fire(title="x" * 5000))
        assert row is not None
        assert len(row["title"]) <= 200


class TestReadingItBack:
    def test_newest_first(self, store):
        for n in range(3):
            store.record_fire("trader", fire(alertId=f"a{n}", title=f"fire {n}"))
        assert [row["title"] for row in store.list_fires("trader")] == [
            "fire 2",
            "fire 1",
            "fire 0",
        ]

    def test_two_firings_on_the_same_instant_are_both_listed_newest_first(self, store):
        # One bar can fire two alerts, and both rows then carry the same
        # timestamp. The query breaks the tie on id so the order is defined
        # rather than left to the database.
        #
        # This asserts the order, but it cannot fail if the tiebreak is removed:
        # SQLite happens to return equal sort keys in the order this wants
        # anyway. The tiebreak earns its place on PostgreSQL, where a tie is
        # genuinely arbitrary and the same page can come back two ways.
        same = store._utc_now()
        for alert_id in ("first", "second"):
            store.db_session.add(
                store.AlertFire(user_id="trader", alert_id=alert_id, fired_at=same)
            )
        store.db_session.commit()

        listed = store.list_fires("trader")
        assert [row["alertId"] for row in listed] == ["second", "first"]

    def test_never_reads_more_than_one_page_however_many_there_are(self, store):
        # The cap is what stops one page load becoming a multi-megabyte
        # response after a busy month, so there have to be more rows than it.
        when = store._utc_now()
        store.db_session.add_all(
            store.AlertFire(user_id="trader", alert_id=f"a{n}", fired_at=when)
            for n in range(store.MAX_LOG_PAGE + 25)
        )
        store.db_session.commit()

        assert len(store.list_fires("trader", limit=10_000)) == store.MAX_LOG_PAGE

    def test_one_users_log_is_not_anothers(self, store):
        store.record_fire("trader", fire(title="mine"))
        store.record_fire("other", fire(title="theirs"))
        assert [row["title"] for row in store.list_fires("trader")] == ["mine"]

    @pytest.mark.parametrize("limit", ["", None, "abc", -1, 0])
    def test_a_nonsense_limit_reads_the_default_rather_than_failing(self, store, limit):
        store.record_fire("trader", fire())
        assert len(store.list_fires("trader", limit=limit)) == 1

    def test_an_empty_log_is_a_list_not_an_error(self, store):
        assert store.list_fires("nobody") == []


class TestClearing:
    def test_clears_this_users_log_and_says_how_many(self, store):
        for n in range(3):
            store.record_fire("trader", fire(alertId=f"a{n}"))
        store.record_fire("other", fire())

        assert store.clear_fires("trader") == 3
        assert store.list_fires("trader") == []
        # Somebody else's history is not this button's business.
        assert len(store.list_fires("other")) == 1

    def test_clears_one_alerts_rows_on_their_own(self, store):
        store.record_fire("trader", fire(alertId="keep"))
        store.record_fire("trader", fire(alertId="drop"))
        store.record_fire("trader", fire(alertId="drop"))

        assert store.clear_fires("trader", alert_id="drop") == 2
        assert [row["alertId"] for row in store.list_fires("trader")] == ["keep"]


class TestRetention:
    def test_drops_what_is_past_the_window_and_keeps_what_is_not(self, store):
        old = store._utc_now() - timedelta(days=store.RETENTION_DAYS + 5)
        recent = store._utc_now() - timedelta(days=1)
        for when, alert_id in ((old, "old"), (recent, "recent")):
            store.db_session.add(
                store.AlertFire(user_id="trader", alert_id=alert_id, fired_at=when)
            )
        store.db_session.commit()

        # The trim runs on write, so there is no scheduler to forget about.
        store.record_fire("trader", fire(alertId="new"))

        kept = {row["alertId"] for row in store.list_fires("trader")}
        assert "old" not in kept
        assert {"recent", "new"} <= kept

    def test_a_firing_survives_a_trim_that_could_not_run(self, store, monkeypatch):
        # The row the trader cares about is already committed; housekeeping
        # failing afterwards must not lose it.
        monkeypatch.setattr(store, "_trim", lambda user_id: 1 / 0)
        assert store.record_fire("trader", fire()) is not None
