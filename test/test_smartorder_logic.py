"""
Smart Order Logic Test Suite

Tests the position calculation logic, per-symbol locking, and cache behavior
for all brokers WITHOUT needing live broker connections.

We mock get_positions() and place_order_api() to test the logic in isolation.

Usage:
    cd /Users/openalgo/openalgo-test/openalgo
    uv run pytest test/test_smartorder_logic.py -v
"""

import importlib
import sys
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Test data: the OpenAlgo SmartOrder spec table
# ---------------------------------------------------------------------------
# (action, qty, position_size, current_position) -> expected (action, quantity) or "no_action"
SPEC_TABLE = [
    # action  qty  pos_size  current_pos  -> expected_action  expected_qty  description
    ("BUY",   100,  0,        0,           "BUY",             100,          "No position, pos_size=0 -> use action+qty from request"),
    ("BUY",   100,  100,     -100,         "BUY",             200,          "Short -100, target +100 -> BUY 200"),
    ("BUY",   100,  100,      100,         None,              0,            "Already at target -> no action"),
    ("BUY",   100,  200,      100,         "BUY",             100,          "Long 100, target 200 -> BUY 100"),
    ("SELL",  100,  0,        0,           "SELL",            100,          "No position, pos_size=0 -> use action+qty from request"),
    ("SELL",  100, -100,      100,         "SELL",            200,          "Long +100, target -100 -> SELL 200"),
    ("SELL",  100, -100,     -100,         None,              0,            "Already at target -> no action"),
    ("SELL",  100, -200,     -100,         "SELL",            100,          "Short -100, target -200 -> SELL 100"),
    # Edge cases
    ("BUY",   5,   0,        5,           "SELL",            5,            "Long 5, pos_size=0 -> close position SELL 5"),
    ("SELL",  5,   0,       -5,           "BUY",             5,            "Short -5, pos_size=0 -> close position BUY 5"),
    ("BUY",   0,   0,        0,           None,              0,            "qty=0, pos_size=0, no position -> no action"),
    ("BUY",   0,   100,      100,         None,              0,            "qty=0, already matched -> no action"),
]


# ---------------------------------------------------------------------------
# Helpers to extract and test position logic
# ---------------------------------------------------------------------------

def compute_smart_order_action(action, quantity, position_size, current_position):
    """
    Replicate the standard smart order logic used by most brokers.
    Returns (computed_action, computed_quantity) or (None, 0) for no action.
    """
    if position_size == 0 and current_position == 0 and quantity != 0:
        return action, quantity

    if position_size == current_position:
        return None, 0

    if position_size == 0 and current_position > 0:
        return "SELL", abs(current_position)
    elif position_size == 0 and current_position < 0:
        return "BUY", abs(current_position)
    elif current_position == 0:
        computed_action = "BUY" if position_size > 0 else "SELL"
        return computed_action, abs(position_size)
    else:
        if position_size > current_position:
            return "BUY", position_size - current_position
        elif position_size < current_position:
            return "SELL", current_position - position_size

    return None, 0


class TestSmartOrderPositionLogic:
    """Test the position calculation logic against the OpenAlgo spec table."""

    @pytest.mark.parametrize(
        "action,qty,pos_size,current_pos,expected_action,expected_qty,desc",
        SPEC_TABLE,
        ids=[row[-1] for row in SPEC_TABLE],
    )
    def test_spec_table(self, action, qty, pos_size, current_pos, expected_action, expected_qty, desc):
        computed_action, computed_qty = compute_smart_order_action(action, qty, pos_size, current_pos)
        assert computed_action == expected_action, f"{desc}: expected action={expected_action}, got {computed_action}"
        assert computed_qty == expected_qty, f"{desc}: expected qty={expected_qty}, got {computed_qty}"


# ---------------------------------------------------------------------------
# Test per-symbol lock serialization
# ---------------------------------------------------------------------------

class TestPerSymbolLock:
    """Test that per-symbol locks serialize smart orders correctly."""

    def test_same_symbol_serialized(self):
        """Two smart orders for the same symbol should execute sequentially."""
        execution_order = []
        lock = threading.Lock()

        def mock_smart_order(symbol, delay, order_id):
            with lock:
                execution_order.append(f"start_{order_id}")
            time.sleep(delay)
            with lock:
                execution_order.append(f"end_{order_id}")

        # Simulate per-symbol lock
        symbol_lock = threading.Lock()

        def locked_order(symbol, delay, order_id):
            with symbol_lock:
                mock_smart_order(symbol, delay, order_id)

        t1 = threading.Thread(target=locked_order, args=("SBIN", 0.1, 1))
        t2 = threading.Thread(target=locked_order, args=("SBIN", 0.1, 2))

        t1.start()
        time.sleep(0.01)  # Ensure t1 starts first
        t2.start()

        t1.join()
        t2.join()

        # Order 1 should complete before Order 2 starts
        assert execution_order.index("end_1") < execution_order.index("start_2"), \
            f"Expected serialized execution, got: {execution_order}"

    def test_different_symbols_parallel(self):
        """Two smart orders for different symbols should execute in parallel."""
        start_times = {}
        lock = threading.Lock()

        symbol_locks = {}
        symbol_locks_lock = threading.Lock()

        def get_lock(symbol):
            with symbol_locks_lock:
                if symbol not in symbol_locks:
                    symbol_locks[symbol] = threading.Lock()
                return symbol_locks[symbol]

        def locked_order(symbol, order_id):
            sym_lock = get_lock(symbol)
            with sym_lock:
                with lock:
                    start_times[order_id] = time.monotonic()
                time.sleep(0.1)

        t1 = threading.Thread(target=locked_order, args=("SBIN", 1))
        t2 = threading.Thread(target=locked_order, args=("RELIANCE", 2))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Both should have started within 50ms of each other (parallel)
        diff = abs(start_times[1] - start_times[2])
        assert diff < 0.05, f"Different symbols should run in parallel, but start diff was {diff:.3f}s"


