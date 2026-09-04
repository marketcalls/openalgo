"""Agent construction: model resolution, the session store, and the tool seam.

One public entry point, :func:`build_agent`, turns a :class:`ToolContext` into a
configured agno ``Agent``. Everything it does is arranged around three rules
from the build contract.

**Resolve before the first stream byte.** :func:`resolve_model` runs to
completion, and raises a typed :class:`AgentBuildError`, before an ``Agent``
exists and long before the SSE generator writes anything. A model id that names
nothing, a model the operator disabled, or a provider with no stored key, is
therefore a clean HTTP status with a readable message rather than a stream that
opens and then dies halfway through an answer. Resolution order is: the model
the request names, then the ``is_default`` row, then an error. A named model
that is missing or disabled is **never** silently swapped for the default; the
operator asked for a specific model and quietly using another one is how a run
ends up on a provider they did not intend to send account data to.

**Tools are a callable factory, not a list.** ``Agent(tools=...)`` receives a
closure, so agno re-evaluates it on every run against ``run_context``. A session
that has not enabled trading never has an order tool in its schema, and turning
trading off in the settings takes effect on the next run rather than on the next
restart. That closure is this module's main extension seam: adding a capability
is a file in ``tools/`` plus a registry line, and nothing here changes.

**The session store is its own database.** ``SqliteDb`` gets ``db/agent.db``,
never ``openalgo.db``. It holds agno's own run and session state, which is what
lets a run pause for a human confirmation in one request and resume in the next.
The engine comes from ``database.engine_factory.create_db_engine`` so it obeys
the project-wide NullPool rule, and it is a module-level singleton because a new
engine per request is a file-descriptor leak in a worker that never restarts.

Secrets
-------

The decrypted API key exists only inside :func:`build_model`, as a local, for
the few lines it takes to construct the model. It is never stored on
:class:`ResolvedModel`, never logged, and never included in an exception
message. In that function, and only there, errors are logged with
``logger.error`` and no traceback, because ``exc_info`` captures frame locals and
would write the key into ``log/errors.jsonl``.

Nothing here reads the process environment. Provider, model, credential and
policy all come from the database.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from database import agent_db
from database.engine_factory import create_db_engine
from services.agent import chatgpt_oauth, prompts, settings
from services.agent import tools as agent_tools
from services.agent.frames import ErrorKind
from services.agent.providers import (
    litellm_kwargs,
    litellm_model_id,
    reasoning_capable,
    validate_provider_config,
    vision_capable,
)
from services.agent.tools import ToolContext
from utils.logging import get_logger
from utils.real_threading import Lock

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from agno.agent import Agent
    from agno.db.sqlite import SqliteDb
    from agno.models.litellm import LiteLLM

logger = get_logger(__name__)

__all__ = [
    "AGENT_ID",
    "DEFAULT_NUM_HISTORY_RUNS",
    "DEFAULT_TOOL_CALL_LIMIT",
    "AgentBuildError",
    "AgnoNotInstalled",
    "InvalidModelConfig",
    "MissingCredential",
    "ModelDisabled",
    "ModelNotConfigured",
    "ModelNotFound",
    "ResolvedModel",
    "VisionUnsupported",
    "build_agent",
    "build_model",
    "build_session_state",
    "reset_session_db",
    "resolve_model",
    "session_db_path",
    "session_db",
    "tool_factory",
]

PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: Agno's own store, in its own file. Not ``openalgo.db``: this database is
#: written by a library on its own schema, and a paused confirmation living in
#: the same file as the broker session buys nothing and risks a lock held by one
#: feature stalling the other.
SESSION_DB_PATH = PROJECT_ROOT / "db" / "agent.db"

#: Stable agno agent id, so rows written by different runs belong to one agent
#: rather than to a new one per request.
AGENT_ID = "openalgo-agent"

#: How many tool calls one run may make before agno stops it. An agent that
#: loops is a cost and a risk, not merely a bug, and this is enforced across the
#: whole run rather than per turn.
DEFAULT_TOOL_CALL_LIMIT = 25

#: How many previous runs of the conversation are replayed into context.
DEFAULT_NUM_HISTORY_RUNS = 8

#: Character budget for the system prompt. Generous, because trimming drops
#: whole sections; the pinned security rules survive any budget.
#:
#: Raised from 24000 when the generated OpenUI Lang reference joined the chat
#: prompt. That section alone renders about 8.8k characters, which took the
#: chat surface to roughly 24.3k, and the way ``render_sections`` enforces a cap
#: is to drop **whole** unpinned sections from the end with nothing but a log
#: line: the section actually lost was the one telling the model that a
#: visualization is a deliberate act. Overshooting this number does not truncate
#: the section that overshot it, it deletes a different one, which is why
#: ``test_agent_openui_tool.py`` asserts every surface renders whole rather than
#: leaving the next addition to find out in production.
#:
#: Raised again from 28000 when the live card section joined the base prompt.
#: The arithmetic, measured across all eight surface configurations rather than
#: estimated: the worst case (chat, trading disabled, analyzer on) was 26541
#: characters before that section and is 27676 after it, so 28000 left 324
#: characters of headroom. That is less than one bullet, and the failure mode is
#: not a truncated bullet, it is a **different** whole section disappearing with
#: only a log line. 30000 restores about two thousand characters of room. The
#: cap is a ceiling and not a target, so raising it costs nothing until a
#: section actually grows into it.
DEFAULT_MAX_PROMPT_CHARS = 30000

#: The operator's timezone. Indian markets, and every schedule in this platform,
#: run on IST. This is not configuration, it is what the exchanges do.
IST = ZoneInfo("Asia/Kolkata")


# ---------------------------------------------------------------------------
# Typed errors
# ---------------------------------------------------------------------------


class AgentBuildError(RuntimeError):
    """An agent could not be built, with enough detail to say why.

    Raised before a stream opens, so a route can answer with :attr:`status` and
    :attr:`message` rather than emitting a half-written answer.

    Attributes:
        message: Text safe to show the operator. Never carries a secret.
        kind: A :class:`services.agent.frames.ErrorKind` value, for the error
            frame when one is emitted anyway.
        status: The HTTP status a route should answer with.
    """

    kind: str = ErrorKind.CONFIG
    status: int = 409

    def __init__(self, message: str) -> None:
        """Store the message on the exception as well as in its args."""
        super().__init__(message)
        self.message = message


class ModelNotConfigured(AgentBuildError):
    """No usable model is configured, so `/agent` is still behind its setup gate."""

    status = 409


class ModelNotFound(AgentBuildError):
    """The request named a model id that is not registered."""

    status = 404


class ModelDisabled(AgentBuildError):
    """The request named a model the operator has switched off."""

    status = 409


class MissingCredential(AgentBuildError):
    """The resolved model's provider needs an API key and none is stored."""

    status = 409


