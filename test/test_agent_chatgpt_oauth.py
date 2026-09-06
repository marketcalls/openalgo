"""ChatGPT subscription OAuth: custody, the device flow, and the cost it has none of.

Three claims are made by `services/agent/chatgpt_oauth.py` and each one has to
resolve to a test here or it is only a claim.

**Custody.** LiteLLM writes the access token, the refresh token and the id token
as plain JSON to `CHATGPT_TOKEN_DIR`, which defaults to an expansion of
`~/.config/litellm/chatgpt`. That expansion has already produced a literal `~`
directory inside this repository holding live credentials. So the tests below
assert where the file lands, that it lands nowhere near a tilde, that the
directory ignores itself from git, and that the database is the copy that
survives the file being deleted.

**The eventlet crossing.** The device flow polls for up to fifteen minutes.
Production is a single eventlet worker, so a poll on the green side would stop
the whole platform. The proof of that is at the bottom of this file and runs
eventlet in a **subprocess**, because `monkey_patch()` is global and cannot be
undone, and it asserts on **elapsed time and hub liveness** rather than on
return values, which were always right. Its first case asserts the defect
itself, so the rest cannot pass vacuously. That is the shape of
`test/test_eventlet_cross_thread_locks.py` and
`test/test_agent_stream_eventlet.py`.

**Cost.** A subscription turn has no per-token price. It must report tokens and
no cost, and it must be distinguishable from a turn that genuinely cost nothing.

**Nothing here touches the network.** Every request is served by a stub
transport, because a test that needs a real ChatGPT login is a test nobody will
run.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

pytest.importorskip("litellm", reason="the chatgpt provider ships inside litellm")

from services.agent import catalog  # noqa: E402
from services.agent import chatgpt_oauth as oauth  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Values shaped like the real thing: long enough that a leak into a log line or
# a payload is unmistakable, and distinctive enough to grep a whole structure
# for. Nothing here is a credential to anything.
FAKE_REFRESH_TOKEN = "rt-NotARealChatGptRefreshToken-0123456789abcdef"
FAKE_ACCOUNT_ID = "acct-not-a-real-account"


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


def _b64(raw: bytes) -> str:
    """URL-safe base64 without padding, which is how a JWT segment is encoded.

    Args:
        raw: The bytes to encode.

    Returns:
        The encoded segment.
    """
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _jwt(claims: dict) -> str:
    """A syntactically real, cryptographically worthless JWT.

    LiteLLM reads the `exp` claim and the ChatGPT account id straight out of the
    payload without verifying anything, so a fake signature is enough to
    exercise the record-building path it actually runs.

    Args:
        claims: The payload claims.

    Returns:
        A three-segment token.
    """
    header = _b64(json.dumps({"alg": "none", "typ": "JWT"}).encode("utf-8"))
    payload = _b64(json.dumps(claims).encode("utf-8"))
    return f"{header}.{payload}.not-a-signature"


def _access_token(ttl_seconds: int = 3600) -> str:
    """An access token that expires when we say it does.

    Args:
        ttl_seconds: Seconds until expiry. Negative for an already-dead token.

    Returns:
        A JWT carrying `exp` and the ChatGPT account id.
    """
    return _jwt(
        {
            "exp": int(time.time()) + ttl_seconds,
            "https://api.openai.com/auth": {"chatgpt_account_id": FAKE_ACCOUNT_ID},
        }
    )


class StubResponse:
    """The two things this module asks of an HTTP response."""

    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self) -> dict:
        """The decoded body.

        Returns:
            The payload this response was built with.
        """
        return self._payload


class StubTransport:
    """A scripted transport. One queue of responses per URL, then the last one.

    Holding a queue rather than a single response is what lets a test drive the
    real shape of the device flow, where the poll answers 403 until the operator
    approves and 200 afterwards.
    """

    def __init__(self, script: dict[str, list[StubResponse]]) -> None:
        self.script = {url: list(responses) for url, responses in script.items()}
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    def post(self, url: str, **kwargs) -> StubResponse:
        """Answer the next scripted response for this URL.

        Args:
            url: The absolute URL.
            **kwargs: Recorded, so a test can assert the timeout and the body.

        Returns:
            The scripted response.
        """
        self.calls.append((url, kwargs))
        queue = self.script.get(url)
        if not queue:
            raise AssertionError(f"no scripted response for {url}")
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def close(self) -> None:
        """Record that the transport was closed."""
        self.closed = True

    def urls(self) -> list[str]:
        """Every URL called, in order.

        Returns:
            The URL of each recorded call.
        """
        return [url for url, _ in self.calls]


class MemorySecrets:
    """An in-memory stand-in for the two `ag_secret` helpers this module uses.

    It reproduces the one behaviour that matters and is easy to get wrong:
    `set_secret` compares the **decrypted plaintext** and writes nothing when it
    has not changed. Comparing ciphertext instead is what produced real
    "database is locked" failures elsewhere in this codebase, so a test that
    only checked the value round-tripped would miss the defect entirely.
    """

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.writes = 0

    def set_secret(self, name: str, value: str) -> tuple[bool, str | None]:
        """Store a secret, skipping an unchanged write.

        Args:
            name: The secret name.
            value: The plaintext.

        Returns:
            `(ok, error)`.
        """
        if self.values.get(name) == value:
            return True, None
        self.values[name] = value
        self.writes += 1
        return True, None

    def get_secret(self, name: str) -> str | None:
        """Read a secret.

        Args:
            name: The secret name.

        Returns:
            The plaintext, or None.
        """
        return self.values.get(name)

    def delete_secret(self, name: str) -> bool:
        """Remove a secret.

        Args:
            name: The secret name.

        Returns:
            True when a value was removed.
        """
        return self.values.pop(name, None) is not None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def token_dir(tmp_path, monkeypatch):
    """Point the module at a scratch token directory and put it back afterwards.

    The module caches the resolved directory and sets two environment
    variables, all of which are process-wide, so both are restored.
    """
    monkeypatch.setattr(oauth, "_token_dir", None, raising=False)
    monkeypatch.delenv("CHATGPT_TOKEN_DIR", raising=False)
    monkeypatch.delenv("CHATGPT_AUTH_FILE", raising=False)

    path = oauth.configure_token_dir(tmp_path / "chatgpt_oauth")
    yield path

    oauth.cancel_login()
    monkeypatch.setattr(oauth, "_login", oauth.LoginStatus(), raising=False)
    monkeypatch.setattr(oauth, "_thread", None, raising=False)
    monkeypatch.setattr(oauth, "_cancel", None, raising=False)
    oauth._token_dir = None


@pytest.fixture
def secrets(monkeypatch):
    """Replace the `ag_secret` helpers with an in-memory store.

    The module imports `database.agent_db` lazily inside each custody function
    precisely so this works, and so the billing helpers and the login machinery
    import with no database stack behind them.
    """
    from database import agent_db

    store = MemorySecrets()
    monkeypatch.setattr(agent_db, "set_secret", store.set_secret)
    monkeypatch.setattr(agent_db, "get_secret", store.get_secret)
    monkeypatch.setattr(agent_db, "delete_secret", store.delete_secret)
    return store


@pytest.fixture
def bits():
    """LiteLLM's chatgpt endpoints, which the stub transport is keyed by.

    Returns:
        The pinned contract object.
    """
    return oauth._bits()


def _script(bits, poll: list[StubResponse]) -> dict[str, list[StubResponse]]:
    """A full device-flow script with a caller-chosen poll sequence.

    Args:
        bits: The pinned LiteLLM contract.
        poll: What the device-token endpoint answers, in order.

    Returns:
        A script keyed by URL for :class:`StubTransport`.
    """
    return {
        bits.device_code_url: [
            # A small interval keeps the suite quick. The endpoint's own value
            # is a floor rather than a suggestion, exactly as LiteLLM treats it,
            # which the interval case below pins.
            StubResponse(
                200,
                {"device_auth_id": "dev-1", "user_code": "WXYZ-1234", "interval": 0.05},
            )
        ],
        bits.device_token_url: poll,
        bits.oauth_token_url: [
            StubResponse(
                200,
                {
                    "access_token": _access_token(),
                    "refresh_token": FAKE_REFRESH_TOKEN,
                    # LiteLLM reads the ChatGPT account id out of the id token
                    # first, so that is where a real one carries it.
                    "id_token": _jwt(
                        {
                            "sub": "user",
                            "https://api.openai.com/auth": {"chatgpt_account_id": FAKE_ACCOUNT_ID},
                        }
                    ),
                },
            )
        ],
    }


def _approved() -> StubResponse:
    """The poll answer that means the operator approved the code.

    Returns:
        A 200 carrying the three fields the exchange needs.
    """
    return StubResponse(
        200,
        {
            "authorization_code": "auth-code-1",
            "code_challenge": "challenge-1",
            "code_verifier": "verifier-1",
        },
    )


def _await_login(*states: str, timeout: float = 10.0) -> oauth.LoginStatus:
    """Wait for the login to reach one of `states`.

    Args:
        *states: Acceptable terminal states.
        timeout: How long to wait.

    Returns:
        The snapshot.

    Raises:
        AssertionError: When the deadline passes first.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = oauth.login_status()
        if status.state in states:
            return status
        time.sleep(0.02)
    raise AssertionError(f"login stayed {oauth.login_status().state}, wanted one of {states}")


