"""Contract tests for the /api/v1/telegram REST surface.

These are static checks over `restx_api/telegram_bot.py`. They exist because the
module is a thin translation layer over `telegram_bot_service`, and nothing else
exercises it: the /telegram web UI talks to `blueprints/telegram.py` instead, so
a broken call in the REST surface reaches production as an HTTP 500 that only an
API user ever sees.

Three real defects were shipped this way and are each pinned below:

* `run_async(bot.start_polling())` referenced a name that was never defined or
  imported anywhere in the module (NameError).
* `initialize_bot(token=..., webhook_url=...)` passed a keyword the service does
  not accept (TypeError), and `start_polling` was never a method of the service.
* `run_async(telegram_bot_service.stop_bot())` awaited a plain synchronous
  method, so `run_until_complete()` was handed a tuple (TypeError).

The checks are deliberately coarse: they only fail on things that cannot work at
runtime, so they do not need updating when the endpoints change shape.
"""

import ast
import builtins
import inspect
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "restx_api" / "telegram_bot.py"


@pytest.fixture(scope="module")
def module_tree() -> ast.Module:
    return ast.parse(MODULE_PATH.read_text(encoding="utf-8"), filename=str(MODULE_PATH))


def _bound_names(tree: ast.Module) -> set[str]:
    """Every name bound anywhere in the module, ignoring scope.

    Ignoring scope makes this an over-approximation: a name bound in one
    function counts as bound everywhere. That is intentional. It means the
    check never reports a name that merely looks out of scope, and only fires
    on a name that is bound nowhere at all - which is what a typo or a lost
    import looks like.
    """
    names = set(dir(builtins))

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
            args = node.args
            for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
                names.add(arg.arg)
            if args.vararg:
                names.add(args.vararg.arg)
            if args.kwarg:
                names.add(args.kwarg.arg)
        elif isinstance(node, ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            names.add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, ast.Global):
            names.update(node.names)

    return names


def test_no_unbound_names(module_tree: ast.Module):
    """Every name read in the module is bound somewhere in it.

    Pins the `bot.start_polling()` NameError: `bot` was read at module line 229
    but assigned, imported and defined nowhere.
    """
    bound = _bound_names(module_tree)

    unbound = sorted(
        {
            f"{node.id} (line {node.lineno})"
            for node in ast.walk(module_tree)
            if isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id not in bound
        }
    )

    assert not unbound, f"names read but never bound in {MODULE_PATH.name}: {unbound}"


def _service_calls(tree: ast.Module) -> list[ast.Call]:
    """Every `telegram_bot_service.<attr>(...)` call in the module."""
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "telegram_bot_service"
    ]


def test_service_calls_match_the_service(module_tree: ast.Module):
    """Each service call names a real method and passes arguments it accepts.

    Pins two defects: `start_polling` never existed on the service, and
    `initialize_bot()` was called with a `webhook_url` keyword it does not take.
    """
    service_module = pytest.importorskip(
        "services.telegram_bot_service",
        reason="python-telegram-bot is not installed in this environment",
    )
    service = service_module.telegram_bot_service

    calls = _service_calls(module_tree)
    assert calls, "expected the REST surface to call telegram_bot_service"

    problems = []
    for call in calls:
        attr = call.func.attr
        method = getattr(service, attr, None)
        if method is None:
            problems.append(f"line {call.lineno}: telegram_bot_service has no attribute {attr!r}")
            continue

        # Bind the call's keywords against the real signature. Positional args
        # are passed as placeholders; only argument *names* are being checked.
        kwargs = {kw.arg: None for kw in call.keywords if kw.arg is not None}
        try:
            inspect.signature(method).bind(*[None] * len(call.args), **kwargs)
        except TypeError as exc:
            problems.append(f"line {call.lineno}: {attr}(...) does not match its signature: {exc}")

    assert not problems, "REST surface calls do not match telegram_bot_service:\n" + "\n".join(
        problems
    )


def test_service_calls_are_synchronous(module_tree: ast.Module):
    """The REST surface only calls synchronous service methods.

    `run_async(telegram_bot_service.stop_bot())` handed a plain tuple to
    `loop.run_until_complete()`. Requiring synchronous methods here also keeps
    the module free of the asyncio bridging that breaks under eventlet.
    """
    service_module = pytest.importorskip(
        "services.telegram_bot_service",
        reason="python-telegram-bot is not installed in this environment",
    )
    service = service_module.telegram_bot_service

    coroutine_calls = [
        f"{call.func.attr} (line {call.lineno})"
        for call in _service_calls(module_tree)
        if inspect.iscoroutinefunction(getattr(service, call.func.attr, None))
    ]

    assert not coroutine_calls, (
        "coroutine methods called from the Flask request path: "
        f"{coroutine_calls}. Use the synchronous variant "
        "(initialize_bot_sync / start_bot / stop_bot) instead."
    )


def test_no_event_loop_construction(module_tree: ast.Module):
    """No request handler builds its own asyncio event loop.

    Production runs `gunicorn --worker-class eventlet -w 1`, where eventlet has
    monkey-patched the stdlib and `asyncio.new_event_loop()` /
    `run_until_complete()` do not work. Code that does this passes on the dev
    server and fails only once deployed.
    """
    banned = {"new_event_loop", "run_until_complete", "set_event_loop", "run"}

    offenders = [
        f"{node.func.attr} (line {node.lineno})"
        for node in ast.walk(module_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in banned
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in {"asyncio", "loop"}
    ]

    assert not offenders, (
        f"asyncio event-loop calls in {MODULE_PATH.name}: {offenders}. "
        "These break under gunicorn+eventlet in production."
    )


def test_notify_is_gated_on_bot_state(module_tree: ast.Module):
    """POST /notify refuses to send while the bot is stopped.

    GitHub issue #1577: stopping the bot left this endpoint sending messages,
    because only `send_order_alert()` consulted the bot's active flag.
    """
    notify_handlers = [
        node
        for node in ast.walk(module_tree)
        if isinstance(node, ast.FunctionDef)
        and ast.get_docstring(node)
        and "notification to a specific user" in ast.get_docstring(node)
    ]

    assert len(notify_handlers) == 1, "expected exactly one /notify handler"

    gate_checked = any(
        isinstance(node, ast.Attribute) and node.attr == "is_bot_active"
        for node in ast.walk(notify_handlers[0])
    )

    assert gate_checked, (
        "POST /notify must check is_bot_active() before sending, "
        "otherwise a stopped bot keeps delivering messages (issue #1577)"
    )