class InvalidModelConfig(AgentBuildError):
    """The stored row does not describe a usable model."""

    status = 409


class VisionUnsupported(AgentBuildError):
    """The turn carries an image and the resolved model cannot read one.

    Raised in preference to sending the image anyway, because the two ways of
    being lenient are both worse. Passing it on gets either a provider error or,
    on a provider that quietly drops what it cannot parse, an answer written
    without the picture: the operator asked about a screenshot, got a confident
    reply, and has no way to tell it was never seen. Dropping the image
    ourselves and answering on the text alone is the same failure with our name
    on it. So the turn is refused, the model is named, and the operator picks a
    model that can see or removes the image.
    """

    kind = ErrorKind.INPUT
    status = 400


class AgnoNotInstalled(AgentBuildError):
    """The optional `agno` dependency is not installed."""

    kind = ErrorKind.INTERNAL
    status = 503


# ---------------------------------------------------------------------------
# Optional dependency
# ---------------------------------------------------------------------------
#
# agno is imported inside functions rather than at module scope, for the same
# reason the tool registry does it: `blueprints/agent.py` and the tests must
# import this module with agno absent, and a platform that will not boot because
# an optional feature's dependency is missing is worse than one that boots
# without the feature.


def _require_agno() -> tuple[type, type, type]:
    """Import the agno classes this module builds with.

    Returns:
        The ``Agent``, ``LiteLLM`` and ``SqliteDb`` classes.

    Raises:
        AgnoNotInstalled: When the package is not installed, carrying the
            command that fixes it.
    """
    try:
        from agno.agent import Agent
        from agno.db.sqlite import SqliteDb
        from agno.models.litellm import LiteLLM
    except ImportError as exc:
        raise AgnoNotInstalled(
            "The agent module requires the 'agno' package, which is not installed. "
            "Install it with: uv add agno"
        ) from exc
    return Agent, LiteLLM, SqliteDb


