"""The ChatGPT subscription, wired into the parts of the agent that must know.

`services/agent/chatgpt_oauth.py` is tested on its own in
`test_agent_chatgpt_oauth.py`, with every outbound socket blocked. This file
tests the four seams it plugs into, and each one exists because of a specific
wrong answer the platform would otherwise give:

* the config page asking for an API key that cannot exist, because
  `ProviderInfo.needs_key` defaults to true;
* `validate_provider_config` refusing a `chatgpt/` row for having no key;
* a run reaching LiteLLM with nothing to authenticate with, at which point
  `Authenticator.get_access_token` falls through to `_login_device_code`, which
  prints a code to a stdout nobody is reading and then polls for fifteen minutes
  on the run thread;
* a usage frame rendering `$0.00` under an answer that consumed plan quota,
  because LiteLLM's `completion_cost` answers zero for a model it cannot price
  and agno hands that through as `metrics.cost`.

Nothing here calls a provider, opens a socket, or starts a device flow.
"""

from __future__ import annotations

import sys
from datetime import datetime
from types import SimpleNamespace

import pytest
import pytz
from flask import Blueprint, Flask

import blueprints.agent as agent_routes
from limiter import limiter
from services.agent import builder, catalog, chatgpt_oauth
from services.agent.frames import Usage
from services.agent.providers import litellm_model_id, validate_provider_config
from services.agent.stream import EventTranslator

USER = "chatgpt-wiring-tests"

#: One of the two subscription-only models, chosen deliberately: it shares its
#: bare name with nothing on `openai`, which is what makes it useful for proving
#: that a bare name is *not* what identifies a plan turn.
SUBSCRIPTION_ONLY = "gpt-5.3-instant"

#: One of the eight that do share a bare name with an `openai` model. The
#: `chatgpt/` prefix is the only thing separating the two billing systems.
SHARED_NAME = "gpt-5.4"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class Event:
    """Anything with an `event` attribute is an agno event as far as we care."""

    def __init__(self, **fields: object) -> None:
        self.__dict__.update(fields)


def usage_frames(
    resolved_model: str | None,
    reported_model: str | None,
    reported_cost: float | None,
) -> list[Usage]:
    """Run one synthetic turn and return every usage frame it produced.

    The turn is a model call followed by a `RunCompleted` whose metrics carry
    larger totals, because a repeated total is deduplicated and would leave the
    reported-cost path unexercised.

    Args:
        resolved_model: The id resolved from the operator's row.
        reported_model: The id the provider reported back.
        reported_cost: What agno put on `metrics.cost`.

    Returns:
        The usage frames, in order.
    """
    translator = EventTranslator(1, model=resolved_model)
    produced = list(
        translator.translate(
            Event(
                event="ModelRequestCompleted",
                model=reported_model,
                input_tokens=1000,
                output_tokens=500,
                total_tokens=1500,
                cache_read_tokens=0,
                reasoning_tokens=0,
                time_to_first_token=0.4,
            )
        )
    )
    produced += translator.translate(
        Event(
            event="RunCompleted",
            metrics=Event(
                input_tokens=1200,
                output_tokens=600,
                total_tokens=1800,
                cache_read_tokens=0,
                reasoning_tokens=0,
                time_to_first_token=0.4,
                cost=reported_cost,
            ),
        )
    )
    return [frame for frame in produced if isinstance(frame, Usage)]


def model_row(
    model_name: str, kind: str = "litellm", base_url: str | None = None
) -> SimpleNamespace:
    """An `ag_provider_model` row, with only the fields `resolve_model` reads."""
    return SimpleNamespace(
        id=7,
        provider_kind=kind,
        model_name=model_name,
        display_name=f"Test {model_name}",
        base_url=base_url,
        enabled=True,
        is_default=False,
        supports_reasoning=False,
        default_reasoning_effort="off",
        supports_vision=False,
        tools_unreliable=False,
    )


def _subscription_ids() -> list[str]:
    """Every `chatgpt/` id LiteLLM ships metadata for, or a stand-in.

    Read from the library so a LiteLLM bump widens the parametrisation on its
    own. The literal fallback keeps the file collectable on a build that has no
    chatgpt entries at all, where the tests below are then trivially true.
    """
    import litellm

    found = sorted(name for name in litellm.model_cost if name.startswith("chatgpt/"))
    return found or [f"chatgpt/{SHARED_NAME}", f"chatgpt/{SUBSCRIPTION_ONLY}"]


