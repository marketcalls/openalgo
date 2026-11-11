"""The Telegram bot obeys only a chat linked with this instance's own API key.

``/link <api_key> <host_url>`` used to decide by asking the host in the
command whether the key was good. The sender chooses that host, so a stranger
who found the bot could name a server of their own that says yes to any key
and be linked. Linked was then all the mode buttons and the Python strategy
stops asked for, and those act on this server directly, not through the API
key: a stranger could switch the platform between Live and Analyze and stop
every running strategy.

Now the key is checked against this instance's stored API key before anything
is sent anywhere, and every action on this server checks it again at the
moment it is asked for.
"""

from __future__ import annotations

import asyncio
import sys
import types

import pytest

OWNER_KEY = "the-owners-api-key"
OWNER = 101
STRANGER = 666

SUCCESS = {"status": "success", "data": {"username": "somebody-else"}}


class _Message:
    def __init__(self):
        self.replies: list[str] = []

    async def reply_text(self, text, **_kwargs):
        self.replies.append(text)


class _Query:
    def __init__(self, data: str, telegram_id: int):
        self.data = data
        self.from_user = types.SimpleNamespace(id=telegram_id)
        self.message = types.SimpleNamespace(chat=types.SimpleNamespace(id=202))
        self.edits: list[str] = []

    async def answer(self):
        return None

    async def edit_message_text(self, text, **_kwargs):
        self.edits.append(text)


class _Bot:
    def __init__(self):
        self.sent: list[str] = []

    async def send_message(self, chat_id, text, **_kwargs):
        self.sent.append(text)


@pytest.fixture
def bot(monkeypatch):
    """A bot service whose link table, API key check and SDK are in memory.

    ``links`` is the link table: Telegram id to the key that chat was linked
    with. ``hosts`` records every host the bot built an SDK client for, which
    is every host it was about to send the key to.
    """
    import extensions
    import services.telegram_bot_service as tg

    links: dict[int, dict] = {}
    hosts: list[str] = []
    answers = {"funds": SUCCESS}

    monkeypatch.setattr(tg, "get_bot_config", lambda: {"bot_token": "1:a", "is_active": False})
    monkeypatch.setattr(tg, "update_bot_config", lambda values: True)
    monkeypatch.setattr(tg, "log_command", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        tg, "get_username_by_apikey", lambda key: "trader" if key == OWNER_KEY else None
    )
    monkeypatch.setattr(tg, "get_broker_name", lambda key: "zerodha")
    monkeypatch.setattr(tg, "get_telegram_user", lambda telegram_id: links.get(telegram_id))
    monkeypatch.setattr(tg, "get_user_credentials", lambda telegram_id: links.get(telegram_id))

    def link(telegram_id, username, api_key=None, host_url=None, **_fields):
        links[telegram_id] = {"username": username, "api_key": api_key, "host_url": host_url}
        return True

    monkeypatch.setattr(tg, "create_or_update_telegram_user", link)

    class _Sdk:
        """The SDK client: whatever host it is given answers as the test says."""

        def __init__(self, api_key, host):
            hosts.append(host)

        def funds(self):
            return answers["funds"]

    monkeypatch.setattr(sys.modules["openalgo"], "api", _Sdk)
    monkeypatch.setattr(extensions, "emit_from_any_thread", lambda *args, **kwargs: None)

    svc = tg.TelegramBotService()
    svc.links, svc.hosts, svc.answers, svc.tg = links, hosts, answers, tg
    return svc


def _send(svc, handler, telegram_id: int, *args: str) -> _Message:
    """Send a command as one Telegram account and return what it was told."""
    message = _Message()
    update = types.SimpleNamespace(
        effective_user=types.SimpleNamespace(
            id=telegram_id, username="someone", first_name="A", last_name="B"
        ),
        effective_chat=types.SimpleNamespace(id=202),
        message=message,
    )
    context = types.SimpleNamespace(args=list(args), user_data={})
    asyncio.run(getattr(svc, handler)(update, context))
    return message


