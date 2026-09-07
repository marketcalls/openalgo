"""ChatGPT subscription OAuth: run the agent on a plan instead of an API key.

LiteLLM 1.99.0 ships a real `chatgpt` provider that talks to the Codex backend
with an OAuth access token obtained from a device-code login, so an operator who
already pays for ChatGPT can drive this agent without an OpenAI API key. Ten
models are addressable that way, and eight of them share a bare name with an
`openai` model, `gpt-5.4` included. The same model name therefore reaches two
different billing systems depending on the prefix, and everything an operator
sees has to make the path unambiguous.

Three problems come with that provider, and this module exists for them.

**Custody.** `litellm.llms.chatgpt.authenticator.Authenticator` writes the
access token, the refresh token and the id token as **plain JSON** to
`CHATGPT_TOKEN_DIR`, defaulting to `os.path.expanduser("~/.config/litellm/chatgpt")`.
On Windows, where HOME is often unset, that expansion has already produced a
literal `~` directory inside this repository holding live credentials, one
`git add -A` from being committed. Here the file is moved under `db/`, the
directory this project already uses for its own state and the directory Docker
mounts as a volume, and `ag_secret` becomes the system of record: the encrypted
copy in the database is authoritative and the file is a cache this module
restores. A database restored into a fresh container is already authorised.

**The eventlet crossing.** The device flow polls every five seconds for up to
fifteen minutes. Production is `gunicorn --worker-class eventlet -w 1`, so a
poll loop inside a request, or on a green thread, stops the entire worker for as
long as it runs: one operator authorising their subscription would freeze the
platform, orders included. So `start_login` does exactly one bounded HTTP
request on the caller's side, returns the verification URL and the user code
immediately, and hands the poll to a **real OS thread** from
`utils.real_threading`. The green side never waits on it: `login_status` reads a
snapshot under a real lock held only across a dict copy, and `cancel_login`
joins with `real_threading.join`, which polls and yields rather than blocking.

**Cost.** `litellm.model_cost` prices `gpt-5.4` and has an entry for
`chatgpt/gpt-5.4` with no price keys at all, which is deliberate and correct: a
subscription turn has no per-token price. `catalog.estimate_cost` therefore
already answers None for it, and this module supplies the missing half, which is
the *reason* it is None. A subscription turn must be reported as **tokens and no
cost, labelled as subscription usage**. Reporting 0.00 implies the turn was free
when it consumed plan quota; falling back to the bare `gpt-5.4` price would show
the API price for usage that was never billed that way. Both are lies and the
second is worse. This is the same principle as the absent fundamentals on the
instrument card: say what is not known rather than substitute a number.

Nothing here reads `.env`. The token directory is computed from the project
layout and the credential lives in the database, exactly as every other agent
secret does.

Typical use
-----------

    from services.agent import chatgpt_oauth

    ok, reason = chatgpt_oauth.ensure_ready()      # no network, no blocking
    if not ok:
        raise MissingCredential(reason)

    status = chatgpt_oauth.start_login()           # returns immediately
    status.verification_url, status.user_code      # show these to the operator
    chatgpt_oauth.login_status()                   # cheap, poll this
    chatgpt_oauth.cancel_login()                   # stops the real thread
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

import httpx

from utils.logging import get_logger
from utils.real_threading import Event, Lock, Thread, join

logger = get_logger(__name__)

__all__ = [
    "AUTH_FILE_NAME",
    "BILLING_METERED",
    "BILLING_SUBSCRIPTION",
    "LOGIN_AUTHORISED",
    "LOGIN_CANCELLED",
    "LOGIN_EXPIRED",
    "LOGIN_FAILED",
    "LOGIN_IDLE",
    "LOGIN_PENDING",
    "MODEL_PREFIX",
    "PROVIDER_ID",
    "SECRET_NAME",
    "ChatGptOAuthError",
    "ChatGptOAuthUnavailable",
    "DeviceCodeExpired",
    "LoginStatus",
    "apply_billing",
    "auth_file",
    "billing_mode",
    "cancel_login",
    "configure_token_dir",
    "ensure_ready",
    "forget",
    "is_authorised",
    "is_subscription_model",
    "is_subscription_turn",
    "login_status",
    "refresh_access_token",
    "restore_tokens",
    "start_login",
    "status",
    "store_tokens",
    "token_dir",
]

#: LiteLLM's provider id, and the prefix every one of its model ids carries.
PROVIDER_ID = "chatgpt"
MODEL_PREFIX = f"{PROVIDER_ID}/"

#: The `ag_secret` row that owns the credential. Its own namespace, alongside
#: `provider:{kind}`, `model:{id}` and `websearch:{provider}`: this is not a
#: pasteable API key for a provider kind, and `provider:litellm` already means
#: something else, so reusing either name would collide.
SECRET_NAME = "oauth:chatgpt"

#: The two billing paths a model id can resolve to.
BILLING_SUBSCRIPTION = "subscription"
BILLING_METERED = "metered"

#: Login states. `pending` is the only non-terminal one.
LOGIN_IDLE = "idle"
LOGIN_PENDING = "pending"
LOGIN_AUTHORISED = "authorised"
LOGIN_EXPIRED = "expired"
LOGIN_FAILED = "failed"
LOGIN_CANCELLED = "cancelled"

TERMINAL_LOGIN_STATES = frozenset({LOGIN_AUTHORISED, LOGIN_EXPIRED, LOGIN_FAILED, LOGIN_CANCELLED})

PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: Where the token file goes. `db/` is where this project already keeps its own
#: state, it is the directory Docker mounts as a volume, and it is emphatically
#: not a tilde folder in the source tree.
DEFAULT_TOKEN_DIR = PROJECT_ROOT / "db" / "chatgpt_oauth"

#: Pinned rather than left to LiteLLM's default, so the name this module reads
#: and the name LiteLLM writes cannot drift apart through an environment
#: variable neither of us set.
AUTH_FILE_NAME = "auth.json"

#: Written into the token directory the moment it is created. The directory is
#: not covered by any rule in the repository's own `.gitignore`, and it holds a
#: live refresh token. A nested ignore file needs no edit to a tracked file and
#: travels with the directory.
_TOKEN_DIR_GITIGNORE = """\
# Written by services/agent/chatgpt_oauth.py.
#
# This directory holds a live OpenAI OAuth refresh token as plain JSON, cached
# from the encrypted copy in ag_secret. It must never be committed. The rule
# below ignores this file too, which is intended: nothing here is tracked.
*
"""

#: Every outbound request in this module carries one. CLAUDE.md's FD hygiene
#: rule is explicit that an HTTP call without a timeout is a leak waiting for a
#: slow peer, and the auth host is not ours.
HTTP_TIMEOUT_SECONDS = 15.0

#: How long the poll thread sleeps between checks of the cancel event. The
#: device endpoint wants five seconds between polls; sleeping five seconds in
#: one go would make a cancel take up to five seconds to be noticed, and a join
#: after it just as long.
_CANCEL_SLICE_SECONDS = 0.25

#: How long `cancel_login` waits for the thread, cooperatively. Long enough to
#: cover an in-flight request against a slow peer, short enough that a route
#: answers.
_CANCEL_JOIN_SECONDS = 20.0

#: The floor under every poll interval, however small a caller or the device
#: endpoint asks for. A wait of zero is a hot loop against someone else's auth
#: host on a real OS thread for a quarter of an hour, which burns a core and
#: earns a rate limit. Small enough that the tests, which pass their own tiny
#: interval to stay quick, are unaffected.
_MIN_POLL_SECONDS = 0.01

# The unpatched sleep, resolved exactly as `utils/real_threading` resolves its
# primitives. The poll thread is a real OS thread and has no business waking the
# hub's timers; under eventlet `time.sleep` is the hub's, and using it here
# would hand the poll loop's cadence to a scheduler it does not belong to.
if "eventlet" in sys.modules:
    import eventlet

    _real_sleep = eventlet.patcher.original("time").sleep
else:
    _real_sleep = time.sleep


class ChatGptOAuthError(RuntimeError):
    """A ChatGPT OAuth operation failed and the operator needs the reason."""


class ChatGptOAuthUnavailable(ChatGptOAuthError):
    """LiteLLM is not installed, or is too old to carry the chatgpt provider."""


class DeviceCodeExpired(ChatGptOAuthError):
    """The device code was never approved and is no longer accepted.

    Its own class because it is not a failure in the ordinary sense and the
    operator's next step is different: nothing is broken, they simply have to
    start again. `login_status` reports it as `expired` rather than `failed`.
    """


# ---------------------------------------------------------------------------
# The LiteLLM contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _LiteLlmChatGpt:
    """The pieces of LiteLLM's chatgpt provider this module is pinned to.

    Held in one object so a LiteLLM upgrade that moves or renames any of them
    fails once, loudly, at the point of use, rather than as a partially applied
    login. `test_agent_chatgpt_oauth.py` asserts every name here still resolves.

    Attributes:
        authenticator_cls: `litellm.llms.chatgpt.authenticator.Authenticator`.
            Used for its **pure** helpers and for reading and writing the auth
            file, so the file's shape stays LiteLLM's rather than a copy of it
            that can drift.
        client_id: The OAuth client id the device flow authenticates as.
        device_code_url: Where a device code is requested.
        device_token_url: Where the authorization code is polled for.
        oauth_token_url: Where a code, or a refresh token, is exchanged.
        verify_url: The page the operator opens to enter the user code.
        auth_base: The origin the redirect URI is built from.
        timeout_seconds: LiteLLM's own device-code deadline.
        poll_seconds: LiteLLM's own minimum interval between polls.
    """

    authenticator_cls: Any
    client_id: str
    device_code_url: str
    device_token_url: str
    oauth_token_url: str
    verify_url: str
    auth_base: str
    timeout_seconds: int
    poll_seconds: int


_litellm_bits: _LiteLlmChatGpt | None = None


def _bits() -> _LiteLlmChatGpt:
    """Import LiteLLM's chatgpt provider once and hold on to what we use.

    Imported lazily rather than at module import for the same reason
    `catalog.py` does it: the billing helpers below have to answer for a model
    id on an installation that has no LiteLLM, and an import error at module
    scope would take the whole agent module with it.

    Returns:
        The pinned contract.

    Raises:
        ChatGptOAuthUnavailable: When LiteLLM is missing or predates the
            provider.
    """
    global _litellm_bits

    if _litellm_bits is not None:
        return _litellm_bits

    try:
        from litellm.llms.chatgpt.authenticator import (
            DEVICE_CODE_POLL_SLEEP_SECONDS,
            DEVICE_CODE_TIMEOUT_SECONDS,
            Authenticator,
        )
        from litellm.llms.chatgpt.common_utils import (
            CHATGPT_AUTH_BASE,
            CHATGPT_CLIENT_ID,
            CHATGPT_DEVICE_CODE_URL,
            CHATGPT_DEVICE_TOKEN_URL,
            CHATGPT_DEVICE_VERIFY_URL,
            CHATGPT_OAUTH_TOKEN_URL,
        )
    except Exception as exc:
        logger.exception("LiteLLM's ChatGPT subscription provider is not available")
        raise ChatGptOAuthUnavailable(
            "This LiteLLM install has no ChatGPT subscription provider. "
            f"Upgrade litellm and restart ({type(exc).__name__})."
        ) from None

    _litellm_bits = _LiteLlmChatGpt(
        authenticator_cls=Authenticator,
        client_id=CHATGPT_CLIENT_ID,
        device_code_url=CHATGPT_DEVICE_CODE_URL,
        device_token_url=CHATGPT_DEVICE_TOKEN_URL,
        oauth_token_url=CHATGPT_OAUTH_TOKEN_URL,
        verify_url=CHATGPT_DEVICE_VERIFY_URL,
        auth_base=CHATGPT_AUTH_BASE,
        timeout_seconds=int(DEVICE_CODE_TIMEOUT_SECONDS),
        poll_seconds=int(DEVICE_CODE_POLL_SLEEP_SECONDS),
    )
    return _litellm_bits


def _authenticator() -> Any:
    """A LiteLLM `Authenticator` bound to this module's token directory.

    Constructing one reads `CHATGPT_TOKEN_DIR` and creates the directory, so
    the environment has to be set first. LiteLLM builds a fresh `ChatGPTConfig`,
    and therefore a fresh `Authenticator`, on every completion, so the variable
    is read again on every call and a change here takes effect immediately.

    Only its file and JWT helpers are used. Its `_login_device_code` is not:
    that one prints to stdout and blocks for up to fifteen minutes, which is
    exactly the behaviour this module exists to keep out of a request.

    Returns:
        A configured `Authenticator`.
    """
    configure_token_dir()
    return _bits().authenticator_cls()


# ---------------------------------------------------------------------------
# The token directory
# ---------------------------------------------------------------------------

_token_dir: Path | None = None


def configure_token_dir(path: Path | str | None = None) -> Path:
    """Point LiteLLM's token cache inside the instance data directory.

    Idempotent and cheap after the first call, so every public entry point here
    calls it without thinking, and that is the whole mechanism: there is no
    startup hook, because the containment only has to be in place before an
    `Authenticator` is constructed, and every path that constructs one comes
    through this module first.

    `CHATGPT_TOKEN_DIR` is **set**, not defaulted. An operator who exported one
    is overridden deliberately: the point of this module is that the credential
    is custodied by the database and cached in a directory we control, and a
    stray environment variable pointing at a home directory is the failure being
    prevented, not a configuration option being honoured. Nothing is read from
    `.env`, here or anywhere in this module.

    Args:
        path: An explicit directory, for tests. Defaults to
            :data:`DEFAULT_TOKEN_DIR`.

    Returns:
        The absolute token directory, which now exists.

    Raises:
        ValueError: If the path contains a literal `~` segment, which is the
            expansion failure this module was written to stop.
        ChatGptOAuthError: If the directory cannot be created.
    """
    global _token_dir

    if path is None and _token_dir is not None:
        return _token_dir

    target = Path(path) if path is not None else DEFAULT_TOKEN_DIR
    if "~" in str(target):
        raise ValueError(
            f"Refusing a ChatGPT token directory containing a literal tilde: {target}. "
            "An unexpanded '~' becomes a real folder holding live credentials."
        )
    target = target.expanduser().resolve()

    try:
        target.mkdir(parents=True, exist_ok=True)
        _harden(target, 0o700)
        ignore = target / ".gitignore"
        if not ignore.exists():
            ignore.write_text(_TOKEN_DIR_GITIGNORE, encoding="utf-8")
    except OSError as exc:
        logger.exception("Could not prepare the ChatGPT token directory at %s", target)
        raise ChatGptOAuthError(f"Could not prepare {target}: {exc}") from None

    os.environ["CHATGPT_TOKEN_DIR"] = str(target)
    os.environ["CHATGPT_AUTH_FILE"] = AUTH_FILE_NAME

    if _token_dir != target:
        logger.info("ChatGPT subscription tokens are cached at %s", target)
    _token_dir = target
    return target


def token_dir() -> Path:
    """The token directory, creating and pinning it on first use.

    Returns:
        The absolute directory holding the cached auth file.
    """
    return configure_token_dir()


def auth_file() -> Path:
    """The cached auth file LiteLLM reads and writes.

    Returns:
        The absolute path, which may not exist yet.
    """
    return token_dir() / AUTH_FILE_NAME


def _harden(path: Path, mode: int) -> None:
    """Narrow a path's permissions, best effort.

    POSIX honours this; Windows largely ignores it and that is fine, because
    the containment that matters on Windows is the location rather than the
    mode. A failure is not worth failing a login over.

    Args:
        path: The file or directory to narrow.
        mode: The octal mode to apply.
    """
    try:
        os.chmod(path, mode)
    except OSError:
        logger.debug("Could not set mode %o on %s", mode, path)


# ---------------------------------------------------------------------------
# Custody: the file is a cache, ag_secret is the record
# ---------------------------------------------------------------------------


def _read_record() -> dict[str, Any] | None:
    """The cached auth record, or None when there is not a usable one.

    Args:
        None.

    Returns:
        The parsed JSON object, or None when the file is absent, unreadable or
        not an object.
    """
    path = auth_file()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        record = json.loads(raw)
    except ValueError:
        logger.warning("The cached ChatGPT auth file is not valid JSON; ignoring it")
        return None
    return record if isinstance(record, dict) else None


def _write_record(record: dict[str, Any]) -> bool:
    """Replace the cached auth file, then narrow its permissions.

    Written through LiteLLM's own `_write_auth_file` so the on-disk shape is
    always the one LiteLLM will read back, rather than a copy of it here that a
    future LiteLLM release can quietly diverge from.

    **The write is read back, because LiteLLM's does not report failure.**
    `_write_auth_file` catches its own `OSError` and logs it, so a full disk or a
    read-only mount returns exactly like a success. Every caller here is about to
    claim a credential was persisted: without this check a login on a full disk
    published "ChatGPT subscription authorised", and `store_tokens` then read the
    file back, found the *previous* record still there, and stored that. The
    operator was told their new subscription was saved while the token that was
    actually saved was the old one. Reporting success for a write that did not
    happen is the failure this project treats as worse than failing loudly.

    Args:
        record: The auth record to persist.

    Returns:
        True when the record is on disk afterwards.
    """
    _authenticator()._write_auth_file(record)
    _harden(auth_file(), 0o600)
    return _read_record() == record


def _canonical(record: dict[str, Any]) -> str:
    """Serialise an auth record so an unchanged credential serialises identically.

    `set_secret` skips the write when the **decrypted plaintext** matches what
    is stored, which is the comparison Fernet's non-determinism forces and the
    one whose absence produced real "database is locked" failures elsewhere in
    this codebase. That skip only works if the same credential always produces
    the same string, so the keys are sorted and the separators fixed.

    Args:
        record: The auth record.

    Returns:
        A stable JSON string.
    """
    return json.dumps(record, sort_keys=True, separators=(",", ":"))


def store_tokens() -> bool:
    """Copy the cached auth file into `ag_secret`, encrypted, if it has changed.

    The database is the system of record. LiteLLM refreshes the access token on
    its own schedule and rotates the refresh token whenever the provider hands
    back a new one, both of which land in the file and nowhere else, so this
    runs before every run as well as after a login.

    Returns:
        True when a credential was written or was already current, False when
        there is nothing worth storing or the store refused it.
    """
    record = _read_record()
    if not _has_credential(record):
        return False

    from database import agent_db

    ok, error = agent_db.set_secret(SECRET_NAME, _canonical(record))
    if not ok:
        # No traceback and no value: this frame holds the decrypted credential.
        logger.error("Could not store the ChatGPT subscription token: %s", error)
        return False
    return True


def restore_tokens(force: bool = False) -> bool:
    """Write the cached auth file from `ag_secret` when it is missing.

    This is what makes a restored database sufficient. A fresh container has an
    empty `db/chatgpt_oauth/`, and the first call rebuilds the file from the
    encrypted row rather than sending the operator back through a device login.

    Args:
        force: Overwrite an existing file. Off by default, because the file is
            usually the *newer* copy: LiteLLM writes a refreshed access token
            there and nothing tells the database until `store_tokens` runs.

    Returns:
        True when the file was written from the stored secret.
    """
    if not force and _has_credential(_read_record()):
        return False

    from database import agent_db

    stored = agent_db.get_secret(SECRET_NAME)
    if not stored:
        return False

    try:
        record = json.loads(stored)
    except ValueError:
        logger.error("The stored ChatGPT subscription token is not valid JSON")
        return False
    finally:
        stored = None

    if not isinstance(record, dict) or not _has_credential(record):
        logger.error("The stored ChatGPT subscription token carries no usable credential")
        return False

    if not _write_record(record):
        logger.error("Could not write the ChatGPT subscription token to %s", auth_file())
        return False

    logger.info("Restored the ChatGPT subscription token from the database")
    return True


def forget() -> bool:
    """Sign the subscription out: drop the stored secret and the cached file.

    Returns:
        True when either copy was removed.
    """
    cancel_login()

    from database import agent_db

    removed = bool(agent_db.delete_secret(SECRET_NAME))

    path = auth_file()
    try:
        path.unlink()
        removed = True
    except FileNotFoundError:
        pass
    except OSError:
        logger.exception("Could not remove the cached ChatGPT auth file")

    # The snapshot is reset whether or not anything was removed. It describes a
    # login, and after a sign-out there is no longer one to describe: leaving it
    # said "ChatGPT subscription authorised." in `status()["login"]["message"]`
    # right beside `"authorised": false`, which is a screen telling an operator
    # two opposite things about the same credential.
    _set_login(
        state=LOGIN_IDLE,
        user_code="",
        verification_url="",
        started_at=None,
        expires_at=None,
        message="",
    )

    if removed:
        logger.info("ChatGPT subscription authorisation removed")
    return removed


def _has_credential(record: dict[str, Any] | None) -> bool:
    """Whether a record carries something that can still authenticate a call.

    A refresh token is enough on its own, because LiteLLM exchanges it for an
    access token when it needs one. An unexpired access token is enough on its
    own for the same reason in the other direction.

    Args:
        record: A parsed auth record, or None.

    Returns:
        True when the record can still produce an access token.
    """
    if not isinstance(record, dict):
        return False
    if record.get("refresh_token"):
        return True
    access = record.get("access_token")
    return bool(access) and not _access_token_expired(record)


def _access_token_expired(record: dict[str, Any]) -> bool:
    """Whether the record's access token is past its expiry.

    Read from the record's own `expires_at` where LiteLLM stored one, and
    otherwise from the token's own `exp` claim, which is a local base64 decode
    and not a network call. An expiry that cannot be established counts as
    expired, because the refresh token is then the thing that will be used.

    Args:
        record: A parsed auth record.

    Returns:
        True when the access token cannot be relied on.
    """
    expires_at = record.get("expires_at")
    if expires_at is None:
        expires_at = _expiry_claim(record.get("access_token"))
    if expires_at is None:
        return True
    try:
        return time.time() >= float(expires_at)
    except (TypeError, ValueError):
        return True


def _expiry_claim(token: str | None) -> int | None:
    """The `exp` claim of a JWT, without verifying it.

    Delegated to LiteLLM's own decoder so a malformed token is handled the same
    way it handles one, which is by answering None rather than raising.

    Args:
        token: A JWT, or None.

    Returns:
        The expiry as a Unix timestamp, or None.
    """
    if not token:
        return None
    try:
        return _authenticator()._get_expires_at(token)
    except Exception:
        logger.debug("Could not read an expiry claim from the cached ChatGPT token")
        return None


def is_authorised() -> bool:
    """Whether a call to a `chatgpt/` model can authenticate right now.

    Does no network work and never triggers a device login, so it is safe from
    a request handler and from the setup gate.

    Returns:
        True when a usable credential is cached or stored.
    """
    if _has_credential(_read_record()):
        return True
    return restore_tokens() and _has_credential(_read_record())


def ensure_ready() -> tuple[bool, str | None]:
    """Make the cached file current with the database, and say whether it works.

    Call this **before** building a `chatgpt/` model. It is the gate that keeps
    LiteLLM from starting its own device login inside the run: with no usable
    token, `Authenticator.get_access_token` falls through to
    `_login_device_code`, which prints to stdout and polls for fifteen minutes
    on whatever thread the run is on. Refusing here turns that into a clean
    error before the first stream byte.

    Performs no network work of any kind, so it is safe on the green side.

    Returns:
        `(ok, reason)`. `reason` is None when ok, and otherwise a message the
        operator can act on.
    """
    try:
        configure_token_dir()
        restore_tokens()
        store_tokens()
    except ChatGptOAuthUnavailable as exc:
        return False, str(exc)
    except Exception as exc:
        # logger.error and no traceback: this is a credential-set path, and the
        # build contract carves it out. The vector is the exception's own
        # message, which a storage or encryption failure can build out of the
        # material it choked on, and which utils.logging's redaction patterns
        # do not match because they all key off a "token=" or "secret:" label.
        # The class name is what locates the bug.
        logger.error(
            "Could not prepare the ChatGPT subscription credential: %s", type(exc).__name__
        )
        return False, "The ChatGPT subscription credential could not be prepared."

    if _has_credential(_read_record()):
        return True, None
    return False, (
        "This model runs on a ChatGPT subscription and no subscription is authorised. "
        "Sign in to ChatGPT from agent settings."
    )


def status() -> dict[str, Any]:
    """Everything the setup UI needs, and no token.

    A fingerprint is what an operator sees, exactly as for an API key: last four
    characters plus a truncated SHA-256, which is enough to tell two credentials
    apart and not enough to recover either. The tokens themselves never leave
    this module.

    **This is the fingerprint to show, and the `ag_secret` row's is not.** The
    stored value is the whole auth record as canonical JSON, so `set_secret`
    fingerprints the JSON blob and its row reads `...ef"} sha256:...` rather
    than anything about the credential. The one here is taken over the refresh
    token, so it survives an access-token refresh and stays the identifier the
    operator saw when they signed in. A settings screen that rendered
    `list_secrets()` for this row would show a second, different fingerprint for
    the same credential, which defeats the point of having one.

    Returns:
        A JSON-safe dict describing the authorisation and any login in flight.
    """
    from database import agent_db

    record = _read_record()
    authorised = _has_credential(record)
    expires_at = None
    account_id = None
    finger = "...????"

    if record is not None:
        raw_expiry = record.get("expires_at") or _expiry_claim(record.get("access_token"))
        try:
            expires_at = float(raw_expiry) if raw_expiry is not None else None
        except (TypeError, ValueError):
            expires_at = None
        account_id = record.get("account_id") or None
        # The fingerprint is taken over the durable half of the credential, so
        # it survives an access-token refresh and stays the same identifier the
        # operator saw when they signed in.
        finger = agent_db.fingerprint(record.get("refresh_token") or record.get("access_token"))

    return {
        "provider": PROVIDER_ID,
        "authorised": authorised,
        "fingerprint": finger,
        "account_id": account_id,
        "access_token_expires_at": expires_at,
        # Only meaningful when there is an access token to be expired. A record
        # holding nothing but LiteLLM's `device_code_requested_at` marker, which
        # is exactly what an abandoned sign-in leaves behind, would otherwise
        # report an expired token that never existed.
        "access_token_expired": bool((record or {}).get("access_token"))
        and _access_token_expired(record or {}),
        "stored_in_database": agent_db.get_secret(SECRET_NAME) is not None,
        "token_dir": str(token_dir()),
        "login": login_status().as_dict(),
    }


# ---------------------------------------------------------------------------
# Billing: tokens, and no cost
# ---------------------------------------------------------------------------


def is_subscription_model(model_id: str | None) -> bool:
    """Whether a model id is billed against a ChatGPT plan rather than per token.

    The prefix decides it, which is the whole point of the prefix: `gpt-5.4` and
    `chatgpt/gpt-5.4` name the same model on two different billing systems, and
    eight of the ten subscription models share a bare name with an `openai` one.
    The catalogue is consulted as a second opinion so a future model addressed
    some other way still resolves.

    Args:
        model_id: A LiteLLM model id, prefixed or bare.

    Returns:
        True when the call is billed to a subscription.
    """
    name = (model_id or "").strip()
    if not name:
        return False
    if name.startswith(MODEL_PREFIX):
        return True

    try:
        from services.agent import catalog

        meta = catalog.get_model_meta(name)
    except Exception:
        logger.debug("Could not consult the model catalogue for %s", name)
        return False
    return meta is not None and meta.provider == PROVIDER_ID


def is_subscription_turn(*model_ids: str | None) -> bool:
    """Whether any of these names for one turn's model says "subscription".

    The usage layer holds two names for the same model and they are not
    guaranteed to stay equal. One is the id resolved from the operator's row,
    which always carries the `chatgpt/` prefix because that is what
    `providers.litellm_model_id` stores. The other is whatever the provider
    reported back, which `stream.EventTranslator._usage_frame` overwrites the
    first with as soon as it arrives.

    Today those agree: agno fills `ModelRequestCompletedEvent.model` from
    `agent.model.id`, which is the prefixed id. But the prefix is the *only*
    thing separating a plan turn from a metered one for eight of the ten
    models, so a reported name that ever arrived bare would silently re-price
    the turn at the OpenAI API rate, which is the worse of the two lies this
    module exists to prevent. One prefixed name is therefore enough: a metered
    row can never report a `chatgpt/` model, so there is no false positive to
    trade against.

    Args:
        *model_ids: Every name known for the model this turn ran on.

    Returns:
        True when any of them is billed to a subscription.
    """
    return any(is_subscription_model(model_id) for model_id in model_ids)


def billing_mode(model_id: str | None) -> str:
    """Which billing system a turn on this model lands in.

    Args:
        model_id: A LiteLLM model id.

    Returns:
        :data:`BILLING_SUBSCRIPTION` or :data:`BILLING_METERED`.
    """
    return BILLING_SUBSCRIPTION if is_subscription_model(model_id) else BILLING_METERED


def apply_billing(
    model_id: str | None,
    cost_usd: float | None,
    *,
    resolved_model_id: str | None = None,
) -> tuple[str, float | None]:
    """Settle what a usage frame may claim about the price of a turn.

    The one function the usage layer needs. A subscription turn is forced to a
    null cost whatever anybody computed or reported, because there is no
    per-token price to report: the tokens came out of a plan.

    Two specific wrong answers this exists to prevent:

    * **0.00.** LiteLLM's own `completion_cost` answers zero for a model it
      cannot price, and agno hands that through as `metrics.cost`. Zero reads as
      "this turn was free" when it in fact consumed plan quota.
    * **The API price.** Falling back from `chatgpt/gpt-5.4` to `gpt-5.4`
      resolves a real, and entirely inapplicable, per-token price. That one is
      worse, because it is a plausible number nobody will question.

    A metered turn is passed through untouched, including a genuine 0.0 from a
    free model, which is a different claim and a true one.

    Args:
        model_id: The model id the provider billed.
        cost_usd: The cost anybody computed or reported, possibly None.
        resolved_model_id: The id resolved from the operator's own row, when the
            caller has it. Pass it: it is the authoritative name, and the
            reported one is only as trustworthy as the provider. See
            :func:`is_subscription_turn`.

    Returns:
        `(billing, cost_usd)`, where `cost_usd` is None for a subscription turn.
    """
    if is_subscription_turn(model_id, resolved_model_id):
        return BILLING_SUBSCRIPTION, None
    return BILLING_METERED, cost_usd


# ---------------------------------------------------------------------------
# The device flow
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LoginStatus:
    """A snapshot of the one login this module will run at a time.

    Attributes:
        state: One of the `LOGIN_*` constants.
        user_code: The code the operator types at `verification_url`. Shown to
            the authenticated operator and **never logged**: a device code is a
            standing phishing target, which is why LiteLLM's own prompt says so.
        verification_url: The page to open.
        started_at: Unix time the device code was issued.
        expires_at: Unix time the device code stops being accepted.
        message: Why a terminal state is what it is, empty while pending.
    """

    state: str = LOGIN_IDLE
    user_code: str = ""
    verification_url: str = ""
    started_at: float | None = None
    expires_at: float | None = None
    message: str = ""

    @property
    def pending(self) -> bool:
        """Whether a login is still in flight.

        Returns:
            True while the poll thread is running.
        """
        return self.state == LOGIN_PENDING

    def as_dict(self) -> dict[str, Any]:
        """Render for the HTTP layer.

        Returns:
            A dict of plain types.
        """
        return {
            "state": self.state,
            "user_code": self.user_code,
            "verification_url": self.verification_url,
            "started_at": self.started_at,
            "expires_at": self.expires_at,
            "message": self.message,
        }


class Transport(Protocol):
    """The two calls this module makes of an HTTP client.

    A protocol rather than an `httpx.Client` so a test drives the whole device
    flow, the refresh and every failure path with no network at all. A test that
    needs a real ChatGPT login is a test nobody will run.
    """

    def post(self, url: str, **kwargs: Any) -> Any:
        """Issue one POST.

        Args:
            url: The absolute URL.
            **kwargs: `json`, `content`, `headers` and `timeout`.

        Returns:
            Anything exposing `status_code` and `json()`.
        """
        ...

    def close(self) -> None:
        """Release the client, if this transport owns one."""
        ...


class _SharedTransport:
    """The project's pooled client, for a single request on the caller's side.

    `utils.httpx_client` is the green world's client: its event hooks touch
    Flask's `g`, and its connection pool's locks were built after eventlet
    patched the standard library. One request from a greenlet is exactly what it
    is for. It is emphatically not for the poll thread.
    """

    def post(self, url: str, **kwargs: Any) -> Any:
        """Issue one POST on the shared pooled client.

        Args:
            url: The absolute URL.
            **kwargs: Passed through to httpx.

        Returns:
            The httpx response.
        """
        from utils.httpx_client import get_httpx_client

        return get_httpx_client().post(url, **kwargs)

    def close(self) -> None:
        """Nothing to release: the client is process-wide and shared."""
        return None


class _OwnedTransport:
    """A private client, created on and used only by the poll thread.

    Sharing the pooled client with a real OS thread is the crossing CLAUDE.md
    describes: httpx's pool locks are green under eventlet, and a real thread
    contending on one is how a thread ends up blocked forever. A client the
    thread creates and closes is confined to it, and there is at most one at a
    time because there is at most one login in flight, so this is not the
    per-call client the FD rules forbid.
    """

    def __init__(self) -> None:
        self._client = httpx.Client(timeout=HTTP_TIMEOUT_SECONDS)

    def post(self, url: str, **kwargs: Any) -> Any:
        """Issue one POST on the private client.

        Args:
            url: The absolute URL.
            **kwargs: Passed through to httpx.

        Returns:
            The httpx response.
        """
        return self._client.post(url, **kwargs)

    def close(self) -> None:
        """Close the private client. Called from the thread's `finally`."""
        try:
            self._client.close()
        except Exception:
            logger.exception("Could not close the ChatGPT OAuth HTTP client")