def _expected(litellm_id: str, probe: str) -> bool:
    """What the entry says, falling back to the bare name when it says nothing.

    LiteLLM's own rule, and the reason it is a rule: a sparse provider entry
    inherits the complete metadata from the bare-name one, while an explicit
    False is respected and does not fall through.
    """
    import litellm

    entry = litellm.model_cost.get(litellm_id) or {}
    answer = entry.get(probe)
    if answer is None:
        answer = (litellm.model_cost.get(litellm_id.split("/", 1)[-1]) or {}).get(probe)
    return bool(answer)


@pytest.fixture(autouse=True)
def _isolated_token_dir(tmp_path, monkeypatch):
    """Never read the machine's real ChatGPT credential.

    Without this the suite reads `db/chatgpt_oauth/auth.json`, so it passes on
    a machine with no subscription and fails on one that has signed in: the
    gate finds a genuine token, `ensure_ready` answers True, and a test
    expecting `MissingCredential` sees a working model instead. It also means a
    developer's live credential is exercised by the tests, which is the part
    that should not happen at all.

    Points the module at a temporary directory for every test in this file, and
    puts it back afterwards.
    """
    monkeypatch.setenv("CHATGPT_TOKEN_DIR", str(tmp_path / "chatgpt"))
    chatgpt_oauth.configure_token_dir(tmp_path / "chatgpt")
    yield
    chatgpt_oauth.configure_token_dir(None)


@pytest.fixture
def keyless_row(monkeypatch):
    """Resolve one model row with no API key stored for it."""

    def install(row: SimpleNamespace) -> None:
        monkeypatch.setattr(builder.agent_db, "get_model", lambda model_id: row)
        monkeypatch.setattr(builder.agent_db, "resolve_api_key", lambda row_id, kind: (None, None))

    return install


# ---------------------------------------------------------------------------
# The provider takes no key
# ---------------------------------------------------------------------------


class TestTheProviderAsksForNoKey:
    """A plan is reached through a device flow, so there is no key to paste."""

    def test_the_catalogue_reports_the_provider_keyless(self):
        info = {provider.id: provider for provider in catalog.list_providers()}
        assert "chatgpt" in info, "LiteLLM no longer exposes a chatgpt provider"
        assert info["chatgpt"].needs_key is False
        assert info["chatgpt"].needs_base_url is False
        assert info["chatgpt"].provider_kind == "litellm"

    def test_every_model_it_offers_can_call_functions(self):
        """This agent is entirely tool driven, so the check is load bearing."""
        models = catalog.list_models("chatgpt")
        assert models, "the chatgpt provider offers no models"
        assert all(model.supports_function_calling for model in models)

    @pytest.mark.parametrize("name", [SHARED_NAME, SUBSCRIPTION_ONLY])
    def test_a_subscription_row_saves_without_a_key(self, name):
        assert validate_provider_config("litellm", f"chatgpt/{name}", None, has_key=False) is None

    @pytest.mark.parametrize(
        ("kind", "name"),
        [("litellm", f"openai/{SHARED_NAME}"), ("litellm", SHARED_NAME), ("openai", SHARED_NAME)],
    )
    def test_every_other_row_still_needs_one(self, kind, name):
        """The carve-out is for the prefix, not for the kind."""
        error = validate_provider_config(kind, name, None, has_key=False)
        assert error is not None
        assert "API key" in error

    def test_the_model_id_keeps_its_prefix(self):
        """The prefix is what LiteLLM routes on and what billing keys off."""
        assert litellm_model_id("litellm", f"chatgpt/{SHARED_NAME}") == f"chatgpt/{SHARED_NAME}"

    def test_the_carve_out_fails_closed_when_the_module_cannot_be_imported(self, monkeypatch):
        """An unreadable subscription check asks for a key rather than skipping it.

        Refusing to save a row is recoverable and says why; saving one that can
        never authenticate puts a model in the picker that fails at run time.
        """
        import services.agent.providers as providers_module

        # Poisoning the entry makes `from ... import is_subscription_model`
        # raise, which is the failure this fallback exists for.
        monkeypatch.setitem(sys.modules, "services.agent.chatgpt_oauth", None)

        assert providers_module._is_subscription(f"chatgpt/{SHARED_NAME}") is False
        error = validate_provider_config("litellm", f"chatgpt/{SHARED_NAME}", None, has_key=False)
        assert error is not None
        assert "API key" in error


# ---------------------------------------------------------------------------
# The run gate
# ---------------------------------------------------------------------------


