import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from flask import Blueprint, Flask
from flask_cors import cross_origin

from cors import init_cors


@pytest.fixture(autouse=True)
def clear_cors_environment(monkeypatch):
    for name in (
        "CORS_ENABLED",
        "CORS_ALLOWED_ORIGINS",
        "CORS_ALLOWED_METHODS",
        "CORS_ALLOWED_HEADERS",
        "CORS_EXPOSED_HEADERS",
        "CORS_ALLOW_CREDENTIALS",
        "CORS_MAX_AGE",
    ):
        monkeypatch.delenv(name, raising=False)


def create_test_app():
    app = Flask(__name__)

    @app.route("/api/test", methods=["GET", "OPTIONS"])
    def api_test():
        return {"status": "ok"}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    init_cors(app)
    return app


def test_disabled_cors_does_not_add_allow_origin(monkeypatch):
    monkeypatch.setenv("CORS_ENABLED", "FALSE")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://example.com")

    response = (
        create_test_app().test_client().get("/api/test", headers={"Origin": "https://example.com"})
    )

    assert "Access-Control-Allow-Origin" not in response.headers


def test_unset_cors_is_disabled(monkeypatch):
    monkeypatch.delenv("CORS_ENABLED", raising=False)
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://example.com")
    response = (
        create_test_app().test_client().get("/api/test", headers={"Origin": "https://example.com"})
    )
    assert "Access-Control-Allow-Origin" not in response.headers


def test_disabled_cors_does_not_add_preflight_headers(monkeypatch):
    monkeypatch.setenv("CORS_ENABLED", "FALSE")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://evil.example")
    response = (
        create_test_app()
        .test_client()
        .options(
            "/api/test",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "X-API-KEY",
            },
        )
    )
    assert not any(
        header.lower().startswith("access-control-") for header in response.headers.keys()
    )


def test_enabled_cors_without_origins_fails_closed(monkeypatch):
    monkeypatch.setenv("CORS_ENABLED", "TRUE")
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    response = (
        create_test_app().test_client().get("/api/test", headers={"Origin": "https://evil.example"})
    )
    assert "Access-Control-Allow-Origin" not in response.headers


def test_non_api_path_is_untouched(monkeypatch):
    monkeypatch.setenv("CORS_ENABLED", "TRUE")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://allowed.example")
    response = (
        create_test_app()
        .test_client()
        .get("/health", headers={"Origin": "https://allowed.example"})
    )
    assert "Access-Control-Allow-Origin" not in response.headers


def test_enabled_cors_allows_configured_origin(monkeypatch):
    monkeypatch.setenv("CORS_ENABLED", "TRUE")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://allowed.example")

    response = (
        create_test_app()
        .test_client()
        .get("/api/test", headers={"Origin": "https://allowed.example"})
    )

    assert response.headers["Access-Control-Allow-Origin"] == "https://allowed.example"


def test_enabled_cors_rejects_unlisted_origin(monkeypatch):
    monkeypatch.setenv("CORS_ENABLED", "TRUE")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://allowed.example")

    response = (
        create_test_app()
        .test_client()
        .get("/api/test", headers={"Origin": "https://unlisted.example"})
    )

    assert "Access-Control-Allow-Origin" not in response.headers


def create_decorated_blueprint():
    blueprint = Blueprint("tools", __name__)

    @blueprint.post("/tools/api/test")
    @cross_origin()
    def tool_test():
        # Like the production blueprints, authentication belongs to the view,
        # while Flask-CORS handles OPTIONS without entering the view.
        return {"status": "error", "message": "Authentication required"}, 401

    return blueprint


def create_decorated_app(blueprint=None):
    app = create_test_app()
    app.register_blueprint(blueprint or create_decorated_blueprint())
    return app


def request_tool(app, method, origin="https://allowed.example"):
    return app.test_client().open(
        "/tools/api/test",
        method=method,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-API-KEY, X-Unlisted",
        },
    )


def cors_headers(response):
    return {
        name: value
        for name, value in response.headers
        if name.lower().startswith("access-control-")
    }


@pytest.mark.parametrize("enabled", [None, "FALSE", "false", "", "1", "invalid"])
@pytest.mark.parametrize("method", ["POST", "OPTIONS"])
def test_decorated_route_denies_cors_unless_explicitly_enabled(monkeypatch, enabled, method):
    if enabled is not None:
        monkeypatch.setenv("CORS_ENABLED", enabled)
    # Keep a matching origin and credentials configured so neither can mask a
    # missing enable gate.
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://allowed.example")
    monkeypatch.setenv("CORS_ALLOW_CREDENTIALS", "TRUE")

    response = request_tool(create_decorated_app(), method)

    assert response.status_code == (200 if method == "OPTIONS" else 401)
    assert not cors_headers(response)
    if method == "POST":
        assert response.json["message"] == "Authentication required"


@pytest.mark.parametrize("origins", [None, "", "   ", " , , "])
@pytest.mark.parametrize("method", ["POST", "OPTIONS"])
def test_decorated_route_without_origins_fails_closed(monkeypatch, origins, method):
    monkeypatch.setenv("CORS_ENABLED", "TRUE")
    monkeypatch.setenv("CORS_ALLOW_CREDENTIALS", "TRUE")
    if origins is not None:
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", origins)

    response = request_tool(create_decorated_app(), method)

    assert response.status_code == (200 if method == "OPTIONS" else 401)
    assert not cors_headers(response)