# In-memory bookkeeping for the one login. The lock is real, from
# utils.real_threading, because the poll thread and the green request handler
# both touch this, and every critical section below is a dict copy: a greenlet
# waiting on a real lock stops the whole worker for as long as the holder takes.
_lock = Lock()
_login = LoginStatus()
_thread: Thread | None = None
_cancel: Event | None = None


def login_status() -> LoginStatus:
    """The current login snapshot. Cheap, non-blocking, safe from a greenlet.

    This is what a UI polls. It reads a frozen dataclass out from under a real
    lock held across one assignment and does nothing else.

    Returns:
        The snapshot.
    """
    with _lock:
        return _login


def _set_login(**changes: Any) -> LoginStatus:
    """Replace fields on the login snapshot under the lock.

    Args:
        **changes: Fields of :class:`LoginStatus` to change.

    Returns:
        The new snapshot.
    """
    global _login

    with _lock:
        _login = replace(_login, **changes)
        return _login


def start_login(
    *,
    force: bool = False,
    transport: Transport | None = None,
    timeout_seconds: float | None = None,
    poll_interval: float | None = None,
) -> LoginStatus:
    """Request a device code and start polling for it on a real OS thread.

    Returns as soon as the device code is issued, which is one bounded HTTP
    request. The fifteen-minute poll runs on a real thread from
    `utils.real_threading`, and nothing green ever waits on it.

    **A second start returns the login already in flight rather than replacing
    it.** Two reasons, both concrete. The device endpoint applies a five-minute
    cooldown after a code is issued, recorded in the auth file as
    `device_code_requested_at`, which LiteLLM's own client honours; asking for a
    second code inside it gets nowhere. And the first code is already on the
    operator's screen and may be half typed into `chat.openai.com`, so silently
    invalidating it turns a slow login into a failed one for no reason.
    Replacing it is a deliberate act: `force=True`, which is what a "start over"
    control sends, cancels the running login first.

    Args:
        force: Cancel a login in flight and begin a new one.
        transport: An HTTP client for both the device-code request and the poll.
            Defaults to the project's pooled client for the request and a
            private client for the thread. A supplied transport is never closed
            by this module; the caller owns it.
        timeout_seconds: How long the poll runs before reporting `expired`.
            Defaults to LiteLLM's own `DEVICE_CODE_TIMEOUT_SECONDS`.
        poll_interval: Seconds between polls, floored by whatever the device
            endpoint asked for and by :data:`_MIN_POLL_SECONDS`. Defaults to
            LiteLLM's own `DEVICE_CODE_POLL_SLEEP_SECONDS`.

    Returns:
        The snapshot, carrying the verification URL and the user code.

    Raises:
        ChatGptOAuthUnavailable: When LiteLLM has no chatgpt provider.
        ChatGptOAuthError: When the device code could not be issued. The state
            is also set to `failed`, so a client that only polls still sees it.
    """
    global _thread, _cancel

    bits = _bits()
    configure_token_dir()

    with _lock:
        # A login is in flight when the snapshot says `pending`, **not** merely
        # when the thread object is alive. A worker that has already published
        # its terminal state is still alive for as long as its `finally` takes:
        # it closes the HTTP client, imports `database.agent_db` and removes the
        # thread's scoped session. An operator clicking "Sign in" again the
        # moment a failure appeared landed inside that window, and was handed
        # back the *failed* snapshot with an empty user code while no device
        # code was requested at all. Nothing then happened until they clicked a
        # second time. Starting a new login there is correct and safe: `_retire`
        # matches on the cancel Event's identity, so the departing worker leaves
        # the new one's handles alone.
        running = _thread is not None and _thread.is_alive() and _login.state == LOGIN_PENDING
        if running and not force:
            return _login

    if running:
        cancel_login()

    deadline = float(timeout_seconds if timeout_seconds is not None else bits.timeout_seconds)
    interval = float(poll_interval if poll_interval is not None else bits.poll_seconds)

    owned = transport is None
    request_transport: Transport = transport or _SharedTransport()

    try:
        device = _request_device_code(request_transport, bits)
    except ChatGptOAuthError as exc:
        _set_login(
            state=LOGIN_FAILED,
            user_code="",
            verification_url=bits.verify_url,
            started_at=time.time(),
            expires_at=None,
            message=str(exc),
        )
        raise

    # LiteLLM's own cooldown bookkeeping, written the same way it writes it, so
    # a later call through LiteLLM's client sees a consistent file.
    try:
        _authenticator()._record_device_code_request()
    except Exception:
        logger.exception("Could not record the ChatGPT device-code request time")

    now = time.time()
    snapshot = _set_login(
        state=LOGIN_PENDING,
        user_code=device["user_code"],
        verification_url=bits.verify_url,
        started_at=now,
        expires_at=now + deadline,
        message="",
    )

    cancel = Event()
    thread = Thread(
        target=_poll_worker,
        args=(device, cancel, deadline, interval, None if owned else transport),
        name="agent-chatgpt-oauth",
        daemon=True,
    )
    with _lock:
        _cancel = cancel
        _thread = thread
    thread.start()

    # The user code is deliberately absent from this line. It is a standing
    # phishing target and belongs on the operator's screen, not in a log file.
    logger.info("ChatGPT subscription login started; polling for up to %.0fs", deadline)
    return snapshot


