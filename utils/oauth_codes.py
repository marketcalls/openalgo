"""In-memory authorization code store with TTL.

Authorization codes are deliberately NOT persisted: they live ~60 seconds
and a process restart legitimately invalidates any in-flight OAuth dance.
A short-lived dict with a janitor pass on every access is enough.

Thread/eventlet safety: a single :class:`threading.Lock` protects all
mutations. Eventlet monkey-patches ``threading.Lock`` to a green-thread
mutex so this is a no-op cost in production. The locked critical
sections are tiny (dict ops only) so no scheduler starvation.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Optional


# Default per the PRD. Configurable via MCP_OAUTH_CODE_TTL but capped at
# 5 minutes regardless — RFC 6749 §4.1.2 recommends "very short".
_DEFAULT_TTL = 60
_MAX_TTL = 300


@dataclass
class AuthorizationCode:
    """Issued at /oauth/authorize, consumed at /oauth/token.

    All fields except ``used`` are written exactly once at issuance.
    ``used`` flips to True the first time the code is consumed —
    subsequent presentations of the same code are rejected (and the
    family-of-tokens that may have been issued from it on the prior
    success is left alone; reuse-detection on refresh tokens covers
    the post-issuance attack path).
    """

    code: str
    client_id: str
    redirect_uri: str
    scope: str
    user_id: int
    code_challenge: str
    code_challenge_method: str
    issued_at: float
    expires_at: float
    state: str | None = None
    used: bool = False


class _CodeStore:
    """A small TTL dict. Lookup and consume run in O(1)."""

    def __init__(self) -> None:
        self._codes: dict[str, AuthorizationCode] = {}
        self._lock = threading.Lock()

    def _purge(self, now: float) -> None:
        # Called under the lock. Drop expired or used codes whose
        # ``used`` flag has been set for longer than the TTL — keeps
        # the dict bounded under burst traffic.
        stale = [c for c, e in self._codes.items() if e.expires_at < now]
        for c in stale:
            self._codes.pop(c, None)

    def issue(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        scope: str,
        user_id: int,
        code_challenge: str,
        code_challenge_method: str,
        state: str | None,
        ttl_seconds: int = _DEFAULT_TTL,
    ) -> AuthorizationCode:
        """Mint a new authorization code. Returns the freshly stored entry."""
        ttl = max(1, min(int(ttl_seconds), _MAX_TTL))
        code_value = secrets.token_urlsafe(32)
        now = time.time()
        entry = AuthorizationCode(
            code=code_value,
            client_id=client_id,
            redirect_uri=redirect_uri,
            scope=scope,
            user_id=user_id,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            state=state,
            issued_at=now,
            expires_at=now + ttl,
        )
        with self._lock:
            self._purge(now)
            self._codes[code_value] = entry
        return entry

    def consume(self, code: str) -> AuthorizationCode | None:
        """Return the code if it exists, isn't expired, and hasn't been used.

        Marks it used as a side-effect — calling consume() twice for
        the same code returns None on the second call. The first
        successful call is the only path that should issue tokens.
        """
        if not code:
            return None
        now = time.time()
        with self._lock:
            self._purge(now)
            entry = self._codes.get(code)
            if entry is None:
                return None
            if entry.used:
                return None
            if entry.expires_at < now:
                return None
            entry.used = True
            return entry

    def discard(self, code: str) -> None:
        """Drop a code from the store. Used on consent rejection."""
        with self._lock:
            self._codes.pop(code, None)

    def __len__(self) -> int:  # for tests / observability
        with self._lock:
            return len(self._codes)


# Module-level singleton — single store per process. Fine for OpenAlgo's
# single-eventlet-worker production model. Multi-worker deployments
# would need a shared backend (Redis), but the broader architecture
# already mandates -w 1 for SocketIO.
_store = _CodeStore()


def issue(
    *,
    client_id: str,
    redirect_uri: str,
    scope: str,
    user_id: int,
    code_challenge: str,
    code_challenge_method: str,
    state: str | None,
    ttl_seconds: int = _DEFAULT_TTL,
) -> AuthorizationCode:
    return _store.issue(
        client_id=client_id,
        redirect_uri=redirect_uri,
        scope=scope,
        user_id=user_id,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        state=state,
        ttl_seconds=ttl_seconds,
    )


def consume(code: str) -> AuthorizationCode | None:
    return _store.consume(code)


def discard(code: str) -> None:
    _store.discard(code)


def size() -> int:
    return len(_store)