class TestTheRunRefusesBeforeLiteLlmCanStartADeviceFlow:
    """`ensure_ready` is checked in `resolve_model`, before an Agent exists."""

    def test_an_unauthorised_subscription_is_a_clean_typed_error(self, monkeypatch, keyless_row):
        keyless_row(model_row(f"chatgpt/{SHARED_NAME}"))
        monkeypatch.setattr(
            builder.chatgpt_oauth, "ensure_ready", lambda: (False, "Sign in to ChatGPT.")
        )

        with pytest.raises(builder.MissingCredential) as caught:
            builder.resolve_model(7)

        assert caught.value.message == "Sign in to ChatGPT."
        assert caught.value.status == 409

    def test_an_authorised_subscription_resolves(self, monkeypatch, keyless_row, no_device_flow):
        keyless_row(model_row(f"chatgpt/{SUBSCRIPTION_ONLY}"))
        monkeypatch.setattr(builder.chatgpt_oauth, "ensure_ready", lambda: (True, None))

        resolved = builder.resolve_model(7)

        assert resolved.litellm_id == f"chatgpt/{SUBSCRIPTION_ONLY}"
        assert resolved.has_key is False

    def test_a_metered_model_is_never_asked_about_a_subscription(self, monkeypatch, keyless_row):
        """The gate must not run for a row that has nothing to do with a plan."""
        calls: list[int] = []

        def record() -> tuple[bool, str | None]:
            calls.append(1)
            return True, None

        keyless_row(model_row("llama3", kind="ollama", base_url="http://127.0.0.1:11434"))
        monkeypatch.setattr(builder.chatgpt_oauth, "ensure_ready", record)

        builder.resolve_model(7)

        assert calls == []

    def test_the_gate_does_no_network_work(self, monkeypatch, keyless_row):
        """`ensure_ready` runs inside a request, so it must not reach a socket.

        Proved by making the module's own HTTP transports raise: if anything on
        this path opened one, the resolution below would fail with that error
        rather than with the module's own message.
        """

        def forbidden(*args: object, **kwargs: object):
            raise AssertionError("the resolve path opened an HTTP client")

        monkeypatch.setattr(chatgpt_oauth, "_SharedTransport", forbidden)
        monkeypatch.setattr(chatgpt_oauth, "_OwnedTransport", forbidden)
        keyless_row(model_row(f"chatgpt/{SHARED_NAME}"))

        with pytest.raises(builder.MissingCredential):
            builder.resolve_model(7)


@pytest.fixture
def no_device_flow(monkeypatch):
    """Record every LiteLLM capability probe, and make none of them reachable.

    Measured against `litellm==1.99.0`: `litellm.supports_reasoning(model=
    "chatgpt/gpt-5.4")` resolves the provider through `ChatGPTConfig.
    _get_openai_compatible_provider_info`, which calls
    `Authenticator.get_access_token`, which with no cached token falls through
    to `_login_device_code` and polls OpenAI for fifteen minutes on the calling
    thread after printing a code to stdout. Left unguarded, that runs inside
    this suite: it did, and the run died on the sixty-second test timeout inside
    `_poll_for_authorization_code`.

    **The assertion is on the recorded calls, never on an exception.**
    `_supports_factory` wraps the whole resolution in `try/except` and answers
    False, and `_litellm_opinion` catches too and falls back to the operator's
    flag, so a tripwire raised down the chain is swallowed twice over and proves
    nothing. The recorders therefore raise only as a safety net against a
    regression starting a real login, and what the tests read is the list.

    Returns:
        The list of `(probe, model)` pairs that reached LiteLLM.
    """
    import litellm

    pytest.importorskip("litellm.llms.chatgpt.authenticator")
    calls: list[tuple[str, str]] = []

    def recorder(probe: str):
        def record(model: str, *args: object, **kwargs: object) -> bool:
            calls.append((probe, model))
            raise AssertionError(f"{probe} was called for {model}")

        return record

    for probe in ("supports_vision", "supports_reasoning"):
        monkeypatch.setattr(litellm, probe, recorder(probe))
    return calls