def cancel_login() -> bool:
    """Stop a login in flight and wait for its thread to finish.

    Joined with `real_threading.join`, which polls and yields: a blocking
    `Thread.join()` from a greenlet stops every other request on the worker for
    the whole wait, and this is called from a route.

    Returns:
        True when a running login was stopped.
    """
    global _thread, _cancel

    with _lock:
        thread, cancel = _thread, _cancel

    if thread is None or not thread.is_alive():
        return False

    if cancel is not None:
        cancel.set()

    stopped = join(thread, timeout=_CANCEL_JOIN_SECONDS)
    if not stopped:
        logger.warning("The ChatGPT login thread did not stop within the cancel timeout")

    # The state is read **after** the join, never before it. A login that
    # succeeded in the moment between the two would otherwise be overwritten
    # with "cancelled" while the token it just wrote sat in the file, and the
    # operator would be told to sign in again for no reason.
    with _lock:
        if _thread is thread:
            _thread = None
            _cancel = None
        still_pending = _login.state == LOGIN_PENDING

    if still_pending:
        _set_login(state=LOGIN_CANCELLED, user_code="", message="Sign-in cancelled.")
        logger.info("ChatGPT subscription login cancelled")
    return stopped


def _poll_worker(
    device: dict[str, str],
    cancel: Event,
    deadline_seconds: float,
    interval: float,
    transport: Transport | None,
) -> None:
    """Poll for the authorization code, exchange it, and persist the result.

    Runs on a real OS thread. Everything it touches is either confined to this
    thread (its own HTTP client), a real primitive (`cancel`, `_lock`), or the
    database, which the agent's tools already write to from this same kind of
    thread.

    Args:
        device: The issued device code fields.
        cancel: The real Event `cancel_login` sets.
        deadline_seconds: How long to keep polling.
        interval: Seconds between polls.
        transport: A caller-supplied client, or None to create a private one.
    """
    owned = transport is None
    client: Transport | None = None

    # Everything, the client's construction included, is inside the try. A
    # failure before it would otherwise skip the `finally` entirely, leaving a
    # dead thread still referenced and the state stuck on "pending" for the
    # life of a worker that never restarts.
    try:
        client = transport or _OwnedTransport()
        bits = _bits()
        code = _poll_for_code(client, bits, device, cancel, deadline_seconds, interval)
        if code is None:
            return
        tokens = _exchange_code(client, bits, code)
        record = _authenticator()._build_auth_record(tokens)
        if not _write_record(record):
            raise ChatGptOAuthError(
                f"The sign-in was approved but the token could not be written to "
                f"{auth_file().parent}. Check the directory is writable and try again."
            )
        stored = store_tokens()
        _set_login(
            state=LOGIN_AUTHORISED,
            user_code="",
            message=(
                "ChatGPT subscription authorised."
                if stored
                else "ChatGPT subscription authorised, but the token could not be saved "
                "to the database. It will be lost if this instance is rebuilt."
            ),
        )
        logger.info("ChatGPT subscription authorised")
    except DeviceCodeExpired as exc:
        # Not a failure: the operator simply did not finish in time, and the
        # fix is to start again rather than to investigate anything.
        _set_login(state=LOGIN_EXPIRED, user_code="", message=str(exc))
        logger.info("ChatGPT subscription sign-in code expired unapproved")
    except ChatGptOAuthError as exc:
        _set_login(state=LOGIN_FAILED, user_code="", message=str(exc))
        logger.error("ChatGPT subscription login failed: %s", exc)
    except Exception as exc:
        # Same carve-out as ensure_ready, and for the same reason: the frames
        # this would unwind hold the exchanged tokens, and a provider error
        # message can quote the material it rejected. The class name locates
        # the bug without quoting anything.
        logger.error("The ChatGPT subscription login thread failed: %s", type(exc).__name__)
        _set_login(
            state=LOGIN_FAILED,
            user_code="",
            message="The sign-in failed unexpectedly. Try again.",
        )
    finally:
        if owned and client is not None:
            client.close()
        # A scoped_session keyed on this thread would otherwise sit in the
        # registry for the life of the worker. There is one login thread at a
        # time, so this is a small leak rather than a large one, and closing it
        # here costs nothing.
        _release_session()
        _retire(cancel)