def _press(svc, data: str, telegram_id: int, user_data: dict | None = None) -> _Query:
    query = _Query(data, telegram_id)
    update = types.SimpleNamespace(callback_query=query)
    context = types.SimpleNamespace(bot=_Bot(), user_data=user_data or {})
    asyncio.run(svc.button_callback(update, context))
    return query


@pytest.fixture
def server(bot, monkeypatch):
    """What the mode buttons and strategy stops act on, recorded in memory."""
    from database import settings_db
    from utils import runtime

    state = types.SimpleNamespace(mode=False, stopped=[], listed=0)
    monkeypatch.setattr(runtime, "gthread_active", lambda: False)
    monkeypatch.setattr(settings_db, "get_analyze_mode", lambda: state.mode)
    monkeypatch.setattr(settings_db, "set_analyze_mode", lambda mode: setattr(state, "mode", mode))

    def running():
        state.listed += 1
        return [("s1", "Nifty scalper"), ("s2", "Bank Nifty straddle")]

    def stop(strategy_id):
        state.stopped.append(strategy_id)
        return True, "stopped"

    monkeypatch.setattr(bot.tg, "_running_python_strategies", running)
    monkeypatch.setattr(bot.tg, "_stop_python_strategy", stop)
    return state


# ---------------------------------------------------------------------------
# /link
# ---------------------------------------------------------------------------


def test_a_host_that_says_yes_to_a_wrong_key_does_not_link(bot):
    """The defect itself: the sender's own server vouching for any key."""
    message = _send(bot, "cmd_link", STRANGER, "not-the-key", "https://their-server.example")

    assert bot.links == {}
    assert "Failed to validate API key" in message.replies[-1]
    # Nothing was sent to the host the stranger named, the key included.
    assert bot.hosts == []


def test_the_owners_key_links_and_the_host_is_still_tried(bot):
    message = _send(bot, "cmd_link", OWNER, OWNER_KEY, "http://127.0.0.1:5000/")

    assert "Account linked successfully" in message.replies[-1]
    assert bot.hosts == ["http://127.0.0.1:5000"]
    assert bot.links[OWNER]["api_key"] == OWNER_KEY
    assert bot.links[OWNER]["host_url"] == "http://127.0.0.1:5000"


def test_the_account_name_comes_from_this_instance_not_from_the_host(bot):
    """The host's answer names "somebody-else"; the key belongs to "trader"."""
    _send(bot, "cmd_link", OWNER, OWNER_KEY, "http://127.0.0.1:5000")

    assert bot.links[OWNER]["username"] == "trader"


def test_the_owners_key_with_a_host_that_does_not_answer_is_not_linked(bot):
    bot.answers["funds"] = {"status": "error", "message": "no"}
    message = _send(bot, "cmd_link", OWNER, OWNER_KEY, "http://wrong-host.example")

    assert bot.links == {}
    assert "Failed to validate API key" in message.replies[-1]


# ---------------------------------------------------------------------------
# Actions on this server
# ---------------------------------------------------------------------------


def _link_made_before_the_check(bot, telegram_id: int) -> None:
    """A row in the link table whose key is not this instance's API key.

    What a stranger's /link left behind before the key was checked here, and
    what the owner's own link becomes once the API key is regenerated.
    """
    bot.links[telegram_id] = {
        "username": "trader",
        "api_key": "not-the-key",
        "host_url": "https://their-server.example",
    }


@pytest.mark.parametrize("button", ["mode_analyze", "mode_live"])
def test_a_chat_that_is_not_linked_cannot_change_the_mode(bot, server, button):
    server.mode = button == "mode_live"
    before = server.mode

    query = _press(bot, button, STRANGER)

    assert server.mode is before
    assert query.edits == [bot.tg.LINK_AGAIN_MESSAGE]


def test_a_link_with_a_key_that_is_not_this_instances_cannot_change_the_mode(bot, server):
    _link_made_before_the_check(bot, STRANGER)

    query = _press(bot, "mode_analyze", STRANGER)

    assert server.mode is False
    assert query.edits == [bot.tg.LINK_AGAIN_MESSAGE]


