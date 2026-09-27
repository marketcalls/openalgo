"""Regression tests for GHSA-pmxj-9wx6-hjmf (host header poisoning in password reset).

Two distinct defects are covered:

1. The emailed reset link was built with ``url_for(..., _external=True)``, which
   derives its host from the request's ``Host`` header. A poisoned header sent
   the victim's reset token to an attacker-controlled origin.
2. The raw reset token was stored in the Flask session, which is a signed but
   *unencrypted* cookie. Whoever triggered the reset - an unauthenticated caller
   who only needs to know the target's email address - could read the token
   straight back out of their own cookie, with no Host trickery at all.
"""

import base64
import hashlib
import json
import os
import secrets

import pytest

os.environ.setdefault("HOST_SERVER", "https://legit.example.com")

from blueprints.auth import _hash_reset_token  # noqa: E402
from utils.config import build_external_url  # noqa: E402


class TestBuildExternalUrl:
    """The reset/callback links must be rooted at HOST_SERVER, not the Host header."""

    def test_uses_configured_host_server(self, monkeypatch):
        monkeypatch.setenv("HOST_SERVER", "https://legit.example.com")
        assert (
            build_external_url("/auth/reset-password-email/abc")
            == "https://legit.example.com/auth/reset-password-email/abc"
        )

    def test_trailing_slash_does_not_double_up(self, monkeypatch):
        monkeypatch.setenv("HOST_SERVER", "https://legit.example.com/")
        assert build_external_url("/auth/x") == "https://legit.example.com/auth/x"

    def test_relative_path_without_leading_slash(self, monkeypatch):
        monkeypatch.setenv("HOST_SERVER", "https://legit.example.com")
        assert build_external_url("auth/x") == "https://legit.example.com/auth/x"

    def test_ignores_attacker_supplied_host(self, monkeypatch):
        """The whole point: nothing from the request can steer the result."""
        monkeypatch.setenv("HOST_SERVER", "https://legit.example.com")
        link = build_external_url("/auth/reset-password-email/TOKEN")
        assert "evil.com" not in link
        assert link.startswith("https://legit.example.com/")


class TestResetTokenHashing:
    """The session must never carry the raw reset token."""

    def test_hash_is_sha256_hex(self):
        token = "some-token-value"
        expected = hashlib.sha256(token.encode("utf-8")).hexdigest()
        assert _hash_reset_token(token) == expected
        assert len(_hash_reset_token(token)) == 64

    def test_hash_is_stable_and_distinct(self):
        assert _hash_reset_token("a") == _hash_reset_token("a")
        assert _hash_reset_token("a") != _hash_reset_token("b")

    def test_raw_token_not_recoverable_from_session_cookie(self):
        """Simulate the cookie-decode attack against the stored value.

        A Flask session cookie is signed, not encrypted - its payload decodes
        with no secret. Storing the hash means the decoded payload is useless
        for completing the reset.
        """
        token = secrets.token_urlsafe(32)
        session_payload = {
            "reset_token": _hash_reset_token(token),
            "reset_email": "victim@example.com",
        }

        # What an attacker holding the cookie can read.
        decoded = json.loads(
            base64.urlsafe_b64decode(
                base64.urlsafe_b64encode(json.dumps(session_payload).encode())
            ).decode()
        )

        assert token not in json.dumps(decoded)
        assert decoded["reset_token"] != token
        # And the hash cannot be replayed as if it were the token.
        assert _hash_reset_token(decoded["reset_token"]) != decoded["reset_token"]

    def test_submitted_token_verifies_against_stored_hash(self):
        """The legitimate flow still succeeds: raw token in, hash comparison passes."""
        token = secrets.token_urlsafe(32)
        stored = _hash_reset_token(token)
        assert secrets.compare_digest(_hash_reset_token(token), stored)

    def test_wrong_token_fails_verification(self):
        stored = _hash_reset_token(secrets.token_urlsafe(32))
        assert not secrets.compare_digest(_hash_reset_token(secrets.token_urlsafe(32)), stored)


class TestNoExternalUrlForRemains:
    """url_for(_external=True) must not come back into the outbound-link paths."""

    @pytest.mark.parametrize("path", ["blueprints/auth.py", "blueprints/brlogin.py"])
    def test_source_has_no_external_url_for(self, path):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(repo_root, path), encoding="utf-8") as f:
            lines = f.readlines()

        # Comments legitimately name the old pattern to explain why it is gone,
        # so only executable code is checked.
        offenders = [
            (n, line.rstrip())
            for n, line in enumerate(lines, start=1)
            if "_external=True" in line.split("#", 1)[0]
        ]
        assert not offenders, (
            f"{path} reintroduced url_for(_external=True) at {offenders}; outbound "
            "links must use build_external_url() so a poisoned Host header cannot "
            "steer them"
        )