def _retire(cancel: Event) -> None:
    """Drop the module's handle on a login thread that has finished.

    A finished thread that is still referenced is not a running thread, but it
    is indistinguishable from one to anything reading `_thread`, and this
    worker never restarts, so the handle would outlive the login by weeks.
    Identity on the cancel Event is what says "this is still my login": a
    `force=True` restart has already installed a different one.

    Args:
        cancel: The Event this worker was started with.
    """
    global _thread, _cancel

    with _lock:
        if _cancel is cancel:
            _thread = None
            _cancel = None


def _release_session() -> None:
    """Drop the thread-local database session this thread may have opened."""
    try:
        from database import agent_db

        agent_db.db_session.remove()
    except Exception:
        logger.debug("Could not release the ChatGPT login thread's database session")


def _request_device_code(transport: Transport, bits: _LiteLlmChatGpt) -> dict[str, str]:
    """Ask the device endpoint for a code the operator can type.

    Args:
        transport: The HTTP client.
        bits: The pinned LiteLLM contract.

    Returns:
        `device_auth_id`, `user_code` and `interval`.

    Raises:
        ChatGptOAuthError: On any transport, status or shape failure.
    """
    response = _post(transport, bits.device_code_url, json={"client_id": bits.client_id})
    if response.status_code != 200:
        raise ChatGptOAuthError(
            f"The ChatGPT sign-in service refused the request (HTTP {response.status_code})."
        )

    data = _json(response)
    device_auth_id = data.get("device_auth_id")
    user_code = data.get("user_code") or data.get("usercode")
    if not device_auth_id or not user_code:
        raise ChatGptOAuthError("The ChatGPT sign-in service returned an incomplete device code.")

    return {
        "device_auth_id": str(device_auth_id),
        "user_code": str(user_code),
        "interval": str(data.get("interval") or bits.poll_seconds),
    }


