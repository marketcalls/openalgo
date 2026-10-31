"""Starting a broker login on the server, and checking the broker's answer.

The broker login page used to build each broker's sign-in address in the
browser, from the API key the server handed it, and the callback accepted any
answer that arrived while the trader was signed in. Anyone who could get a
trader's browser to open a callback address with their own broker's code could
connect that trader's OpenAlgo to an account of the attacker's choosing.

Now the trader starts the login with a CSRF-checked POST
(/auth/broker/login). The server checks that the broker may be used, puts its
keys in place, builds the address itself and records a pending login: a random
nonce kept in the browser's signed session, and a random state. The server
keeps only their SHA-256 digests, in the broker_login_states table
(database/broker_keys_db.py), as OpenAlgo Desktop keeps pending_oauth: a login
survives a restart while the trader is at the broker's site, and a copy of the
table completes nothing. A broker's answer completes a login only when the
browser that started it brings the nonce back in its session, or when the
answer carries the state the server generated. Every pending login is used once
(a delete only one caller can win) and lasts ten minutes.

The two XTS brokers (CompositEdge, RMoney) post their answer from their own
site, and a cross-site POST never carries the session cookie (SameSite=Lax), so
for them the state rides on the return address, as OpenAlgo Desktop does.
Before this, any such post logged in whoever sent it, with no password. Every
other broker's address is exactly the one the login page built before.
"""

import re
import secrets
from urllib.parse import quote

from flask import session

from database.broker_keys_db import (
    clear_login_states,
    consume_login_state,
    find_login_state,
    record_login_state,
)

#: Brokers that post their answer to the callback from the broker's own site.
#: Every other POST to a callback comes from OpenAlgo's own login form. IIFL
#: Capital's callback reads its answer from a GET or a POST.
BROKER_SITE_POST_BROKERS = frozenset({"compositedge", "rmoney", "iiflcapital"})

#: Brokers whose sign-in starts at the callback route: the form brokers, whose
#: callback shows the login form, and those whose sign-in address the callback
#: builds itself.
CALLBACK_START_BROKERS = frozenset(
    {
        "fivepaisa",
        "fivepaisaxts",
        "aliceblue",
        "angel",
        "mstock",
        "indmoney",
        "deltaexchange",
        "jainamxts",
        "dhan_sandbox",
        "definedge",
        "firstock",
        "samco",
        "motilal",
        "nubra",
        "groww",
        "sahi",
        "ibulls",
        "iifl",
        "kotak",
        "shoonya",
        "tradejini",
        "tradesmart",
        "wisdom",
        "zebu",
        "iiflcapital",
    }
)

#: Brokers that bring back a state the server generates, so the answer can be
#: checked against it even without the cookie. The XTS pair and IIFL Capital
#: carry it on the return address; the others echo the OAuth state parameter.
STATE_BROKERS = frozenset({"fyers", "pocketful", "compositedge", "rmoney", "iiflcapital"})

_SESSION_KEY = "broker_login"
_SAFE_URL_VALUE = re.compile(r"[A-Za-z0-9._~:/-]+")


class BrokerLoginRefused(Exception):
    """A broker answer that does not belong to a login started here."""


def _open_login(broker):
    """Record a new pending login for this browser and return its state."""
    nonce = secrets.token_urlsafe(32)
    state = secrets.token_urlsafe(24)
    if not record_login_state(broker, nonce, state):
        raise BrokerLoginRefused(broker)
    # The state is the browser's own: it is handed to the broker on the
    # sign-in address anyway. Only the server copy is reduced to a digest.
    session[_SESSION_KEY] = {"broker": broker, "nonce": nonce, "state": state}
    return state


def _marker(broker):
    """This browser's pending-login marker for a broker, or None."""
    marker = session.get(_SESSION_KEY)
    if isinstance(marker, dict) and marker.get("broker") == broker and marker.get("nonce"):
        return marker
    return None


def _url_value(value):
    """A value as it goes into a sign-in address.

    Keys and callback addresses are passed as they are, as the login page did;
    anything with other characters is percent-encoded so it cannot add or end a
    query parameter.
    """
    value = value or ""
    return value if _SAFE_URL_VALUE.fullmatch(value) else quote(value, safe="")