# ---------------------------------------------------------------------------
# The LiteLLM contract
# ---------------------------------------------------------------------------


def test_the_litellm_names_this_module_is_pinned_to_still_resolve():
    """A LiteLLM bump that moves any of these must fail here, not in production.

    This module drives LiteLLM's device flow rather than calling
    `Authenticator._login_device_code`, which prints to stdout and blocks for
    fifteen minutes. That means it depends on a handful of private names, and
    the cost of that choice is this test.
    """
    bits = oauth._bits()

    assert bits.client_id
    assert bits.device_code_url.startswith("https://")
    assert bits.device_token_url.startswith("https://")
    assert bits.oauth_token_url.startswith("https://")
    assert bits.verify_url.startswith("https://")
    assert bits.timeout_seconds == 15 * 60
    assert bits.poll_seconds == 5

    for name in (
        "_read_auth_file",
        "_write_auth_file",
        "_build_auth_record",
        "_get_expires_at",
        "_extract_account_id",
        "_record_device_code_request",
    ):
        assert hasattr(bits.authenticator_cls, name), f"litellm Authenticator lost {name}"


def test_litellm_reads_the_token_directory_on_every_call():
    """The containment only holds because `Authenticator` re-reads the variable.

    `ProviderConfigManager` builds a fresh `ChatGPTConfig` per completion, and
    `ChatGPTConfig.__init__` builds a fresh `Authenticator`, which reads
    `CHATGPT_TOKEN_DIR` in its own `__init__`. If either were cached at import,
    setting the variable from this module would be too late and the tokens would
    land in the home directory anyway.
    """
    import os
    import tempfile

    import litellm.utils as litellm_utils

    source = Path(litellm_utils.__file__).read_text(encoding="utf-8")
    assert "lambda: litellm.ChatGPTConfig()" in source, (
        "litellm no longer builds ChatGPTConfig per call; the token directory "
        "may now be resolved once at import"
    )

    # The behaviour rather than the source: build the config twice, pointing
    # the variable somewhere else in between, and check the second one followed.
    from litellm.llms.chatgpt.chat.transformation import ChatGPTConfig

    first = Path(tempfile.mkdtemp(prefix="oa-chatgpt-a-"))
    second = Path(tempfile.mkdtemp(prefix="oa-chatgpt-b-"))
    previous = os.environ.get("CHATGPT_TOKEN_DIR")
    try:
        os.environ["CHATGPT_TOKEN_DIR"] = str(first)
        assert Path(ChatGPTConfig().authenticator.auth_file).parent == first
        os.environ["CHATGPT_TOKEN_DIR"] = str(second)
        assert Path(ChatGPTConfig().authenticator.auth_file).parent == second
    finally:
        if previous is None:
            os.environ.pop("CHATGPT_TOKEN_DIR", None)
        else:
            os.environ["CHATGPT_TOKEN_DIR"] = previous


# ---------------------------------------------------------------------------
# Custody
# ---------------------------------------------------------------------------


def test_the_default_token_directory_is_inside_the_instance_data_directory():
    """`db/`, not a home directory, and not the source tree at large."""
    assert oauth.DEFAULT_TOKEN_DIR == PROJECT_ROOT / "db" / "chatgpt_oauth"
    assert oauth.DEFAULT_TOKEN_DIR.is_relative_to(PROJECT_ROOT / "db")
    assert "~" not in str(oauth.DEFAULT_TOKEN_DIR)


def test_configuring_the_directory_never_creates_a_tilde_folder(token_dir, tmp_path):
    """The exact accident this module exists to stop.

    A literal `~` folder in the repository root, holding OAuth state and one
    `git add -A` from being committed, is what an unexpanded
    `~/.config/litellm/chatgpt` produced here.

    The assertion is that **this module** creates none, measured across the two
    calls that could: resolving the directory, and constructing LiteLLM's own
    `Authenticator`. It is deliberately not "the repository has no tilde
    directory", because a leftover from before this module existed would then
    fail a test about code that cannot have created it.
    """
    tilde = PROJECT_ROOT / "~"
    before = tilde.exists()

    resolved = oauth.configure_token_dir(tmp_path / "again")
    oauth._bits().authenticator_cls()

    assert tilde.exists() == before, "a tilde directory appeared while resolving the token path"
    assert "~" not in str(resolved)
    assert "~" not in str(token_dir)
    assert token_dir.is_dir()

    with pytest.raises(ValueError, match="tilde"):
        oauth.configure_token_dir("~/.config/litellm/chatgpt")


