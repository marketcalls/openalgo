"""The warning startup prints when it cannot save FERNET_SALT to .env says
which salt is in use, and that salt is the one the database layer derives its
key from.

Three cases reach that warning with an unwritable .env (a read-only bind
mount, a .env owned by another user). Only one of them runs on the legacy
static salt:

- a valid FERNET_SALT that is not directly below API_KEY_PEPPER: startup
  only moves the line, and the value in .env stays in use;
- the sample's placeholder directly below API_KEY_PEPPER: no salt is set,
  so the legacy static salt is in use;
- no FERNET_SALT line at all: the same.

The first case used to say "Continuing with the legacy static salt", which
sent an operator whose stored credentials were fine looking for a fault.
"""

import os

import pytest

import utils.env_check as env_check
from database import auth_db

PEPPER = "b2" * 32
SALT = "c3" * 16
LEGACY = b"openalgo_static_salt"


def _unwritable(*_args, **_kwargs):
    raise PermissionError(13, "Permission denied")


@pytest.fixture
def read_only_env(tmp_path, monkeypatch):
    """Write a .env, load its keys into the environment, and make every
    write startup attempts on it fail."""
    monkeypatch.setattr(env_check, "_atomic_replace_text", _unwritable)
    monkeypatch.setattr(env_check, "_atomic_rewrite_dotenv", _unwritable)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'openalgo.db').as_posix()}")
    monkeypatch.delenv("FERNET_SALT", raising=False)
    monkeypatch.setattr(auth_db._resolve_fernet_salt, "_warned", True, raising=False)

    def write(text, salt=None):
        env = tmp_path / ".env"
        env.write_text(text, encoding="utf-8")
        monkeypatch.setenv("API_KEY_PEPPER", PEPPER)
        if salt is not None:
            monkeypatch.setenv("FERNET_SALT", salt)
        return str(env)

    return write


def _run(env_path, capsys):
    env_check._ensure_fernet_salt(env_path)
    return capsys.readouterr().err


def test_a_salt_that_only_could_not_be_moved_is_reported_as_in_use(read_only_env, capsys):
    env = read_only_env(
        f"API_KEY_PEPPER = '{PEPPER}'\n\n# a comment between them\nFERNET_SALT = '{SALT}'\n",
        salt=SALT,
    )

    warning = _run(env, capsys)

    assert auth_db._resolve_fernet_salt() == bytes.fromhex(SALT)
    assert os.environ["FERNET_SALT"] == SALT
    assert "Could not move the FERNET_SALT line" in warning
    assert "FERNET_SALT value from .env is in use" in warning
    assert "legacy static salt" not in warning


def test_a_placeholder_that_could_not_be_replaced_is_reported_as_legacy(read_only_env, capsys):
    env = read_only_env(
        f"API_KEY_PEPPER = '{PEPPER}'\nFERNET_SALT = '{env_check.PLACEHOLDER_FERNET_SALT}'\n",
        salt=env_check.PLACEHOLDER_FERNET_SALT,
    )

    warning = _run(env, capsys)

    assert auth_db._resolve_fernet_salt() == LEGACY
    assert "Could not rotate FERNET_SALT placeholder" in warning
    assert "Continuing with the legacy static salt" in warning


def test_a_missing_salt_that_could_not_be_written_is_reported_as_legacy(read_only_env, capsys):
    env = read_only_env(f"API_KEY_PEPPER = '{PEPPER}'\n")

    warning = _run(env, capsys)

    assert auth_db._resolve_fernet_salt() == LEGACY
    assert "Could not write FERNET_SALT to .env" in warning
    assert "Continuing with the legacy static salt" in warning


def test_the_warnings_carry_no_long_dashes(read_only_env, capsys):
    """Startup output follows the project's writing rules."""
    env = read_only_env(f"API_KEY_PEPPER = '{PEPPER}'\n\nFERNET_SALT = '{SALT}'\n", salt=SALT)
    moved = _run(env, capsys)
    env = read_only_env(f"API_KEY_PEPPER = '{PEPPER}'\n")
    legacy = _run(env, capsys)

    for text in (moved, legacy):
        assert "—" not in text and "–" not in text
