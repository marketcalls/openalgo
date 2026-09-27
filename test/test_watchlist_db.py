"""Watchlist store behaviour.

The blueprint is thin (validation and status codes), so the contract worth
pinning is the store's: what it does with a duplicate, a full list, a reorder
computed against a stale view, and a delete.
"""

import pytest

from database import watchlist_db as wl

USER = "watchlist_test_user"
OTHER = "watchlist_other_user"


@pytest.fixture(autouse=True)
def clean_slate():
    """Each test starts and ends with no lists for either test user."""
    wl.init_db()
    for user in (USER, OTHER):
        for row in wl.get_watchlists(user):
            wl.delete_watchlist(user, row["id"])
    yield
    for user in (USER, OTHER):
        for row in wl.get_watchlists(user):
            wl.delete_watchlist(user, row["id"])


def test_create_returns_the_list_and_get_reads_it_back():
    created = wl.create_watchlist(USER, "Heavy Weights")

    assert created["name"] == "Heavy Weights"
    assert created["items"] == []
    assert [row["name"] for row in wl.get_watchlists(USER)] == ["Heavy Weights"]


def test_duplicate_name_is_refused_rather_than_silently_creating_a_second():
    wl.create_watchlist(USER, "Heavy Weights")

    assert wl.create_watchlist(USER, "Heavy Weights") is None
    assert len(wl.get_watchlists(USER)) == 1


def test_the_same_name_is_free_for_a_different_user():
    wl.create_watchlist(USER, "Heavy Weights")

    assert wl.create_watchlist(OTHER, "Heavy Weights") is not None


def test_create_can_seed_items_so_a_copy_is_one_call():
    seed = [{"symbol": "RELIANCE", "exchange": "NSE"}, {"symbol": "TCS", "exchange": "NSE"}]
    created = wl.create_watchlist(USER, "Copy", seed)

    assert [item["symbol"] for item in created["items"]] == ["RELIANCE", "TCS"]


def test_symbols_and_exchanges_are_normalised_to_upper_case():
    lst = wl.create_watchlist(USER, "Mixed")
    item = wl.add_item(USER, lst["id"], " reliance ", " nse ")

    assert item["symbol"] == "RELIANCE"
    assert item["exchange"] == "NSE"


def test_adding_the_same_instrument_twice_is_a_no_op_not_an_error():
    lst = wl.create_watchlist(USER, "Dupes")
    first = wl.add_item(USER, lst["id"], "TCS", "NSE")
    second = wl.add_item(USER, lst["id"], "TCS", "NSE")

    # The user's intent is already satisfied, so it reports the existing row
    # rather than failing.
    assert second is not None
    assert second["id"] == first["id"]
    assert len(wl.get_watchlists(USER)[0]["items"]) == 1


def test_positions_survive_a_deletion_in_the_middle():
    lst = wl.create_watchlist(USER, "Gaps")
    for symbol in ("A", "B", "C"):
        wl.add_item(USER, lst["id"], symbol, "NSE")

    items = wl.get_watchlists(USER)[0]["items"]
    wl.remove_item(USER, lst["id"], items[1]["id"])
    added = wl.add_item(USER, lst["id"], "D", "NSE")

    # max()+1, not len(): a deletion leaves a gap, so the count is not the next
    # free slot and reusing it would collide with C.
    assert added["position"] == 3
    assert [i["symbol"] for i in wl.get_watchlists(USER)[0]["items"]] == ["A", "C", "D"]


def test_reorder_moves_the_named_items_and_keeps_the_rest():
    lst = wl.create_watchlist(USER, "Order")
    for symbol in ("A", "B", "C"):
        wl.add_item(USER, lst["id"], symbol, "NSE")
    items = {i["symbol"]: i["id"] for i in wl.get_watchlists(USER)[0]["items"]}

    # Only two of three named, as a reorder computed against a stale view would be.
    wl.reorder_items(USER, lst["id"], [items["C"], items["A"]])

    # The omitted item keeps a stable place after the ones that were sent,
    # rather than being dropped from the list.
    assert [i["symbol"] for i in wl.get_watchlists(USER)[0]["items"]] == ["C", "A", "B"]


def test_reorder_ignores_ids_from_another_list():
    first = wl.create_watchlist(USER, "First")
    second = wl.create_watchlist(USER, "Second")
    wl.add_item(USER, first["id"], "A", "NSE")
    stranger = wl.add_item(USER, second["id"], "B", "NSE")

    assert wl.reorder_items(USER, first["id"], [stranger["id"]]) is True
    assert [i["symbol"] for i in wl.get_watchlists(USER)[0]["items"]] == ["A"]


def test_clear_empties_the_list_but_keeps_it():
    lst = wl.create_watchlist(USER, "Keep")
    wl.add_item(USER, lst["id"], "A", "NSE")

    assert wl.clear_watchlist(USER, lst["id"]) is True
    assert wl.get_watchlists(USER)[0]["items"] == []


def test_delete_takes_the_items_with_it():
    lst = wl.create_watchlist(USER, "Doomed")
    wl.add_item(USER, lst["id"], "A", "NSE")

    assert wl.delete_watchlist(USER, lst["id"]) is True
    assert wl.get_watchlists(USER) == []
    # The rows went with the parent rather than being orphaned.
    assert (
        wl.db_session.query(wl.WatchlistItem).filter_by(watchlist_id=lst["id"]).count() == 0
    )


def test_a_user_cannot_touch_another_users_list():
    lst = wl.create_watchlist(OTHER, "Theirs")

    assert wl.rename_watchlist(USER, lst["id"], "Mine") is False
    assert wl.delete_watchlist(USER, lst["id"]) is False
    assert wl.clear_watchlist(USER, lst["id"]) is False
    assert wl.add_item(USER, lst["id"], "A", "NSE") is None


def test_rename_refuses_a_name_already_in_use():
    first = wl.create_watchlist(USER, "First")
    wl.create_watchlist(USER, "Second")

    assert wl.rename_watchlist(USER, first["id"], "Second") is False
    assert wl.rename_watchlist(USER, first["id"], "Third") is True


def test_the_item_cap_is_enforced():
    lst = wl.create_watchlist(USER, "Full")
    for n in range(wl.MAX_ITEMS_PER_LIST):
        wl.add_item(USER, lst["id"], f"SYM{n}", "NSE")

    assert wl.add_item(USER, lst["id"], "ONEMORE", "NSE") is None


def test_seeded_items_are_capped_too():
    seed = [{"symbol": f"S{n}", "exchange": "NSE"} for n in range(wl.MAX_ITEMS_PER_LIST + 25)]
    created = wl.create_watchlist(USER, "Imported", seed)

    assert len(created["items"]) == wl.MAX_ITEMS_PER_LIST


def test_an_empty_name_is_refused():
    assert wl.create_watchlist(USER, "   ") is None
