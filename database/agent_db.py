# database/agent_db.py
"""
Persistence for the /agent module: the LLM agent with a chat surface and a
docked chart surface.

Six tables, all ``ag_`` prefixed. The prefix is not decoration: this codebase
already carries ``strategy_``, ``sm_`` and ``flow_`` prefixes for unrelated
things, and "model" and "message" are words several of them would otherwise
want.

- ``ag_provider_model``  one row per model the operator has enabled
- ``ag_secret``          Fernet ciphertext for a provider or per-model API key
- ``ag_setting``         key/value agent settings, no migration to add one
- ``ag_conversation``    what the UI lists
- ``ag_message``         what the UI renders
- ``ag_audit``           append-only record of every mutating tool call

Three rules this module exists to hold:

1. **The API key is never a column on the model.** It lives in ``ag_secret``
   keyed ``provider:{kind}``, so adding a fourth GPT model does not mean pasting
   the OpenAI key a fourth time. A per-model override at ``model:{id}`` is
   honoured when present and wins over the provider key, which covers two
   accounts with the same provider.
2. **Exactly one model carries ``is_default``**, and the clearing of the old one
   happens in the same transaction as the setting of the new one. Doing it in
   two commits leaves a window with two defaults, and resolution would then pick
   whichever the query ordering happened to return.
3. **A secret is compared as decrypted plaintext, never as ciphertext.** Fernet
   is non-deterministic, so a ciphertext comparison never matches and rewrites
   the row on every save. That exact mistake produced real "database is locked"
   errors in ``database/telegram_db.py``; its fix is the pattern copied here.

Timestamps are stored naive UTC and converted at the API boundary. SQLite does
not preserve a timezone on a DateTime column whatever you pass it, so storing
aware datetimes would silently hand back naive ones on the next read and make
every comparison a coin flip.

Sessions are not released per call. This module follows
``database/strategy_module_db.py``: Flask requests are covered by the
``teardown_appcontext`` handler in ``app.py``, and the module is registered in
``utils/db_sessions.py`` so anything running outside a request (the agent's real
OS thread, which is where the audit rows are written) releases it by calling
``utils.db_sessions.remove_all_scoped_sessions()`` when the run ends.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from cachetools import TTLCache
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from database.auth_db import encrypt_token, safe_decrypt_token
from database.engine_factory import create_db_engine
from utils.logging import get_logger

logger = get_logger(__name__)

# Canonical engine factory enforces the project-wide pooling policy
# (SQLite -> NullPool with check_same_thread=False) for FD hygiene.
engine = create_db_engine()

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

# Settings are read on paths that run per request and per tool call (the
# trading-enabled flag and the kill switch are both read before an order is
# built), and they change only when an operator saves the settings page. Small,
# short-lived, and invalidated explicitly on every write, so the TTL only covers
# a path that forgot to invalidate.
_settings_cache: TTLCache = TTLCache(maxsize=64, ttl=300)

# Decrypted secrets are deliberately NOT cached. They are read once per agent
# run, not per token, so a cache would buy nothing and would keep provider
# plaintext alive in module state long after the run that needed it.


# ---------------------------------------------------------------------------
# Enumerated values
#
# Plain tuples rather than SQL CHECK constraints. SQLite cannot alter a CHECK
# constraint in place, so a constraint here would make every future value a
# table rebuild (see CLAUDE.md on migrations). Validation happens in the store
# and at the API boundary, where it can return a useful error.
# ---------------------------------------------------------------------------

PROVIDER_KINDS = ("openai", "anthropic", "ollama", "openai_compatible", "litellm")

# Kinds that address a private endpoint and therefore cannot work without one.
PROVIDER_KINDS_REQUIRING_BASE_URL = ("ollama", "openai_compatible")

REASONING_EFFORTS = ("off", "low", "medium", "high")

SURFACES = ("chat", "chart")

MESSAGE_ROLES = ("user", "assistant", "system", "tool")

AUDIT_PHASES = ("attempt", "result", "decision")

# Setting keys. Named constants rather than string literals at the call sites so
# a typo is an ImportError instead of a silently missing setting.
SETTING_SYSTEM_PROMPT = "system_prompt"
SETTING_DEFAULT_REASONING_EFFORT = "default_reasoning_effort"
SETTING_TRADING_ENABLED = "trading_enabled"
# The first check in services/agent/safety/risk.py. Set by an operator who wants
# every mutating tool refused without disabling the agent itself.
SETTING_KILL_SWITCH = "kill_switch"

SECRET_PROVIDER_PREFIX = "provider:"
SECRET_MODEL_PREFIX = "model:"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class AgProviderModel(Base):
    """One model the operator has enabled.

    Several providers are configured at once, each with its own key: OpenAI with
    an OpenAI key, Anthropic with an Anthropic key, a local Ollama with no key at
    all. All of them sit enabled here simultaneously and the chat surface offers
    a picker over every enabled row.

    The capability flags are operator-set, never inferred. The catalog is
    advisory: a model it has never heard of is still addable, and nothing here
    constrains ``model_name`` to a known string.
    """

    __tablename__ = "ag_provider_model"

    id = Column(Integer, primary_key=True)

    provider_kind = Column(String(32), nullable=False)
    # Passed to LiteLLM. For provider_kind 'litellm' it carries its own provider
    # prefix and is used verbatim; for the others providers.py adds the prefix.
    model_name = Column(String(200), nullable=False)
    display_name = Column(String(200), nullable=False)
    # Required for 'ollama' and 'openai_compatible', meaningless for the rest.
    base_url = Column(String(500), nullable=True)

    enabled = Column(Boolean, nullable=False, default=True)
    # Exactly one row carries this, enforced by set_default_model in the same
    # transaction that sets it. Never assign it directly.
    is_default = Column(Boolean, nullable=False, default=False)

    supports_reasoning = Column(Boolean, nullable=False, default=False)
    default_reasoning_effort = Column(String(16), nullable=False, default="off")
    supports_vision = Column(Boolean, nullable=False, default=False)
    # A tool-driven agent has to know this. A model that mangles tool calls is
    # still usable for prose and still worth listing, but the builder needs the
    # flag to decide what to hand it.
    tools_unreliable = Column(Boolean, nullable=False, default=False)

    last_tested_at = Column(DateTime, nullable=True)
    last_test_ok = Column(Boolean, nullable=True)
    # The provider's own message, verbatim. "invalid API key" and "model not
    # found" need different fixes, and a generic failure message helps nobody.
    last_test_error = Column(Text, nullable=True)

    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        onupdate=lambda: datetime.now(UTC).replace(tzinfo=None),
    )

    __table_args__ = (
        # Declared for the schema, but not relied upon: SQLite treats NULLs as
        # distinct in a UNIQUE constraint, so two rows with the same kind and
        # model_name and a NULL base_url both pass it. create_model and
        # update_model do the duplicate check themselves for that reason.
        UniqueConstraint(
            "provider_kind", "model_name", "base_url", name="uq_ag_provider_model_identity"
        ),
        Index("ix_ag_provider_model_enabled", "enabled"),
    )


class AgSecret(Base):
    """A provider or per-model API key, encrypted at rest.

    Encryption reuses OpenAlgo's existing cipher (``database.auth_db``: Fernet
    derived from ``API_KEY_PEPPER`` and ``FERNET_SALT``, both auto-provisioned
    per install). No second secret outside the database, and no second cipher.

    ``name`` is ``provider:{provider_kind}`` or ``model:{id}``. The value itself
    never leaves this module: everything that renders a secret renders the
    fingerprint and a boolean.
    """

    __tablename__ = "ag_secret"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False, unique=True, index=True)
    ciphertext = Column(Text, nullable=False)
    # Display-safe. Never the value, and not reversible to it.
    fingerprint = Column(String(80), nullable=False, default="")
    last_used_at = Column(DateTime, nullable=True)


class AgSetting(Base):
    """One agent setting. The key is the primary key.

    Key/value rather than columns so the system-prompt override, the default
    reasoning effort, the trading-enabled flag and anything added later cost no
    migration. Values are Text; booleans are stored as 'true'/'false' by
    set_bool_setting and read back by get_bool_setting.
    """

    __tablename__ = "ag_setting"

    key = Column(String(120), primary_key=True)
    value = Column(Text, nullable=True)


class AgConversation(Base):
    """One conversation, on one surface.

    Agno's own ``SqliteDb`` owns run and requirement state so a paused
    confirmation survives across requests, and it points at its own file under
    ``db/``. This table owns what the UI lists; ``agno_session_id`` is the join
    between the two.
    """

    __tablename__ = "ag_conversation"

    id = Column(Integer, primary_key=True)
    # The session username, matching database/watchlist_db.py and
    # database/strategy_module_db.py. OpenAlgo is single user per deployment, so
    # this keeps the schema honest rather than isolating tenants.
    user_id = Column(String(80), nullable=False, index=True)

    title = Column(String(300), nullable=True)
    surface = Column(String(20), nullable=False, default="chat")
    agno_session_id = Column(String(120), nullable=True, index=True)

    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        onupdate=lambda: datetime.now(UTC).replace(tzinfo=None),
    )

    __table_args__ = (Index("ix_ag_conversation_user_updated", "user_id", "updated_at"),)


class AgMessage(Base):
    """One rendered turn.

    ``tools`` and ``notices`` are JSON because they are only ever read as part of
    the message that owns them, never queried across messages. A child table
    would buy nothing and cost a migration every time a frame gains a field.
    """

    __tablename__ = "ag_message"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(
        Integer,
        ForeignKey("ag_conversation.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False, default="")
    tools = Column(JSON, nullable=True)
    notices = Column(JSON, nullable=True)

    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None)
    )

    __table_args__ = (Index("ix_ag_message_conversation_created", "conversation_id", "created_at"),)


class AgAudit(Base):
    """Append-only record of every mutating tool call.

    Two rows per call, ``attempt`` then ``result``, and one more per approval
    ``decision``. Nothing in this module updates or deletes a row here.

    ``conversation_id`` is a plain Integer with no foreign key on purpose: this
    is a trade audit and it has to outlive the conversation it was typed into,
    so deleting a conversation leaves these rows exactly where they are.

    ``run_id`` is a String because agno's run ids are opaque strings, and the
    same id appears in the ``start`` frame the client received.
    """

    __tablename__ = "ag_audit"

    id = Column(Integer, primary_key=True)
    ts = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None))

    phase = Column(String(16), nullable=False)
    tool = Column(String(120), nullable=False)
    conversation_id = Column(Integer, nullable=True, index=True)
    run_id = Column(String(120), nullable=True, index=True)

    args = Column(JSON, nullable=True)
    risk_verdict = Column(String(60), nullable=True)
    ok = Column(Boolean, nullable=True)
    response = Column(JSON, nullable=True)
    order_ids = Column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_ag_audit_conversation_ts", "conversation_id", "ts"),
        Index("ix_ag_audit_run_ts", "run_id", "ts"),
    )


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


def init_db() -> None:
    """Create the agent tables if they do not exist.

    Failures are logged and swallowed. The agent is optional, and a platform
    that will not boot because the agent could not create its tables is worse
    than one that boots without it. The scoped session is released here because
    this runs in a startup worker that then goes away.
    """
    try:
        from database.db_init_helper import init_db_with_logging

        init_db_with_logging(Base, engine, "Agent DB", logger)
    except Exception:
        logger.exception("Agent DB: failed to initialize")
        db_session.rollback()
    finally:
        db_session.remove()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def utcnow() -> datetime:
    """Naive UTC, matching how every timestamp column in this module is stored."""
    return datetime.now(UTC).replace(tzinfo=None)


def _iso(value: datetime | None) -> str | None:
    """A stored naive-UTC timestamp as an explicit UTC ISO string.

    The API layer converts to IST for display. Emitting the offset here means a
    consumer never has to guess what the bare string meant.
    """
    if value is None:
        return None
    return value.replace(tzinfo=UTC).isoformat()


def fingerprint(value: str | None) -> str:
    """A display-safe identifier for a secret.

    Last four characters plus a truncated SHA-256, which is enough for an
    operator to tell two keys apart and to confirm the one they pasted is the
    one that is stored, and not enough to recover any of it. A value of eight
    characters or fewer has no safe tail to show, so it gets a constant.

    Args:
        value: The plaintext secret, or None.

    Returns:
        Either ``"...abcd sha256:0123456789ab"`` or ``"...????"``.
    """
    if not value or len(value) <= 8:
        return "...????"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"...{value[-4:]} sha256:{digest}"


def provider_secret_name(provider_kind: str) -> str:
    """The secret name shared by every model of one provider kind.

    Args:
        provider_kind: One of ``PROVIDER_KINDS``.

    Returns:
        The ``provider:{kind}`` secret name.
    """
    return f"{SECRET_PROVIDER_PREFIX}{provider_kind}"


def model_secret_name(model_id: int) -> str:
    """The secret name for a per-model key override.

    Args:
        model_id: The ``ag_provider_model`` row id.

    Returns:
        The ``model:{id}`` secret name.
    """
    return f"{SECRET_MODEL_PREFIX}{model_id}"


def _normalize_base_url(base_url: str | None) -> str | None:
    """An empty or whitespace-only base URL is NULL, not an empty string.

    Two spellings of "no endpoint" would defeat the duplicate check and would
    make ``providers.py`` decide whether to pass ``api_base=""`` to LiteLLM.
    """
    if base_url is None:
        return None
    cleaned = str(base_url).strip()
    return cleaned or None


def _secret_index(names: list[str]) -> dict[str, AgSecret]:
    """Look up several secrets by name in one query, as a name -> row map."""
    if not names:
        return {}
    rows = db_session.query(AgSecret).filter(AgSecret.name.in_(set(names))).all()
    return {row.name: row for row in rows}


# ---------------------------------------------------------------------------
# Serialization
#
# Nothing here ever returns a secret value. A key is reported as a boolean and
# a fingerprint, which is what the setup UI needs and all it is allowed to have:
# the password input starts empty even when a key is configured, and blank on
# save means "keep the existing key".
# ---------------------------------------------------------------------------


def provider_model_to_dict(
    row: AgProviderModel, secret_index: dict[str, AgSecret] | None = None
) -> dict:
    """One model row as plain JSON-safe data, with its key described but not shown.

    Args:
        row: The model row.
        secret_index: Optional pre-fetched name -> secret map, so listing many
            models costs one secret query rather than one per row. Looked up
            here when not supplied.

    Returns:
        A dict carrying ``has_api_key``, ``api_key_fingerprint`` and
        ``api_key_source`` and never the key itself.
    """
    own = model_secret_name(row.id)
    shared = provider_secret_name(row.provider_kind)
    if secret_index is None:
        secret_index = _secret_index([own, shared])

    secret = secret_index.get(own) or secret_index.get(shared)
    if secret is not None and not secret.ciphertext:
        secret = None

    return {
        "id": row.id,
        "provider_kind": row.provider_kind,
        "model_name": row.model_name,
        "display_name": row.display_name,
        "base_url": row.base_url,
        "enabled": bool(row.enabled),
        "is_default": bool(row.is_default),
        "supports_reasoning": bool(row.supports_reasoning),
        "default_reasoning_effort": row.default_reasoning_effort,
        "supports_vision": bool(row.supports_vision),
        "tools_unreliable": bool(row.tools_unreliable),
        "last_tested_at": _iso(row.last_tested_at),
        "last_test_ok": row.last_test_ok,
        "last_test_error": row.last_test_error,
        "has_api_key": secret is not None,
        "api_key_fingerprint": secret.fingerprint if secret is not None else None,
        "api_key_source": secret.name if secret is not None else None,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def secret_to_dict(row: AgSecret) -> dict:
    """One secret row as plain JSON-safe data, without its value.

    Args:
        row: The secret row.

    Returns:
        Its name, fingerprint, a presence boolean and when it was last used.
    """
    return {
        "name": row.name,
        "fingerprint": row.fingerprint,
        "has_value": bool(row.ciphertext),
        "last_used_at": _iso(row.last_used_at),
    }


def conversation_to_dict(row: AgConversation) -> dict:
    """One conversation row as plain JSON-safe data."""
    return {
        "id": row.id,
        "user_id": row.user_id,
        "title": row.title,
        "surface": row.surface,
        "agno_session_id": row.agno_session_id,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def message_to_dict(row: AgMessage) -> dict:
    """One message row as plain JSON-safe data."""
    return {
        "id": row.id,
        "conversation_id": row.conversation_id,
        "role": row.role,
        "content": row.content or "",
        "tools": row.tools or [],
        "notices": row.notices or [],
        "created_at": _iso(row.created_at),
    }


def audit_to_dict(row: AgAudit) -> dict:
    """One audit row as plain JSON-safe data."""
    return {
        "id": row.id,
        "ts": _iso(row.ts),
        "phase": row.phase,
        "tool": row.tool,
        "conversation_id": row.conversation_id,
        "run_id": row.run_id,
        "args": row.args,
        "risk_verdict": row.risk_verdict,
        "ok": row.ok,
        "response": row.response,
        "order_ids": row.order_ids or [],
    }


# ---------------------------------------------------------------------------
# Provider models
# ---------------------------------------------------------------------------


def _validate_model_config(
    provider_kind: str,
    model_name: str,
    display_name: str,
    base_url: str | None,
    default_reasoning_effort: str,
) -> str | None:
    """Check a model's fields. Returns an error message, or None when valid."""
    if provider_kind not in PROVIDER_KINDS:
        return f"Unknown provider kind '{provider_kind}'"
    if not model_name or not model_name.strip():
        return "A model name is required"
    if not display_name or not display_name.strip():
        return "A display name is required"
    if default_reasoning_effort not in REASONING_EFFORTS:
        return f"Unknown reasoning effort '{default_reasoning_effort}'"
    if provider_kind in PROVIDER_KINDS_REQUIRING_BASE_URL and not base_url:
        return f"A base URL is required for {provider_kind}"
    return None