class TestReadingACapabilityNeverAuthenticates:
    """The probe is a table lookup, and for this provider it has to stay one.

    This path sits behind no gate at all. `GET /agent/api/models` resolves every
    registered row's capabilities through these two functions, so a probe that
    authenticates turns listing a model into a fifteen-minute hang.
    """

    @pytest.mark.parametrize("name", [SHARED_NAME, SUBSCRIPTION_ONLY])
    def test_a_subscription_model_is_answered_from_the_price_table(self, no_device_flow, name):
        import litellm

        from services.agent.providers import reasoning_capable, vision_capable

        litellm_id = f"chatgpt/{name}"
        entry = litellm.model_cost[litellm_id]

        assert vision_capable(litellm_id, False) is bool(entry.get("supports_vision", False))
        assert reasoning_capable(litellm_id, True) is _expected(litellm_id, "supports_reasoning")
        assert no_device_flow == []

    @pytest.mark.parametrize("litellm_id", sorted(_subscription_ids()))
    @pytest.mark.parametrize("probe", ["supports_reasoning", "supports_vision"])
    def test_the_table_read_is_the_answer_the_predicate_would_give(
        self, monkeypatch, no_device_flow, litellm_id, probe
    ):
        """The lookup has to agree with LiteLLM, on every model and both probes.

        Asserting the read against the prefixed entry alone asserts the
        implementation, and it hid a real defect: none of the ten `chatgpt/`
        entries carries `supports_reasoning`, so that read answered False for
        all ten while `_supports_factory` answers True for eight, because an
        *absent* key falls through to the bare-name entry (LiteLLM #20885).
        Every reasoning model on a plan was silently demoted to a non-reasoning
        one.

        The comparison runs against the real `_supports_factory` with only
        `get_llm_provider` stubbed, which is the single step that reaches the
        authenticator. What it is replaced with is exactly what it returns after
        a successful sign-in: the bare name, the provider id, the access token
        as the dynamic key, and no api_base. Everything after it is a table
        lookup and runs for real.
        """
        from litellm import utils as litellm_utils

        from services.agent.providers import _litellm_opinion

        monkeypatch.setattr(
            litellm_utils.litellm,
            "get_llm_provider",
            lambda model, custom_llm_provider=None, *a, **k: (
                model.split("/", 1)[-1],
                "chatgpt",
                "not-a-real-access-token",
                None,
            ),
        )
        predicate = litellm_utils._supports_factory(
            model=litellm_id, custom_llm_provider=None, key=probe
        )

        assert _litellm_opinion(litellm_id, probe) is predicate
        assert no_device_flow == []

    def test_resolving_an_authorised_subscription_stays_offline(
        self, monkeypatch, keyless_row, no_device_flow
    ):
        """The whole of `resolve_model`, not just the gate."""
        keyless_row(model_row(f"chatgpt/{SHARED_NAME}"))
        monkeypatch.setattr(builder.chatgpt_oauth, "ensure_ready", lambda: (True, None))

        assert builder.resolve_model(7).litellm_id == f"chatgpt/{SHARED_NAME}"
        assert no_device_flow == []

    def test_a_metered_model_still_asks_litellm(self, monkeypatch):
        """The carve-out is for the one provider that authenticates on lookup."""
        import litellm

        from services.agent.providers import vision_capable

        asked: list[str] = []
        real = litellm.supports_vision

        def record(model: str) -> bool:
            asked.append(model)
            return real(model=model)

        monkeypatch.setattr(litellm, "supports_vision", record)

        assert vision_capable("gpt-4o", False) is True
        assert asked == ["gpt-4o"]


# ---------------------------------------------------------------------------
# Billing
# ---------------------------------------------------------------------------