# ---------------------------------------------------------------------------
# Model resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResolvedModel:
    """A model row, read off the ORM instance and safe to hold.

    Every field is a plain value copied out of the row while its session was
    still open. An ORM instance would raise ``DetachedInstanceError`` on the
    first attribute access after the request's ``scoped_session`` is removed,
    and this object outlives that.

    **No API key.** The key is decrypted inside :func:`build_model`, used, and
    dropped. Storing it here would put a plaintext credential on an object that
    a caller may log, serialise or attach to an exception.

    Attributes:
        id: The ``ag_provider_model`` row id.
        provider_kind: One of the five closed provider kinds.
        model_name: The model name as configured.
        display_name: The name shown in the picker.
        base_url: The configured base URL, normalised, or None.
        litellm_id: The model id LiteLLM is addressed with.
        supports_reasoning: Resolved against LiteLLM, not the raw column.
        default_reasoning_effort: The row's own effort, ``off`` when unset.
        supports_vision: Resolved against LiteLLM, not the raw column. The
            operator's checkbox only decides for a model LiteLLM has never
            heard of.
        tools_unreliable: Operator-set flag. A tool-driven agent has to know.
        is_default: Whether this is the ``is_default`` row.
        has_key: Whether a key is stored for this model or its provider.
        secret_name: Which stored secret answered, for the last-used timestamp.
    """

    id: int
    provider_kind: str
    model_name: str
    display_name: str
    base_url: str | None
    litellm_id: str
    supports_reasoning: bool
    default_reasoning_effort: str
    supports_vision: bool
    tools_unreliable: bool
    is_default: bool
    has_key: bool
    secret_name: str | None