def _duplicate_model_exists(
    provider_kind: str, model_name: str, base_url: str | None, exclude_id: int | None = None
) -> bool:
    """Whether another row already claims this (kind, model_name, base_url).

    Done in Python rather than left to the UNIQUE constraint because SQLite
    treats NULLs as distinct, so the constraint does not fire for the common
    case of a provider that needs no base URL.
    """
    query = db_session.query(AgProviderModel.id).filter(
        AgProviderModel.provider_kind == provider_kind,
        AgProviderModel.model_name == model_name,
    )
    if base_url is None:
        query = query.filter(AgProviderModel.base_url.is_(None))
    else:
        query = query.filter(AgProviderModel.base_url == base_url)
    if exclude_id is not None:
        query = query.filter(AgProviderModel.id != exclude_id)
    return query.first() is not None


def _clear_other_defaults(model_id: int | None) -> None:
    """Drop ``is_default`` from every row except one. Does not commit.

    Called inside the transaction that sets the new default, so there is never a
    committed state with two defaults. ``model_id`` of None clears all of them.
    """
    query = db_session.query(AgProviderModel).filter(AgProviderModel.is_default.is_(True))
    if model_id is not None:
        query = query.filter(AgProviderModel.id != model_id)
    query.update({"is_default": False}, synchronize_session=False)