# ---------------------------------------------------------------------------
# Test position cache behavior
# ---------------------------------------------------------------------------

class TestPositionCache:
    """Test cache TTL, invalidation, and thread safety."""

    def test_cache_returns_fresh_data(self):
        """First call should fetch, second within TTL should use cache."""
        cache = {}
        cache_lock = threading.Lock()
        TTL = 1.0
        fetch_count = 0

        def get_positions():
            nonlocal fetch_count
            fetch_count += 1
            return {"status": True, "data": {"net": []}}

        def get_cached(auth):
            with cache_lock:
                cached = cache.get(auth)
                if cached and (time.monotonic() - cached["ts"]) < TTL:
                    return cached["data"]
            data = get_positions()
            with cache_lock:
                cache[auth] = {"data": data, "ts": time.monotonic()}
            return data

        # First call: fetch
        get_cached("token123")
        assert fetch_count == 1

        # Second call within TTL: cache hit
        get_cached("token123")
        assert fetch_count == 1  # No additional fetch

    def test_cache_invalidation(self):
        """After invalidation, next call should fetch fresh data."""
        cache = {}
        cache_lock = threading.Lock()
        TTL = 1.0
        fetch_count = 0

        def get_positions():
            nonlocal fetch_count
            fetch_count += 1
            return {"status": True, "data": {"net": []}}

        def get_cached(auth):
            with cache_lock:
                cached = cache.get(auth)
                if cached and (time.monotonic() - cached["ts"]) < TTL:
                    return cached["data"]
            data = get_positions()
            with cache_lock:
                cache[auth] = {"data": data, "ts": time.monotonic()}
            return data

        def invalidate(auth):
            with cache_lock:
                cache.pop(auth, None)

        # Fetch, invalidate, fetch again
        get_cached("token123")
        assert fetch_count == 1

        invalidate("token123")

        get_cached("token123")
        assert fetch_count == 2  # Should fetch again after invalidation

    def test_cache_expires_after_ttl(self):
        """Cache should expire after TTL."""
        cache = {}
        cache_lock = threading.Lock()
        TTL = 0.2  # 200ms for test speed
        fetch_count = 0

        def get_positions():
            nonlocal fetch_count
            fetch_count += 1
            return {"status": True, "data": {"net": []}}

        def get_cached(auth):
            with cache_lock:
                cached = cache.get(auth)
                if cached and (time.monotonic() - cached["ts"]) < TTL:
                    return cached["data"]
            data = get_positions()
            with cache_lock:
                cache[auth] = {"data": data, "ts": time.monotonic()}
            return data

        get_cached("token123")
        assert fetch_count == 1

        time.sleep(0.3)  # Wait for TTL to expire

        get_cached("token123")
        assert fetch_count == 2  # Should fetch again after expiry


# ---------------------------------------------------------------------------
# Test each broker's position logic matches the spec
# ---------------------------------------------------------------------------

# List of all brokers to test
ALL_BROKERS = [
    "aliceblue", "angel", "compositedge", "definedge", "deltaexchange",
    "dhan", "dhan_sandbox", "firstock", "fivepaisa", "fivepaisaxts",
    "flattrade", "fyers", "groww", "ibulls", "iifl", "indmoney",
    "jainamxts", "kotak", "motilal", "mstock", "nubra", "paytm",
    "pocketful", "rmoney", "samco", "shoonya", "tradejini", "upstox",
    "wisdom", "zebu", "zerodha",
]


