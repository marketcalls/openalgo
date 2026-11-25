"""One market-data token per Symphony XTS broker, shared by every process.

An XTS market-data session allows one live token per app key: each login to
``/apibinarymarketdata/auth/login`` ends the token issued before it. OpenAlgo
reaches market data from two processes, the web worker (quotes, depth,
history) and the websocket proxy (the live feed), and each used to log in on
its own whenever its token was refused. One side's login ended the other's
token, the other logged in again, and on IIFL that cycle ran every few seconds
for as long as anything polled quotes: the feed's subscriptions failed with
``e-session-0007 Invalid Token`` and history requests failed with the same
words.

Both sides now use the token stored in the broker's ``auth`` row. A side whose
token is refused calls :meth:`MarketDataTokenStore.renew` with that token:

* if the stored token is already a different one, another side renewed it,
  and that token is returned without a login;
* otherwise one login is made and its token stored with a compare-and-set on
  the exact stored value (``database.auth_db.replace_market_data_token``),
  which never revives a signed-out row and never runs upsert_auth's feed
  teardown.

Two renewals in different processes at the same instant can still each log
in; the loser's next refusal finds the winner's token stored and adopts it,
so the sides settle on one token after at most one extra round instead of
alternating forever.

No lock is held across the broker login: under eventlet a real lock held
across a network call freezes the hub (CLAUDE.md). Within one process a
second caller waits in short sleeps (green under eventlet) while the first
logs in, then reads what it stored.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from utils import real_threading
from utils.logging import get_logger

logger = get_logger(__name__)

#: A login function returning ``(token, user_id, error)``, as the XTS
#: plugins' ``auth_api.get_feed_token`` do.
LoginFn = Callable[[], tuple]

_WAIT_STEP = 0.2  # seconds between checks while this process's renewal runs
_WAIT_STEPS = 50  # about ten seconds at most


class MarketDataTokenStore:
    """The shared market-data token of one broker, in this process."""

    def __init__(self, broker: str, login: LoginFn):
        self.broker = broker
        self._login = login
        self._state = real_threading.Lock()  # guards _renewing only: no I/O under it
        self._renewing = False
        #: The ``userID`` of this process's last login reply. The streaming
        #: socket's address needs it, and it is fixed for an account, so it
        #: is remembered. It is NOT the token's ``userID`` claim, which has a
        #: suffix ("1048131_856F2F...") the socket address does not take.
        self.user_id: str | None = None

    def current(self) -> str | None:
        """The stored token, read fresh from the database."""
        from database.auth_db import read_market_data_token

        return read_market_data_token(self.broker)[1]

    def renew(self, rejected: str | None, need_user_id: bool = False) -> str | None:
        """A token to use in place of ``rejected``, the one just refused.

        Returns the stored token when it is already a different one, else the
        token of one new login (stored for the other side when the row still
        holds what was read). ``None`` when no token could be had.

        ``need_user_id``: the caller needs :attr:`user_id`, which only a login
        reply carries; while it is unknown in this process, log in rather than
        adopt.
        """
        from database.auth_db import read_market_data_token, replace_market_data_token

        for _ in range(_WAIT_STEPS):
            stored_blob, stored = read_market_data_token(self.broker)
            must_login = need_user_id and not self.user_id
            if stored and stored != rejected and not must_login:
                return stored  # renewed by another side: no login

            with self._state:
                mine = not self._renewing
                if mine:
                    self._renewing = True
            if not mine:
                time.sleep(_WAIT_STEP)  # this process is logging in: wait for it
                continue  # then adopt what that login stored

            try:
                token, user_id, error = self._login()
                if user_id:
                    self.user_id = str(user_id)
                if not token:
                    logger.error(
                        "Could not renew the %s market data session: %s",
                        self.broker,
                        error or "the broker gave no token",
                    )
                    return None
                if replace_market_data_token(self.broker, stored_blob, token):
                    logger.info("Renewed the %s market data session and stored it", self.broker)
                    return token
                # The row changed while this login ran: another side stored a
                # token meanwhile, or the row was signed out. Use the stored
                # one. If this login happened to end it, the next refusal finds
                # it stored and equal to the rejected token, and logs in once
                # more; the sides then share that token.
                _, latest = read_market_data_token(self.broker)
                return latest or token
            finally:
                with self._state:
                    self._renewing = False

        logger.warning("Timed out waiting for the %s market data session renewal", self.broker)
        return read_market_data_token(self.broker)[1]


_stores: dict[str, MarketDataTokenStore] = {}
_stores_lock = real_threading.Lock()


def market_data_tokens(broker: str, login: LoginFn) -> MarketDataTokenStore:
    """The process-wide store for ``broker``, created on first use."""
    with _stores_lock:
        store = _stores.get(broker)
        if store is None:
            store = _stores[broker] = MarketDataTokenStore(broker, login)
        return store