def test_the_owner_changes_the_mode_as_before(bot, server):
    _send(bot, "cmd_link", OWNER, OWNER_KEY, "http://127.0.0.1:5000")

    query = _press(bot, "mode_analyze", OWNER)

    assert server.mode is True
    assert "Analyze Mode" in query.edits[-1]


@pytest.mark.parametrize(
    "button", ["csy_all", "csy_0", "spy_all", "spy_0", "confirm_closeall_with_strategies"]
)
def test_a_stranger_cannot_stop_or_list_strategies_by_button(bot, server, button):
    _link_made_before_the_check(bot, STRANGER)
    listed = [("s1", "Nifty scalper"), ("s2", "Bank Nifty straddle")]

    query = _press(bot, button, STRANGER, {"stoppy_list": listed})

    assert server.stopped == []
    assert server.listed == 0
    assert query.edits == [bot.tg.LINK_AGAIN_MESSAGE]
    # The SDK client that closes positions was never built either.
    assert bot.hosts == []


def test_the_owner_stops_every_strategy_as_before(bot, server):
    _send(bot, "cmd_link", OWNER, OWNER_KEY, "http://127.0.0.1:5000")

    _press(bot, "csy_all", OWNER)

    assert server.stopped == ["s1", "s2"]


@pytest.mark.parametrize("command", ["cmd_stoppython", "cmd_mode"])
def test_the_commands_refuse_a_link_that_is_not_the_owners(bot, server, command):
    _link_made_before_the_check(bot, STRANGER)

    message = _send(bot, command, STRANGER)

    assert message.replies == [bot.tg.LINK_AGAIN_MESSAGE]
    # /stoppython would have named the running strategies.
    assert server.listed == 0


def test_the_owner_is_offered_the_running_strategies_as_before(bot, server):
    _send(bot, "cmd_link", OWNER, OWNER_KEY, "http://127.0.0.1:5000")

    message = _send(bot, "cmd_stoppython", OWNER)

    assert server.listed == 1
    assert "Running Python Strategies" in message.replies[-1]


def test_a_regenerated_api_key_ends_what_the_old_link_could_do(bot, server, monkeypatch):
    _send(bot, "cmd_link", OWNER, OWNER_KEY, "http://127.0.0.1:5000")
    monkeypatch.setattr(
        bot.tg, "get_username_by_apikey", lambda key: "trader" if key == "a-new-key" else None
    )

    query = _press(bot, "mode_analyze", OWNER)

    assert server.mode is False
    assert query.edits == [bot.tg.LINK_AGAIN_MESSAGE]


def test_a_key_check_that_fails_reads_as_not_the_owner(bot, server, monkeypatch):
    _send(bot, "cmd_link", OWNER, OWNER_KEY, "http://127.0.0.1:5000")

    def broken(key):
        raise RuntimeError("the key store is unreadable")

    monkeypatch.setattr(bot.tg, "get_username_by_apikey", broken)

    query = _press(bot, "mode_analyze", OWNER)

    assert server.mode is False
    assert query.edits == [bot.tg.LINK_AGAIN_MESSAGE]


def test_every_button_that_reaches_this_server_is_one_the_press_checks():
    """A new branch that stops a strategy or writes the mode must be listed.

    Reads ``button_callback`` and finds each branch whose body calls into this
    server (through ``_in_app_world``); the callback data that selects it has
    to be one ``_acts_on_this_server`` answers True for.
    """
    import ast
    import inspect

    import services.telegram_bot_service as tg

    tree = ast.parse(inspect.getsource(tg))
    callback = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "button_callback"
    )
    checked = 0
    for branch in callback.body:
        if not isinstance(branch, ast.If):
            continue
        body = ast.Module(body=branch.body, type_ignores=[])
        reaches_server = any(
            isinstance(node, ast.Attribute) and node.attr == "_in_app_world"
            for node in ast.walk(body)
        )
        if not reaches_server:
            continue
        literals = [
            node.value
            for node in ast.walk(branch.test)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ]
        assert literals, ast.unparse(branch.test)
        for literal in literals:
            sample = literal + "0" if literal.endswith("_") else literal
            assert tg._acts_on_this_server(sample), literal
            checked += 1
    assert checked >= 4