def _poll_for_code(
    transport: Transport,
    bits: _LiteLlmChatGpt,
    device: dict[str, str],
    cancel: Event,
    deadline_seconds: float,
    interval: float,
) -> dict[str, str] | None:
    """Poll until the operator approves, the deadline passes, or cancel is set.

    403 and 404 are the "not yet" answers, which is what LiteLLM's own poll
    treats them as. Anything else is a failure worth reporting rather than
    retrying, because retrying a 500 for fifteen minutes tells the operator
    nothing.

    Args:
        transport: The HTTP client.
        bits: The pinned LiteLLM contract.
        device: The issued device code fields.
        cancel: The real Event `cancel_login` sets.
        deadline_seconds: How long to keep polling.
        interval: Seconds between polls.

    Returns:
        The authorization code fields, or None when cancelled.

    Raises:
        ChatGptOAuthError: On a hard failure or when the code expires.
    """
    wait = _poll_wait(interval, device.get("interval"))
    deadline = time.monotonic() + float(deadline_seconds)

    while not cancel.is_set():
        if time.monotonic() >= deadline:
            raise DeviceCodeExpired("The sign-in code expired before it was approved. Start again.")

        response = _post(
            transport,
            bits.device_token_url,
            json={
                "device_auth_id": device["device_auth_id"],
                "user_code": device["user_code"],
            },
        )

        if response.status_code == 200:
            data = _json(response)
            if all(k in data for k in ("authorization_code", "code_challenge", "code_verifier")):
                return {str(k): str(v) for k, v in data.items()}
        elif response.status_code not in (403, 404):
            raise ChatGptOAuthError(
                f"The ChatGPT sign-in service refused the poll (HTTP {response.status_code})."
            )

        if not _sleep_unless_cancelled(cancel, wait):
            break

    return None