def _promote_replacement_default(excluded_id: int) -> None:
    """Hand the default to another tested, enabled model. Does not commit.

    Called when the current default is deleted or disabled. A default must be
    tested, so an untested model is never promoted and the agent correctly falls
    back to reporting itself unconfigured until the operator tests one.
    """
    replacement = (
        db_session.query(AgProviderModel.id)
        .filter(
            AgProviderModel.id != excluded_id,
            AgProviderModel.enabled.is_(True),
            AgProviderModel.last_test_ok.is_(True),
        )
        .order_by(AgProviderModel.id.asc())
        .first()
    )
    if replacement is None:
        return
    _clear_other_defaults(replacement[0])
    db_session.query(AgProviderModel).filter(AgProviderModel.id == replacement[0]).update(
        {"is_default": True}, synchronize_session=False
    )


def create_model(config: dict) -> tuple[dict | None, str | None]:
    """Register a model.

    The key is not part of this call. It is written once per provider through
    ``set_secret(provider_secret_name(kind), key)``, which is what lets the
    setup panel add several models of one provider from one pasted key.

    A new model is never the default: a default has to be tested first, and a
    model that has just been created has not been. ``set_default_model`` or a
    successful ``record_model_test`` promotes it.

    Args:
        config: ``provider_kind``, ``model_name`` and ``display_name`` are
            required. ``base_url``, ``enabled``, ``supports_reasoning``,
            ``default_reasoning_effort``, ``supports_vision`` and
            ``tools_unreliable`` are optional.

    Returns:
        ``(payload, error)``. Exactly one of the two is not None.
    """
    try:
        provider_kind = str(config.get("provider_kind") or "").strip()
        model_name = str(config.get("model_name") or "").strip()
        display_name = str(config.get("display_name") or "").strip()
        base_url = _normalize_base_url(config.get("base_url"))
        effort = str(config.get("default_reasoning_effort") or "off").strip()

        error = _validate_model_config(provider_kind, model_name, display_name, base_url, effort)
        if error:
            return None, error

        if _duplicate_model_exists(provider_kind, model_name, base_url):
            return None, f"{display_name} is already registered for this provider"

        row = AgProviderModel(
            provider_kind=provider_kind,
            model_name=model_name,
            display_name=display_name,
            base_url=base_url,
            enabled=bool(config.get("enabled", True)),
            is_default=False,
            supports_reasoning=bool(config.get("supports_reasoning", False)),
            default_reasoning_effort=effort,
            supports_vision=bool(config.get("supports_vision", False)),
            tools_unreliable=bool(config.get("tools_unreliable", False)),
        )
        db_session.add(row)
        db_session.commit()
        return provider_model_to_dict(row), None
    except Exception:
        db_session.rollback()
        logger.exception("Could not create agent model %s", config.get("model_name"))
        return None, "Could not register the model"