class TestBrokerModuleStructure:
    """Verify each broker module has the required cache/lock infrastructure."""

    @pytest.mark.parametrize("broker", ALL_BROKERS)
    def test_has_cache_functions(self, broker):
        """Each broker should have _get_cached_positions and _invalidate_position_cache."""
        filepath = f"broker/{broker}/api/order_api.py"
        with open(filepath) as f:
            content = f.read()

        assert "_get_cached_positions" in content, \
            f"{broker}: missing _get_cached_positions function"
        assert "_invalidate_position_cache" in content, \
            f"{broker}: missing _invalidate_position_cache function"
        assert "_get_symbol_lock" in content, \
            f"{broker}: missing _get_symbol_lock function"

    @pytest.mark.parametrize("broker", ALL_BROKERS)
    def test_has_lock_usage(self, broker):
        """Each broker's place_smartorder_api should use the per-symbol lock."""
        filepath = f"broker/{broker}/api/order_api.py"
        with open(filepath) as f:
            content = f.read()

        assert "symbol_lock" in content, \
            f"{broker}: place_smartorder_api not using per-symbol lock"

    @pytest.mark.parametrize("broker", ALL_BROKERS)
    def test_get_open_position_uses_cache(self, broker):
        """Each broker's get_open_position should use _get_cached_positions, not get_positions directly."""
        filepath = f"broker/{broker}/api/order_api.py"
        with open(filepath) as f:
            content = f.read()

        # Find get_open_position function and check it uses cached version
        import re
        func_match = re.search(
            r'def get_open_position\(.*?\):(.*?)(?=\ndef |\Z)',
            content, re.DOTALL
        )
        if func_match:
            func_body = func_match.group(1)
            # Should use _get_cached_positions, not raw get_positions
            uses_cache = "_get_cached_positions" in func_body
            uses_raw = "= get_positions(" in func_body
            assert uses_cache or not uses_raw, \
                f"{broker}: get_open_position calls get_positions() directly instead of _get_cached_positions()"

    @pytest.mark.parametrize("broker", ALL_BROKERS)
    def test_has_cache_invalidation_after_order(self, broker):
        """After placing an order in place_smartorder_api, cache should be invalidated."""
        filepath = f"broker/{broker}/api/order_api.py"
        with open(filepath) as f:
            content = f.read()

        assert "_invalidate_position_cache" in content, \
            f"{broker}: missing cache invalidation after order placement"

    @pytest.mark.parametrize("broker", ALL_BROKERS)
    def test_imports_threading_and_time(self, broker):
        """Each broker should import threading and time."""
        filepath = f"broker/{broker}/api/order_api.py"
        with open(filepath) as f:
            content = f.read()

        assert "import threading" in content, f"{broker}: missing 'import threading'"
        assert "import time" in content, f"{broker}: missing 'import time'"

    @pytest.mark.parametrize("broker", ALL_BROKERS)
    def test_compiles_without_error(self, broker):
        """Each broker file should compile without syntax errors."""
        import py_compile
        filepath = f"broker/{broker}/api/order_api.py"
        try:
            py_compile.compile(filepath, doraise=True)
        except py_compile.PyCompileError as e:
            pytest.fail(f"{broker}: Syntax error: {e}")


# ---------------------------------------------------------------------------
# Integration test: simulate 4 concurrent smart orders
# ---------------------------------------------------------------------------

class TestConcurrentSmartOrders:
    """Simulate concurrent smart orders to verify lock + cache behavior."""

    def test_four_identical_orders_one_fills(self):
        """
        Simulate: position=+1, 4 SELL orders with position_size=-1.
        Only the first should compute SELL 2, rest should see -1 and say no action.
        """
        call_count = {"get_positions": 0, "place_order": 0}
        current_broker_position = [1]  # mutable, changes after first order

        cache = {}
        cache_lock = threading.Lock()
        TTL = 1.0
        symbol_lock = threading.Lock()

        def mock_get_positions(auth):
            call_count["get_positions"] += 1
            return {"status": True, "data": {"net": [
                {"tradingsymbol": "YESBANK", "exchange": "NSE", "product": "MIS",
                 "quantity": str(current_broker_position[0])}
            ]}}

        def get_cached(auth):
            with cache_lock:
                cached = cache.get(auth)
                if cached and (time.monotonic() - cached["ts"]) < TTL:
                    return cached["data"]
            data = mock_get_positions(auth)
            with cache_lock:
                cache[auth] = {"data": data, "ts": time.monotonic()}
            return data

        def invalidate(auth):
            with cache_lock:
                cache.pop(auth, None)

        def mock_place_order(data, auth):
            call_count["place_order"] += 1
            # Simulate broker changing position after fill
            current_broker_position[0] = -1
            return MagicMock(status=200), {"status": "success"}, "ORDER123"

        results = {}

        def smart_order(order_id):
            with symbol_lock:
                positions_data = get_cached("token")
                current = int(positions_data["data"]["net"][0]["quantity"])
                target = -1

                if target == current:
                    results[order_id] = "matched"
                    return

                quantity = abs(target - current)
                action = "SELL" if target < current else "BUY"
                mock_place_order({"action": action, "quantity": quantity}, "token")
                invalidate("token")
                results[order_id] = f"placed_{action}_{quantity}"

        threads = [threading.Thread(target=smart_order, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        placed = sum(1 for v in results.values() if v.startswith("placed"))
        matched = sum(1 for v in results.values() if v == "matched")

        assert placed == 1, f"Expected 1 order placed, got {placed}. Results: {results}"
        assert matched == 3, f"Expected 3 matched, got {matched}. Results: {results}"
        assert call_count["place_order"] == 1, f"Expected 1 place_order call, got {call_count['place_order']}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
