"""No log line in the XTS broker family carries a credential.

The XTS integrations (compositedge, fivepaisaxts, ibulls, iifl, jainamxts,
rmoney, wisdom) log their own authentication: the session login, the market
data login, the request headers and the Socket.IO connection. Each of those
holds a token. The log filter in ``utils/logging.py`` masks most shapes, but a
line is safe only while its shape keeps matching, and a token prefix and
suffix (``value=eyJh...ig9x``) never matched at all. So these files must not
put a credential into a log message in the first place.

The check is static: it reads every logging call's f-string and refuses one
that interpolates a credential other than through ``len``, ``type`` or
``bool``, or that slices any token, key or secret. Nothing is imported from the broker packages, so no broker library
is needed and no network is reached. Issue #1853.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

XTS_BROKERS = ("compositedge", "fivepaisaxts", "ibulls", "iifl", "jainamxts", "rmoney", "wisdom")

# samco is not XTS, but it logged its session token's first and last characters
# the same way the XTS adapters did.
EXTRA_FILES = ("broker/samco/streaming/samcoWebSocket.py",)

LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}

# Names that hold a credential, or something with one inside it: the headers
# carry the authorization token, the socket URL carries it in the query, and the
# login payload carries the app key and secret.
CREDENTIAL_NAMES = {
    "auth_token",
    "AUTH_TOKEN",
    "feed_token",
    "FEED_TOKEN",
    "market_data_token",
    "session_token",
    "access_token",
    "api_key",
    "api_secret",
    "secret_key",
    "password",
    "headers",
    "connection_url",
    "login_payload",
}

# A bare ``token`` is usually an instrument token, so it is not refused by
# name. Any slice of a name like these is refused instead: an instrument token is
# never sliced for a log line, and a credential's prefix or suffix is still part
# of the credential.
SECRET_FRAGMENTS = ("token", "key", "secret", "password")

# Wrapping a credential in one of these logs only metadata about it.
SAFE_WRAPPERS = {"len", "type", "bool"}


def _source_files() -> list[Path]:
    files = [
        path for broker in XTS_BROKERS for path in sorted((ROOT / "broker" / broker).rglob("*.py"))
    ]
    return files + [ROOT / name for name in EXTRA_FILES]


def _is_log_call(node: ast.Call) -> bool:
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in LOG_METHODS:
        return False
    target = func.value
    name = target.id if isinstance(target, ast.Name) else getattr(target, "attr", "")
    return name == "logger"


def _identifier(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _names_in(node: ast.AST) -> list[str]:
    return [ident for n in ast.walk(node) if (ident := _identifier(n))]


def _credential_uses(expr: ast.AST) -> list[str]:
    """Credentials in an interpolated expression, outside len/type/bool."""
    found: list[str] = []

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in SAFE_WRAPPERS:
                return
            # The names of the headers, without their values.
            if node.func.id in ("list", "sorted") and [_identifier(a) for a in node.args] == [
                "headers"
            ]:
                return
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
            sliced = [
                n for n in _names_in(node.value) if any(f in n.lower() for f in SECRET_FRAGMENTS)
            ]
            if sliced:
                found.append(f"a slice of {sliced[-1]}")
                return
        # The broker's reply headers, not the ones that carry our token.
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "headers"
            and _identifier(node.value) == "response"
        ):
            return
        ident = _identifier(node)
        if ident in CREDENTIAL_NAMES:
            found.append(ident)
            return
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(expr)
    return found


def _login_reply_logged(fstring: ast.JoinedStr) -> bool:
    """A whole market data login reply, which holds the token on success."""
    text = "".join(part.value for part in fstring.values if isinstance(part, ast.Constant))
    if "LOGIN] Response" not in text:
        return False
    return any(
        isinstance(part, ast.FormattedValue)
        and isinstance(part.value, ast.Name)
        and part.value.id == "result"
        for part in fstring.values
    )


def _sliced_secret(fstring: ast.JoinedStr) -> str | None:
    for part in fstring.values:
        if isinstance(part, ast.FormattedValue):
            for name in _credential_uses(part.value):
                if name.startswith("a slice of"):
                    return name
    return None


def find_leaks(source: str) -> list[str]:
    """Return ``line: message`` for every logging call that interpolates a credential.

    A slice of a secret is refused in any f-string, not only inside a logging
    call: the prefix and suffix were built into a variable first and logged
    through it, which a check on the call alone never sees.
    """
    tree = ast.parse(source)
    leaks: list[str] = []
    logged: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_log_call(node):
            continue
        for arg in node.args:
            for fstring in (n for n in ast.walk(arg) if isinstance(n, ast.JoinedStr)):
                logged.add(id(fstring))
                if _login_reply_logged(fstring):
                    leaks.append(f"{node.lineno}: logs the whole market data login reply")
                for part in fstring.values:
                    if isinstance(part, ast.FormattedValue):
                        for name in _credential_uses(part.value):
                            leaks.append(f"{node.lineno}: interpolates {name}")
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr) and id(node) not in logged:
            sliced = _sliced_secret(node)
            if sliced:
                leaks.append(f"{node.lineno}: builds {sliced} into a string")
    return leaks


# ---------------------------------------------------------------------------
# The checker itself: each pattern that leaked before must be caught, or the
# file-level test below would pass without checking anything.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "snippet",
    [
        'logger.debug(f"Auth Token: {auth_token}")',
        'logger.info(f"Feed token: {FEED_TOKEN}")',
        'logger.debug(f"Headers: {json.dumps(headers, indent=2)}")',
        'self.logger.info(f"Connecting: {connection_url}")',
        'self.logger.info(f"[MARKET DATA LOGIN] Response: {result}")',
        'self.logger.info(f"with token: {self.session_token[:4]}...{self.session_token[-4:]}")',
        'self.logger.debug(f"value={str(token)[:4]}...{str(token)[-4:]}")',
        'logger.debug(f"Using feed token: {feed_token[:20]}..." if feed_token else "No feed token")',
        'self.logger.debug(f"Token: {self.market_data_token[:30] if self.market_data_token else None}...")',
        # Built first, logged through a variable.
        'info = f"value={str(token)[:4]}...{str(token)[-4:]}"\nself.logger.debug(f"token_info: {info}")',
        'preview = f"{self.session_token[:4]}...{self.session_token[-4:]}"\nself.logger.info(f"with: {preview}")',
    ],
)
def test_checker_catches_the_patterns_that_leaked(snippet):
    assert find_leaks(snippet), snippet


@pytest.mark.parametrize(
    "snippet",
    [
        'logger.debug("Auth token received")',
        'logger.debug(f"Header names: {list(headers)}")',
        'self.logger.debug(f"type={type(token)}, len={len(str(token))}")',
        "self.logger.info(f\"[MARKET DATA LOGIN] Response type: {result.get('type')}\")",
        'self.logger.error(f"[MARKET DATA LOGIN] API returned error: {result}")',
        'logger.debug(f"Response Headers: {dict(response.headers)}")',
        # Instrument tokens, not credentials.
        'logger.debug(f"Found token {symbol_info.token} for {exchange}:{br_symbol}")',
        'self.logger.debug(f"symbol={symbol}, exchange={exchange} -> token={token}")',
    ],
)
def test_checker_allows_safe_diagnostics(snippet):
    assert find_leaks(snippet) == [], snippet


# ---------------------------------------------------------------------------
# The broker files.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", _source_files(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_no_credential_reaches_a_log_line(path):
    leaks = find_leaks(path.read_text(encoding="utf-8"))
    assert leaks == [], f"{path.relative_to(ROOT).as_posix()} logs credentials:\n" + "\n".join(
        leaks
    )
