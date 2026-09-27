"""Caching of the /trading chart's custom indicator modules.

A folder of hundreds of user indicators made every page reload fetch every
module again. The chart asks for each module at ``?v=<mtime>``, so the bytes
behind a versioned URL never change and the browser may keep them for good,
while the index that lists the files must always be revalidated or a new or
edited indicator would stay hidden.
"""

import sys

import pytest


@pytest.fixture
def indicators_client(monkeypatch, tmp_path):
    """The blueprint alone, with the session check lifted and a temporary folder."""
    import utils.session as us

    monkeypatch.setattr(us, "check_session_validity", lambda f: f)
    for module in list(sys.modules):
        if module == "blueprints.custom_indicators":
            del sys.modules[module]

    from flask import Flask

    import blueprints.custom_indicators as bp_module

    folder = tmp_path / "indicators"
    folder.mkdir()
    (folder / "demo.js").write_text("export default () => {}\n", encoding="utf-8")
    monkeypatch.setattr(bp_module, "INDICATORS_DIR", folder)

    app = Flask(__name__)
    app.register_blueprint(bp_module.custom_indicators_bp)
    yield app.test_client()
    for module in list(sys.modules):
        if module == "blueprints.custom_indicators":
            del sys.modules[module]


def test_a_versioned_module_is_cacheable_for_good(indicators_client):
    res = indicators_client.get("/custom-indicators/demo.js?v=1700000000")
    assert res.status_code == 200
    assert res.headers["Cache-Control"] == "private, max-age=31536000, immutable"
    assert res.mimetype == "text/javascript"


def test_an_unversioned_module_is_revalidated(indicators_client):
    res = indicators_client.get("/custom-indicators/demo.js")
    assert res.status_code == 200
    assert res.headers["Cache-Control"] == "no-cache"


def test_the_index_is_always_revalidated(indicators_client):
    res = indicators_client.get("/custom-indicators/index.json")
    assert res.status_code == 200
    assert res.headers["Cache-Control"] == "no-cache"
    assert [m["file"] for m in res.get_json()] == ["demo.js"]
