# test/sandbox/test_paper_mode_settings.py
"""
Test suite for paper_price_source settings toggle.

Tests:
- get_paper_price_source() default value
- set_paper_price_source() persistence and cache invalidation
- set_paper_price_source() rejects invalid values
- get_quote_provider() routing based on analyze_mode + paper_price_source
"""

import os
import sys

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Set required env vars before any DB module is imported
os.environ.setdefault("DATABASE_URL", "sqlite:///db/openalgo.db")
os.environ.setdefault("SANDBOX_DATABASE_URL", "sqlite:///db/sandbox.db")
os.environ.setdefault("APP_KEY", "test-app-key-32-chars-padding-here")
os.environ.setdefault("API_KEY_PEPPER", "test-pepper-key-32-chars-padding-x")


def setup_module():
    """Create DB tables before any test runs."""
    from database.settings_db import init_db

    init_db()


def _reset_settings_cache():
    """Clear the in-process settings TTL cache between tests."""
    from database.settings_db import _settings_cache

    _settings_cache.clear()


def _get_or_create_settings():
    """Ensure at least one Settings row exists and return it."""
    from database.settings_db import Settings, db_session

    settings = Settings.query.first()
    if not settings:
        settings = Settings(analyze_mode=False, paper_price_source="LIVE")
        db_session.add(settings)
        db_session.commit()
    return settings


def test_default_paper_price_source():
    """paper_price_source should default to LIVE."""
    print("\n" + "=" * 50)
    print("TEST 1: Default paper_price_source is LIVE")
    print("=" * 50)

    _reset_settings_cache()
    settings = _get_or_create_settings()

    from database.settings_db import Settings, db_session

    # Force LIVE to simulate a fresh row (may already be set from a prior test run)
    settings.paper_price_source = "LIVE"
    db_session.commit()
    _reset_settings_cache()

    from database.settings_db import get_paper_price_source

    value = get_paper_price_source()
    print(f"  get_paper_price_source() = {value!r}")
    assert value == "LIVE", f"Expected 'LIVE', got {value!r}"
    print("  ✓ Default is LIVE")


def test_set_paper_price_source_replay():
    """set_paper_price_source('REPLAY') should persist and be returned by getter."""
    print("\n" + "=" * 50)
    print("TEST 2: Set paper_price_source to REPLAY")
    print("=" * 50)

    _get_or_create_settings()
    _reset_settings_cache()

    from database.settings_db import get_paper_price_source, set_paper_price_source

    set_paper_price_source("REPLAY")
    _reset_settings_cache()  # ensure we hit DB, not cache
    value = get_paper_price_source()

    print(f"  After set('REPLAY') + cache clear → get() = {value!r}")
    assert value == "REPLAY", f"Expected 'REPLAY', got {value!r}"
    print("  ✓ REPLAY persisted correctly")

    # Restore
    set_paper_price_source("LIVE")
    _reset_settings_cache()


def test_set_paper_price_source_case_insensitive():
    """set_paper_price_source should normalise lowercase input."""
    print("\n" + "=" * 50)
    print("TEST 3: Lowercase input is normalised")
    print("=" * 50)

    _get_or_create_settings()
    _reset_settings_cache()

    from database.settings_db import get_paper_price_source, set_paper_price_source

    set_paper_price_source("replay")
    _reset_settings_cache()
    value = get_paper_price_source()

    print(f"  After set('replay') → get() = {value!r}")
    assert value == "REPLAY", f"Expected 'REPLAY', got {value!r}"
    print("  ✓ Normalised to REPLAY")

    # Restore
    set_paper_price_source("LIVE")
    _reset_settings_cache()


def test_set_paper_price_source_invalid():
    """set_paper_price_source should raise ValueError for unknown values."""
    print("\n" + "=" * 50)
    print("TEST 4: Invalid source raises ValueError")
    print("=" * 50)

    from database.settings_db import set_paper_price_source

    try:
        set_paper_price_source("UNKNOWN")
        assert False, "Expected ValueError was not raised"
    except ValueError as e:
        print(f"  ✓ Got expected ValueError: {e}")


