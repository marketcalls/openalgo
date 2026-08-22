from flask import Flask

from cors import init_cors


def create_test_app():
    app = Flask(__name__)

    @app.get("/api/test")
    def api_test():
        return {"status": "ok"}

    init_cors(app)
    return app


def test_disabled_cors_does_not_add_allow_origin(monkeypatch):
    monkeypatch.setenv("CORS_ENABLED", "FALSE")
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)

    response = (
        create_test_app().test_client().get("/api/test", headers={"Origin": "https://example.com"})
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
