"""Contracts that keep interactive diagnostics out of pytest collection."""

from __future__ import annotations

import ast
import re
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _assigned_string_list(tree: ast.Module, name: str) -> list[str]:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            assert isinstance(value, list)
            return value
    raise AssertionError(f"{name} assignment not found")


def test_interactive_websocket_service_is_ignored_but_keeps_its_cli_entrypoint(
    monkeypatch,
) -> None:
    conftest_tree = ast.parse((ROOT / "test" / "conftest.py").read_text())
    ignored = _assigned_string_list(conftest_tree, "collect_ignore")
    assert "test_websocket_service.py" in ignored

    script_path = ROOT / "test" / "test_websocket_service.py"
    source = script_path.read_text()
    assert re.search(r"[0-9a-fA-F]{64}", source) is None
    assert 'os.getenv("OPENALGO_API_KEY", "")' in source
    script_tree = ast.parse(source)
    functions = {
        node.name: node
        for node in script_tree.body
        if isinstance(node, ast.FunctionDef)
    }
    assert "main" in functions
    assert [argument.arg for argument in functions["test_ltp"].args.args] == [
        "client",
        "symbols",
    ]
    assert any(
        isinstance(node, ast.If)
        and ast.unparse(node.test) == "__name__ == '__main__'"
        and any(
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Name)
            and statement.value.func.id == "main"
            for statement in node.body
        )
        for node in script_tree.body
    )

    monkeypatch.delenv("OPENALGO_API_KEY", raising=False)
    namespace = runpy.run_path(str(script_path), run_name="manual_websocket_service")
    messages: list[str] = []
    main_globals = namespace["main"].__globals__
    main_globals["print"] = lambda message="": messages.append(str(message))
    main_globals["WebSocketClient"] = lambda _api_key: (_ for _ in ()).throw(
        AssertionError("manual script constructed a client without an API key")
    )
    main_globals["test_service_layer_functions"] = lambda: (_ for _ in ()).throw(
        AssertionError("manual script ran service calls without an API key")
    )
    namespace["main"]()

    assert any("OPENALGO_API_KEY is required" in message for message in messages)


def test_live_websocket_script_is_ignored_and_has_no_embedded_api_key(
    monkeypatch,
) -> None:
    conftest_tree = ast.parse((ROOT / "test" / "conftest.py").read_text())
    ignored = _assigned_string_list(conftest_tree, "collect_ignore")
    assert "test_websocket.py" in ignored

    script_path = ROOT / "test" / "test_websocket.py"
    source = script_path.read_text()
    assert re.search(r"[0-9a-fA-F]{64}", source) is None
    assert 'os.environ.get("OPENALGO_API_KEY", "")' in source

    monkeypatch.delenv("OPENALGO_API_KEY", raising=False)
    namespace = runpy.run_path(str(script_path), run_name="manual_websocket_test")
    messages: list[str] = []
    main_globals = namespace["main"].__globals__
    main_globals["print"] = lambda message="": messages.append(str(message))
    monkeypatch.setattr(main_globals["sys"], "argv", [str(script_path)])

    def unexpected_run(_coroutine) -> None:
        raise AssertionError("manual script attempted a connection without an API key")

    monkeypatch.setattr(main_globals["asyncio"], "run", unexpected_run)
    namespace["main"]()

    assert any("OPENALGO_API_KEY is required" in message for message in messages)
