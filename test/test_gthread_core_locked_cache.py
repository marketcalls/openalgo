"""Every module cache under database/ and utils/ is a LockedTTLCache.

cachetools' TTLCache is not thread-safe, and under the gthread worker request,
bot and background threads really do use these caches at once: a membership
test followed by a subscript raises KeyError when the entry goes in between,
and two writers can corrupt the expiry list. The foundation tests prove the
locked cache holds up where a plain one fails; this file makes sure every
module actually uses it, and that the modules that used to cache ORM rows now
cache plain values.
"""

from __future__ import annotations

import ast
import threading
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
ALLOWED = {REPO / "utils" / "thread_safe_cache.py"}


def _constructs_ttlcache(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name == "TTLCache":
                lines.append(node.lineno)
    return lines


def test_no_module_under_database_or_utils_builds_a_plain_ttlcache():
    offenders = []
    for folder in ("database", "utils"):
        for path in sorted((REPO / folder).rglob("*.py")):
            if path in ALLOWED:
                continue
            for line in _constructs_ttlcache(path):
                offenders.append(f"{path.relative_to(REPO)}:{line}")
    assert offenders == [], (
        "Use utils.thread_safe_cache.LockedTTLCache: cachetools.TTLCache is not "
        f"thread-safe under the gthread worker. Found: {offenders}"
    )


def test_the_module_caches_are_locked():
    import database.agent_db as agent_db
    import database.flow_db as flow_db
    import database.latency_db as latency_db
    import database.leverage_db as leverage_db
    import database.market_calendar_db as market_calendar_db
    import database.telegram_db as telegram_db
    import database.user_db as user_db
    import database.whatsapp_db as whatsapp_db
    from utils import trading_calendar
    from utils.thread_safe_cache import LockedTTLCache

    caches = [
        agent_db._settings_cache,
        flow_db._workflow_webhook_cache,
        flow_db._workflow_cache,
        latency_db._stats_cache,
        leverage_db._leverage_cache,
        market_calendar_db._timings_cache,
        market_calendar_db._holidays_cache,
        telegram_db._telegram_user_cache,
        telegram_db._telegram_username_cache,
        telegram_db._user_preferences_cache,
        telegram_db._user_credentials_cache,
        user_db.username_cache,
        whatsapp_db._wa_user_cache,
        whatsapp_db._wa_username_cache,
        whatsapp_db._wa_preferences_cache,
        whatsapp_db._wa_credentials_cache,
        trading_calendar._HOLIDAY_CACHE,
    ]
    assert all(isinstance(cache, LockedTTLCache) for cache in caches)


@pytest.fixture
def login_user():
    import database.user_db as user_db

    user_db.init_db()
    name = f"gt-login-{uuid.uuid4().hex[:8]}"
    user_db.add_user(name, f"{name}@example.com", "Correct-Horse-9!", is_admin=False)
    user_db.db_session.remove()
    yield name
    try:
        user_db.User.query.filter_by(username=name).delete()
        user_db.db_session.commit()
    finally:
        user_db.db_session.remove()
        user_db.username_cache.invalidate()


def test_a_login_caches_the_hash_not_the_user_row(login_user):
    import database.user_db as user_db

    assert user_db.authenticate_user(login_user, "Correct-Horse-9!") is True
    cached = user_db.username_cache.get(f"user-{login_user}")
    assert isinstance(cached, str) and cached.startswith("$argon2")

    # A later request on another thread, after the first request's session is
    # gone: with a cached row this could raise DetachedInstanceError.
    user_db.db_session.remove()
    outcome = {}

    def other_request():
        try:
            outcome["good"] = user_db.authenticate_user(login_user, "Correct-Horse-9!")
            outcome["bad"] = user_db.authenticate_user(login_user, "wrong")
        finally:
            user_db.db_session.remove()

    thread = threading.Thread(target=other_request)
    thread.start()
    thread.join(30)
    assert outcome == {"good": True, "bad": False}
    # A wrong password drops the entry, as before.
    assert user_db.username_cache.get(f"user-{login_user}") is None


def test_a_setting_written_during_a_read_is_not_overwritten():
    import database.agent_db as agent_db

    agent_db.init_db()
    key = f"gt_core_{uuid.uuid4().hex[:8]}"
    try:
        assert agent_db.set_setting(key, "old") is True
        agent_db._settings_cache.invalidate()
        generation = agent_db._settings_cache.generation
        # A write commits between some reader's generation read and its fill.
        assert agent_db.set_setting(key, "new") is True
        assert agent_db._settings_cache.fill(key, "old", generation) is False
        assert agent_db.get_setting(key) == "new"
    finally:
        agent_db.delete_setting(key)
        agent_db.db_session.remove()