def resolve_model(model_id: int | str | None = None) -> ResolvedModel:
    """Resolve which model a run uses, or raise a typed error saying why not.

    Called before any stream byte is written. Resolution order is the request's
    model, then the ``is_default`` row, then an error; a named model that is
    missing or disabled is an error rather than a silent fall back to the
    default.

    Args:
        model_id: The model the request asked for, or None for the default. A
            numeric string is accepted because it arrives from a JSON body.

    Returns:
        The resolved model, with no credential attached.

    Raises:
        ModelNotFound: The named model is not registered.
        ModelDisabled: The named model is registered but switched off.
        ModelNotConfigured: No model was named and no enabled default exists.
        MissingCredential: The provider needs a key and none is stored.
        InvalidModelConfig: The row does not describe a usable model.
    """
    requested = _as_model_id(model_id)

    if requested is not None:
        row = agent_db.get_model(requested)
        if row is None:
            raise ModelNotFound(
                f"Model {requested} is not registered. Choose one of the configured models."
            )
        if not bool(row.enabled):
            raise ModelDisabled(
                f"Model {_row_label(row)} is disabled. Enable it in agent settings "
                "or choose another model."
            )
    else:
        row = agent_db.get_default_model()
        if row is None:
            raise ModelNotConfigured(
                "No default model is configured. Add a model and set it as the "
                "default before using the agent."
            )

    kind = str(row.provider_kind or "").strip()
    model_name = str(row.model_name or "").strip()
    base_url = str(row.base_url or "").strip() or None
    row_id = int(row.id)
    display_name = str(row.display_name or model_name or f"model {row_id}")

    # The key is fetched only to learn whether one exists. The plaintext is not
    # returned to the caller and does not leave this function.
    api_key, secret_name = agent_db.resolve_api_key(row_id, kind)
    has_key = bool(api_key)
    del api_key

    error = validate_provider_config(kind, model_name, base_url, has_key=has_key)
    if error:
        if not has_key and "API key" in error:
            raise MissingCredential(
                f"{error} for {display_name}. Add the provider's key in agent settings."
            )
        raise InvalidModelConfig(f"{error} ({display_name}).")

    litellm_id = litellm_model_id(kind, model_name)

    # A subscription model has no key to validate, so the gate above passes it
    # and this one has to hold. Without it the run reaches LiteLLM with nothing
    # to authenticate with, and `Authenticator.get_access_token` falls through to
    # `_login_device_code`, which prints a code to stdout nobody is reading and
    # then polls for fifteen minutes on the run thread. `ensure_ready` does no
    # network work at all, so it is safe here on the green side.
    if chatgpt_oauth.is_subscription_model(litellm_id):
        ready, reason = chatgpt_oauth.ensure_ready()
        if not ready:
            raise MissingCredential(
                reason or f"No ChatGPT subscription is authorised for {display_name}."
            )

    resolved = ResolvedModel(
        id=row_id,
        provider_kind=kind,
        model_name=model_name,
        display_name=display_name,
        base_url=base_url,
        litellm_id=litellm_id,
        supports_reasoning=reasoning_capable(litellm_id, bool(row.supports_reasoning)),
        default_reasoning_effort=str(row.default_reasoning_effort or "off").strip().lower(),
        supports_vision=vision_capable(litellm_id, bool(row.supports_vision)),
        tools_unreliable=bool(row.tools_unreliable),
        is_default=bool(row.is_default),
        has_key=has_key,
        secret_name=secret_name,
    )

    if resolved.tools_unreliable:
        logger.warning(
            "Agent model %s is flagged tools_unreliable; this agent is tool driven "
            "and answers from it may be poor",
            resolved.display_name,
        )

    return resolved