def test_any_tilde_directory_left_in_the_repository_is_at_least_ignored():
    """The hazard, pinned even where history has already tripped over it.

    An unexpanded `~` folder that predates this module is not something it can
    delete safely, but a credential directory that git would commit is a real
    problem, so the ignore rule is asserted rather than assumed.
    """
    tilde = PROJECT_ROOT / "~"
    if not tilde.exists():
        pytest.skip("no leftover tilde directory in this checkout")

    result = subprocess.run(
        ["git", "check-ignore", "-v", "~/.config/litellm/chatgpt/auth.json"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, "a leftover tilde credential directory is not gitignored"


def test_the_directory_is_pinned_into_the_environment_litellm_reads(token_dir):
    """LiteLLM only looks at these two variables, so both are set explicitly."""
    import os

    assert os.environ["CHATGPT_TOKEN_DIR"] == str(token_dir)
    assert os.environ["CHATGPT_AUTH_FILE"] == oauth.AUTH_FILE_NAME
    assert oauth.auth_file() == token_dir / "auth.json"

    # And LiteLLM's own Authenticator, constructed fresh, agrees.
    authenticator = oauth._bits().authenticator_cls()
    assert Path(authenticator.auth_file) == oauth.auth_file()


def test_the_directory_ignores_itself_from_git(token_dir):
    """No tracked file had to be edited to contain a live refresh token.

    The repository's own `.gitignore` covers `*.db` but nothing under
    `db/chatgpt_oauth/`, so a nested ignore file travels with the directory the
    module creates.
    """
    ignore = token_dir / ".gitignore"
    assert ignore.is_file()
    assert ignore.read_text(encoding="utf-8").strip().endswith("*")


def test_git_actually_ignores_the_real_token_path(tmp_path):
    """Not asserted about the file's contents: asked of git itself.

    `git check-ignore` is run inside a throwaway repository holding the same
    nested ignore file, so this proves the rule works rather than that it was
    written.
    """
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    target = tmp_path / "db" / "chatgpt_oauth"
    oauth.configure_token_dir(target)
    (target / "auth.json").write_text("{}", encoding="utf-8")
    oauth._token_dir = None

    result = subprocess.run(
        ["git", "check-ignore", "-v", "db/chatgpt_oauth/auth.json"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, "git would have committed the OAuth token file"

    staged = subprocess.run(["git", "add", "-A"], cwd=tmp_path, capture_output=True, text=True)
    assert staged.returncode == 0
    listing = subprocess.run(
        ["git", "diff", "--cached", "--name-only"], cwd=tmp_path, capture_output=True, text=True
    )
    assert "auth.json" not in listing.stdout


def test_a_login_result_is_stored_encrypted_and_restores_without_the_file(token_dir, secrets):
    """`ag_secret` is the system of record; the file is a cache we can rebuild.

    This is what makes a restored database sufficient: a fresh container has an
    empty token directory, and the first call rebuilds the file rather than
    sending the operator back through a device login.
    """
    record = {
        "access_token": _access_token(),
        "refresh_token": FAKE_REFRESH_TOKEN,
        "id_token": _jwt({"sub": "user"}),
        "expires_at": int(time.time()) + 3600,
        "account_id": FAKE_ACCOUNT_ID,
    }
    oauth._write_record(record)

    assert oauth.store_tokens() is True
    assert oauth.SECRET_NAME in secrets.values

    oauth.auth_file().unlink()
    assert oauth._read_record() is None

    assert oauth.restore_tokens() is True
    assert oauth._read_record()["refresh_token"] == FAKE_REFRESH_TOKEN
    assert oauth.is_authorised() is True


def test_an_unchanged_credential_is_not_rewritten(token_dir, secrets):
    """Compared as decrypted plaintext, which is why the write is skippable.

    Fernet is non-deterministic, so a ciphertext comparison never matches and
    every save rewrites the row. The same mistake in `telegram_db.py` produced
    real "database is locked" failures, and `ensure_ready` runs this before
    every single agent run.
    """
    oauth._write_record({"refresh_token": FAKE_REFRESH_TOKEN, "account_id": FAKE_ACCOUNT_ID})

    for _ in range(5):
        assert oauth.store_tokens() is True
    assert secrets.writes == 1

    # A genuinely rotated refresh token is a change, and must be written.
    oauth._write_record({"refresh_token": FAKE_REFRESH_TOKEN + "-rotated", "account_id": "x"})
    assert oauth.store_tokens() is True
    assert secrets.writes == 2


def test_the_serialisation_is_stable_across_key_order(token_dir, secrets):
    """Two spellings of the same record must compare equal, or the skip is moot."""
    first = {"access_token": "a", "refresh_token": "b", "id_token": "c"}
    second = {"id_token": "c", "access_token": "a", "refresh_token": "b"}
    assert oauth._canonical(first) == oauth._canonical(second)


def test_restore_does_not_clobber_a_newer_file(token_dir, secrets):
    """The file is usually ahead of the database, not behind it.

    LiteLLM refreshes the access token straight into the file and tells nobody,
    so an unconditional restore would roll a live credential back to whatever
    was last stored.
    """
    secrets.values[oauth.SECRET_NAME] = json.dumps({"refresh_token": "old"})
    oauth._write_record({"refresh_token": "new", "access_token": _access_token()})

    assert oauth.restore_tokens() is False
    assert oauth._read_record()["refresh_token"] == "new"

    assert oauth.restore_tokens(force=True) is True
    assert oauth._read_record()["refresh_token"] == "old"


def test_a_silently_failed_write_is_never_reported_as_an_authorised_login(
    token_dir, secrets, bits, monkeypatch
):
    """LiteLLM's `_write_auth_file` catches its own `OSError` and logs it, so a
    full disk or a read-only mount returns exactly like a success.

    Without reading the write back, the login published "ChatGPT subscription
    authorised" and `store_tokens` then read the file, found the **previous**
    record still sitting there, and stored that. On an instance that had signed
    in before, the operator is told their new subscription was saved while the
    credential actually saved is the old one. Claiming a success for a write
    that did not happen is the failure this project treats as the worse one.
    """
    stale = {"refresh_token": FAKE_REFRESH_TOKEN + "-previous"}
    assert oauth._write_record(stale) is True
    oauth.store_tokens()
    assert secrets.writes == 1

    # The disk stops accepting writes, reported the way LiteLLM reports it.
    monkeypatch.setattr(bits.authenticator_cls, "_write_auth_file", lambda self, data: None)
    assert oauth._write_record({"refresh_token": "anything"}) is False

    transport = StubTransport(_script(bits, [_approved()]))
    oauth.start_login(transport=transport, timeout_seconds=5, poll_interval=0.01)
    final = _await_login(oauth.LOGIN_FAILED)

    assert "could not be written" in final.message
    # And the old credential was not laundered into the database as the new one.
    assert secrets.writes == 1
    assert json.loads(secrets.get_secret(oauth.SECRET_NAME))["refresh_token"].endswith("-previous")


def test_a_restore_that_cannot_write_the_file_reports_failure(
    token_dir, secrets, bits, monkeypatch
):
    """`restore_tokens` said True and logged "Restored" whatever happened.

    Everything downstream reads that as "the file is now there", and
    `is_authorised` would have answered True on a file that does not exist.
    """
    secrets.values[oauth.SECRET_NAME] = json.dumps({"refresh_token": FAKE_REFRESH_TOKEN})
    monkeypatch.setattr(bits.authenticator_cls, "_write_auth_file", lambda self, data: None)

    assert oauth.restore_tokens() is False
    assert oauth.is_authorised() is False


def test_forget_removes_both_copies(token_dir, secrets):
    """Signing out has to clear the cache as well as the record."""
    oauth._write_record({"refresh_token": FAKE_REFRESH_TOKEN})
    oauth.store_tokens()

    assert oauth.forget() is True
    assert oauth.auth_file().exists() is False
    assert secrets.get_secret(oauth.SECRET_NAME) is None
    assert oauth.is_authorised() is False


def test_forget_leaves_no_stale_login_snapshot(token_dir, secrets, bits):
    """Signing out must not leave the screen saying two opposite things.

    `status()` carries both the authorisation and the last login snapshot. A
    completed login sets that snapshot to `authorised` with the message
    "ChatGPT subscription authorised.", and `forget()` used to leave it there,
    so the panel read `authorised: false` beside a message saying otherwise.
    """
    transport = StubTransport(_script(bits, [_approved()]))
    oauth.start_login(transport=transport, timeout_seconds=5, poll_interval=0.01)
    _await_login(oauth.LOGIN_AUTHORISED)
    assert oauth.status()["login"]["state"] == oauth.LOGIN_AUTHORISED

    oauth.forget()

    payload = oauth.status()
    assert payload["authorised"] is False
    assert payload["login"]["state"] == oauth.LOGIN_IDLE
    assert payload["login"]["message"] == ""
    assert payload["login"]["verification_url"] == ""


def test_an_abandoned_sign_in_does_not_report_an_expired_token_it_never_had(token_dir, secrets):
    """The record LiteLLM leaves behind for an unfinished login holds one field.

    `_record_device_code_request` writes `device_code_requested_at` into an
    otherwise empty file, which is exactly what the leftover tilde directory in
    this repository still contains. Reading that as "the access token expired"
    sends an operator looking for a token that was never issued.
    """
    oauth._write_record({"device_code_requested_at": time.time()})

    payload = oauth.status()
    assert payload["authorised"] is False
    assert payload["access_token_expired"] is False
    assert payload["access_token_expires_at"] is None
    assert payload["fingerprint"] == "...????"

    # A real, genuinely expired access token still reports as expired.
    oauth._write_record({"access_token": _access_token(ttl_seconds=-60)})
    assert oauth.status()["access_token_expired"] is True


def test_ensure_ready_refuses_with_no_credential_and_does_no_network(
    token_dir, secrets, monkeypatch
):
    """The gate that stops LiteLLM starting its own device login inside a run.

    With no usable token, `Authenticator.get_access_token` falls through to
    `_login_device_code`, which prints to stdout and polls for fifteen minutes
    on whatever thread the run happens to be on. Refusing here turns that into
    a clean error before the first stream byte.

    It also runs on the green side before every run, so it must make no request
    at all. Every outbound call in the module goes through `_post`, which is
    booby-trapped for the duration.
    """

    def explode(*_args, **_kwargs):
        raise AssertionError("ensure_ready must not make a network call")

    monkeypatch.setattr(oauth, "_post", explode)

    ok, reason = oauth.ensure_ready()
    assert ok is False
    assert "no subscription is authorised" in reason

    oauth._write_record({"refresh_token": FAKE_REFRESH_TOKEN})
    ok, reason = oauth.ensure_ready()
    assert ok is True and reason is None
    # ensure_ready is also the sync point, so the database now has the token.
    assert secrets.get_secret(oauth.SECRET_NAME) is not None


def test_an_expired_access_token_with_a_refresh_token_is_still_ready(token_dir, secrets):
    """LiteLLM exchanges the refresh token itself; an expired access token is fine."""
    oauth._write_record(
        {"access_token": _access_token(ttl_seconds=-60), "refresh_token": FAKE_REFRESH_TOKEN}
    )
    ok, reason = oauth.ensure_ready()
    assert ok is True and reason is None

    # Cleared, because ensure_ready has just stored the working record and
    # would otherwise restore it straight back over the broken one.
    secrets.values.clear()
    oauth._write_record({"access_token": _access_token(ttl_seconds=-60)})
    ok, reason = oauth.ensure_ready()
    assert ok is False and "no subscription is authorised" in reason


# ---------------------------------------------------------------------------
# The device flow
# ---------------------------------------------------------------------------


def test_start_returns_the_code_immediately_and_authorises_in_the_background(
    token_dir, secrets, bits
):
    """The shape the interface needs: a request cannot block for fifteen minutes."""
    transport = StubTransport(_script(bits, [StubResponse(403), _approved()]))

    began = time.monotonic()
    status = oauth.start_login(transport=transport, timeout_seconds=5, poll_interval=0.01)
    elapsed = time.monotonic() - began

    assert status.state == oauth.LOGIN_PENDING
    assert status.user_code == "WXYZ-1234"
    assert status.verification_url == bits.verify_url
    assert elapsed < 1.0, f"start_login took {elapsed:.2f}s; it must issue one request and return"

    final = _await_login(oauth.LOGIN_AUTHORISED)
    assert final.user_code == "", "the device code must not linger after the login"
    assert oauth.is_authorised() is True
    assert oauth._read_record()["account_id"] == FAKE_ACCOUNT_ID
    assert secrets.get_secret(oauth.SECRET_NAME) is not None
    assert transport.urls().count(bits.device_token_url) == 2


def test_every_request_carries_an_explicit_timeout(token_dir, secrets, bits):
    """FD hygiene: a request without one is a leak waiting for a slow peer."""
    transport = StubTransport(_script(bits, [_approved()]))
    oauth.start_login(transport=transport, timeout_seconds=5, poll_interval=0.01)
    _await_login(oauth.LOGIN_AUTHORISED)

    assert transport.calls
    for url, kwargs in transport.calls:
        assert kwargs.get("timeout") == oauth.HTTP_TIMEOUT_SECONDS, f"{url} had no timeout"


def test_a_second_start_returns_the_login_already_in_flight(token_dir, secrets, bits):
    """The device endpoint applies a five-minute cooldown after issuing a code,
    and the first code may already be half typed into the operator's browser.
    Replacing it silently turns a slow login into a failed one."""
    transport = StubTransport(_script(bits, [StubResponse(403)]))

    first = oauth.start_login(transport=transport, timeout_seconds=5, poll_interval=0.05)
    second = oauth.start_login(transport=transport, timeout_seconds=5, poll_interval=0.05)

    assert second.user_code == first.user_code
    assert second.started_at == first.started_at
    assert transport.urls().count(bits.device_code_url) == 1, "a second device code was requested"

    assert oauth.cancel_login() is True


def test_a_start_the_instant_the_last_login_ended_begins_a_new_one(
    token_dir, secrets, bits, monkeypatch
):
    """ "In flight" is what the snapshot says, not whether the thread object lives.

    A worker that has already published its terminal state is still alive for
    as long as its `finally` takes: it closes the HTTP client, imports
    `database.agent_db` and removes the thread's scoped session. An operator
    clicking "Sign in" again the moment a failure appeared landed inside that
    window and was handed back the **failed** snapshot, with an empty user code,
    while no device code was requested at all. Nothing happened until they
    clicked a second time.

    The `finally` is widened here so the window is hit on every run. It exists
    without that; the sleep only makes it wide enough to test.
    """
    real_release = oauth._release_session
    monkeypatch.setattr(oauth, "_release_session", lambda: (time.sleep(0.5), real_release())[1])

    first = StubTransport(_script(bits, [StubResponse(500)]))
    oauth.start_login(transport=first, timeout_seconds=30, poll_interval=0.01)
    failed = _await_login(oauth.LOGIN_FAILED)

    assert failed.user_code == ""
    assert oauth._thread is not None and oauth._thread.is_alive(), (
        "the worker must still be inside its finally, or this case proves nothing"
    )

    second = StubTransport(_script(bits, [StubResponse(403)]))
    snapshot = oauth.start_login(transport=second, timeout_seconds=30, poll_interval=0.05)

    assert snapshot.state == oauth.LOGIN_PENDING
    assert snapshot.user_code == "WXYZ-1234"
    assert second.urls().count(bits.device_code_url) == 1, "no new device code was requested"

    assert oauth.cancel_login() is True


def test_forcing_a_restart_replaces_the_login_deliberately(token_dir, secrets, bits):
    """`force=True` is the "start over" control, and it cancels first."""
    transport = StubTransport(_script(bits, [StubResponse(403)]))
    oauth.start_login(transport=transport, timeout_seconds=5, poll_interval=0.05)

    oauth.start_login(transport=transport, force=True, timeout_seconds=5, poll_interval=0.05)
    assert transport.urls().count(bits.device_code_url) == 2
    assert oauth.login_status().state == oauth.LOGIN_PENDING

    assert oauth.cancel_login() is True


def test_cancel_stops_the_thread_and_does_not_leave_it_running(token_dir, secrets, bits):
    """An operator who closes the dialog must not leave a thread polling for a
    quarter of an hour in a worker that never restarts."""
    transport = StubTransport(_script(bits, [StubResponse(403)]))
    oauth.start_login(transport=transport, timeout_seconds=600, poll_interval=0.05)

    thread = oauth._thread
    assert thread is not None and thread.is_alive()

    began = time.monotonic()
    assert oauth.cancel_login() is True
    elapsed = time.monotonic() - began

    assert elapsed < 5.0, f"cancel took {elapsed:.2f}s"
    assert thread.is_alive() is False, "the poll thread outlived its cancel"
    assert oauth.login_status().state == oauth.LOGIN_CANCELLED
    assert oauth._thread is None
    assert oauth.cancel_login() is False, "cancelling nothing must report nothing"


def test_only_one_thread_ever_exists(token_dir, secrets, bits):
    """No per-call thread and no executor: this worker never restarts."""
    import threading

    transport = StubTransport(_script(bits, [StubResponse(403)]))
    before = {t.name for t in threading.enumerate()}

    for _ in range(4):
        oauth.start_login(transport=transport, timeout_seconds=600, poll_interval=0.05)

    ours = [t for t in threading.enumerate() if t.name == "agent-chatgpt-oauth"]
    assert len(ours) == 1, f"expected one login thread, found {len(ours)}"

    oauth.cancel_login()
    time.sleep(0.1)
    after = {t.name for t in threading.enumerate()}
    assert "agent-chatgpt-oauth" not in after - before


def test_an_unapproved_code_reports_expired_not_failed(token_dir, secrets, bits):
    """Different states because the operator's next step differs: nothing is
    broken, they simply have to start again."""
    transport = StubTransport(_script(bits, [StubResponse(403)]))
    oauth.start_login(transport=transport, timeout_seconds=0.2, poll_interval=0.05)

    final = _await_login(oauth.LOGIN_EXPIRED)
    assert "expired" in final.message.lower()
    assert oauth.is_authorised() is False


def test_a_hard_poll_failure_stops_rather_than_retrying_for_fifteen_minutes(
    token_dir, secrets, bits
):
    """403 and 404 mean "not yet"; a 500 means something is wrong and the
    operator deserves to be told rather than watched for a quarter of an hour."""
    transport = StubTransport(_script(bits, [StubResponse(500)]))
    oauth.start_login(transport=transport, timeout_seconds=30, poll_interval=0.05)

    final = _await_login(oauth.LOGIN_FAILED)
    assert "500" in final.message
    assert transport.urls().count(bits.device_token_url) == 1


def test_the_endpoints_own_poll_interval_is_a_floor_not_a_suggestion(token_dir, secrets, bits):
    """Polling faster than the endpoint asked for is how a client gets rate
    limited off the flow. LiteLLM takes the larger of its own minimum and the
    interval the endpoint returned, and so does this."""
    script = _script(bits, [StubResponse(403), _approved()])
    script[bits.device_code_url] = [
        StubResponse(200, {"device_auth_id": "dev-1", "user_code": "WXYZ-1234", "interval": 0.4})
    ]
    transport = StubTransport(script)

    began = time.monotonic()
    oauth.start_login(transport=transport, timeout_seconds=10, poll_interval=0.0)
    _await_login(oauth.LOGIN_AUTHORISED)
    elapsed = time.monotonic() - began

    assert elapsed >= 0.4, f"the endpoint asked for 0.4s between polls, waited {elapsed:.2f}s"


def test_no_combination_of_intervals_produces_a_poll_loop_with_no_wait(token_dir, bits):
    """A zero wait is a hot loop against someone else's auth host, on a real OS
    thread, for a quarter of an hour: a burnt core and a rate limit.

    The endpoint's value is also parsed defensively. It is built from whatever
    JSON the auth host sent, and one that would not parse used to raise
    `ValueError` out of the poll loop into the catch-all that reports "The
    sign-in failed unexpectedly" and names nothing.
    """
    assert oauth._poll_wait(0.0, 0) >= oauth._MIN_POLL_SECONDS
    assert oauth._poll_wait(0.0, None) >= oauth._MIN_POLL_SECONDS
    assert oauth._poll_wait(0.0, "not-a-number") >= oauth._MIN_POLL_SECONDS
    assert oauth._poll_wait("nonsense", "5") == 5.0

    # The endpoint's interval stays a floor rather than a suggestion, and the
    # caller's stays one too.
    assert oauth._poll_wait(0.0, "0.4") == 0.4
    assert oauth._poll_wait(7.0, "5") == 7.0

    # And end to end: a device code carrying junk still completes the login.
    script = _script(bits, [StubResponse(403), _approved()])
    script[bits.device_code_url] = [
        StubResponse(
            200, {"device_auth_id": "dev-1", "user_code": "WXYZ-1234", "interval": "who knows"}
        )
    ]
    oauth.start_login(transport=StubTransport(script), timeout_seconds=5, poll_interval=0.01)
    assert _await_login(oauth.LOGIN_AUTHORISED).state == oauth.LOGIN_AUTHORISED


def test_a_refused_device_code_fails_immediately_and_is_visible_to_a_poller(token_dir, bits):
    """The synchronous half raises, because the caller is right there. The state
    is set as well, so a client that only polls still learns what happened."""
    transport = StubTransport({bits.device_code_url: [StubResponse(429)]})

    with pytest.raises(oauth.ChatGptOAuthError, match="429"):
        oauth.start_login(transport=transport)

    assert oauth.login_status().state == oauth.LOGIN_FAILED
    assert oauth._thread is None


def test_an_incomplete_device_code_response_is_refused(token_dir, bits):
    """A 200 carrying half the fields is a failure, not a login."""
    transport = StubTransport({bits.device_code_url: [StubResponse(200, {"user_code": "AB-12"})]})

    with pytest.raises(oauth.ChatGptOAuthError, match="incomplete"):
        oauth.start_login(transport=transport)


def test_an_incomplete_token_exchange_is_refused(token_dir, secrets, bits):
    """A token exchange that answers 200 without a refresh token is not a login."""
    script = _script(bits, [_approved()])
    script[bits.oauth_token_url] = [StubResponse(200, {"access_token": _access_token()})]
    transport = StubTransport(script)

    oauth.start_login(transport=transport, timeout_seconds=5, poll_interval=0.01)
    final = _await_login(oauth.LOGIN_FAILED)

    assert "incomplete" in final.message
    assert oauth.is_authorised() is False


def test_a_transport_error_becomes_a_readable_failure(token_dir, secrets, bits):
    """A dead network is a message, not a traceback in the operator's face."""

    class DeadTransport:
        def post(self, url, **kwargs):
            raise OSError("no route to host")

        def close(self):
            return None

    with pytest.raises(oauth.ChatGptOAuthError, match="OSError"):
        oauth.start_login(transport=DeadTransport())

    assert oauth.login_status().state == oauth.LOGIN_FAILED


# ---------------------------------------------------------------------------
# The refresh path
# ---------------------------------------------------------------------------


def test_a_refresh_writes_the_new_access_token_to_both_copies(token_dir, secrets, bits):
    """A rotated refresh token that only reached the file would leave the
    database holding one that no longer works, which a restored backup would
    discover months later."""
    oauth._write_record(
        {"access_token": _access_token(ttl_seconds=-60), "refresh_token": FAKE_REFRESH_TOKEN}
    )
    oauth.store_tokens()

    rotated = FAKE_REFRESH_TOKEN + "-rotated"
    fresh = _access_token()
    transport = StubTransport(
        {
            bits.oauth_token_url: [
                StubResponse(
                    200,
                    {
                        "access_token": fresh,
                        "refresh_token": rotated,
                        "id_token": _jwt({"sub": "user"}),
                    },
                )
            ]
        }
    )

    ok, error = oauth.refresh_access_token(transport=transport)
    assert ok is True and error is None

    record = oauth._read_record()
    assert record["access_token"] == fresh
    assert record["refresh_token"] == rotated
    assert json.loads(secrets.get_secret(oauth.SECRET_NAME))["refresh_token"] == rotated


def test_a_refresh_keeps_the_old_token_when_the_provider_sends_none(token_dir, secrets, bits):
    """Not every refresh rotates. Dropping the old token would end the session."""
    oauth._write_record({"refresh_token": FAKE_REFRESH_TOKEN})
    transport = StubTransport(
        {
            bits.oauth_token_url: [
                StubResponse(
                    200, {"access_token": _access_token(), "id_token": _jwt({"sub": "user"})}
                )
            ]
        }
    )

    ok, error = oauth.refresh_access_token(transport=transport)
    assert ok is True and error is None
    assert oauth._read_record()["refresh_token"] == FAKE_REFRESH_TOKEN


def test_a_refused_refresh_reports_the_status_and_changes_nothing(token_dir, secrets, bits):
    """A revoked subscription must not quietly wipe the stored credential."""
    oauth._write_record({"refresh_token": FAKE_REFRESH_TOKEN})
    transport = StubTransport({bits.oauth_token_url: [StubResponse(400, {"error": "bad_grant"})]})

    ok, error = oauth.refresh_access_token(transport=transport)
    assert ok is False
    assert "400" in error
    assert oauth._read_record()["refresh_token"] == FAKE_REFRESH_TOKEN


def test_a_refresh_that_cannot_be_written_reports_failure_rather_than_success(
    token_dir, secrets, bits, monkeypatch
):
    """The same silent-write hazard on the path LiteLLM does not drive itself.

    A refresh that answered `(True, None)` after failing to write leaves the
    operator believing their session was renewed while the file still holds the
    token that was already expiring.
    """
    oauth._write_record({"refresh_token": FAKE_REFRESH_TOKEN})
    monkeypatch.setattr(bits.authenticator_cls, "_write_auth_file", lambda self, data: None)

    transport = StubTransport(
        {
            bits.oauth_token_url: [
                StubResponse(
                    200, {"access_token": _access_token(), "id_token": _jwt({"sub": "user"})}
                )
            ]
        }
    )

    ok, error = oauth.refresh_access_token(transport=transport)
    assert ok is False
    assert "could not be written" in error


def test_a_refresh_with_nothing_stored_says_so(token_dir, secrets, bits):
    """No token is a different answer from a rejected one."""
    ok, error = oauth.refresh_access_token(transport=StubTransport({}))
    assert ok is False
    assert "Sign in" in error


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------


def test_every_subscription_model_reports_tokens_and_no_price():
    """LiteLLM prices `gpt-5.4` and deliberately does not price
    `chatgpt/gpt-5.4`. A subscription turn consumes plan quota, so there is no
    per-token price to report, and reporting one would be an invention."""
    import litellm

    models = list(litellm.models_by_provider.get("chatgpt", []))
    # Ten from LiteLLM plus the ones services/agent/chatgpt_models.py adds,
    # rather than a hard 10: the supplement is expected to grow, and the claim
    # worth pinning is that NO plan model carries a price, whatever the count.
    assert len(models) >= 10, f"expected at least 10 chatgpt models, litellm lists {len(models)}"

    for model in models:
        model_id = model if model.startswith(oauth.MODEL_PREFIX) else oauth.MODEL_PREFIX + model
        assert oauth.is_subscription_model(model_id) is True
        assert catalog.estimate_cost(model_id, 1000, 500) is None, model_id
        assert oauth.apply_billing(model_id, None) == (oauth.BILLING_SUBSCRIPTION, None)


def test_the_same_model_name_on_two_billing_systems_stays_distinguishable():
    """Eight of the ten share a bare name with an `openai` model, `gpt-5.4`
    included, so the prefix is the only thing separating a plan turn from a
    metered one."""
    assert oauth.is_subscription_model("chatgpt/gpt-5.4") is True
    assert oauth.is_subscription_model("gpt-5.4") is False
    assert oauth.is_subscription_model("openai/gpt-5.4") is False

    assert oauth.billing_mode("chatgpt/gpt-5.4") == oauth.BILLING_SUBSCRIPTION
    assert oauth.billing_mode("openai/gpt-5.4") == oauth.BILLING_METERED

    metered = catalog.estimate_cost("openai/gpt-5.4", 1000, 500)
    assert metered is not None and metered > 0


def test_a_subscription_turn_is_never_reported_as_free():
    """The two wrong answers, named.

    Zero reads as "this turn cost nothing" when it consumed plan quota. The
    bare-name price reads as an authoritative figure for usage never billed
    that way, which is worse because nobody questions a plausible number.
    """
    assert oauth.apply_billing("chatgpt/gpt-5.4", 0.0) == (oauth.BILLING_SUBSCRIPTION, None)
    assert oauth.apply_billing("chatgpt/gpt-5.4", 0.0123) == (oauth.BILLING_SUBSCRIPTION, None)

    # A metered turn that genuinely cost nothing keeps its zero: that is a
    # different claim, and a true one.
    assert oauth.apply_billing("ollama/llama3", 0.0) == (oauth.BILLING_METERED, 0.0)
    assert oauth.apply_billing("openai/gpt-5.4", 0.01) == (oauth.BILLING_METERED, 0.01)


def test_the_reported_model_name_alone_cannot_re_price_a_plan_turn():
    """The usage layer holds two names for one model, and only one is trusted.

    `stream.EventTranslator` starts from the id resolved off the operator's row,
    which always carries the prefix, and then overwrites it with whatever the
    provider reported. Those agree today: agno fills
    `ModelRequestCompletedEvent.model` from `agent.model.id`, which is the
    prefixed id `providers.litellm_model_id` stored. But the prefix is the only
    thing separating a plan turn from a metered one for eight of the ten models,
    so a bare reported name would resolve `gpt-5.4` to the OpenAI price list and
    quote an authoritative figure for usage never billed that way.
    """
    assert oauth.is_subscription_turn("gpt-5.4", "chatgpt/gpt-5.4") is True
    assert oauth.is_subscription_turn("chatgpt/gpt-5.4", None) is True
    assert oauth.is_subscription_turn("gpt-5.4", "openai/gpt-5.4") is False

    # The reported name has lost its prefix; the resolved one has not.
    assert oauth.apply_billing("gpt-5.4", 0.01, resolved_model_id="chatgpt/gpt-5.4") == (
        oauth.BILLING_SUBSCRIPTION,
        None,
    )
    # A genuinely metered turn is unaffected by the extra argument.
    assert oauth.apply_billing("gpt-5.4", 0.01, resolved_model_id="openai/gpt-5.4") == (
        oauth.BILLING_METERED,
        0.01,
    )
    # And omitting it keeps the old behaviour, so an un-updated caller still works.
    assert oauth.apply_billing("chatgpt/gpt-5.4", 0.01) == (oauth.BILLING_SUBSCRIPTION, None)


def test_the_stored_row_fingerprint_is_not_the_one_to_show(token_dir, secrets):
    """Two fingerprints exist for this credential and they are different.

    The whole auth record is what gets encrypted, so `agent_db.set_secret`
    fingerprints the canonical JSON and the `ag_secret` row ends up describing a
    blob rather than a credential. `status()` fingerprints the refresh token, so
    it survives an access-token refresh. A settings screen that rendered the row
    would show a second, different identifier for the same credential.
    """
    from database import agent_db

    record = {"refresh_token": FAKE_REFRESH_TOKEN, "account_id": FAKE_ACCOUNT_ID}
    oauth._write_record(record)
    oauth.store_tokens()

    shown = oauth.status()["fingerprint"]
    row = agent_db.fingerprint(secrets.get_secret(oauth.SECRET_NAME))

    assert shown == agent_db.fingerprint(FAKE_REFRESH_TOKEN)
    assert shown != row, "if these ever agree, drop the warning in status()'s docstring"


def test_the_subscription_models_are_offered_by_the_catalogue():
    """They are `mode: responses`, which the catalogue already counts as chat.
    If that changed they would vanish from the picker for no visible reason."""
    from services.agent import chatgpt_models

    models = catalog.list_models("chatgpt", chat_only=True)
    ids = {model.id for model in models}
    assert "chatgpt/gpt-5.4" in ids
    # The supplement must reach the picker too, or the models it exists to add
    # are registered for the runtime and invisible to the operator.
    for name in chatgpt_models.SUPPLEMENTAL:
        assert f"chatgpt/{name}" in ids, name
    assert len(models) >= 10
    assert all(model.supports_function_calling for model in models)
    assert all(model.input_price_per_million is None for model in models)


# ---------------------------------------------------------------------------
# A token never reaches a log, a return value or a repr
# ---------------------------------------------------------------------------


def _flatten(value) -> str:
    """Every scalar in a structure, joined, so a token hiding in a nested field
    is still found by a substring search.

    Args:
        value: Any JSON-ish structure.

    Returns:
        One string.
    """
    if isinstance(value, dict):
        return " ".join(_flatten(item) for pair in value.items() for item in pair)
    if isinstance(value, (list, tuple)):
        return " ".join(_flatten(item) for item in value)
    return str(value)


def test_status_describes_the_credential_and_shows_none_of_it(token_dir, secrets):
    """A fingerprint is what an operator sees, exactly as for an API key."""
    access = _access_token()
    oauth._write_record(
        {
            "access_token": access,
            "refresh_token": FAKE_REFRESH_TOKEN,
            "id_token": _jwt({"sub": "user"}),
            "account_id": FAKE_ACCOUNT_ID,
        }
    )
    oauth.store_tokens()

    payload = oauth.status()
    flat = _flatten(payload)

    assert FAKE_REFRESH_TOKEN not in flat
    assert access not in flat
    assert payload["authorised"] is True
    assert payload["account_id"] == FAKE_ACCOUNT_ID
    assert payload["fingerprint"].startswith("...")
    assert "sha256:" in payload["fingerprint"]
    assert payload["fingerprint"][-4:] != FAKE_REFRESH_TOKEN[-8:]


def test_no_token_reaches_a_log_line_across_the_whole_flow(token_dir, secrets, bits, caplog):
    """Asserted over the captured records of a complete login, a refresh and a
    status read, rather than by reading the source for `logger` calls.

    The device **user code** is checked too: it is shown on the operator's
    screen by design and is a standing phishing target, which is why LiteLLM's
    own prompt says never to share it.
    """
    caplog.set_level(logging.DEBUG)

    transport = StubTransport(_script(bits, [StubResponse(403), _approved()]))
    oauth.start_login(transport=transport, timeout_seconds=5, poll_interval=0.01)
    _await_login(oauth.LOGIN_AUTHORISED)
    oauth.refresh_access_token(
        transport=StubTransport(
            {
                bits.oauth_token_url: [
                    StubResponse(
                        200,
                        {
                            "access_token": _access_token(),
                            "refresh_token": FAKE_REFRESH_TOKEN,
                            "id_token": _jwt({"sub": "user"}),
                        },
                    )
                ]
            }
        )
    )
    oauth.status()

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert FAKE_REFRESH_TOKEN not in logged
    assert "WXYZ-1234" not in logged, "the device code reached a log line"
    for access in (call[1].get("json", {}) or {} for call in transport.calls):
        for value in access.values():
            assert str(value) not in logged or len(str(value)) < 8


def test_a_login_snapshot_repr_carries_no_credential(token_dir, secrets, bits):
    """`LoginStatus` is a dataclass and its repr goes into any traceback that
    happens to hold one."""
    transport = StubTransport(_script(bits, [_approved()]))
    oauth.start_login(transport=transport, timeout_seconds=5, poll_interval=0.01)
    final = _await_login(oauth.LOGIN_AUTHORISED)

    text = repr(final) + repr(final.as_dict())
    assert FAKE_REFRESH_TOKEN not in text
    assert oauth._read_record()["access_token"] not in text


def test_the_module_does_not_print(token_dir):
    """LiteLLM's own `_login_device_code` prints the code to stdout, which is
    why this module drives the flow rather than calling it. `print()` is banned
    here, and a copy of LiteLLM's implementation would have brought one in."""
    source = Path(oauth.__file__).read_text(encoding="utf-8")

    # A bare `print(` call, not `fingerprint(` or `pprint(`.
    assert re.search(r"(?<![A-Za-z0-9_.])print\s*\(", source) is None

    # And LiteLLM's own blocking, printing login is never invoked.
    assert "._login_device_code(" not in source
    assert ".get_access_token(" not in source


# ---------------------------------------------------------------------------
# The threading, proven under a real eventlet hub
# ---------------------------------------------------------------------------


def _eventlet_installed() -> bool:
    """Whether eventlet can be imported at all.

    A module-level `importorskip` would be wrong here: eventlet is installed by
    the production installer rather than by `pyproject.toml`, and skipping the
    whole file on a developer machine would take the custody, device-flow and
    cost cases with it. Only the hub proof needs it.

    Returns:
        True when eventlet is importable.
    """
    from importlib.util import find_spec

    return find_spec("eventlet") is not None


requires_eventlet = pytest.mark.skipif(
    not _eventlet_installed(),
    reason="eventlet is installed by the production installer, not by pyproject",
)

PREAMBLE = '''
import eventlet
eventlet.monkey_patch()

import json
import sys
import tempfile
import threading
import time

import eventlet.patcher

# The unpatched originals. `_real_sleep` is how a blocking C-served read looks
# to the hub: it does not yield, it does not fire timers, it just stops.
_orig_time = eventlet.patcher.original("time")
_orig_threading = eventlet.patcher.original("threading")
_real_sleep = _orig_time.sleep

POLL_BLOCKS_FOR = 0.25
TICK = 0.02

from services.agent import chatgpt_oauth as oauth

# No database in this subprocess. The custody write is proven by the pytest
# cases above; what is on trial here is the hub, and importing the database
# stack would only add noise.
oauth.store_tokens = lambda: True
oauth.restore_tokens = lambda force=False: False

TOKEN_DIR = tempfile.mkdtemp(prefix="oa-chatgpt-oauth-")
oauth.configure_token_dir(TOKEN_DIR)
BITS = oauth._bits()


class Response:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class BlockingTransport:
    """Every poll blocks in unpatched C for POLL_BLOCKS_FOR seconds.

    That is what a TLS read on the auth host looks like to the hub: it does not
    yield. If this ran on the green side the worker would stop for the whole
    fifteen minutes of the device flow.
    """

    def __init__(self, block_device_code=False):
        self.block_device_code = block_device_code
        self.polls = 0

    def post(self, url, **kwargs):
        if url == BITS.device_code_url:
            if self.block_device_code:
                _real_sleep(POLL_BLOCKS_FOR)
            return Response(
                200, {"device_auth_id": "d", "user_code": "AAAA-0000", "interval": 0.05}
            )
        self.polls += 1
        _real_sleep(POLL_BLOCKS_FOR)
        return Response(403)

    def close(self):
        return None


def hub_ticks(seconds):
    """Run a greenlet that counts its own wakeups for `seconds`.

    A frozen hub records nothing, which is the measurement this file is for:
    the return values were always right.
    """
    ticks = []

    def counter():
        while True:
            ticks.append(1)
            eventlet.sleep(TICK)

    g = eventlet.spawn(counter)
    eventlet.sleep(seconds)
    g.kill()
    return len(ticks)
'''


def run(body: str) -> subprocess.CompletedProcess:
    """Run one eventlet case in a subprocess.

    `monkey_patch()` is global and cannot be undone, so importing it into the
    pytest process would change the meaning of every test that ran afterwards.

    Args:
        body: The case source, appended to :data:`PREAMBLE`.

    Returns:
        The finished process.
    """
    return subprocess.run(
        [sys.executable, "-c", PREAMBLE + textwrap.dedent(body)],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(PROJECT_ROOT),
    )


@requires_eventlet
def test_polling_on_the_green_side_would_freeze_the_worker():
    """The defect itself, so nothing below can pass vacuously.

    The same poll loop, called inline from a greenlet, stops the hub for its
    whole duration. In production that is every other request on the box,
    orders included, for as long as the operator takes to approve a code.
    """
    result = run(
        """
        transport = BlockingTransport()
        device = {"device_auth_id": "d", "user_code": "AAAA-0000", "interval": "0"}
        cancel = oauth.Event()

        ticks = []

        def counter():
            while True:
                ticks.append(1)
                eventlet.sleep(TICK)

        g = eventlet.spawn(counter)
        eventlet.sleep(0.05)
        before = len(ticks)
        t0 = time.monotonic()
        try:
            oauth._poll_for_code(transport, BITS, device, cancel, 0.9, 0.0)
        except oauth.ChatGptOAuthError:
            pass
        took = time.monotonic() - t0
        during = len(ticks) - before
        g.kill()

        assert took >= 0.5, "the inline poll did not actually block"
        assert during <= 1, (
            "expected an inline poll to freeze the hub, got %d ticks in %.2fs; "
            "if this stops holding, the whole file is moot" % (during, took)
        )
        print("OK")
        """
    )
    assert "OK" in result.stdout, result.stderr


@requires_eventlet
def test_a_login_in_flight_does_not_stall_a_green_worker():
    """`start_login` returns at once and the hub keeps running while the real
    OS thread polls behind it, with the transport blocking in unpatched C the
    whole time."""
    result = run(
        """
        transport = BlockingTransport()

        t0 = time.monotonic()
        status = oauth.start_login(
            transport=transport, timeout_seconds=30, poll_interval=0.0
        )
        started_in = time.monotonic() - t0

        assert status.state == oauth.LOGIN_PENDING, status.state
        assert status.user_code == "AAAA-0000"
        assert started_in < 0.5, "start_login took %.2fs" % started_in

        ticks = hub_ticks(0.8)
        assert ticks > 20, "the hub only ticked %d times while a login polled" % ticks
        assert transport.polls >= 2, "the background thread never polled"
        assert oauth.login_status().state == oauth.LOGIN_PENDING

        t0 = time.monotonic()
        assert oauth.cancel_login() is True
        assert time.monotonic() - t0 < 5, "cancel was slow"
        assert oauth._thread is None
        print("OK")
        """
    )
    assert "OK" in result.stdout, result.stderr


@requires_eventlet
def test_cancelling_from_a_greenlet_does_not_freeze_the_hub_either():
    """`cancel_login` joins a real OS thread, and `Thread.join()` from a
    greenlet blocks the whole worker for the length of the wait. It uses
    `real_threading.join`, which polls and yields."""
    result = run(
        """
        transport = BlockingTransport()
        oauth.start_login(transport=transport, timeout_seconds=30, poll_interval=0.0)
        eventlet.sleep(0.05)

        ticks = []

        def counter():
            while True:
                ticks.append(1)
                eventlet.sleep(TICK)

        g = eventlet.spawn(counter)
        eventlet.sleep(0.05)
        before = len(ticks)
        t0 = time.monotonic()
        stopped = oauth.cancel_login()
        took = time.monotonic() - t0
        during = len(ticks) - before
        g.kill()

        assert stopped is True
        assert during > 2, (
            "cancel_login froze the hub: %d ticks over %.2fs" % (during, took)
        )
        assert oauth.login_status().state == oauth.LOGIN_CANCELLED
        print("OK")
        """
    )
    assert "OK" in result.stdout, result.stderr


@requires_eventlet
def test_the_login_bookkeeping_uses_real_primitives():
    """Guards the specific attributes, so an edit back to plain `threading`
    fails here rather than in production, where a real thread contending on a
    green lock is blocked forever."""
    result = run(
        """
        green_lock = type(threading.Lock())
        green_event = threading.Event

        assert not isinstance(oauth._lock, green_lock), (
            "the login lock is green; the poll thread takes it from a real OS thread"
        )

        transport = BlockingTransport()
        oauth.start_login(transport=transport, timeout_seconds=30, poll_interval=0.0)
        assert not isinstance(oauth._cancel, green_event), (
            "the cancel Event is green; a set() from a greenlet would never "
            "wake the real poll thread"
        )
        assert isinstance(oauth._thread, _orig_threading.Thread), (
            "the poll thread is a green thread; the whole worker would block"
        )
        oauth.cancel_login()
        print("OK")
        """
    )
    assert "OK" in result.stdout, result.stderr


@requires_eventlet
def test_the_status_read_a_ui_polls_never_blocks_the_hub():
    """`login_status` is what a UI hits every second while a login runs. It
    copies a frozen dataclass out from under a real lock and does nothing
    else."""
    result = run(
        """
        transport = BlockingTransport()
        oauth.start_login(transport=transport, timeout_seconds=30, poll_interval=0.0)

        ticks = []

        def counter():
            while True:
                ticks.append(1)
                eventlet.sleep(TICK)

        g = eventlet.spawn(counter)
        eventlet.sleep(0.05)
        before = len(ticks)
        t0 = time.monotonic()
        for _ in range(200):
            oauth.login_status()
        took = time.monotonic() - t0
        during = len(ticks) - before
        g.kill()

        assert took < 0.5, "200 status reads took %.2fs" % took
        # 200 reads are faster than one hub tick, so the measurement that means
        # anything is that the hub is still running afterwards rather than that
        # it ticked during. A green lock taken from the poll thread would have
        # left the hub dead by now.
        assert hub_ticks(0.3) > 5, "the hub was dead after the status reads"
        oauth.cancel_login()
        print("OK")
        """
    )
    assert "OK" in result.stdout, result.stderr


@requires_eventlet
def test_the_token_directory_never_becomes_a_tilde_folder_under_eventlet():
    """The containment holds in the process shape that produced the accident."""
    result = run(
        """
        import os
        from pathlib import Path

        repo = Path(oauth.PROJECT_ROOT)
        tilde = repo / "~"
        before = tilde.exists()

        assert "~" not in os.environ["CHATGPT_TOKEN_DIR"]
        assert Path(os.environ["CHATGPT_TOKEN_DIR"]).is_dir()

        authenticator = BITS.authenticator_cls()
        assert Path(authenticator.auth_file).parent == Path(os.environ["CHATGPT_TOKEN_DIR"])
        assert tilde.exists() == before, "constructing an Authenticator created a tilde directory"
        print("OK")
        """
    )
    assert "OK" in result.stdout, result.stderr