class TestAPlanTurnReportsTokensAndNoCost:
    """The rule: tokens, no cost, labelled. Zero and the API price are both lies."""

    def test_a_frame_defaults_to_metered(self):
        """A client that never hears about a plan keeps its existing meaning."""
        assert Usage().billing == "metered"
        assert Usage().to_dict()["billing"] == "metered"

    def test_the_catalogue_declines_to_price_a_plan_model(self):
        """The upstream half of the rule, and the reason the frame can be honest."""
        assert catalog.estimate_cost(f"chatgpt/{SHARED_NAME}", 1000, 500) is None
        assert catalog.estimate_cost(f"openai/{SHARED_NAME}", 1000, 500) > 0

    def test_a_reported_zero_is_not_rendered_as_free(self):
        """LiteLLM answers 0.0 for a model it cannot price; that is not a price."""
        frame = usage_frames(f"chatgpt/{SHARED_NAME}", f"chatgpt/{SHARED_NAME}", 0.0)[-1]

        assert frame.billing == "subscription"
        assert frame.cost_usd is None
        assert frame.total_tokens == 1800

    def test_a_bare_reported_name_does_not_re_price_the_turn(self):
        """The resolved id is kept precisely because the reported one can go bare.

        A bare subscription name is unrecognisable on its own: the catalogue has
        no entry for it. The prefix survives on the resolved id, which is what
        this frame is settled against.
        """
        assert catalog.get_model_meta(SUBSCRIPTION_ONLY) is None

        frame = usage_frames(f"chatgpt/{SUBSCRIPTION_ONLY}", SUBSCRIPTION_ONLY, 0.0)[-1]

        assert frame.billing == "subscription"
        assert frame.cost_usd is None
        assert frame.model == SUBSCRIPTION_ONLY

    def test_a_metered_turn_keeps_its_real_price(self):
        frame = usage_frames(f"openai/{SHARED_NAME}", f"openai/{SHARED_NAME}", None)[-1]

        assert frame.billing == "metered"
        assert frame.cost_usd == pytest.approx(
            catalog.estimate_cost(f"openai/{SHARED_NAME}", 1200, 600)
        )

    def test_a_metered_turn_still_falls_back_to_the_reported_cost(self):
        """The fallback is untouched for a model the price table does not carry."""
        frame = usage_frames("openai/not-a-real-model", "openai/not-a-real-model", 0.0123)[-1]

        assert frame.billing == "metered"
        assert frame.cost_usd == pytest.approx(0.0123)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch):
    """A Flask app carrying only this blueprint, with a logged-in session."""
    monkeypatch.setattr(limiter, "enabled", False)
    application = Flask(__name__)
    application.config.update(
        TESTING=True,
        SECRET_KEY="agent-chatgpt-wiring-tests",
        PROPAGATE_EXCEPTIONS=True,
    )
    application.register_blueprint(agent_routes.agent_bp)

    test_client = application.test_client()
    with test_client.session_transaction() as flask_session:
        flask_session["logged_in"] = True
        flask_session["user"] = USER
        flask_session["login_time"] = datetime.now(pytz.timezone("Asia/Kolkata")).isoformat()
    return test_client


def snapshot(**changes: object) -> chatgpt_oauth.LoginStatus:
    """A login snapshot with the fields a pending sign-in carries."""
    base = chatgpt_oauth.LoginStatus(
        state=chatgpt_oauth.LOGIN_PENDING,
        user_code="ABCD-EFGH",
        verification_url="https://example.invalid/device",
        started_at=1000.0,
        expires_at=1900.0,
    )
    return base if not changes else type(base)(**{**base.as_dict(), **changes})