# Fields a PATCH is allowed to touch. An allowlist, not a denylist: it is the
# only thing standing between a mass-assignment and a caller setting is_default
# or last_test_ok directly, both of which have their own transactions.
#
# provider_kind and model_name are absent because they are the model's identity.
# Changing either would leave the row's test result, and the provider secret it
# resolves to, describing a different model entirely; registering the other
# model is one call and leaves an honest audit.
UPDATABLE_MODEL_FIELDS = frozenset(
    {
        "display_name",
        "base_url",
        "enabled",
        "supports_reasoning",
        "default_reasoning_effort",
        "supports_vision",
        "tools_unreliable",
    }
)


def update_model(model_id: int, changes: dict) -> tuple[dict | None, str | None]:
    """Update a registered model.

    A change of ``base_url`` invalidates the test result and any default status
    that rested on it: the credentials were tested against the old endpoint and
    say nothing about the new one.

    Disabling the current default hands the default to another tested, enabled
    model when there is one, in the same transaction.

    Args:
        model_id: The row to update.
        changes: Any subset of ``UPDATABLE_MODEL_FIELDS``.

    Returns:
        ``(payload, error)``. Exactly one of the two is not None.
    """
    try:
        row = db_session.query(AgProviderModel).filter_by(id=model_id).first()
        if row is None:
            return None, "Model not found"

        # Said rather than silently dropped. Both live outside the allowlist, so
        # a caller asking for them would otherwise get a 200 and a row that did
        # not change, which reads as success.
        if "is_default" in changes:
            return None, "Use the default action to change which model is the default"
        for identity_field in ("provider_kind", "model_name"):
            requested = changes.get(identity_field)
            if requested is not None and requested != getattr(row, identity_field):
                return None, (
                    "A model's provider and model name cannot be changed. "
                    "Register the other model instead."
                )

        base_url = row.base_url
        if "base_url" in changes:
            base_url = _normalize_base_url(changes["base_url"])
        effort = str(changes.get("default_reasoning_effort", row.default_reasoning_effort))
        display_name = str(changes.get("display_name", row.display_name) or "").strip()

        error = _validate_model_config(
            row.provider_kind, row.model_name, display_name, base_url, effort
        )
        if error:
            return None, error

        if base_url != row.base_url and _duplicate_model_exists(
            row.provider_kind, row.model_name, base_url, exclude_id=row.id
        ):
            return None, f"{display_name} is already registered at that endpoint"

        endpoint_changed = base_url != row.base_url
        was_default = bool(row.is_default)

        for field, value in changes.items():
            if field not in UPDATABLE_MODEL_FIELDS:
                continue
            if field == "base_url":
                row.base_url = base_url
            elif field == "display_name":
                row.display_name = display_name
            elif field in ("enabled", "supports_reasoning", "supports_vision", "tools_unreliable"):
                setattr(row, field, bool(value))
            else:
                setattr(row, field, value)

        if endpoint_changed:
            row.last_tested_at = None
            row.last_test_ok = None
            row.last_test_error = None

        lost_default = was_default and (endpoint_changed or not row.enabled)
        if lost_default:
            row.is_default = False
            db_session.flush()
            _promote_replacement_default(row.id)

        db_session.commit()
        db_session.expire_all()
        row = db_session.query(AgProviderModel).filter_by(id=model_id).first()
        return (provider_model_to_dict(row) if row is not None else None), None
    except Exception:
        db_session.rollback()
        logger.exception("Could not update agent model %s", model_id)
        return None, "Could not update the model"


def delete_model(model_id: int) -> tuple[bool, str | None]:
    """Remove a model, its per-model key override, and its default status.

    The ``model:{id}`` secret goes with it. SQLite reuses a deleted row's id when
    it was the highest one, so a secret left behind would silently become the
    key of whichever model is registered next.

    Args:
        model_id: The row to remove.

    Returns:
        ``(ok, error)``.
    """
    try:
        row = db_session.query(AgProviderModel).filter_by(id=model_id).first()
        if row is None:
            return False, "Model not found"

        was_default = bool(row.is_default)
        db_session.query(AgSecret).filter(AgSecret.name == model_secret_name(model_id)).delete(
            synchronize_session=False
        )
        db_session.delete(row)
        db_session.flush()
        if was_default:
            _promote_replacement_default(model_id)
        db_session.commit()
        db_session.expire_all()
        return True, None
    except Exception:
        db_session.rollback()
        logger.exception("Could not delete agent model %s", model_id)
        return False, "Could not delete the model"