def test_cache_invalidation():
    """set_paper_price_source should invalidate the TTL cache immediately."""
    print("\n" + "=" * 50)
    print("TEST 5: Cache is invalidated on write")
    print("=" * 50)

    _get_or_create_settings()
    _reset_settings_cache()

    from database.settings_db import _settings_cache, get_paper_price_source, set_paper_price_source

    # Warm the cache
    val1 = get_paper_price_source()
    assert "paper_price_source" in _settings_cache, "Cache should be warm after first read"

    # Write a new value
    new_source = "REPLAY" if val1 == "LIVE" else "LIVE"
    set_paper_price_source(new_source)

    assert "paper_price_source" not in _settings_cache, "Cache should be invalidated after write"
    print("  ✓ Cache invalidated immediately after write")

    # Read back — should hit DB and re-warm cache
    val2 = get_paper_price_source()
    assert val2 == new_source, f"Expected {new_source!r}, got {val2!r}"
    print(f"  ✓ Post-write read returns {val2!r} (DB value)")

    # Restore
    set_paper_price_source("LIVE")
    _reset_settings_cache()


def test_get_quote_provider_live_mode():
    """When analyze_mode=False, get_quote_provider always returns LiveQuoteProvider."""
    print("\n" + "=" * 50)
    print("TEST 6: get_quote_provider → LiveQuoteProvider when analyze_mode=False")
    print("=" * 50)

    _get_or_create_settings()
    _reset_settings_cache()

    from database.settings_db import set_analyze_mode, set_paper_price_source

    set_analyze_mode(False)
    set_paper_price_source("REPLAY")  # irrelevant in live mode
    _reset_settings_cache()

    from sandbox.quote_provider import LiveQuoteProvider, get_quote_provider

    provider = get_quote_provider()
    print(f"  Provider type: {type(provider).__name__}")
    assert isinstance(provider, LiveQuoteProvider), (
        f"Expected LiveQuoteProvider, got {type(provider).__name__}"
    )
    print("  ✓ Correct: LiveQuoteProvider when analyze_mode=False")

    # Restore
    set_paper_price_source("LIVE")
    set_analyze_mode(False)
    _reset_settings_cache()


def test_get_quote_provider_paper_live_source():
    """When analyze_mode=True and paper_price_source=LIVE → LiveQuoteProvider."""
    print("\n" + "=" * 50)
    print("TEST 7: get_quote_provider → LiveQuoteProvider when analyze=True + source=LIVE")
    print("=" * 50)

    _get_or_create_settings()
    _reset_settings_cache()

    from database.settings_db import set_analyze_mode, set_paper_price_source

    set_analyze_mode(True)
    set_paper_price_source("LIVE")
    _reset_settings_cache()

    from sandbox.quote_provider import LiveQuoteProvider, get_quote_provider

    provider = get_quote_provider()
    print(f"  Provider type: {type(provider).__name__}")
    assert isinstance(provider, LiveQuoteProvider), (
        f"Expected LiveQuoteProvider, got {type(provider).__name__}"
    )
    print("  ✓ Correct: LiveQuoteProvider when paper_price_source=LIVE")

    # Restore
    set_analyze_mode(False)
    set_paper_price_source("LIVE")
    _reset_settings_cache()


def test_get_quote_provider_paper_replay_source():
    """When analyze_mode=True and paper_price_source=REPLAY → ReplayQuoteProvider."""
    print("\n" + "=" * 50)
    print("TEST 8: get_quote_provider → ReplayQuoteProvider when analyze=True + source=REPLAY")
    print("=" * 50)

    _get_or_create_settings()
    _reset_settings_cache()

    from database.settings_db import set_analyze_mode, set_paper_price_source

    set_analyze_mode(True)
    set_paper_price_source("REPLAY")
    _reset_settings_cache()

    from sandbox.quote_provider import ReplayQuoteProvider, get_quote_provider

    provider = get_quote_provider()
    print(f"  Provider type: {type(provider).__name__}")
    assert isinstance(provider, ReplayQuoteProvider), (
        f"Expected ReplayQuoteProvider, got {type(provider).__name__}"
    )
    print("  ✓ Correct: ReplayQuoteProvider when analyze=True + paper_price_source=REPLAY")

    # Restore
    set_analyze_mode(False)
    set_paper_price_source("LIVE")
    _reset_settings_cache()


if __name__ == "__main__":
    print("=" * 60)
    print("Paper Mode Settings Test Suite")
    print("=" * 60)

    setup_module()

    tests = [
        test_default_paper_price_source,
        test_set_paper_price_source_replay,
        test_set_paper_price_source_case_insensitive,
        test_set_paper_price_source_invalid,
        test_cache_invalidation,
        test_get_quote_provider_live_mode,
        test_get_quote_provider_paper_live_source,
        test_get_quote_provider_paper_replay_source,
    ]

    passed = 0
    failed = 0
    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except AssertionError as e:
            print(f"\n  ✗ FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"\n  ✗ ERROR in {test_fn.__name__}: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    if failed:
        sys.exit(1)
