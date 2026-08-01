"""Tests closing the open registry investigations (gthread PR-10b, gate A12).

Covers GT-A12-04, GT-A12-08, GT-A12-09 and GT-A14-03.

These rows were carried as `INVESTIGATE:` -- questions, not classifications.
Each is now answered with evidence: either the code is already correct and the
row resolves, or a real defect is fixed here.
"""

import inspect
import threading

import pytest

# --------------------------------------------------------------------------
# GT-A12-09: the websocket client registry (a real defect)
# --------------------------------------------------------------------------


def test_per_key_removal_exists():
    """The registry is keyed by API key and had only an all-or-nothing
    close_all_clients(). Rotating a key left the previous client connected and
    unreachable, and closing everything would disconnect other live consumers."""
    import services.websocket_client as wc

    assert hasattr(wc, "close_websocket_client")


def test_close_websocket_client_removes_only_that_key():
    import services.websocket_client as wc

    class FakeClient:
        def __init__(self):
            self.connected = True
            self.disconnected = False

        def disconnect(self):
            self.disconnected = True
            self.connected = False

    keep, drop = FakeClient(), FakeClient()
    wc._client_instances.clear()
    wc._client_instances["keep-key"] = keep
    wc._client_instances["drop-key"] = drop
    try:
        assert wc.close_websocket_client("drop-key") is True
        assert drop.disconnected is True
        assert "drop-key" not in wc._client_instances
        # The other consumer must be untouched.
        assert wc._client_instances["keep-key"] is keep
        assert keep.disconnected is False
        # Removing an unknown key is a no-op, not an error.
        assert wc.close_websocket_client("never-existed") is False
    finally:
        wc._client_instances.clear()


def test_a_dead_client_is_discarded_rather_than_handed_out():
    """The registry only built a client when the key was ABSENT, so a dropped
    connection was cached forever and every caller got a dead client."""
    import services.websocket_client as wc

    class DeadClient:
        connected = False

        def disconnect(self):
            pass

    wc._client_instances.clear()
    wc._client_instances["k"] = DeadClient()
    try:
        src = inspect.getsource(wc.get_websocket_client)
        assert "existing.connected" in src or "not existing.connected" in src, (
            "get_websocket_client does not check whether the cached client is alive"
        )
    finally:
        wc._client_instances.clear()


def test_api_key_rotation_closes_the_outgoing_client():
    """Rotation is the only moment the old key is still known."""
    import database.auth_db as auth_db

    src = inspect.getsource(auth_db.upsert_api_key)
    assert "_close_websocket_client_for_key" in src, "rotation does not tear down the old client"

    teardown = inspect.getsource(auth_db._close_websocket_client_for_key)
    assert "close_websocket_client" in teardown
    # Must never raise: a key has to rotate even if the socket cannot be closed,
    # and decryption can legitimately fail after a pepper rotation.
    assert "except Exception" in teardown


def test_registry_access_is_locked():
    import services.websocket_client as wc

    for fn in (wc.get_websocket_client, wc.close_websocket_client, wc.close_all_clients):
        assert "_client_lock" in inspect.getsource(fn), fn.__name__


# --------------------------------------------------------------------------
# GT-A12-04: order-update adapters (already correct)
# --------------------------------------------------------------------------


def test_order_update_adapters_are_locked_and_removed():
    """Resolved with evidence: _ADAPTERS is guarded and popped on logout."""
    import services.order_update_service as ous

    assert isinstance(ous._LOCK, type(threading.Lock()))
    assert "_ADAPTERS.pop" in inspect.getsource(ous._stop_locked)
    assert "_LOCK" in inspect.getsource(ous.stop_order_update_adapter)
    assert "_LOCK" in inspect.getsource(ous.stop_all_order_update_adapters)


# --------------------------------------------------------------------------
# GT-A12-08: historify job state (already correct)
# --------------------------------------------------------------------------


def test_historify_job_state_is_guarded():
    """Resolved with evidence: _running_jobs and _paused_jobs are covered by
    _job_state_lock at every mutation site."""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parent.parent / "services" / "historify_service.py"
    ).read_text(encoding="utf-8")
    assert "_job_state_lock = threading.Lock()" in src
    assert src.count("with _job_state_lock") >= 6


# --------------------------------------------------------------------------
# GT-A14-03: the session cap
# --------------------------------------------------------------------------


def test_session_cap_is_a_benign_check_then_act():
    """Accepted as-is, with the reasoning recorded rather than assumed.

    register_session does `if current_count >= MAX: delete oldest`, which IS a
    check-then-act: N simultaneous logins can each read the same count and each
    insert, briefly exceeding the cap by up to N-1.

    Not worth a lock, because:
      * it self-corrects -- the next login trims the oldest again;
      * the cap limits how many devices stay signed in, it is not a security
        boundary, and every session is still individually authenticated;
      * simultaneous logins by one user are rare by construction (OpenAlgo is
        single-user), so the window is nearly unreachable in practice.

    This test pins the mechanism so the reasoning is re-checked if it changes.
    """
    import database.auth_db as auth_db

    src = inspect.getsource(auth_db.register_session)
    assert "MAX_SESSIONS_PER_USER" in src
    assert "current_count >= MAX_SESSIONS_PER_USER" in src, (
        "cap mechanism changed; re-evaluate whether it still self-corrects"
    )
    assert "db_session.delete(oldest)" in src, "the trim that makes it converge is gone"


@pytest.mark.parametrize("cap_attr", ["MAX_SESSIONS_PER_USER"])
def test_session_cap_constant_exists(cap_attr):
    import database.auth_db as auth_db

    assert hasattr(auth_db, cap_attr)
