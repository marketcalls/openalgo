"""The route that stores and serves the trader's OpenScript sources.

These drive the real blueprint through a real Flask client and assert on
responses, never on the presence of a decorator. Two of them are about safety
rather than behaviour and are the reason this file exists at all:

- a source is served as ``text/plain`` and never as a JavaScript type, because a
  response the page could ``import()`` would execute in the page with the page's
  own authority, which is exactly what compiling to data avoids;
- a name that climbs out of the directory is refused before anything touches the
  filesystem.

The write is atomic, and there is a test for the failure that makes it worth
being atomic: a replace that dies partway leaves the previous script whole.
"""

import os
from pathlib import Path

import pytest
from flask import Blueprint, Flask

import blueprints.openscript as openscript
import utils.session
from blueprints.openscript import openscript_bp

SOURCE = 'version 1\nstudy("Range", overlay = true)\nplot(close, "C", aqua)\n'


@pytest.fixture
def scripts(tmp_path, monkeypatch):
    """Point the blueprint at a directory this test owns."""
    directory = tmp_path / "strategies" / "openscript"
    directory.mkdir(parents=True)
    monkeypatch.setattr(openscript, "SCRIPTS_DIR", directory)
    return directory


@pytest.fixture
def client(scripts, monkeypatch):
    """A minimal app carrying the real blueprint, with a session that is valid.

    ``check_session_validity`` is applied at import, so the decorator cannot be
    replaced here. It resolves ``is_session_valid`` from its own module at call
    time, which is the seam: the real decorator still runs, and still refuses
    when the session is not valid, which is what the last test below relies on.
    """
    monkeypatch.setattr(utils.session, "is_session_valid", lambda: True)
    application = Flask(__name__)
    application.config["TESTING"] = True
    application.secret_key = "test-only"
    application.register_blueprint(openscript_bp)
    return application.test_client()


def test_a_saved_script_comes_back_exactly(client, scripts):
    saved = client.post("/openscript/range.oscript", json={"source": SOURCE})
    assert saved.status_code == 200
    assert saved.get_json()["bytes"] == len(SOURCE.encode("utf-8"))

    fetched = client.get("/openscript/range.oscript")
    assert fetched.status_code == 200
    assert fetched.get_data(as_text=True) == SOURCE
    assert (scripts / "range.oscript").read_text(encoding="utf-8") == SOURCE


def test_a_source_is_never_served_as_a_module(client):
    """The security-relevant assertion, and the reason for the explicit mimetype.

    Catches a route that reached for ``text/javascript`` to match the indicator
    route beside it. That response is importable, and a page that can import a
    trader's file has handed it the page's own authority, which is the whole
    thing the compiled program format exists to prevent.
    """
    client.post("/openscript/range.oscript", json={"source": SOURCE})
    fetched = client.get("/openscript/range.oscript")

    assert fetched.mimetype == "text/plain"
    assert "javascript" not in fetched.headers["Content-Type"].lower()
    assert "ecmascript" not in fetched.headers["Content-Type"].lower()


@pytest.mark.parametrize(
    "name",
    [
        "../../secrets.env",
        "..%2Fescape.oscript",
        "sub/dir.oscript",
        "indicator.js",
        "script.oscript.js",
        ".hidden.oscript",
        "",
        "x" * 80 + ".oscript",
    ],
)
def test_a_name_this_route_does_not_own_is_refused(client, scripts, name):
    """Refused for reading, writing and deleting alike, and nothing is written.

    Catches a check placed on the read route only, which is where the traversal
    would be least useful to an attacker and most obvious to a reviewer.
    """
    assert client.get(f"/openscript/{name}").status_code in (400, 404, 308)
    assert client.post(f"/openscript/{name}", json={"source": SOURCE}).status_code in (
        400,
        404,
        308,
    )
    assert client.delete(f"/openscript/{name}").status_code in (400, 404, 308)
    assert sorted(p.name for p in scripts.iterdir()) == []


def test_the_listing_shows_only_scripts(client, scripts):
    # Written as bytes rather than text: this platform translates a newline on
    # the way out, which would make the reported size disagree with the source
    # for a reason that has nothing to do with the route.
    (scripts / "one.oscript").write_bytes(SOURCE.encode("utf-8"))
    (scripts / "two.oscript").write_bytes(SOURCE.encode("utf-8"))
    (scripts / "notes.txt").write_bytes(b"not a script")
    (scripts / "indicator.js").write_bytes(b"export default () => {}")
    (scripts / "one.oscript.bak").write_bytes(b"older")

    listed = client.get("/openscript/index.json").get_json()

    assert [entry["file"] for entry in listed] == ["one.oscript", "two.oscript"]
    assert all(entry["bytes"] == len(SOURCE.encode("utf-8")) for entry in listed)
    assert all(isinstance(entry["mtime"], int) for entry in listed)


def test_saving_over_a_script_keeps_what_was_there(client, scripts):
    client.post("/openscript/range.oscript", json={"source": SOURCE})
    client.post("/openscript/range.oscript", json={"source": 'version 1\nstudy("Two")\n'})

    assert (scripts / "range.oscript.bak").read_text(encoding="utf-8") == SOURCE