def get_model(model_id: int) -> AgProviderModel | None:
    """One model row, or None.

    Args:
        model_id: The row id.

    Returns:
        The ORM row. Callers that serialize it use ``provider_model_to_dict``.
    """
    try:
        return db_session.query(AgProviderModel).filter_by(id=model_id).first()
    except Exception:
        logger.exception("Could not read agent model %s", model_id)
        return None


def get_default_model() -> AgProviderModel | None:
    """The enabled default model, or None when nothing is configured.

    The ``enabled`` filter is part of the query rather than a caller's
    responsibility: a disabled default is a contradiction the store already
    prevents, and reading it back would resolve a run onto a model the operator
    switched off.
    """
    try:
        return (
            db_session.query(AgProviderModel)
            .filter(
                AgProviderModel.is_default.is_(True),
                AgProviderModel.enabled.is_(True),
            )
            .order_by(AgProviderModel.id.asc())
            .first()
        )
    except Exception:
        logger.exception("Could not read the default agent model")
        return None


def list_models(enabled_only: bool = False) -> list[dict]:
    """Every registered model, with its key described but not shown.

    Args:
        enabled_only: Restrict to models the operator has switched on.

    Returns:
        A list of dicts, defaults first, then oldest first.
    """
    try:
        query = db_session.query(AgProviderModel)
        if enabled_only:
            query = query.filter(AgProviderModel.enabled.is_(True))
        rows = query.order_by(AgProviderModel.is_default.desc(), AgProviderModel.id.asc()).all()

        names: list[str] = []
        for row in rows:
            names.append(model_secret_name(row.id))
            names.append(provider_secret_name(row.provider_kind))
        index = _secret_index(names)
        return [provider_model_to_dict(row, index) for row in rows]
    except Exception:
        logger.exception("Could not list agent models")
        return []


def set_default_model(model_id: int) -> tuple[bool, str | None]:
    """Make one model the default, clearing every other in the same transaction.

    Refuses an untested model. A model may be saved untested; it may not be made
    the default untested, because the default is what an unqualified request
    resolves to and a failure there surfaces mid-stream instead of at setup.

    Args:
        model_id: The model to promote.

    Returns:
        ``(ok, error)``.
    """
    try:
        row = db_session.query(AgProviderModel).filter_by(id=model_id).first()
        if row is None:
            return False, "Model not found"
        if not row.enabled:
            return False, "Enable the model before making it the default"
        if not row.last_test_ok:
            return False, "Test the model's credentials before making it the default"

        _clear_other_defaults(model_id)
        db_session.query(AgProviderModel).filter(AgProviderModel.id == model_id).update(
            {"is_default": True}, synchronize_session=False
        )
        db_session.commit()
        db_session.expire_all()
        return True, None
    except Exception:
        db_session.rollback()
        logger.exception("Could not set agent model %s as the default", model_id)
        return False, "Could not set the default model"


def record_model_test(model_id: int, ok: bool, error: str | None = None) -> tuple[bool, str | None]:
    """Store the outcome of a credential test.

    On success the error is cleared, and the model takes the default when no
    model holds it: the first model an operator tests successfully is the one
    they meant to use, and leaving the platform unconfigured after a passing
    test is a dead end with no obvious next click. Promotion happens in this
    transaction, so there is never a committed state with two defaults.

    On failure the provider's own message is stored verbatim, and a model that
    was the default loses it: resolution must not send a run to credentials that
    are known not to work.

    Args:
        model_id: The model that was tested.
        ok: Whether the test call succeeded.
        error: The provider's own failure message, verbatim.

    Returns:
        ``(ok, error)`` describing the write, not the test.
    """
    try:
        row = db_session.query(AgProviderModel).filter_by(id=model_id).first()
        if row is None:
            return False, "Model not found"

        row.last_tested_at = utcnow()
        row.last_test_ok = bool(ok)
        row.last_test_error = None if ok else (error or "The provider rejected the request")

        if ok:
            if row.enabled:
                has_default = (
                    db_session.query(AgProviderModel.id)
                    .filter(
                        AgProviderModel.is_default.is_(True),
                        AgProviderModel.enabled.is_(True),
                        AgProviderModel.id != model_id,
                    )
                    .first()
                    is not None
                )
                if not has_default:
                    _clear_other_defaults(model_id)
                    row.is_default = True
        elif row.is_default:
            row.is_default = False
            db_session.flush()
            _promote_replacement_default(model_id)

        db_session.commit()
        db_session.expire_all()
        return True, None
    except Exception:
        db_session.rollback()
        logger.exception("Could not record the test result for agent model %s", model_id)
        return False, "Could not record the test result"


def is_configured() -> bool:
    """Whether ``/agent`` has a usable model, which is what the setup gate asks.

    True only for an enabled default whose last credential test passed. Every
    chat route returns 409 while this is False, so the frontend is not the only
    thing enforcing it.
    """
    try:
        return (
            db_session.query(AgProviderModel.id)
            .filter(
                AgProviderModel.is_default.is_(True),
                AgProviderModel.enabled.is_(True),
                AgProviderModel.last_test_ok.is_(True),
            )
            .first()
            is not None
        )
    except Exception:
        logger.exception("Could not read the agent configuration state")
        return False


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------