def login_url(keys, state):
    """The address that starts a broker's sign-in.

    Args:
        keys: The broker's BrokerKeys.
        state: The random state for brokers in STATE_BROKERS.

    Returns:
        str: A path on this server, or the broker's own sign-in address.
    """
    broker = keys.broker
    if broker in CALLBACK_START_BROKERS:
        return f"/{broker}/callback"
    if broker == "dhan":
        return "/dhan/initiate-oauth"

    key = _url_value(keys.api_key)
    redirect = _url_value(keys.redirect_url)
    if broker in ("compositedge", "rmoney"):
        return xts_login_url(broker, keys.api_key, keys.redirect_url, state)
    if broker == "flattrade":
        parts = (keys.api_key or "").split(":::")
        app_key = _url_value(parts[1] if len(parts) > 1 else keys.api_key)
        return f"https://auth.flattrade.in/?app_key={app_key}"
    if broker == "fyers":
        return (
            f"https://api-t1.fyers.in/api/v3/generate-authcode?client_id={key}"
            f"&redirect_uri={redirect}&response_type=code&state={state}"
        )
    if broker == "upstox":
        return (
            "https://api.upstox.com/v2/login/authorization/dialog?response_type=code"
            f"&client_id={key}&redirect_uri={redirect}"
        )
    if broker == "zerodha":
        return f"https://kite.trade/connect/login?api_key={key}"
    if broker == "arrow":
        return f"https://app.arrow.trade/app/login?appID={key}"
    if broker == "rupeezy":
        return f"https://flow.rupeezy.in?applicationId={key}"
    if broker == "hdfcsecurities":
        return f"https://developer.hdfcsec.com/oapi/v1/login?api_key={key}"
    if broker == "hdfcsky":
        return f"https://developer.hdfcsky.com/oapi/v1/login?api_key={key}"
    if broker == "paytm":
        return f"https://login.paytmmoney.com/merchant-login?apiKey={key}&state={{default}}"
    if broker == "pocketful":
        scope = quote("orders holdings", safe="")
        return (
            f"https://trade.pocketful.in/oauth2/auth?client_id={key}&redirect_uri={redirect}"
            f"&response_type=code&scope={scope}&state={state}"
        )
    return f"/{broker}/callback"


def xts_login_url(broker, api_key, redirect_url, state):
    """The XTS third-party sign-in address, with the state on the return address.

    The broker posts the session back to the return address it was given, so
    the state rides there (encoded once, as OpenAlgo Desktop sends it).
    """
    if broker == "rmoney":
        from broker.rmoney.baseurl import INTERACTIVE_URL

        base = INTERACTIVE_URL
    else:
        base = "https://xts.compositedge.com/interactive"
    return_url = quote(f"{redirect_url}?state={state}", safe="")
    return f"{base}/thirdparty?appKey={quote(api_key or '', safe='')}&returnURL={return_url}"


def state_for(broker):
    """The state of this browser's pending login for a broker, starting one if needed.

    For the sign-ins the callback builds itself (RMoney, IIFL Capital), which
    carry the state on their return address. Call inside a request.
    """
    marker = _marker(broker)
    if marker and marker.get("state") and find_login_state(broker, nonce=marker["nonce"]):
        return marker["state"]
    return _open_login(broker)


def start_broker_login(keys):
    """Record a pending login for this browser and return where it starts.

    Call inside a request, after the broker's keys are in place.

    Args:
        keys: The broker's BrokerKeys.

    Returns:
        str: The address the browser should open.

    Raises:
        BrokerLoginRefused: When the login could not be recorded.
    """
    return login_url(keys, _open_login(keys.broker))


def is_broker_site_post(broker, method):
    """Whether a POST to a callback is the broker's own answer, not our form."""
    return method == "POST" and broker in BROKER_SITE_POST_BROKERS


def has_pending_login(broker, state=None):
    """Whether a login for this broker was started here, without using it up.

    Checked when a broker's answer (or a sign-in started at the callback)
    arrives, before anything is sent to the broker: a code nobody started a
    login for is never exchanged, and a link from another site cannot make
    OpenAlgo ask a broker to send the trader an OTP.

    Args:
        broker: The broker the request is for.
        state: The state the broker brought back, if any.
    """
    marker = _marker(broker)
    if marker and find_login_state(broker, nonce=marker["nonce"]):
        return True
    if state and broker in STATE_BROKERS:
        return find_login_state(broker, state=state) is not None
    return False


def verify_broker_return(broker, state=None):
    """Accept a broker's answer only for a login this server started.

    Consumes the pending login it matches, so an answer is accepted once.

    Args:
        broker: The broker the answer is for.
        state: The state the broker brought back, if any.

    Raises:
        BrokerLoginRefused: When no pending login matches.
    """
    marker = _marker(broker)
    session.pop(_SESSION_KEY, None)
    if marker:
        state_id = find_login_state(broker, nonce=marker["nonce"])
        if state_id is not None and consume_login_state(state_id):
            return
    if state and broker in STATE_BROKERS:
        state_id = find_login_state(broker, state=state)
        if state_id is not None and consume_login_state(state_id):
            return
    raise BrokerLoginRefused(broker)


def clear_pending_logins():
    """Forget every pending login (tests)."""
    clear_login_states()
