"""The Flow webhook is the product's only remaining unauthenticated entry point.

`/flow/webhook/<token>` places real orders and is reachable by anyone who can
reach the server. It carried no rate limit at all while the legacy `/strategy`
and `/chartink` webhooks it replaces both spent `WEBHOOK_RATE_LIMIT`, so moving
users onto Flow would have quietly removed a control rather than kept it.

These tests drive the real routes through the real `limiter` instance until the
budget is gone. They assert on responses, not on the presence of a decorator: a
limit that is registered but never evaluated would pass a source-level check and
fail every test here.
"""

import os

import pytest
from flask import Flask, jsonify, redirect, request
from flask_limiter.util import get_qualified_name

import blueprints.flow as flow
from blueprints.flow import flow_bp
from limiter import limiter

TOKEN = "wf-token-under-test"


@pytest.fixture
def app():
    """A minimal app carrying the real blueprint, the real limiter, and app.py's 429.

    The application-wide handler is reproduced rather than skipped, because the
    whole point of the blueprint's own handler is that it is consulted first.
    Leave it out and the JSON assertion below would pass against a Flask that
    simply had nothing else to offer.
    """
    application = Flask(__name__)
    application.config["TESTING"] = True
    limiter.init_app(application)
    application.register_blueprint(flow_bp)

    @application.errorhandler(429)
    def app_wide_rate_limited(error):
        # Mirrors app.py: JSON for `/api/`, a redirect for everything else.
        if request.path.startswith("/api/"):
            return {"status": "error", "message": "Rate limit exceeded."}, 429
        return redirect("/rate-limited")

    limiter.reset()
    yield application
    limiter.reset()


@pytest.fixture(autouse=True)
def stub_execution(monkeypatch):
    """Keep the workflow lookup and order placement out of it.

    The routes resolve `_execute_webhook` as a module global at call time, so
    replacing it here leaves the decorators, the key functions and the limiter
    exactly as production has them.
    """
    monkeypatch.setattr(
        flow,
        "_execute_webhook",
        lambda token, webhook_data=None, url_secret=None: (jsonify({"status": "success"}), 200),
    )


@pytest.fixture
def budget(monkeypatch):
    """Shrink both limits so a test can exhaust them in a few requests.

    `limit_provider` is read on every evaluation, so this changes the live
    limit without re-importing the blueprint and re-registering it. The value
    production uses is asserted separately below.
    """

    def apply(caller="1000 per minute", workflow="1000 per minute"):
        monkeypatch.setattr(flow._webhook_caller_limit, "limit_provider", caller)
        monkeypatch.setattr(flow._webhook_workflow_limit, "limit_provider", workflow)

    return apply


def post(client, token=TOKEN, path_suffix="", address="203.0.113.10"):
    return client.post(
        f"/flow/webhook/{token}{path_suffix}",
        data='{"action": "BUY"}',
        content_type="application/json",
        environ_base={"REMOTE_ADDR": address},
    )


def test_the_limiter_is_live_in_this_app(app):
    """Names the reason the rest of the file could go quiet.

    With the limiter disabled every test below would report 200 where it
    expects 429, which is a real failure but an obscure one. This says so.
    """
    assert limiter.enabled
    assert app.config["RATELIMIT_ENABLED"]


def test_requests_within_the_budget_still_reach_the_workflow(app, budget):
    budget(caller="3 per minute", workflow="3 per minute")
    client = app.test_client()

    for _ in range(3):
        response = post(client)
        assert response.status_code == 200
        assert response.get_json()["status"] == "success"


def test_the_request_after_the_budget_is_refused(app, budget):
    budget(caller="3 per minute", workflow="3 per minute")
    client = app.test_client()

    for _ in range(3):
        assert post(client).status_code == 200

    assert post(client).status_code == 429


def test_an_over_limit_caller_gets_json_not_a_redirect(app, budget):
    """app.py answers 429 with a redirect to /rate-limited outside `/api/`.

    A browser reads that page. TradingView follows the redirect, receives HTML
    and 200, and records the alert as delivered, so a throttled workflow would
    look exactly like a working one. The blueprint handler is consulted first
    and keeps a machine caller on a status code it can act on.
    """
    budget(caller="1 per minute", workflow="1 per minute")
    client = app.test_client()
    assert post(client).status_code == 200

    response = post(client)

    assert response.status_code == 429
    assert "Location" not in response.headers
    assert response.is_json
    body = response.get_json()
    assert body["status"] == "error"
    assert body["retry_after"] == 60
    assert response.headers["Retry-After"] == "60"


def test_the_symbol_route_draws_on_the_same_budget(app, budget):
    """Both spellings of one webhook must not add up to twice the rate."""
    budget(caller="2 per minute", workflow="2 per minute")
    client = app.test_client()

    assert post(client).status_code == 200
    assert post(client, path_suffix="/RELIANCE").status_code == 200
    assert post(client, path_suffix="/RELIANCE").status_code == 429


def test_a_token_stays_capped_however_many_addresses_replay_it(app, budget):
    """The token is the credential, so the cap has to follow the token.

    Anything keyed only on the caller lets a leaked token be replayed from as
    many addresses as the attacker has.
    """
    budget(caller="1000 per minute", workflow="2 per minute")
    client = app.test_client()

    assert post(client, address="203.0.113.10").status_code == 200
    assert post(client, address="198.51.100.7").status_code == 200
    assert post(client, address="192.0.2.44").status_code == 429


def test_one_address_cannot_buy_more_budget_by_changing_tokens(app, budget):
    """Every guess in a token sweep carries a different token.

    A token-keyed limit scores each one against an empty bucket and never
    fires, while each miss still costs a database lookup. The caller-keyed
    limit is the only one that ends the sweep.
    """
    budget(caller="2 per minute", workflow="1000 per minute")
    client = app.test_client()

    assert post(client, token="guess-one").status_code == 200
    assert post(client, token="guess-two").status_code == 200
    assert post(client, token="guess-three").status_code == 429


def test_a_different_token_keeps_its_own_workflow_budget(app, budget):
    """The workflow limit is per token, not one bucket for every webhook."""
    budget(caller="1000 per minute", workflow="1 per minute")
    client = app.test_client()

    assert post(client, token="workflow-a").status_code == 200
    assert post(client, token="workflow-a").status_code == 429
    assert post(client, token="workflow-b").status_code == 200


def test_both_limits_spend_the_shared_webhook_budget():
    """The same variable and default `/chartink` reads, so no new knob to set."""
    assert flow.WEBHOOK_RATE_LIMIT == os.getenv("WEBHOOK_RATE_LIMIT", "100 per minute")
    assert flow._webhook_caller_limit.limit_provider == flow.WEBHOOK_RATE_LIMIT
    assert flow._webhook_workflow_limit.limit_provider == flow.WEBHOOK_RATE_LIMIT


def test_only_the_two_webhook_routes_are_rate_limited(app):
    """Every other Flow route is behind `@check_session_validity`.

    The limit exists for callers who have no session, so if a third endpoint
    ever appears on this list it is either a new webhook that needs the same
    treatment or a route that has lost its session guard.
    """
    limited = {
        endpoint
        for endpoint, view in app.view_functions.items()
        if endpoint.startswith("flow.")
        and limiter.limit_manager.decorated_limits(get_qualified_name(view))
    }
    assert limited == {"flow.trigger_webhook", "flow.trigger_webhook_with_symbol"}
