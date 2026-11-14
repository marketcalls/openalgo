"""A failed freeze-cache RE-load keeps the last published limits.

The admin freeze endpoints (add/edit/delete/CSV upload) reload the cache after
every write. A transient DB error during such a reload used to replace the
cache with {} while leaving it marked loaded, so every lookup returned 0
("no limit known") until a restart.
"""

import database.qty_freeze_db as qf


class _BrokenQuery:
    def all(self):
        raise RuntimeError("database is locked")


class _BrokenModel:
    query = _BrokenQuery()


def test_failed_reload_keeps_previous_limits(monkeypatch):
    monkeypatch.setattr(qf, "_cache_loaded", True)
    monkeypatch.setattr(qf, "_freeze_qty_cache", {"NFO:NIFTY": 3510})
    monkeypatch.setattr(qf, "QtyFreeze", _BrokenModel)

    assert qf.load_freeze_qty_cache() is False
    assert qf.get_freeze_qty("NIFTY", "NFO") == 3510


def test_failed_first_load_stays_unloaded_so_the_next_lookup_retries(monkeypatch):
    monkeypatch.setattr(qf, "_cache_loaded", False)
    monkeypatch.setattr(qf, "_freeze_qty_cache", {})
    monkeypatch.setattr(qf, "QtyFreeze", _BrokenModel)

    assert qf.load_freeze_qty_cache() is False
    assert qf._cache_loaded is False
    assert qf.get_freeze_qty("NIFTY", "NFO") == 0