class TestTheRoutes:
    """The four the settings page drives, and what they answer."""

    def test_status_reports_the_authorisation_and_no_token(self, client, monkeypatch):
        monkeypatch.setattr(
            chatgpt_oauth,
            "status",
            lambda: {
                "provider": "chatgpt",
                "authorised": True,
                "fingerprint": "...cdef sha256:0123456789ab",
                "account_id": "acct-1",
                "access_token_expires_at": 1900.0,
                "access_token_expired": False,
                "stored_in_database": True,
                "token_dir": "/tmp/chatgpt",
                "login": chatgpt_oauth.LoginStatus().as_dict(),
            },
        )

        response = client.get("/agent/api/chatgpt/status")
        body = response.get_json()

        assert response.status_code == 200
        assert body["data"]["authorised"] is True
        assert "access_token" not in body["data"]
        assert "refresh_token" not in body["data"]

    def test_login_returns_the_code_to_show_the_operator(self, client, monkeypatch):
        monkeypatch.setattr(chatgpt_oauth, "login_status", chatgpt_oauth.LoginStatus)
        monkeypatch.setattr(chatgpt_oauth, "start_login", lambda *, force: snapshot())

        response = client.post("/agent/api/chatgpt/login", json={"force": False})
        body = response.get_json()

        assert response.status_code == 200
        assert body["data"]["state"] == "pending"
        assert body["data"]["user_code"] == "ABCD-EFGH"
        assert body["reused"] is False

    def test_a_login_already_in_flight_is_reported_as_reused(self, client, monkeypatch):
        """The device endpoint has a cooldown, and the first code may be half typed."""
        live = snapshot()
        monkeypatch.setattr(chatgpt_oauth, "login_status", lambda: live)
        monkeypatch.setattr(chatgpt_oauth, "start_login", lambda *, force: live)

        body = client.post("/agent/api/chatgpt/login", json={}).get_json()

        assert body["reused"] is True

    def test_force_is_read_from_the_body(self, client, monkeypatch):
        seen: list[bool] = []
        monkeypatch.setattr(chatgpt_oauth, "login_status", chatgpt_oauth.LoginStatus)
        monkeypatch.setattr(
            chatgpt_oauth, "start_login", lambda *, force: seen.append(force) or snapshot()
        )

        client.post("/agent/api/chatgpt/login", json={"force": True})
        client.post("/agent/api/chatgpt/login")

        assert seen == [True, False]

    def test_a_provider_without_the_flow_is_a_501(self, client, monkeypatch):
        def unavailable(*, force: bool):
            raise chatgpt_oauth.ChatGptOAuthUnavailable("LiteLLM has no chatgpt provider.")

        monkeypatch.setattr(chatgpt_oauth, "start_login", unavailable)

        response = client.post("/agent/api/chatgpt/login", json={})

        assert response.status_code == 501
        assert response.get_json()["message"] == "LiteLLM has no chatgpt provider."

    def test_a_refused_device_code_is_a_502(self, client, monkeypatch):
        def refused(*, force: bool):
            raise chatgpt_oauth.ChatGptOAuthError("The sign-in service refused the request.")

        monkeypatch.setattr(chatgpt_oauth, "start_login", refused)

        response = client.post("/agent/api/chatgpt/login", json={})

        assert response.status_code == 502
        assert "refused" in response.get_json()["message"]

    def test_cancel_reports_whether_anything_was_running(self, client, monkeypatch):
        cancelled = snapshot(state=chatgpt_oauth.LOGIN_CANCELLED, user_code="")
        monkeypatch.setattr(chatgpt_oauth, "cancel_login", lambda: True)
        monkeypatch.setattr(chatgpt_oauth, "login_status", lambda: cancelled)

        body = client.post("/agent/api/chatgpt/cancel").get_json()

        assert body["stopped"] is True
        assert body["data"]["state"] == "cancelled"

    def test_cancelling_nothing_succeeds(self, client, monkeypatch):
        """Idempotent: the operator asked for no login to run, and none does."""
        monkeypatch.setattr(chatgpt_oauth, "cancel_login", lambda: False)
        monkeypatch.setattr(chatgpt_oauth, "login_status", chatgpt_oauth.LoginStatus)

        body = client.post("/agent/api/chatgpt/cancel").get_json()

        assert body["stopped"] is False
        assert body["data"]["state"] == "idle"

    def test_cancel_does_not_decrypt_the_stored_credential(self, client, monkeypatch):
        """A UI polls this while a code is on screen; `status()` is too expensive."""

        def forbidden() -> dict:
            raise AssertionError("the cancel route called status()")

        monkeypatch.setattr(chatgpt_oauth, "status", forbidden)
        monkeypatch.setattr(chatgpt_oauth, "cancel_login", lambda: False)
        monkeypatch.setattr(chatgpt_oauth, "login_status", chatgpt_oauth.LoginStatus)

        assert client.post("/agent/api/chatgpt/cancel").status_code == 200

    @pytest.mark.parametrize("removed", [True, False])
    def test_signing_out_reports_what_it_removed(self, client, monkeypatch, removed):
        monkeypatch.setattr(chatgpt_oauth, "forget", lambda: removed)

        body = client.delete("/agent/api/chatgpt/session").get_json()

        assert body["removed"] is removed

    def test_every_route_needs_a_session(self, monkeypatch):
        monkeypatch.setattr(limiter, "enabled", False)
        application = Flask(__name__)
        application.config.update(TESTING=True, SECRET_KEY="unauthenticated")
        application.register_blueprint(agent_routes.agent_bp)

        # `check_session_validity` redirects to `auth.login`, which lives in a
        # blueprint this minimal app does not carry. The stub is only a target
        # for `url_for`, so the redirect can be built and asserted on.
        auth_stub = Blueprint("auth", __name__)
        auth_stub.add_url_rule("/login", "login", lambda: "login")
        application.register_blueprint(auth_stub)

        anonymous = application.test_client()

        for method, path in (
            ("get", "/agent/api/chatgpt/status"),
            ("post", "/agent/api/chatgpt/login"),
            ("post", "/agent/api/chatgpt/cancel"),
            ("delete", "/agent/api/chatgpt/session"),
        ):
            response = getattr(anonymous, method)(path)
            assert response.status_code in (302, 401), f"{method} {path} was not refused"

    def test_the_setup_gate_carries_the_authorisation(self, client, monkeypatch):
        """So the config page renders its initial state without a second request."""
        monkeypatch.setattr(agent_routes.chatgpt_oauth, "is_authorised", lambda: True)

        body = client.get("/agent/api/status").get_json()

        assert body["chatgpt_authorised"] is True