def set_secret(name: str, value: str) -> tuple[bool, str | None]:
    """Store or replace one secret, writing nothing when it has not changed.

    The comparison is against the **decrypted plaintext**. Fernet ciphertext is
    non-deterministic, so comparing the stored blob against a fresh encryption
    of the same value never matches, and every save of an unchanged settings
    page would rewrite the row. That is not merely wasteful: the same mistake in
    ``database/telegram_db.py`` produced real "database is locked" failures at
    startup, because openalgo.db is shared by every module and by the
    out-of-process websocket proxy.

    Args:
        name: ``provider:{kind}`` or ``model:{id}``.
        value: The plaintext secret. Empty is rejected; use ``delete_secret``.

    Returns:
        ``(ok, error)``.
    """
    if not name:
        return False, "A secret name is required"
    if not value:
        return False, "A secret value is required"

    try:
        row = db_session.query(AgSecret).filter_by(name=name).first()
        if row is not None and safe_decrypt_token(row.ciphertext) == value:
            logger.debug("Agent secret %s unchanged, skipping write", name)
            return True, None

        ciphertext = encrypt_token(value)
        if not ciphertext:
            return False, "Could not encrypt the secret"

        if row is None:
            row = AgSecret(name=name, ciphertext=ciphertext, fingerprint=fingerprint(value))
            db_session.add(row)
        else:
            row.ciphertext = ciphertext
            row.fingerprint = fingerprint(value)
            # A replaced key has never been used, and carrying the old timestamp
            # forward would claim it had.
            row.last_used_at = None

        db_session.commit()
        return True, None
    except Exception as exc:
        db_session.rollback()
        # logger.error and no traceback: this is the credential-set path the
        # build contract carves out. The exception's own message is the vector
        # that matters, not the frame locals - a stdlib traceback never prints
        # a local, but it does print str(exc), and an unlabelled key inside one
        # is not matched by utils.logging's redaction patterns, which all key
        # off a "token=" / "secret:" style label. So the name and the exception
        # type go to the log and the message does not.
        logger.error("Could not store agent secret %s: %s", name, type(exc).__name__)
        return False, "Could not store the secret"


def get_secret(name: str) -> str | None:
    """The decrypted plaintext of one secret, or None when it is not set.

    A read, not a use: nothing is written here. Call ``mark_secret_used`` when a
    key is actually handed to a provider.

    Args:
        name: ``provider:{kind}`` or ``model:{id}``.

    Returns:
        The plaintext, or None.
    """
    try:
        row = db_session.query(AgSecret).filter_by(name=name).first()
        if row is None or not row.ciphertext:
            return None
        # safe_decrypt_token returns the raw value when decryption fails, which
        # is what lets a column move from plaintext to encrypted with no cutover.
        return safe_decrypt_token(row.ciphertext)
    except Exception as exc:
        # Same carve-out as set_secret: the decrypted plaintext passes through
        # this frame, so nothing derived from the exception beyond its class
        # name is written. See the comment there for why the message, not the
        # locals, is the thing being kept out of log/errors.jsonl.
        logger.error("Could not read agent secret %s: %s", name, type(exc).__name__)
        return None


def resolve_api_key(model_id: int, provider_kind: str) -> tuple[str | None, str | None]:
    """The key a model should use, and which stored secret it came from.

    ``model:{id}`` wins when present, so two accounts with the same provider are
    expressible; ``provider:{kind}`` is the fallback, which is what lets a fourth
    GPT model reuse the OpenAI key already pasted once. Neither being present is
    a legitimate answer for ``ollama``, which needs no key at all, so the caller
    decides whether None is an error.

    Args:
        model_id: The ``ag_provider_model`` row id.
        provider_kind: That row's provider kind.

    Returns:
        ``(api_key, secret_name)``, both None when nothing is stored.
    """
    own = model_secret_name(model_id)
    key = get_secret(own)
    if key:
        return key, own

    shared = provider_secret_name(provider_kind)
    key = get_secret(shared)
    if key:
        return key, shared

    return None, None


def get_api_key_for_model(model_id: int, provider_kind: str) -> str | None:
    """The key a model should use, without saying where it came from.

    Args:
        model_id: The ``ag_provider_model`` row id.
        provider_kind: That row's provider kind.

    Returns:
        The plaintext key, or None when none is stored.
    """
    return resolve_api_key(model_id, provider_kind)[0]


def mark_secret_used(name: str) -> bool:
    """Record that a secret was handed to a provider.

    Separate from ``get_secret`` so a read stays a read. This is one write per
    agent run rather than one per lookup, and a failure is not worth failing the
    run over.

    Args:
        name: The secret that was used.

    Returns:
        True when the row was touched.
    """
    try:
        updated = (
            db_session.query(AgSecret)
            .filter(AgSecret.name == name)
            .update({"last_used_at": utcnow()}, synchronize_session=False)
        )
        db_session.commit()
        return bool(updated)
    except Exception:
        db_session.rollback()
        logger.exception("Could not mark agent secret %s as used", name)
        return False


def delete_secret(name: str) -> bool:
    """Remove one secret.

    Args:
        name: ``provider:{kind}`` or ``model:{id}``.

    Returns:
        True when a row was removed.
    """
    try:
        deleted = (
            db_session.query(AgSecret)
            .filter(AgSecret.name == name)
            .delete(synchronize_session=False)
        )
        db_session.commit()
        return bool(deleted)
    except Exception:
        db_session.rollback()
        logger.exception("Could not delete agent secret %s", name)
        return False


def list_secrets() -> list[dict]:
    """Every stored secret, described and never shown.

    Returns:
        A list of dicts carrying the name, fingerprint and presence flag.
    """
    try:
        rows = db_session.query(AgSecret).order_by(AgSecret.name.asc()).all()
        return [secret_to_dict(row) for row in rows]
    except Exception:
        logger.exception("Could not list agent secrets")
        return []


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def get_setting(key: str, default: str | None = None) -> str | None:
    """One setting's value.

    Args:
        key: The setting key, from the ``SETTING_*`` constants.
        default: Returned when the key has never been written.

    Returns:
        The stored Text value, or ``default``.
    """
    if key in _settings_cache:
        cached = _settings_cache[key]
        return default if cached is None else cached

    try:
        row = db_session.query(AgSetting).filter_by(key=key).first()
        value = row.value if row is not None else None
        _settings_cache[key] = value
        return default if value is None else value
    except Exception:
        logger.exception("Could not read agent setting %s", key)
        return default


def set_setting(key: str, value: str | None) -> bool:
    """Write one setting, writing nothing when it already holds that value.

    The no-op skip is the same lesson as ``set_secret``: openalgo.db is shared,
    and a settings page that rewrites every key on every save turns an idle
    action into write-lock contention.

    Args:
        key: The setting key.
        value: The Text value, or None to store an empty setting.

    Returns:
        True when the setting now holds ``value``.
    """
    if not key:
        return False
    try:
        text_value = None if value is None else str(value)
        row = db_session.query(AgSetting).filter_by(key=key).first()
        if row is not None and row.value == text_value:
            _settings_cache[key] = text_value
            logger.debug("Agent setting %s unchanged, skipping write", key)
            return True

        if row is None:
            db_session.add(AgSetting(key=key, value=text_value))
        else:
            row.value = text_value

        db_session.commit()
        _settings_cache[key] = text_value
        return True
    except Exception:
        db_session.rollback()
        _settings_cache.pop(key, None)
        logger.exception("Could not write agent setting %s", key)
        return False


