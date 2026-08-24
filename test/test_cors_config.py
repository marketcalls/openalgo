from flask import Flask

from cors import init_cors


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
