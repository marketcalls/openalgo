"""Check a strategy file against what /python actually runs.

    uv run python .claude/skills/python-strategy/validate.py <strategy.py> [...]

Static: nothing is executed and nothing is sent. It reads the file's syntax
tree and holds it against the real host and the installed SDK:

* every import must exist in what a server install gets (OpenAlgo's main
  dependencies, from uv.lock), because /python runs strategies with
  OpenAlgo's own interpreter, not with any other environment
* every client call must be a method of the installed openalgo SDK, with its
  required arguments, and literal exchange / product / price type / action
  values must be ones OpenAlgo accepts
* the file must start, stop and authenticate the way /python expects
* a kit strategy's settings must make sense together

Exit 0 when there is no FAIL. A WARN is a way the file runs and then
misbehaves; treat it as a FAIL unless you know why it is fine.
"""

from __future__ import annotations

import ast
import difflib
import importlib.metadata
import importlib.util
import inspect
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _host  # noqa: E402
import kit_sync  # noqa: E402

EXCHANGES = {
    "NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX", "NCDEX", "NCO",
    "NSE_INDEX", "BSE_INDEX", "GLOBAL_INDEX", "CRYPTO",
}  # fmt: skip
PRODUCTS = {"CNC", "NRML", "MIS"}
PRICE_TYPES = {"MARKET", "LIMIT", "SL", "SL-M"}
ACTIONS = {"BUY", "SELL"}
INTERVALS = {"1m", "3m", "5m", "10m", "15m", "30m", "1h", "60m", "D"}
FNO = {"NFO", "BFO", "MCX", "CDS", "BCD", "NCDEX", "NCO"}
CASH = {"NSE", "BSE"}
CLIENT_FACTORIES = {"api", "_OpenAlgoClient", "connect"}
TIME_SETTINGS = (
    "ENTRY_START", "ENTRY_END", "SQUARE_OFF", "DECISION_TIME", "ENTRY_TIME", "EXIT_TIME",
)  # fmt: skip
ELSEWHERE = {
    "vectorbt": "vectorbt is not installed with OpenAlgo. Use the skill's backtest.py; for "
    "research-grade backtests keep vectorbt in a separate script, not in the hosted file.",
    "talib": "TA-Lib is not installed with OpenAlgo. openalgo.ta has the same indicators "
    "(ta.rsi, ta.macd, ta.bbands, ta.atr, ...) and more.",
    "pandas_ta": "pandas_ta is not installed with OpenAlgo. Use openalgo.ta.",
    "sklearn": "scikit-learn is not installed with OpenAlgo. Train elsewhere and put the "
    "fitted numbers (weights, thresholds) in the file's settings.",
    "xgboost": "xgboost is not installed with OpenAlgo.",
    "quantstats": "quantstats is not installed with OpenAlgo.",
    "kiteconnect": "Broker SDKs do not belong in a hosted strategy: OpenAlgo is the broker "
    "connection. Use the openalgo client.",
}


@dataclass
class Report:
    path: Path
    lines: list[tuple[str, str]] = field(default_factory=list)

    def add(self, level: str, message: str) -> None:
        self.lines.append((level, message))

    fixed_host: bool = False  # OpenAlgo's address typed into the file

    @property
    def failures(self) -> int:
        return sum(1 for level, _ in self.lines if level == "FAIL")

    @property
    def warnings(self) -> int:
        return sum(1 for level, _ in self.lines if level == "WARN")


# ---------------------------------------------------------------------------
# What a server install has
# ---------------------------------------------------------------------------

