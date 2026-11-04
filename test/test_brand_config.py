"""Per-instance brand override: /brand-config.js and /custom-brand/<file>."""

import json

import pytest
from flask import Flask

import blueprints.react_app as react_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(react_app, "CUSTOM_BRAND_DIR", tmp_path)
    app = Flask(__name__)
    app.register_blueprint(react_app.react_bp)
    return app.test_client(), tmp_path


def _override(response):
    body = response.get_data(as_text=True)
    prefix = "window.__FASTALGO_BRAND__ = "
    assert body.startswith(prefix)
    return json.loads(body[len(prefix) :].rstrip().rstrip(";"))


def test_no_override_serves_empty_object(client):
    c, _ = client
    response = c.get("/brand-config.js")
    assert response.status_code == 200
    assert response.mimetype == "application/javascript"
    assert response.headers["Cache-Control"] == "no-cache"
    assert _override(response) == {}


def test_display_name_and_existing_logo_are_exposed(client):
    c, brand_dir = client
    (brand_dir / "sharma.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (brand_dir / "brand.json").write_text(
        json.dumps({"displayName": "  Sharma Capital ", "logo": "sharma.png"}), encoding="utf-8"
    )
    assert _override(c.get("/brand-config.js")) == {
        "displayName": "Sharma Capital",
        "logoUrl": "/custom-brand/sharma.png",
    }
    logo = c.get("/custom-brand/sharma.png")
    assert logo.status_code == 200
    logo.close()


def test_missing_logo_is_not_advertised(client):
    # A logo URL that 404s on the login page would count toward an IP ban.
    c, brand_dir = client
    (brand_dir / "brand.json").write_text(json.dumps({"logo": "gone.png"}), encoding="utf-8")
    assert _override(c.get("/brand-config.js")) == {}


def test_logo_path_cannot_leave_the_brand_directory(client):
    c, brand_dir = client
    (brand_dir / "brand.json").write_text(
        json.dumps({"logo": "../../etc/passwd.png"}), encoding="utf-8"
    )
    assert _override(c.get("/brand-config.js")) == {}


def test_non_image_files_are_not_served(client):
    c, brand_dir = client
    (brand_dir / "brand.json").write_text("{}", encoding="utf-8")
    assert c.get("/custom-brand/brand.json").status_code == 404


def test_malformed_json_falls_back_to_default(client):
    c, brand_dir = client
    (brand_dir / "brand.json").write_text("{not json", encoding="utf-8")
    assert _override(c.get("/brand-config.js")) == {}


def test_long_display_name_is_capped(client):
    c, brand_dir = client
    (brand_dir / "brand.json").write_text(json.dumps({"displayName": "x" * 200}), encoding="utf-8")
    assert len(_override(c.get("/brand-config.js"))["displayName"]) == 60


def test_telegram_contact_is_exposed(client):
    c, brand_dir = client
    (brand_dir / "brand.json").write_text(
        json.dumps({"supportTelegramUrl": " https://t.me/SharmaDesk "}), encoding="utf-8"
    )
    assert _override(c.get("/brand-config.js")) == {"supportTelegramUrl": "https://t.me/SharmaDesk"}


@pytest.mark.parametrize(
    "bad",
    [
        "http://t.me/SharmaDesk",
        "https://t.me/abc",
        "https://t.me.evil.example/SharmaDesk",
        "https://evil.example/t.me/SharmaDesk",
        "https://t.me/SharmaDesk/extra",
        "javascript:alert(1)",
        42,
    ],
)
def test_telegram_contact_rejects_anything_but_a_username_link(client, bad):
    c, brand_dir = client
    (brand_dir / "brand.json").write_text(json.dumps({"supportTelegramUrl": bad}), encoding="utf-8")
    assert _override(c.get("/brand-config.js")) == {}


def test_telegram_contact_defaults_without_an_override(tmp_path, monkeypatch):
    from utils import brand

    monkeypatch.setattr(brand, "CUSTOM_BRAND_DIR", tmp_path)
    assert brand.support_telegram_url() == "https://t.me/RanjT55"
    (tmp_path / "brand.json").write_text(
        json.dumps({"supportTelegramUrl": "https://t.me/SharmaDesk"}), encoding="utf-8"
    )
    assert brand.support_telegram_url() == "https://t.me/SharmaDesk"
