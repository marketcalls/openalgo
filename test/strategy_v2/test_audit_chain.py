"""Unit tests for the chained-hash logic in subscribers/strategy_audit_subscriber.py.

This test isolates the pure-function `compute_row_hash` — the integration
with the DB and event bus is covered in Phase 1+ E2E tests.
"""

from subscribers.strategy_audit_subscriber import compute_row_hash


def test_row_hash_is_deterministic():
    a = compute_row_hash('{"k":1}', "")
    b = compute_row_hash('{"k":1}', "")
    assert a == b


def test_row_hash_changes_with_payload():
    a = compute_row_hash('{"k":1}', "")
    b = compute_row_hash('{"k":2}', "")
    assert a != b


def test_row_hash_changes_with_prev():
    a = compute_row_hash('{"k":1}', "")
    b = compute_row_hash('{"k":1}', "previous-hash")
    assert a != b


def test_chain_links():
    """Two consecutive rows compose: row2.prev_hash == row1.row_hash."""
    payload1 = '{"event":"first"}'
    row1_hash = compute_row_hash(payload1, "")

    payload2 = '{"event":"second"}'
    row2_prev = row1_hash
    row2_hash = compute_row_hash(payload2, row2_prev)

    # Recompute row1 → must match
    assert compute_row_hash(payload1, "") == row1_hash
    # Recompute row2 with the original prev → must match
    assert compute_row_hash(payload2, row2_prev) == row2_hash
    # Tamper: change row1's payload, the chain must diverge
    tampered = compute_row_hash('{"event":"first-TAMPERED"}', "")
    assert tampered != row1_hash


def test_hash_is_hex_64():
    h = compute_row_hash('{"k":1}', "")
    assert len(h) == 64
    int(h, 16)  # valid hex
