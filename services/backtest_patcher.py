# services/backtest_patcher.py
"""
Strategy Patcher — Transforms live strategy code for backtest execution.

Approach: Regex-based transformation + namespace injection.
- Intercepts `from openalgo import api` and `api()` constructor
- Replaces `time.sleep()` with a signal to advance to next bar
- Extracts while-True loop body as a single-iteration function
- Provides a safe, sandboxed execution namespace

AST-based approach can be added later for robustness.
"""

import re
import types

from utils.logging import get_logger

logger = get_logger(__name__)


class BarComplete(Exception):
    """Raised when strategy calls time.sleep() — signals engine to advance."""
    pass


class StrategyPatcher:
    """
    Transform a live trading strategy into a backtest-compatible iteration function.
    """

    def patch(self, source_code, client):
        """
        Patch strategy source code and return a callable that executes one iteration.

        Args:
            source_code: Python source code of the strategy
            client: BacktestClient instance to inject

        Returns:
            callable: A function that runs one iteration of the strategy logic

        Raises:
            ValueError: If no strategy entry point can be found
        """
        # Step 1: Remove openalgo imports (we inject our own)
        code = self._remove_openalgo_imports(source_code)

        # Step 2: Replace api() constructor calls with client reference
        code = self._replace_api_constructor(code)

        # Step 3: Try to extract while-True loop body as iteration function
        has_while_loop = self._has_while_true(code)
        if has_while_loop:
            code = self._extract_loop_body(code)

        # Step 4: Remove time.sleep calls (they'd be inside extracted function)
        code = self._remove_sleep_calls(code)

        # Step 5: Build safe namespace
        namespace = self._build_namespace(client)

        # Step 6: Execute the patched code to define functions
        try:
            compiled = compile(code, "<backtest_strategy>", "exec")
            exec(compiled, namespace)
        except Exception as e:
            raise ValueError(f"Failed to compile strategy code: {e}") from e

        # Step 7: Find and return the iteration function
        return self._find_entry_point(namespace, has_while_loop, code, client)

    def _remove_openalgo_imports(self, code):
        """Remove openalgo import statements."""
        code = re.sub(
            r"^\s*from\s+openalgo\s+import\s+api\s*$",
            "# [backtest] openalgo import intercepted",
            code,
            flags=re.MULTILINE,
        )
        code = re.sub(
            r"^\s*import\s+openalgo\s*$",
            "# [backtest] openalgo import intercepted",
            code,
            flags=re.MULTILINE,
        )
        return code

    def _replace_api_constructor(self, code):
        """Replace api(...) constructor calls with _backtest_client reference."""
        # Match: client = api(api_key=..., host=...)
        # or: client = api(...)
        code = re.sub(
            r"(\w+)\s*=\s*api\s*\([^)]*\)",
            r"\1 = _backtest_client",
            code,
        )
        return code

    def _has_while_true(self, code):
        """Check if the code contains a while True loop."""
        return bool(re.search(r"while\s+(True|1)\s*:", code))

    def _extract_loop_body(self, code):
        """
        Extract the body of `while True:` into `def _backtest_iteration():`.

        This handles the common strategy pattern:
            while True:
                ... strategy logic ...
                time.sleep(N)
        """
        lines = code.split("\n")
        result = []
        in_while_loop = False
        while_indent = 0
        found_loop = False

        for i, line in enumerate(lines):
            stripped = line.lstrip()
            indent = len(line) - len(stripped)

            if not in_while_loop:
                if re.match(r"while\s+(True|1)\s*:", stripped) and not found_loop:
                    in_while_loop = True
                    while_indent = indent
                    found_loop = True
                    result.append(" " * indent + "def _backtest_iteration():")
                    continue
                result.append(line)
            else:
                # Check if we've exited the while block
                if stripped and indent <= while_indent:
                    in_while_loop = False
                    result.append(line)
                else:
                    result.append(line)

        return "\n".join(result)

    def _remove_sleep_calls(self, code):
        """Remove time.sleep() calls from the code."""
        code = re.sub(
            r"^\s*time\.sleep\s*\([^)]*\)\s*$",
            "",
            code,
            flags=re.MULTILINE,
        )
        return code

    # Modules blocked from import inside strategy code (network, subprocess, etc.)
    BLOCKED_MODULES = frozenset({
        "requests", "urllib", "urllib2", "httplib", "http.client",
        "socket", "socketserver", "xmlrpc", "ftplib", "smtplib",
        "subprocess", "shutil", "signal", "ctypes", "multiprocessing",
        "threading", "asyncio", "aiohttp", "websocket", "paramiko",
        "boto3", "botocore", "google", "azure",
    })

    def _build_namespace(self, client):
        """Build a safe execution namespace with injected dependencies."""
        import builtins
        import datetime
        import json
        import math

        import numpy as np
        import pandas as pd

        # Create a safe os module (allow getenv, block filesystem writes)
        safe_os = types.ModuleType("os")
        import os as real_os
        safe_os.getenv = real_os.getenv
        safe_os.environ = real_os.environ
        safe_os.path = real_os.path
        safe_os.getcwd = real_os.getcwd

        # Create a safe time module (sleep is a no-op)
        safe_time = types.ModuleType("time")
        safe_time.sleep = lambda *args, **kwargs: None  # no-op in backtest
        safe_time.time = lambda: client.current_timestamp or 0
        safe_time.monotonic = lambda: client.current_timestamp or 0

        # Restricted __import__ that blocks dangerous modules
        blocked = self.BLOCKED_MODULES
        original_import = builtins.__import__

        def _restricted_import(name, *args, **kwargs):
            top_level = name.split(".")[0]
            if top_level in blocked:
                raise ImportError(
                    f"Module '{name}' is blocked in backtest sandbox for security."
                )
            return original_import(name, *args, **kwargs)

        # Build restricted builtins (copy all then override __import__)
        restricted_builtins = dict(vars(builtins))
        restricted_builtins["__import__"] = _restricted_import

        namespace = {
            "__builtins__": restricted_builtins,
            # Injected client
            "_backtest_client": client,
            "api": lambda *args, **kwargs: client,
            # Standard library
            "pd": pd,
            "pandas": pd,
            "np": np,
            "numpy": np,
            "os": safe_os,
            "time": safe_time,
            "datetime": datetime,
            "json": json,
            "math": math,
            # Convenience
            "print": self._safe_print,
        }

        return namespace

    def _safe_print(self, *args, **kwargs):
        """Capture print statements (silently in backtest mode)."""
        pass

    def _find_entry_point(self, namespace, has_while_loop, code, client):
        """
        Find the callable entry point in the patched namespace.
        Priority:
        1. _backtest_iteration (extracted from while loop)
        2. Named functions: main, run, strategy, execute, ema_strategy, etc.
        3. If __name__ == "__main__" block functions
        """
        # Priority 1: extracted iteration function
        if "_backtest_iteration" in namespace and callable(namespace["_backtest_iteration"]):
            return namespace["_backtest_iteration"]

        # Priority 2: common entry point names
        common_names = [
            "main", "run", "strategy", "execute",
            "ema_strategy", "run_strategy", "start_strategy",
            "trading_strategy", "algo",
        ]
        for name in common_names:
            if name in namespace and callable(namespace[name]):
                return namespace[name]

        # Priority 3: scan for any function called in __name__ == __main__ block
        main_match = re.search(
            r'if\s+__name__\s*==\s*["\']__main__["\']\s*:\s*\n\s+(\w+)\s*\(',
            code,
        )
        if main_match:
            func_name = main_match.group(1)
            if func_name in namespace and callable(namespace[func_name]):
                return namespace[func_name]

        # Priority 4: find any user-defined function (excluding dunder methods)
        user_funcs = [
            (name, obj) for name, obj in namespace.items()
            if callable(obj)
            and not name.startswith("_")
            and name not in ("api", "print")
            and isinstance(obj, types.FunctionType)
        ]
        if len(user_funcs) == 1:
            return user_funcs[0][1]

        # If no while loop was found and no functions, the code might be
        # a simple script — wrap the entire code as a function
        if not has_while_loop:
            def _script_iteration():
                pass  # Already executed during compile/exec
            return _script_iteration

        raise ValueError(
            "Could not find strategy entry point. "
            "Strategy must have a while True loop, or a main()/run()/strategy() function."
        )