def _poll_wait(interval: float, endpoint_interval: Any) -> float:
    """How long to wait between two polls.

    The endpoint's own interval is a floor rather than a suggestion, which is
    how LiteLLM treats it too: polling faster than it asked for is how a client
    gets rate limited off the flow. :data:`_MIN_POLL_SECONDS` is the floor under
    both, so no combination of a caller's argument and a hostile or malformed
    endpoint value can produce a loop with no wait in it at all.

    The endpoint's value is parsed defensively. It arrives as a string built
    from whatever JSON the auth host sent, and a value that will not parse used
    to raise `ValueError` out of the poll loop, where the only thing waiting for
    it was the catch-all that reports "The sign-in failed unexpectedly" and
    names nothing.

    Args:
        interval: The caller's interval, already defaulted to LiteLLM's own.
        endpoint_interval: Whatever the device endpoint asked for, unparsed.

    Returns:
        The number of seconds to wait between polls.
    """
    try:
        asked = float(endpoint_interval or 0.0)
    except (TypeError, ValueError):
        logger.debug("The ChatGPT device endpoint sent an unusable poll interval; ignoring it")
        asked = 0.0

    try:
        requested = float(interval)
    except (TypeError, ValueError):
        requested = 0.0

    return max(requested, asked, _MIN_POLL_SECONDS)