@pytest.mark.parametrize("method", ["POST", "OPTIONS"])
def test_decorated_route_rejects_unlisted_origin(monkeypatch, method):
    monkeypatch.setenv("CORS_ENABLED", "TRUE")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://allowed.example")
    monkeypatch.setenv("CORS_ALLOW_CREDENTIALS", "TRUE")

    response = request_tool(create_decorated_app(), method, "https://unlisted.example")

    assert response.status_code == (200 if method == "OPTIONS" else 401)
    assert not cors_headers(response)


@pytest.mark.parametrize("credentials", ["TRUE", "FALSE"])
@pytest.mark.parametrize("method", ["POST", "OPTIONS"])
def test_decorated_route_uses_all_central_options(monkeypatch, credentials, method):
    monkeypatch.setenv("CORS_ENABLED", "true")
    monkeypatch.setenv(
        "CORS_ALLOWED_ORIGINS", " , https://allowed.example, https://other.example, "
    )
    monkeypatch.setenv("CORS_ALLOWED_METHODS", "GET, POST")
    monkeypatch.setenv("CORS_ALLOWED_HEADERS", "Content-Type, X-API-KEY")
    monkeypatch.setenv("CORS_EXPOSED_HEADERS", "X-Result")
    monkeypatch.setenv("CORS_ALLOW_CREDENTIALS", credentials)
    monkeypatch.setenv("CORS_MAX_AGE", "600")
    app = create_decorated_app()

    response = request_tool(app, method)

    assert response.status_code == (200 if method == "OPTIONS" else 401)
    assert response.headers["Access-Control-Allow-Origin"] == "https://allowed.example"
    assert response.headers["Access-Control-Expose-Headers"] == "X-Result"
    assert response.headers.get("Access-Control-Allow-Credentials") == (
        "true" if credentials == "TRUE" else None
    )
    assert "Origin" in response.vary
    if method == "OPTIONS":
        assert response.headers["Access-Control-Allow-Methods"] == "GET, POST"
        assert response.headers["Access-Control-Allow-Headers"] == "X-API-KEY"
        assert response.headers["Access-Control-Max-Age"] == "600"
        assert "POST" in response.allow
        assert "OPTIONS" in response.allow

        central_response = app.test_client().options(
            "/api/test",
            headers={
                "Origin": "https://allowed.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-API-KEY, X-Unlisted",
            },
        )
        assert cors_headers(response) == cors_headers(central_response)


def test_decorated_blueprint_uses_each_apps_policy(monkeypatch):
    # Blueprints are imported once, before app creation. Reusing one must not
    # capture the first app's settings or leak an enabled app's policy to another.
    blueprint = create_decorated_blueprint()
    monkeypatch.setenv("CORS_ENABLED", "TRUE")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://allowed.example")
    allowed_app = create_decorated_app(blueprint)
    monkeypatch.setenv("CORS_ENABLED", "FALSE")
    denied_app = create_decorated_app(blueprint)

    assert not cors_headers(request_tool(denied_app, "POST"))
    assert request_tool(allowed_app, "POST").headers["Access-Control-Allow-Origin"] == (
        "https://allowed.example"
    )


@pytest.mark.parametrize("enabled", ["FALSE", "TRUE"])
@pytest.mark.parametrize("method", ["POST", "OPTIONS"])
def test_oitracker_blueprint_respects_policy_without_bypassing_auth(monkeypatch, enabled, method):
    # Import the real blueprint and session decorator, isolating only database
    # and broker services. Neither OPTIONS nor unauthenticated POST may use them.
    def unexpected_service_call(*args, **kwargs):
        pytest.fail(
            "Preflight and unauthenticated requests must not reach broker/database services"
        )

    auth_db = ModuleType("database.auth_db")
    auth_db.get_api_key_for_tradingview = unexpected_service_call
    service = ModuleType("services.oi_tracker_service")
    service.calculate_max_pain = unexpected_service_call
    service.get_oi_data = unexpected_service_call
    monkeypatch.setitem(sys.modules, "database.auth_db", auth_db)
    monkeypatch.setitem(sys.modules, "services.oi_tracker_service", service)
    path = Path(__file__).resolve().parents[1] / "blueprints" / "oitracker.py"
    spec = importlib.util.spec_from_file_location("cors_test_oitracker", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    monkeypatch.setenv("CORS_ENABLED", enabled)
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://allowed.example")
    app = create_test_app()
    app.config["SECRET_KEY"] = "test-only-cors-key"
    app.register_blueprint(module.oitracker_bp)

    for endpoint in ("/oitracker/api/oi-data", "/oitracker/api/maxpain"):
        response = app.test_client().open(
            endpoint,
            method=method,
            json={},
            headers={
                "Origin": "https://allowed.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == (200 if method == "OPTIONS" else 401)
        if method == "POST":
            assert response.json["error"] == "session_expired"
        if enabled == "TRUE":
            assert response.headers["Access-Control-Allow-Origin"] == "https://allowed.example"
        else:
            assert not cors_headers(response)