def test_a_script_past_the_limit_is_refused_and_changes_nothing(client, scripts):
    client.post("/openscript/range.oscript", json={"source": SOURCE})

    too_big = "x" * (openscript.MAX_SOURCE_BYTES + 1)
    refused = client.post("/openscript/range.oscript", json={"source": too_big})

    assert refused.status_code == 413
    assert str(openscript.MAX_SOURCE_BYTES) in refused.get_json()["message"]
    assert (scripts / "range.oscript").read_text(encoding="utf-8") == SOURCE


def test_a_body_with_no_source_is_refused(client):
    assert client.post("/openscript/range.oscript", json={}).status_code == 400
    assert client.post("/openscript/range.oscript", json={"source": 7}).status_code == 400
    assert client.post("/openscript/range.oscript", data="raw").status_code == 400


def test_a_write_that_dies_partway_leaves_the_previous_script_whole(client, scripts, monkeypatch):
    """The reason the write goes through a temporary file at all.

    Catches the straightforward implementation, opening the target and writing
    into it, which on this failure leaves a truncated or empty script where a
    working one used to be.
    """
    client.post("/openscript/range.oscript", json={"source": SOURCE})

    def die(*args, **kwargs):
        raise OSError("the disk went away")

    monkeypatch.setattr(os, "replace", die)
    failed = client.post("/openscript/range.oscript", json={"source": "version 1\n"})

    assert failed.status_code == 500
    assert (scripts / "range.oscript").read_text(encoding="utf-8") == SOURCE
    assert [p.name for p in scripts.iterdir() if p.suffix == ".partial"] == []


def test_a_failed_wrap_still_closes_the_descriptor(client, scripts, monkeypatch):
    """Production is one worker that never restarts, so a leaked descriptor is forever.

    ``mkstemp`` hands back a raw descriptor and ``fdopen`` is what takes
    ownership of it, so the window between them is the only place a failure
    leaks one. Catches the obvious spelling, wrapping the descriptor inside the
    try that unlinks the temporary file, which cleans up the file and leaves the
    descriptor open.
    """
    client.post("/openscript/range.oscript", json={"source": SOURCE})

    closed = []
    real_close = os.close
    monkeypatch.setattr(os, "close", lambda fd: (closed.append(fd), real_close(fd))[1])

    def refuse_to_wrap(*args, **kwargs):
        raise OSError("out of file handles")

    monkeypatch.setattr(os, "fdopen", refuse_to_wrap)
    failed = client.post("/openscript/range.oscript", json={"source": "version 1\n"})

    assert failed.status_code == 500
    assert closed, "the descriptor mkstemp returned was never closed"
    assert (scripts / "range.oscript").read_text(encoding="utf-8") == SOURCE
    assert [p.name for p in scripts.iterdir() if p.suffix == ".partial"] == []


def test_deleting_takes_the_backup_with_it(client, scripts):
    client.post("/openscript/range.oscript", json={"source": SOURCE})
    client.post("/openscript/range.oscript", json={"source": "version 1\n"})
    assert (scripts / "range.oscript.bak").exists()

    removed = client.delete("/openscript/range.oscript")

    assert removed.status_code == 200
    assert not (scripts / "range.oscript").exists()
    assert not (scripts / "range.oscript.bak").exists()
    assert client.delete("/openscript/range.oscript").status_code == 200


def test_a_missing_directory_lists_nothing_rather_than_failing(client, scripts):
    for entry in scripts.iterdir():
        entry.unlink()
    scripts.rmdir()

    assert client.get("/openscript/index.json").get_json() == []


def test_every_route_is_behind_the_session_guard(scripts, monkeypatch):
    """No route here is reachable without a session.

    Driven rather than read off the source, because a decorator that is present
    but applied under a name the route does not use would pass a source-level
    check and fail this.
    """
    monkeypatch.setattr(utils.session, "is_session_valid", lambda: False)
    monkeypatch.setattr(utils.session, "revoke_user_tokens", lambda: None)
    application = Flask(__name__)
    application.config["TESTING"] = True
    application.secret_key = "test-only"
    application.register_blueprint(openscript_bp)

    # The guard redirects a plain request to `auth.login`, so that endpoint has
    # to exist for the redirect to build. Registering it here rather than
    # sending JSON headers keeps both of the guard's two answers in play: a
    # fetch gets 401 and a plain navigation gets the redirect.
    auth = Blueprint("auth", __name__)
    auth.add_url_rule("/login", "login", lambda: "login")
    application.register_blueprint(auth)

    guarded = application.test_client()

    for response in (
        guarded.get("/openscript/index.json"),
        guarded.get("/openscript/range.oscript"),
        guarded.post("/openscript/range.oscript", json={"source": SOURCE}),
        guarded.delete("/openscript/range.oscript"),
    ):
        assert response.status_code in (302, 401)
    assert not (Path(scripts) / "range.oscript").exists()