_closure_cache: set[str] | None = None


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def server_distributions() -> set[str] | None:
    """Distributions a server install gets: OpenAlgo's main dependencies and
    everything they pull in, from uv.lock. None when uv is not available."""
    global _closure_cache
    if _closure_cache is None:
        try:
            out = subprocess.run(
                ["uv", "export", "--frozen", "--no-dev", "--no-hashes", "--no-emit-project"],
                cwd=_host.REPO,
                capture_output=True,
                text=True,
                timeout=60,
                check=True,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        names = set()
        for line in out.splitlines():
            line = line.strip()
            if line and not line.startswith(("#", "-")):
                names.add(_norm(re.split(r"[=<>~;\[ ]", line, maxsplit=1)[0]))
        _closure_cache = names
    return _closure_cache


def check_import(module: str, path: Path, report: Report, seen: set[str]) -> None:
    top = module.split(".")[0]
    if not top or module in seen:
        return
    seen.add(module)
    if top == "services":
        if module not in ("services", "services.risk") and not module.startswith("services.risk."):
            report.add(
                "FAIL",
                f"imports {module}, an OpenAlgo internal module. A strategy talks to OpenAlgo "
                "through the API (the openalgo client); only services.risk, the pure risk "
                "engine, is imported directly.",
            )
        return
    if (path.parent / f"{top}.py").exists() or (path.parent / top / "__init__.py").exists():
        report.add(
            "FAIL",
            f"imports {top} from a file beside the strategy. /python uploads one file only, "
            f"so {top} will not be there. Put what it needs into this file.",
        )
        return
    if top in sys.stdlib_module_names:
        return
    if (_host.REPO / top).is_dir() or (_host.REPO / f"{top}.py").is_file():
        report.add(
            "FAIL",
            f"imports {top}, part of OpenAlgo itself. A strategy talks to OpenAlgo through "
            "the API (the openalgo client), which keeps working across upgrades.",
        )
        return
    if top in ELSEWHERE:
        report.add("FAIL", f"imports {top}. {ELSEWHERE[top]}")
        return
    if importlib.util.find_spec(top) is None:
        report.add(
            "FAIL",
            f"imports {top}, which is not installed in OpenAlgo's environment, the only one "
            "/python runs strategies with.",
        )
        return
    closure = server_distributions()
    if closure is None:
        return
    dists = {_norm(d) for d in importlib.metadata.packages_distributions().get(top, [])}
    if dists and not dists & closure:
        report.add(
            "FAIL",
            f"imports {top} ({', '.join(sorted(dists))}), which is installed here but is not "
            "one of OpenAlgo's dependencies, so a server install does not have it.",
        )


# ---------------------------------------------------------------------------
# The installed SDK
# ---------------------------------------------------------------------------


def sdk_methods() -> dict[str, inspect.Signature]:
    from openalgo import api

    found = {}
    for name in dir(api):
        if not name.startswith("_") and callable(getattr(api, name)):
            try:
                found[name] = inspect.signature(getattr(api, name))
            except (TypeError, ValueError):
                pass
    return found


def _literal(node: ast.AST):
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        return None


def _is_client(node: ast.AST, names: set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in names
    if isinstance(node, ast.Attribute):
        return node.attr == "client"
    return False


def check_sdk_call(call: ast.Call, method: str, sdk: dict, report: Report) -> None:
    line = call.lineno
    if method not in sdk:
        close = difflib.get_close_matches(method, sdk, n=1)
        hint = f" Did you mean {close[0]}?" if close else ""
        report.add("FAIL", f"line {line}: client.{method} is not an openalgo SDK method.{hint}")
        return
    params = sdk[method].parameters
    named = {n for n, p in params.items() if n != "self" and p.kind != p.VAR_KEYWORD}
    takes_any = any(p.kind == p.VAR_KEYWORD for p in params.values())
    splat = any(kw.arg is None for kw in call.keywords)
    given = {kw.arg for kw in call.keywords if kw.arg}
    required = [
        n
        for n, p in params.items()
        if n != "self" and p.kind == p.KEYWORD_ONLY and p.default is p.empty
    ]
    missing = [n for n in required if n not in given]
    if missing and not splat:
        report.add(
            "FAIL",
            f"line {line}: client.{method} needs {', '.join(missing)}, which this call omits.",
        )
    for kw in call.keywords:
        if not kw.arg or kw.arg in named:
            continue
        close = difflib.get_close_matches(kw.arg, named, n=1, cutoff=0.8)
        if not takes_any:
            report.add("FAIL", f"line {line}: client.{method} has no argument {kw.arg}.")
        elif close:
            report.add(
                "WARN",
                f"line {line}: client.{method}({kw.arg}=...) is not an argument it names; "
                f"it is sent to OpenAlgo as-is. Did you mean {close[0]}?",
            )
    if method == "placesmartorder":
        given_kw = {kw.arg: kw.value for kw in call.keywords if kw.arg}
        size = _literal(given_kw["position_size"]) if "position_size" in given_kw else None
        quantity = given_kw.get("quantity")
        if size == 0 and quantity is not None and _literal(quantity) != 0:
            report.add(
                "FAIL",
                f"line {line}: placesmartorder(position_size=0) with a non-zero quantity "
                "opens a NEW position of that quantity when the account is already flat (a "
                "manual exit or the broker's square-off got there first). To close, send "
                "quantity=0, position_size=0, as the kit's flatten() does.",
            )
    for kw in call.keywords:
        value = _literal(kw.value)
        if not isinstance(value, str):
            continue
        allowed = {
            "exchange": EXCHANGES,
            "product": PRODUCTS,
            "price_type": PRICE_TYPES,
            "pricetype": PRICE_TYPES,
            "action": ACTIONS,
        }.get(kw.arg)
        if allowed and value not in allowed:
            report.add(
                "FAIL",
                f"line {line}: {kw.arg}={value!r} is not accepted. Use one of "
                f"{', '.join(sorted(allowed))}.",
            )
        if kw.arg == "interval" and value not in INTERVALS:
            report.add(
                "WARN",
                f"line {line}: interval={value!r} is not a common interval; check "
                "client.intervals() for what your broker offers.",
            )


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------


def _reads_env(node: ast.AST) -> bool:
    """os.getenv(...) or os.environ.get(...) / os.environ[...]."""
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "getenv":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "get":
            return getattr(func.value, "attr", "") == "environ"
    return isinstance(node, ast.Subscript) and getattr(node.value, "attr", "") == "environ"


def env_fallbacks(tree: ast.Module) -> set[int]:
    """ids of string literals used only as a fallback after an environment
    read: os.getenv("HOST_SERVER") or "http://...", os.getenv("X", "...")."""
    exempt: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            if any(_reads_env(v) for v in node.values):
                exempt.update(id(v) for v in node.values if isinstance(v, ast.Constant))
        if _reads_env(node) and isinstance(node, ast.Call) and len(node.args) > 1:
            exempt.add(id(node.args[1]))
    return exempt


def settings(tree: ast.Module) -> dict[str, object]:
    found: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id.isupper():
                found[target.id] = _literal(node.value)
    return found


def functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}


def validate(path: Path) -> Report:
    report = Report(path)
    if not path.is_file():
        report.add("FAIL", "file not found")
        return report
    raw = path.read_bytes()
    if len(raw) > 1024 * 1024:
        report.add("FAIL", f"file is {len(raw) // 1024} KB; /python accepts up to 1 MB")
    text = raw.decode("utf-8", errors="replace")
    try:
        tree = ast.parse(text, filename=str(path))
        compile(tree, str(path), "exec")
    except SyntaxError as exc:
        report.add("FAIL", f"line {exc.lineno}: does not parse: {exc.msg}")
        return report
    report.add("PASS", f"parses under OpenAlgo's Python {sys.version_info.major}."
               f"{sys.version_info.minor}")  # fmt: skip

    strategy_part, block = kit_sync.split(text)
    uses_kit = block is not None
    sdk = sdk_methods()
    seen: set[str] = set()
    client_names = {"client"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            func = node.value.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name in CLIENT_FACTORIES:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        client_names.add(target.id)

    has_main = sleeps = writes = sigterm = False
    fallbacks = env_fallbacks(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                check_import(alias.name, path, report, seen)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            check_import(node.module, path, report, seen)
            if node.module == "services":
                for alias in node.names:
                    check_import(f"services.{alias.name}", path, report, seen)
        elif isinstance(node, ast.If):
            test = node.test
            if (
                isinstance(test, ast.Compare)
                and isinstance(test.left, ast.Name)
                and test.left.id == "__name__"
            ):
                has_main = True
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if re.fullmatch(r"[0-9a-f]{64}", node.value):
                report.add(
                    "WARN",
                    f"line {node.lineno}: an API key is typed into the file. It works, but it "
                    "travels with every copy of the file and stops working when the key is "
                    "regenerated. Under /python, leave API_KEY to the environment.",
                )
            if (
                re.match(r"https?://", node.value)
                and ("/api/v1" in node.value or ":5000" in node.value)
                and id(node) not in fallbacks
            ):
                report.fixed_host = True
                report.add(
                    "WARN",
                    f"line {node.lineno}: OpenAlgo's address is typed into the file "
                    f"({node.value}), so it works on that server only, and rehearse.py cannot "
                    "hold its orders back. Under /python, leave HOST to the environment.",
                )
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "input":
                report.add(
                    "FAIL",
                    f"line {node.lineno}: input() waits for a keyboard that a hosted strategy "
                    "does not have, so it waits forever.",
                )
            if isinstance(func, ast.Attribute):
                owner = func.value
                if func.attr == "sleep" and getattr(owner, "id", "") in ("time", "_clock"):
                    sleeps = True
                if func.attr in ("to_csv", "to_parquet", "write_text", "write_bytes"):
                    writes = True
                if func.attr == "signal" and node.args:
                    first = node.args[0]
                    if getattr(first, "attr", None) == "SIGTERM":
                        sigterm = True
                if _is_client(owner, client_names):
                    check_sdk_call(node, func.attr, sdk, report)
            if isinstance(func, ast.Name) and func.id in ("api", "_OpenAlgoClient"):
                for kw in node.keywords:
                    if kw.arg == "host" and isinstance(kw.value, ast.Constant):
                        report.fixed_host = True
            if isinstance(func, ast.Name) and func.id == "open" and len(node.args) > 1:
                mode = _literal(node.args[1])
                if isinstance(mode, str) and any(c in mode for c in "wa+"):
                    writes = True

    if not has_main:
        report.add(
            "FAIL",
            'no `if __name__ == "__main__":` block, so nothing runs when /python starts it.',
        )
    if not sigterm:
        report.add(
            "WARN",
            "no SIGTERM handler. Stop at /python (and the schedule's stop) sends SIGTERM; "
            "without a handler the strategy dies mid-step with no chance to log or clean up.",
        )
    if sleeps:
        report.add(
            "WARN",
            "calls time.sleep(). A stop arriving during the sleep is not noticed until it "
            "ends, and /python kills the strategy 5 seconds after Stop. Wait with "
            "pause(seconds) (kit) or a threading.Event's wait() instead.",
        )
    if writes:
        report.add(
            "WARN",
            "writes files. Under /python the file runs from strategies/scripts, shared with "
            "every other strategy, and the working folder is OpenAlgo's own. Keep state at "
            "the broker (positions, orders) rather than in local files.",
        )
    if not any(level == "FAIL" and "imports" in msg for level, msg in report.lines):
        names = sorted({m.split(".")[0] for m in seen if m.split(".")[0] not in
                        sys.stdlib_module_names})  # fmt: skip
        report.add("PASS", "every import is available under /python"
                   + (f" ({', '.join(names)})" if names else ""))  # fmt: skip

    if uses_kit:
        check_kit_strategy(tree, strategy_part, block, report)
    return report


def check_kit_strategy(tree, strategy_part, block, report: Report) -> None:
    current = kit_sync.kit_text()
    have, want = kit_sync.kit_version(block), kit_sync.kit_version()
    if block != current:
        if have != want:
            report.add(
                "WARN",
                f"carries kit {have}; the current kit is {want}. Take it with "
                "kit_sync.py --write (the settings and signals above the kit stay as they are).",
            )
        else:
            report.add(
                "WARN",
                f"the kit {have} block was edited by hand. kit_sync.py --write would undo "
                "those edits; move them above the kit block.",
            )
    else:
        report.add("PASS", f"kit {have} block is intact")

    found = settings(tree)
    fns = functions(tree)
    custom = "run_live" in fns
    if not custom and "signals" not in fns:
        report.add("FAIL", "no signals(df) and no run_live(), so the kit has nothing to run.")
    exchange = str(found.get("EXCHANGE") or "NSE")
    product = str(found.get("PRODUCT") or "MIS")
    for name, allowed in (("EXCHANGE", EXCHANGES), ("PRODUCT", PRODUCTS)):
        value = found.get(name)
        if value is not None and value not in allowed:
            report.add("FAIL", f"{name} = {value!r} is not one of {', '.join(sorted(allowed))}.")
    if not custom and found.get("INTERVAL") not in (None, *INTERVALS):
        report.add("FAIL", f"INTERVAL = {found.get('INTERVAL')!r} is not one the kit runs.")
    if found.get("SIDES") not in (None, "long", "short", "both"):
        report.add("FAIL", 'SIDES must be "long", "short" or "both".')
    if product == "CNC" and exchange in FNO:
        report.add("FAIL", f"PRODUCT CNC is for NSE/BSE delivery; {exchange} uses NRML or MIS.")
    if product == "NRML" and exchange in CASH:
        report.add("FAIL", f"PRODUCT NRML is for F&O; {exchange} equity uses CNC or MIS.")
    if exchange in ("NSE_INDEX", "BSE_INDEX") and not custom:
        report.add(
            "FAIL",
            f"{exchange} is an index: it has prices but cannot be traded. Trade its futures "
            "(resolve_symbol with pick_expiry and futures_symbol) or its options (run_live).",
        )
    for name in TIME_SETTINGS:
        value = found.get(name)
        if value is not None and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(value)):
            report.add("FAIL", f'{name} = {value!r} must be a 24-hour "HH:MM" time.')
    if product == "MIS" and not custom and not found.get("SQUARE_OFF"):
        report.add(
            "WARN",
            "PRODUCT is MIS but SQUARE_OFF is not set. The broker then squares off on its "
            "own, at its time and price, often for a fee.",
        )
    end, square = found.get("ENTRY_END"), found.get("SQUARE_OFF")
    if end and square and str(end) >= str(square):
        report.add("WARN", f"ENTRY_END {end} is not before SQUARE_OFF {square}.")
    for kind in ("STOP_LOSS", "TARGET", "TRAIL"):
        if found.get(f"{kind}_PCT") and found.get(f"{kind}_POINTS"):
            report.add("WARN", f"both {kind}_PCT and {kind}_POINTS are set; points win.")
    if not custom and not (found.get("STOP_LOSS_PCT") or found.get("STOP_LOSS_POINTS")):
        report.add("WARN", "no stop loss: STOP_LOSS_PCT and STOP_LOSS_POINTS are both off.")
    if "signals" in fns:
        for node in ast.walk(fns["signals"]):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "attr", None) == "shift"
                and node.args
            ):
                amount = _literal(node.args[0])
                if isinstance(amount, (int, float)) and amount < 0:
                    report.add(
                        "FAIL",
                        f"line {node.lineno}: signals() uses shift({amount}), which reads "
                        "future bars. Live trading cannot, so the backtest would lie.",
                    )
            if isinstance(node, ast.Subscript) and getattr(node.value, "attr", "") == "iloc":
                report.add(
                    "WARN",
                    f"line {node.lineno}: signals() indexes with .iloc. It must return a flag "
                    "for every bar, computed from that bar and earlier ones, not one value.",
                )
    calendar = {"NSE_INDEX": "NSE", "BSE_INDEX": "BSE"}.get(exchange, exchange)
    if calendar not in _host.host_exchanges():
        report.add("WARN", f"/python cannot schedule on {calendar}; pick the closest exchange.")


def upload_hint(path: Path) -> str | None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    found = settings(tree)
    exchange = str(found.get("EXCHANGE") or "")
    if not exchange:
        return None
    calendar = {"NSE_INDEX": "NSE", "BSE_INDEX": "BSE"}.get(exchange, exchange)
    return f"At /python, upload with exchange {calendar}."


def main() -> int:
    paths = [Path(p) for p in sys.argv[1:]]
    if not paths:
        print(__doc__)
        return 2
    failed = 0
    for path in paths:
        report = validate(path)
        print(f"Validating {path}")
        order = {"FAIL": 0, "WARN": 1, "PASS": 2}
        for level, message in sorted(report.lines, key=lambda x: order[x[0]]):
            print(f"  {level}  {message}")
        if report.failures:
            verdict = "NOT READY"
        elif report.fixed_host:
            verdict = "runs, but rehearse.py needs HOST from the environment"
        elif report.warnings:
            verdict = "ready to rehearse, after reading the warnings"
        else:
            verdict = "ready to rehearse"
        print(f"Result: {verdict} ({report.failures} failed, {report.warnings} warnings)")
        hint = upload_hint(path)
        if hint and not report.failures:
            print(hint)
        print()
        failed += bool(report.failures)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