def _exchange_code(
    transport: Transport, bits: _LiteLlmChatGpt, code: dict[str, str]
) -> dict[str, str]:
    """Exchange an approved authorization code for tokens.

    Args:
        transport: The HTTP client.
        bits: The pinned LiteLLM contract.
        code: The polled authorization code fields.

    Returns:
        `access_token`, `refresh_token` and `id_token`.

    Raises:
        ChatGptOAuthError: On any transport, status or shape failure.
    """
    body = (
        "grant_type=authorization_code"
        f"&code={code['authorization_code']}"
        f"&redirect_uri={bits.auth_base}/deviceauth/callback"
        f"&client_id={bits.client_id}"
        f"&code_verifier={code['code_verifier']}"
    )
    response = _post(
        transport,
        bits.oauth_token_url,
        content=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if response.status_code != 200:
        raise ChatGptOAuthError(f"The ChatGPT token exchange failed (HTTP {response.status_code}).")

    data = _json(response)
    if not all(data.get(k) for k in ("access_token", "refresh_token", "id_token")):
        raise ChatGptOAuthError("The ChatGPT token exchange returned an incomplete response.")
    return {
        "access_token": str(data["access_token"]),
        "refresh_token": str(data["refresh_token"]),
        "id_token": str(data["id_token"]),
    }


def refresh_access_token(*, transport: Transport | None = None) -> tuple[bool, str | None]:
    """Trade the stored refresh token for a fresh access token.

    LiteLLM does this on its own whenever it finds an expired access token, so
    nothing has to call this on the ordinary path. It exists for the two places
    that need the answer rather than the side effect: an operator asking whether
    their subscription still works, and a test proving the refresh path without
    a network.

    One bounded request, so it is as safe from a greenlet as any broker call in
    this codebase. It is not a loop and must not be put in one.

    The rotated refresh token, when the provider sends one, is written to the
    file **and** back to `ag_secret`. A rotation that only reached the file
    would leave the database holding a token that no longer works, which is the
    failure a restored backup would discover months later.

    Args:
        transport: An HTTP client, for tests. Defaults to the pooled one.

    Returns:
        `(ok, error)`. `error` is None on success.
    """
    bits = _bits()
    configure_token_dir()
    restore_tokens()

    record = _read_record()
    refresh_token = (record or {}).get("refresh_token")
    if not refresh_token:
        return False, "No ChatGPT subscription refresh token is stored. Sign in again."

    client: Transport = transport or _SharedTransport()
    try:
        response = _post(
            client,
            bits.oauth_token_url,
            json={
                "client_id": bits.client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": "openid profile email",
            },
        )
    except ChatGptOAuthError as exc:
        return False, str(exc)
    finally:
        refresh_token = None

    if response.status_code != 200:
        return False, f"The ChatGPT refresh was refused (HTTP {response.status_code})."

    data = _json(response)
    if not data.get("access_token") or not data.get("id_token"):
        return False, "The ChatGPT refresh returned an incomplete response."

    previous = (_read_record() or {}).get("refresh_token")
    tokens = {
        "access_token": str(data["access_token"]),
        "refresh_token": str(data.get("refresh_token") or previous or ""),
        "id_token": str(data["id_token"]),
    }
    try:
        if not _write_record(_authenticator()._build_auth_record(tokens)):
            return False, (
                f"The refreshed ChatGPT token could not be written to {auth_file().parent}. "
                "Check the directory is writable."
            )
        store_tokens()
    finally:
        tokens = {}
        previous = None

    logger.info("ChatGPT subscription access token refreshed")
    return True, None


def _sleep_unless_cancelled(cancel: Event, seconds: float) -> bool:
    """Sleep in slices so a cancel is noticed within a quarter of a second.

    The unpatched `time.sleep`, because this runs on a real OS thread that has
    no business driving the hub's timers.

    Args:
        cancel: The real Event `cancel_login` sets.
        seconds: How long to sleep in total.

    Returns:
        True when the full sleep elapsed, False when cancelled part way.
    """
    deadline = time.monotonic() + max(0.0, seconds)
    while not cancel.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return True
        _real_sleep(min(_CANCEL_SLICE_SECONDS, remaining))
    return False


def _post(transport: Transport, url: str, **kwargs: Any) -> Any:
    """Issue one POST with an explicit timeout, turning transport errors into ours.

    Args:
        transport: The HTTP client.
        url: The absolute URL.
        **kwargs: `json`, `content` or `headers`.

    Returns:
        The response.

    Raises:
        ChatGptOAuthError: When the request could not be made at all.
    """
    try:
        return transport.post(url, timeout=HTTP_TIMEOUT_SECONDS, **kwargs)
    except Exception as exc:
        # No traceback: an httpx error message can quote the request body, and
        # the refresh body carries the refresh token. The class name is the part
        # worth keeping.
        logger.error("A ChatGPT sign-in request failed: %s", type(exc).__name__)
        raise ChatGptOAuthError(
            f"Could not reach the ChatGPT sign-in service ({type(exc).__name__})."
        ) from None


def _json(response: Any) -> dict[str, Any]:
    """Read a JSON object off a response, or an empty dict.

    Args:
        response: Anything with a `json()` method.

    Returns:
        The decoded object, or `{}` when the body is not one.
    """
    try:
        data = response.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}