def get_bool_setting(key: str, default: bool = False) -> bool:
    """One setting read as a boolean.

    Anything other than the stored true spellings is False, so a corrupted or
    hand-edited value fails closed. That matters for
    ``SETTING_TRADING_ENABLED``: an unreadable value must not enable trading.

    Args:
        key: The setting key.
        default: Returned when the key has never been written.

    Returns:
        The boolean value.
    """
    raw = get_setting(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("true", "1", "yes", "on")


def set_bool_setting(key: str, value: bool) -> bool:
    """Write one setting as a boolean.

    Args:
        key: The setting key.
        value: The boolean to store, as 'true' or 'false'.

    Returns:
        True when the setting now holds ``value``.
    """
    return set_setting(key, "true" if value else "false")


def get_all_settings() -> dict[str, str | None]:
    """Every stored setting as a plain dict.

    Returns:
        A key -> value map. Keys that have never been written are absent.
    """
    try:
        rows = db_session.query(AgSetting).all()
        return {row.key: row.value for row in rows}
    except Exception:
        logger.exception("Could not read the agent settings")
        return {}


def delete_setting(key: str) -> bool:
    """Remove one setting, so the code default applies again.

    Args:
        key: The setting key.

    Returns:
        True when a row was removed.
    """
    try:
        deleted = (
            db_session.query(AgSetting)
            .filter(AgSetting.key == key)
            .delete(synchronize_session=False)
        )
        db_session.commit()
        _settings_cache.pop(key, None)
        return bool(deleted)
    except Exception:
        db_session.rollback()
        _settings_cache.pop(key, None)
        logger.exception("Could not delete agent setting %s", key)
        return False


def clear_agent_cache() -> None:
    """Drop the settings cache. Called on logout and on session teardown."""
    _settings_cache.clear()


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------


def create_conversation(
    user_id: str,
    title: str | None = None,
    surface: str = "chat",
    agno_session_id: str | None = None,
) -> tuple[dict | None, str | None]:
    """Open a conversation on one surface.

    Args:
        user_id: The session username.
        title: Optional title. The UI derives one from the first message when
            this is None.
        surface: ``chat`` or ``chart``.
        agno_session_id: The agno session this conversation is joined to, when
            it is already known.

    Returns:
        ``(payload, error)``. Exactly one of the two is not None.
    """
    if surface not in SURFACES:
        return None, f"Unknown surface '{surface}'"
    try:
        row = AgConversation(
            user_id=user_id,
            title=(title or None),
            surface=surface,
            agno_session_id=agno_session_id,
        )
        db_session.add(row)
        db_session.commit()
        return conversation_to_dict(row), None
    except Exception:
        db_session.rollback()
        logger.exception("Could not create an agent conversation for %s", user_id)
        return None, "Could not create the conversation"


def get_conversation(conversation_id: int, user_id: str) -> AgConversation | None:
    """One conversation, scoped to its owner.

    The ``user_id`` filter is in the signature rather than left to callers so
    that no call site can forget it.

    Args:
        conversation_id: The row id.
        user_id: The session username.

    Returns:
        The ORM row, or None.
    """
    try:
        return (
            db_session.query(AgConversation).filter_by(id=conversation_id, user_id=user_id).first()
        )
    except Exception:
        logger.exception("Could not read agent conversation %s", conversation_id)
        return None


def list_conversations(user_id: str, surface: str | None = None, limit: int = 100) -> list[dict]:
    """A user's conversations, most recently updated first.

    Args:
        user_id: The session username.
        surface: Restrict to ``chat`` or ``chart``.
        limit: Maximum rows to return.

    Returns:
        A list of conversation dicts.
    """
    try:
        query = db_session.query(AgConversation).filter(AgConversation.user_id == user_id)
        if surface:
            query = query.filter(AgConversation.surface == surface)
        rows = (
            query.order_by(AgConversation.updated_at.desc(), AgConversation.id.desc())
            .limit(limit)
            .all()
        )
        return [conversation_to_dict(row) for row in rows]
    except Exception:
        logger.exception("Could not list agent conversations for %s", user_id)
        return []


def update_conversation(
    conversation_id: int,
    user_id: str,
    title: str | None = None,
    agno_session_id: str | None = None,
) -> tuple[dict | None, str | None]:
    """Rename a conversation, or bind it to its agno session.

    Both arguments are optional and None means "leave it alone", so a rename
    cannot accidentally clear the session binding that a paused confirmation
    depends on.

    Args:
        conversation_id: The row id.
        user_id: The session username.
        title: The new title, or None to leave it.
        agno_session_id: The agno session id, or None to leave it.

    Returns:
        ``(payload, error)``. Exactly one of the two is not None.
    """
    try:
        row = get_conversation(conversation_id, user_id)
        if row is None:
            return None, "Conversation not found"
        if title is not None:
            row.title = title
        if agno_session_id is not None:
            row.agno_session_id = agno_session_id
        row.updated_at = utcnow()
        db_session.commit()
        return conversation_to_dict(row), None
    except Exception:
        db_session.rollback()
        logger.exception("Could not update agent conversation %s", conversation_id)
        return None, "Could not update the conversation"


def touch_conversation(conversation_id: int) -> bool:
    """Move a conversation to the top of the list.

    Not owner-scoped: the caller is the stream, which already resolved the
    conversation through an owner-scoped read.

    Args:
        conversation_id: The row id.

    Returns:
        True when the row was touched.
    """
    try:
        updated = (
            db_session.query(AgConversation)
            .filter(AgConversation.id == conversation_id)
            .update({"updated_at": utcnow()}, synchronize_session=False)
        )
        db_session.commit()
        return bool(updated)
    except Exception:
        db_session.rollback()
        logger.exception("Could not touch agent conversation %s", conversation_id)
        return False


def delete_conversation(conversation_id: int, user_id: str) -> tuple[bool, str | None]:
    """Delete a conversation and its messages.

    The messages are removed explicitly rather than left to the ``ondelete``
    clause on the foreign key. That clause is declarative only here: SQLite
    enforces a foreign key only when ``PRAGMA foreign_keys=ON`` is set per
    connection, and this project never sets it, so relying on the cascade would
    leave every message behind forever, unreachable through any query this
    module offers and growing without bound in a process that never restarts.

    The audit rows stay. They are a trade record and they outlive the
    conversation the trade was typed into.

    Args:
        conversation_id: The row id.
        user_id: The session username.

    Returns:
        ``(ok, error)``.
    """
    try:
        row = get_conversation(conversation_id, user_id)
        if row is None:
            return False, "Conversation not found"

        db_session.query(AgMessage).filter(AgMessage.conversation_id == conversation_id).delete(
            synchronize_session=False
        )
        db_session.delete(row)
        db_session.commit()
        return True, None
    except Exception:
        db_session.rollback()
        logger.exception("Could not delete agent conversation %s", conversation_id)
        return False, "Could not delete the conversation"


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


def add_message(
    conversation_id: int,
    role: str,
    content: str,
    tools: list | None = None,
    notices: list | None = None,
) -> tuple[dict | None, str | None]:
    """Append one turn, and move its conversation to the top of the list.

    Both writes share one transaction, so a listed conversation can never sort
    above a message it does not have or below one it does.

    Args:
        conversation_id: The conversation this turn belongs to.
        role: One of ``MESSAGE_ROLES``.
        content: The rendered text.
        tools: Tool timeline entries, as the UI renders them.
        notices: Notice frames raised during the turn.

    Returns:
        ``(payload, error)``. Exactly one of the two is not None.
    """
    if role not in MESSAGE_ROLES:
        return None, f"Unknown message role '{role}'"
    try:
        row = AgMessage(
            conversation_id=conversation_id,
            role=role,
            content=content or "",
            tools=tools,
            notices=notices,
        )
        db_session.add(row)
        db_session.query(AgConversation).filter(AgConversation.id == conversation_id).update(
            {"updated_at": utcnow()}, synchronize_session=False
        )
        db_session.commit()
        return message_to_dict(row), None
    except Exception:
        db_session.rollback()
        logger.exception("Could not add a message to agent conversation %s", conversation_id)
        return None, "Could not save the message"


def list_messages(conversation_id: int, limit: int = 500) -> list[dict]:
    """A conversation's messages, oldest first.

    Args:
        conversation_id: The conversation to read.
        limit: Maximum rows to return, counted from the newest so a long
            conversation renders its recent turns rather than its first ones.

    Returns:
        A list of message dicts in chronological order.
    """
    try:
        rows = (
            db_session.query(AgMessage)
            .filter(AgMessage.conversation_id == conversation_id)
            .order_by(AgMessage.created_at.desc(), AgMessage.id.desc())
            .limit(limit)
            .all()
        )
        return [message_to_dict(row) for row in reversed(rows)]
    except Exception:
        logger.exception("Could not list messages for agent conversation %s", conversation_id)
        return []


def truncate_messages_from(conversation_id: int, message_id: int) -> list[dict]:
    """Remove one message and everything after it, returning what was removed.

    This is what an edit does to the transcript. The rows come back rather than
    a count because the caller needs their ``notices``: an assistant row carries
    the agno run that produced it, and the model's own history has to be
    truncated alongside this one or the edit is cosmetic.

    Ordering is by id rather than by ``created_at``. Two messages in one turn
    can share a timestamp to the resolution stored, and an ordering that ties is
    an ordering that can drop the wrong row.

    Args:
        conversation_id: The conversation to truncate.
        message_id: The first message to remove, kept in the removal.

    Returns:
        The removed rows, oldest first, as dicts.
    """
    try:
        rows = (
            db_session.query(AgMessage)
            .filter(
                AgMessage.conversation_id == conversation_id,
                AgMessage.id >= message_id,
            )
            .order_by(AgMessage.id.asc())
            .all()
        )
        removed = [message_to_dict(row) for row in rows]
        for row in rows:
            db_session.delete(row)
        db_session.commit()
        return removed
    except Exception:
        db_session.rollback()
        logger.exception(
            "Could not truncate conversation %s from message %s", conversation_id, message_id
        )
        raise


def delete_messages(conversation_id: int) -> int:
    """Clear a conversation without deleting it.

    Args:
        conversation_id: The conversation to empty.

    Returns:
        How many messages were removed.
    """
    try:
        deleted = (
            db_session.query(AgMessage)
            .filter(AgMessage.conversation_id == conversation_id)
            .delete(synchronize_session=False)
        )
        db_session.commit()
        return int(deleted or 0)
    except Exception:
        db_session.rollback()
        logger.exception("Could not clear agent conversation %s", conversation_id)
        return 0


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def record_audit(
    phase: str,
    tool: str,
    conversation_id: int | None = None,
    run_id: str | None = None,
    args: dict[str, Any] | None = None,
    risk_verdict: str | None = None,
    ok: bool | None = None,
    response: Any = None,
    order_ids: list | None = None,
) -> int | None:
    """Append one row to the mutating-call audit trail.

    Two rows per mutating call, ``attempt`` before the service is reached and
    ``result`` after, plus one ``decision`` row per approval. Append-only:
    nothing in this module updates or deletes a row here.

    A write failure is logged and swallowed. This runs on the agent's real OS
    thread inside the tool body, and an audit row that cannot be written must
    never be the reason an approved order does not reach the broker. The
    consequence is recorded in the log rather than raised.

    Args:
        phase: One of ``AUDIT_PHASES``.
        tool: The tool that was called.
        conversation_id: The conversation the call belongs to, when known.
        run_id: The agno run id, matching the one the client received.
        args: The arguments the model supplied.
        risk_verdict: What ``services/agent/safety/risk.py`` decided.
        ok: Whether the call succeeded. None on an ``attempt`` row.
        response: The service response, JSON-safe.
        order_ids: Any broker order ids the call produced.

    Returns:
        The new row id, or None when the write failed.
    """
    try:
        row = AgAudit(
            phase=phase,
            tool=tool,
            conversation_id=conversation_id,
            run_id=run_id,
            args=args,
            risk_verdict=risk_verdict,
            ok=ok,
            response=response,
            order_ids=order_ids,
        )
        db_session.add(row)
        db_session.commit()
        return row.id
    except Exception:
        db_session.rollback()
        logger.exception("Could not write the agent audit row for %s/%s", tool, phase)
        return None


def list_audit(
    conversation_id: int | None = None,
    run_id: str | None = None,
    tool: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """The audit trail, newest first.

    Args:
        conversation_id: Restrict to one conversation.
        run_id: Restrict to one run.
        tool: Restrict to one tool.
        limit: Maximum rows to return.

    Returns:
        A list of audit dicts.
    """
    try:
        query = db_session.query(AgAudit)
        if conversation_id is not None:
            query = query.filter(AgAudit.conversation_id == conversation_id)
        if run_id is not None:
            query = query.filter(AgAudit.run_id == run_id)
        if tool:
            query = query.filter(AgAudit.tool == tool)
        rows = query.order_by(AgAudit.ts.desc(), AgAudit.id.desc()).limit(limit).all()
        return [audit_to_dict(row) for row in rows]
    except Exception:
        logger.exception("Could not list the agent audit trail")
        return []