def _as_model_id(value: Any) -> int | None:
    """Coerce a requested model id to an int, or None when nothing was asked for.

    Args:
        value: The raw value from a request body or a session state mapping.

    Returns:
        The id, or None when the value is absent or blank.

    Raises:
        ModelNotFound: When the value is present but is not a model id at all.
            An unparseable id is the client naming something, so it gets the
            same answer as naming a model that does not exist, never the
            default.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise ModelNotFound(f"{value!r} is not a model id")
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        raise ModelNotFound(f"{text!r} is not a model id") from None


def _row_label(row: Any) -> str:
    """Describe a model row for a message shown to the operator.

    Args:
        row: An ``ag_provider_model`` ORM row.

    Returns:
        The display name when there is one, else the model name, else the id.
    """
    for name in ("display_name", "model_name"):
        value = str(getattr(row, name, "") or "").strip()
        if value:
            return value
    return str(getattr(row, "id", "unknown"))


def _reasoning_effort(resolved: ResolvedModel, requested: str | None = None) -> str | None:
    """Decide the reasoning effort for a run, or None to send none at all.

    A model that does not support reasoning never gets the parameter, because
    LiteLLM forwards it and a provider that does not know it answers with an
    error rather than ignoring it.

    The row's ``off`` is the column's untouched default and is indistinguishable
    from "the operator never chose", so the platform setting fills in for it. A
    row that names a real level is model-specific and wins over the platform
    setting. An explicit request wins over both, including an explicit ``off``.

    Args:
        resolved: The resolved model.
        requested: The effort the request asked for, if any.

    Returns:
        ``low``, ``medium`` or ``high``, or None when no effort should be sent.
    """
    levels = {"low", "medium", "high"}

    if not resolved.supports_reasoning:
        return None

    if requested is not None:
        asked = str(requested).strip().lower()
        if asked in levels:
            return asked
        if asked == "off":
            return None

    on_row = resolved.default_reasoning_effort
    if on_row in levels:
        return on_row

    fallback = str(settings.get_default_reasoning_effort() or "off").strip().lower()
    return fallback if fallback in levels else None


def _register_chatgpt_models() -> None:
    """Teach LiteLLM about the ChatGPT plan models its registry omits.

    Idempotent and cheap after the first call. Silent on failure: the
    supplement is a convenience, and the models LiteLLM does ship are
    unaffected either way. See `services/agent/chatgpt_models.py`.
    """
    try:
        import litellm

        from services.agent import chatgpt_models

        chatgpt_models.register(litellm)
    except Exception:
        logger.exception("Could not register the supplemental ChatGPT models")


def build_model(resolved: ResolvedModel, *, reasoning_effort: str | None = None) -> LiteLLM:
    """Construct the LiteLLM model for a resolved row.

    The decrypted key lives in a local for the length of this call and is
    dropped before returning. That is also why this function logs with
    ``logger.error`` and no traceback: ``exc_info`` captures frame locals, so an
    exception raised while the key is in scope would write it into
    ``log/errors.jsonl``.

    Args:
        resolved: The model resolved by :func:`resolve_model`.
        reasoning_effort: Effort the request asked for, if any.

    Returns:
        A configured ``agno.models.litellm.LiteLLM``.

    Raises:
        AgnoNotInstalled: When the optional dependency is missing.
        MissingCredential: When the stored key vanished between resolution and
            construction, which is what a concurrent delete looks like.
        InvalidModelConfig: When the row cannot be turned into model kwargs.
    """
    # LiteLLM's registry omits several models the ChatGPT subscription serves,
    # and an unregistered one is not merely unlisted: it is routed to the
    # chat-completions bridge and comes back as a Cloudflare interstitial. Done
    # here rather than in `chatgpt_oauth.ensure_ready`, which must stay free of
    # network work and of importing litellm, and rather than only in
    # `catalog._build`, which a run resolving a stored row never reaches.
    _register_chatgpt_models()

    _agent_cls, litellm_cls, _db_cls = _require_agno()

    # Nothing is decrypted for a provider that stores no key. `ollama` is the
    # case that matters: it needs none, and a decryption that cannot succeed is
    # a plaintext credential brought into a frame for no reason.
    api_key = None
    if resolved.has_key:
        api_key = agent_db.get_api_key_for_model(resolved.id, resolved.provider_kind)
        if not api_key:
            raise MissingCredential(
                f"The API key for {resolved.display_name} could not be read. "
                "Re-enter it in agent settings."
            )

    try:
        kwargs = litellm_kwargs(resolved, api_key)
    except ValueError as exc:
        # No traceback: this frame holds the decrypted key in `api_key` and in
        # `kwargs`, and exc_info would serialise both into the error log.
        logger.error("Agent model %s could not be configured: %s", resolved.display_name, str(exc))
        # `from None` for the same reason: a chained cause carries the traceback
        # of the frame that holds the key.
        raise InvalidModelConfig(str(exc)) from None

    effort = _reasoning_effort(resolved, reasoning_effort)
    if effort:
        kwargs["request_params"] = {"reasoning_effort": effort}

    kwargs["name"] = resolved.display_name

    try:
        model = litellm_cls(**kwargs)
    except Exception as exc:
        # Same carve-out: `kwargs` in this frame carries the plaintext key.
        logger.error("Agent model %s could not be built: %s", resolved.display_name, str(exc))
        raise InvalidModelConfig(
            f"The model {resolved.display_name} could not be built: {exc}"
        ) from None
    finally:
        api_key = None
        kwargs = {}

    if resolved.secret_name:
        # Best effort, and deliberately after construction: a failed build must
        # not record the key as used. The store swallows its own failures.
        agent_db.mark_secret_used(resolved.secret_name)

    logger.info(
        "Agent model resolved: %s (%s, reasoning=%s)",
        resolved.display_name,
        resolved.litellm_id,
        effort or "off",
    )
    return model


# ---------------------------------------------------------------------------
# The session store
# ---------------------------------------------------------------------------

_db_lock = Lock()
_session_db: SqliteDb | None = None


def session_db_path() -> Path:
    """Where agno's own session database lives.

    Returns:
        The absolute path to ``db/agent.db``. Deliberately not
        ``openalgo.db``: this file holds a third-party schema written by agno.
    """
    return SESSION_DB_PATH


def session_db() -> SqliteDb:
    """The process-wide agno session store, created on first use.

    Required, not optional: agno keeps paused-run state here, and without it a
    run that stops for a human confirmation cannot be resumed in the next
    request.

    One instance for the process. A new engine per request would leak a file
    descriptor set in a Gunicorn worker that never restarts.

    Returns:
        The shared ``SqliteDb``.

    Raises:
        AgnoNotInstalled: When the optional dependency is missing.
    """
    global _session_db

    if _session_db is not None:
        return _session_db

    _agent_cls, _litellm_cls, sqlite_db_cls = _require_agno()

    # A real lock, held only across in-memory bookkeeping: the engine opens no
    # connection until it is first used, so nothing here can block the hub.
    with _db_lock:
        if _session_db is not None:
            return _session_db

        path = session_db_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        # create_db_engine applies the project-wide NullPool policy. Passing the
        # engine rather than a file path is what keeps agno from building its
        # own pooled engine, which would hold connections open per thread.
        engine = create_db_engine(f"sqlite:///{path.as_posix()}")
        _attach_json_serializer(engine)

        _session_db = sqlite_db_cls(db_engine=engine, db_file=str(path))
        logger.info("Agent session store ready at %s", path)
        return _session_db


def _attach_json_serializer(engine: Any) -> None:
    """Give an engine agno's JSON serializer for its JSON columns.

    Agno passes ``json_serializer`` when it builds its own engine, because run
    and session blobs contain datetimes and UUIDs that the standard library
    encoder refuses. We supply the engine instead, to get NullPool, so the
    serializer has to be attached afterwards.

    A failure is logged and ignored: agno pre-serialises the session blobs
    itself, so the worst case is a narrower set of run payloads than agno's own
    engine would accept, not a broken store.

    Args:
        engine: The SQLAlchemy engine to patch.
    """
    try:
        from agno.db.utils import json_serializer

        engine.dialect._json_serializer = json_serializer
    except Exception:
        logger.exception("Could not attach agno's JSON serializer to the agent session engine")


def reset_session_db() -> None:
    """Drop the cached session store and dispose its engine.

    For tests, and for a path that has to point the store somewhere else. Not
    called in normal operation: the store lives as long as the process.
    """
    global _session_db

    with _db_lock:
        store, _session_db = _session_db, None

    if store is None:
        return
    engine = getattr(store, "db_engine", None)
    if engine is not None:
        try:
            engine.dispose()
        except Exception:
            logger.exception("Could not dispose the agent session engine")


# ---------------------------------------------------------------------------
# The tool seam
# ---------------------------------------------------------------------------


def build_session_state(context: ToolContext, **extra: Any) -> dict[str, Any]:
    """Build the agno session state for a run.

    **No credential goes in here.** Session state is persisted by agno and is
    also what agno would interpolate into a message if variable resolution were
    on, so the OpenAlgo API key is deliberately absent: the tool factory takes
    it from the context it closed over instead.

    Args:
        context: The run's tool context.
        **extra: Additional non-secret values a surface wants to persist.

    Returns:
        A JSON-safe mapping.
    """
    state: dict[str, Any] = {
        "surface": context.surface,
        "trading_enabled": _effective_trading_enabled(context.trading_enabled),
        # Per turn, and persisted here because it has to survive into the run
        # the tool factory rebuilds. A resumed run reads it back off the same
        # state, so a turn sent with search off cannot get the search tools
        # handed to it when the operator approves a pending order.
        "web_search_enabled": bool(context.web_search_enabled),
        "analyzer_mode": bool(context.analyzer_mode),
        "conversation_id": context.conversation_id,
        "user_id": context.user_id,
    }
    state.update(extra)
    return state


def _effective_trading_enabled(session_flag: Any) -> bool:
    """Combine the session's trading flag with the operator's setting.

    Both have to say yes. The session flag alone would keep order tools in the
    schema after the operator switched trading off in settings, and the setting
    alone would offer them on a surface that never asked for them.

    Args:
        session_flag: The value carried by the session state or the context.

    Returns:
        True only when the session asked for trading and the database allows it.
    """
    if not bool(session_flag):
        return False
    try:
        return bool(settings.is_trading_enabled(fresh=True))
    except Exception:
        # Fail closed. The settings module already returns safe defaults on a
        # read failure, so reaching this means something worse; an agent that
        # cannot read its own policy does not get order tools.
        logger.exception("Could not read the agent trading setting; withholding order tools")
        return False


def tool_factory(context: ToolContext) -> Callable[..., list[Any]]:
    """Build the callable agno calls to decide which tools a run gets.

    Agno injects by parameter name, so the returned closure takes
    ``run_context``. It rebuilds a :class:`ToolContext` from that run's session
    state on every run and hands it to
    :func:`services.agent.tools.build_toolkits`, which is where toolkit
    selection actually lives.

    The API key comes from the captured context, never from the session state,
    so the credential is never persisted by agno and never interpolated into a
    message.

    Args:
        context: The context the agent was built with. Supplies the credential
            and the defaults for anything the session state does not carry.

    Returns:
        A callable suitable for ``Agent(tools=...)``.
    """

    def build_tools(run_context: Any = None) -> list[Any]:
        """Re-evaluate tool availability for one run.

        Args:
            run_context: Agno's run context. Absent only in a direct call.

        Returns:
            The toolkits this run may use.
        """
        state = getattr(run_context, "session_state", None)
        state = dict(state) if isinstance(state, Mapping) else {}

        run_context_id = getattr(run_context, "run_id", None) or context.run_id
        session_id = getattr(run_context, "session_id", None) or context.session_id

        per_run = ToolContext.from_session_state(
            state,
            api_key=context.api_key,
            conversation_id=state.get("conversation_id", context.conversation_id),
            surface=state.get("surface", context.surface),
            user_id=state.get("user_id", context.user_id),
            analyzer_mode=state.get("analyzer_mode", context.analyzer_mode),
            trading_enabled=_effective_trading_enabled(
                state.get("trading_enabled", context.trading_enabled)
            ),
            web_search_enabled=bool(state.get("web_search_enabled", context.web_search_enabled)),
            run_id=run_context_id,
            session_id=session_id,
            extras=context.extras,
        )
        return agent_tools.build_toolkits(per_run)

    return build_tools


# ---------------------------------------------------------------------------
# The agent
# ---------------------------------------------------------------------------


def build_agent(
    context: ToolContext,
    *,
    model_id: int | str | None = None,
    session_id: str | None = None,
    reasoning_effort: str | None = None,
    extra_sections: Iterable[prompts.PromptSection] = (),
    extra_runtime_lines: Sequence[str] = (),
    require_vision: bool = False,
    tool_call_limit: int = DEFAULT_TOOL_CALL_LIMIT,
    num_history_runs: int = DEFAULT_NUM_HISTORY_RUNS,
    max_prompt_chars: int | None = DEFAULT_MAX_PROMPT_CHARS,
    now: datetime | None = None,
) -> Agent:
    """Build the agent for one run.

    Every failure this can raise happens here, before the caller opens its SSE
    response, so a bad model id is an HTTP error rather than a stream that dies
    mid-answer.

    Args:
        context: The run's tool context. Carries the OpenAlgo API key, the
            surface, the conversation and whether the session wants trading.
        model_id: The model the request named, or None for the default. Falls
            back to ``context.extras['model_id']`` when not given.
        session_id: Agno session id to resume. None starts a new session.
        reasoning_effort: ``off``, ``low``, ``medium`` or ``high`` for this run,
            overriding the row and the platform setting.
        extra_sections: Prompt sections the surface adds or replaces.
        extra_runtime_lines: Extra bullets for the session section of the
            prompt, such as the chart's current symbol and interval.
        require_vision: True when the turn carries an image. The build is
            refused, by name, on a model that cannot read one.
        tool_call_limit: Maximum tool calls for the whole run.
        num_history_runs: How many previous runs are replayed into context.
        max_prompt_chars: Budget for the system prompt. The pinned security
            rules are never trimmed.
        now: Current time for the prompt. Defaults to now in IST.

    Returns:
        A configured agno ``Agent``, ready for ``run(stream=True)``.

    Raises:
        AgentBuildError: Any of the typed subclasses, each carrying a message
            and an HTTP status.
    """
    agent_cls, _litellm_cls, _db_cls = _require_agno()

    requested = model_id if model_id is not None else context.extras.get("model_id")
    resolved = resolve_model(requested)

    # Before the model is constructed, so an image on a text-only model costs
    # nothing and the operator gets a clean 400 rather than a stream that dies
    # on the provider's own complaint.
    if require_vision and not resolved.supports_vision:
        raise VisionUnsupported(
            f"{resolved.display_name} cannot read images. Remove the image, or "
            "choose a model that supports vision."
        )

    model = build_model(resolved, reasoning_effort=reasoning_effort)

    state = build_session_state(context)
    system_prompt = prompts.build_system_prompt(
        surface=context.surface,
        trading_enabled=bool(state["trading_enabled"]),
        analyzer_mode=bool(state["analyzer_mode"]),
        now=now or datetime.now(IST),
        override=settings.get_system_prompt_override(),
        extra_sections=extra_sections,
        extra_runtime_lines=extra_runtime_lines,
        max_chars=max_prompt_chars,
    )

    agent = agent_cls(
        id=AGENT_ID,
        name=prompts.ASSISTANT_NAME,
        model=model,
        # Agno's own store. Required for a paused confirmation to survive across
        # requests, which is the whole reason a mutating tool can ask a human.
        db=session_db(),
        user_id=context.user_id,
        session_id=session_id or context.session_id,
        session_state=state,
        # Our freshly built state wins over whatever the session last stored.
        # Without this the DB copy takes precedence, so a stale trading_enabled
        # from an earlier session would put order tools back in the schema.
        overwrite_db_session_state=True,
        # The extension seam: a callable, so agno re-evaluates tool availability
        # per run from run_context.session_state rather than freezing the list
        # the agent was built with.
        tools=tool_factory(context),
        # Tool availability is a security control, so it is never served from a
        # cache keyed on the user id.
        cache_callables=False,
        tool_call_limit=tool_call_limit,
        add_history_to_context=True,
        num_history_runs=num_history_runs,
        markdown=True,
        # A verbatim system message, so the anti-injection rule is first and
        # stays first. Agno composes its own message from description and
        # instructions only when this is unset.
        system_message=system_prompt,
        # No `{placeholder}` substitution from session state into messages. The
        # prompt carries JSON examples in braces, and more importantly a message
        # that interpolated session state would be a way for text to read values
        # it was never handed.
        resolve_in_context=False,
        # No output_schema: setting one disables token streaming.
        telemetry=False,
        store_events=False,
    )

    logger.info(
        "Agent built: model=%s surface=%s trading=%s analyzer=%s conversation=%s",
        resolved.display_name,
        context.surface,
        state["trading_enabled"],
        state["analyzer_mode"],
        context.conversation_id,
    )
    return agent
