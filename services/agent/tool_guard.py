"""Agent-wide tool hook: turn a refused argument set into a correction.

agno wraps every tool in pydantic's ``validate_call``. When a call arrives with
an argument missing, of the wrong type, or not at all, the tool body never runs
and pydantic's own text becomes the tool result: ``5 validation errors for
MarketToolkit.get_history ... Missing required argument [type=missing_argument,
input_value=ArgsKwargs(()) ...] For further information visit
https://errors.pydantic.dev``. A model reading that has to work out which
arguments mattered, and agno logs a warning with a full traceback for what is
an ordinary correction.

This hook sits outermost on every tool (``Agent(tool_hooks=[...])``) and
rewrites that one case, a :class:`pydantic.ValidationError` raised for the tool
being called, into a ``RetryAgentRun`` naming each missing and each wrong
argument, which is the same channel every tool already uses for a bad value.
Everything else passes through untouched: a ``RetryAgentRun`` or
``StopAgentRun`` from the tool itself, a cancellation, and a ``ValidationError``
raised by some model deep inside a tool body, which is a defect to see in the
log rather than a correction to hand the model.

It runs on the agent's run thread, so it does no I/O and takes no lock. It does
not see a paused confirmation: agno decides to pause before the tool executes,
so an approved call reaches this hook on resume like any other.
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Callable, Mapping
from functools import lru_cache
from typing import Any

from agno.exceptions import RetryAgentRun
from pydantic import ValidationError

from utils.logging import get_logger

logger = get_logger(__name__)

#: pydantic error types that mean the argument was not supplied at all.
_MISSING = frozenset({"missing_argument", "missing", "missing_keyword_only_argument"})
#: pydantic error types that mean an argument the tool does not take.
_UNEXPECTED = frozenset({"unexpected_keyword_argument", "unexpected_positional_argument"})


def _belongs_to(exc: ValidationError, function_name: str) -> bool:
    """Whether the error validates this tool's own arguments.

    ``validate_call`` titles the error with the function's qualified name, such
    as ``MarketToolkit.get_history``.
    """
    title = str(getattr(exc, "title", "") or "")
    return title == function_name or title.endswith(f".{function_name}")


def _field(error: Mapping[str, Any]) -> str:
    location = error.get("loc") or ()
    if not location:
        return "arguments"
    return ".".join(str(part) for part in location)


def correction(function_name: str, exc: ValidationError, arguments: Mapping[str, Any]) -> str:
    """Build the message the model reads instead of pydantic's text.

    Args:
        function_name: The tool's registered name.
        exc: The validation error raised for that tool.
        arguments: The arguments the call carried.

    Returns:
        One paragraph naming what was missing, what was wrong and what to do.
    """
    missing: list[str] = []
    unexpected: list[str] = []
    wrong: list[str] = []
    for error in exc.errors(include_url=False):
        kind = str(error.get("type") or "")
        field = _field(error)
        if kind in _MISSING:
            missing.append(field)
        elif kind in _UNEXPECTED:
            unexpected.append(field)
        else:
            wrong.append(f"{field} ({error.get('msg') or 'invalid value'})")

    if not arguments:
        lead = (
            f"The call to {function_name} was not run because its arguments did not arrive: "
            "it reached the tool with none at all."
        )
    else:
        lead = f"The call to {function_name} was not run because its arguments were refused."

    parts = [lead]
    if missing:
        parts.append(f"Missing: {', '.join(dict.fromkeys(missing))}.")
    if wrong:
        parts.append(f"Wrong type or value: {'; '.join(dict.fromkeys(wrong))}.")
    if unexpected:
        parts.append(
            f"Not arguments of this tool: {', '.join(dict.fromkeys(unexpected))}. Leave them out."
        )
    parts.append(
        f"Call {function_name} again with every required argument filled in, using the "
        "names and formats in its description."
    )
    if not arguments:
        parts.append(
            "If several calls made together in one turn keep arriving empty, make them one at "
            "a time instead."
        )
    return " ".join(parts)


@lru_cache(maxsize=512)
def required_arguments(tool_name: str) -> frozenset[str]:
    """The arguments a registered tool cannot run without.

    Read from the tool method's own signature, which is also what agno builds
    the schema from, so the two cannot disagree. Used before a confirmation is
    shown: a paused call is decided before the tool runs, so pydantic has not
    checked it yet, and an approval card for a call missing its symbol or
    quantity would ask the operator to approve something that cannot run.
    Bounded by the number of tool names, which is fixed by the registry.

    Args:
        tool_name: The tool's registered name.

    Returns:
        The names of its parameters that have no default. Empty for a tool that
        takes none, or a name no registered toolkit defines.
    """
    from services.agent.tools import TOOLKITS

    for spec in TOOLKITS:
        try:
            toolkit = getattr(importlib.import_module(spec.module), spec.attr, None)
        except Exception:
            logger.exception("Could not import toolkit %s to read its signatures", spec.key)
            continue
        method = getattr(toolkit, tool_name, None)
        if not callable(method):
            continue
        return frozenset(
            name
            for name, parameter in inspect.signature(method).parameters.items()
            if name != "self"
            and parameter.default is inspect.Parameter.empty
            and parameter.kind
            in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        )
    return frozenset()


def missing_arguments(tool_name: str, arguments: Mapping[str, Any] | None) -> list[str]:
    """The required arguments a paused call does not carry, in order.

    A required argument sent as null or as an empty string is as missing as one
    left out: pydantic refuses all three once the call runs.

    Args:
        tool_name: The tool's registered name.
        arguments: The arguments the model supplied.

    Returns:
        The missing names, sorted, so the approval card can name them.
    """
    supplied = arguments or {}
    return sorted(
        name
        for name in required_arguments(tool_name)
        if supplied.get(name) is None or supplied.get(name) == ""
    )


def argument_guard(
    function_name: str, function_call: Callable[..., Any], arguments: dict[str, Any]
) -> Any:
    """Run the tool, rewriting a refusal of its own arguments into a correction.

    The parameter names are the ones agno matches when it builds a hook's call.

    Args:
        function_name: The tool's registered name.
        function_call: The next link in agno's chain, ending at the tool.
        arguments: The arguments the model supplied.

    Returns:
        Whatever the tool returned.

    Raises:
        RetryAgentRun: When pydantic refused this tool's arguments.
    """
    try:
        return function_call(**arguments)
    except ValidationError as exc:
        if not _belongs_to(exc, function_name):
            raise
        message = correction(function_name, exc, arguments or {})
        logger.warning(
            "Agent tool %s refused its arguments (%d errors, %s argument keys)",
            function_name,
            exc.error_count(),
            len(arguments or {}),
        )
        raise RetryAgentRun(message) from None
