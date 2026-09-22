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

The second half of this file is about the compiled program stored beside a
source, and one property runs through all of it: **a runner must never find a
program that is not the program of the source lying next to it.** A stale
program is not a wrong picture on a chart, it is instructions executing that the
trader can no longer read the source of, so the tests below go after every way
one could come to be there: a save that leaves the old one, a client that sends
a program built from other text, and a write that dies between the two files.
"""

import json
import os
from pathlib import Path

import pytest
from flask import Blueprint, Flask

import blueprints.openscript as openscript
import utils.session
from blueprints.openscript import openscript_bp

SOURCE = 'version 1\nstudy("Range", overlay = true)\nplot(close, "C", aqua)\n'

# A second source, so a program can be put beside text it was not built from.
OTHER = 'version 1\nstudy("Range", overlay = true)\nplot(open, "O", aqua)\n'

# The compiled program for SOURCE, in the canonical encoding, as the compiler in
# the browser produces it. A real one rather than a hand written stand in,
# because two of the tests below are about bytes: the canonical encoding is what
# a program's hash is taken over and what an engine loading a program from text
# insists on, so a route that parsed this and wrote it back out would store
# something no engine would accept. Split across lines only to fit the page;
# joined it is the exact text.
PROGRAM_TEXT = (
    '{"callSites":[],"cells":[],"channels":[{"defer":false,"id":0,"once":true,"type":"numbe'
    'r"}],"code":[["SLOAD",0],["EMIT",0],["HALT"]],"compiler":{"name":"openscript","version'
    '":"0.4.0"},"consts":[["z",null],["b",false],["b",true]],"debug":{"fnPos":[],"names":{"'
    'cells":[],"channels":["C"],"series":["close"],"slots":[]},"pos":[[0,3,6],[1,3,1]],"ret'
    'ain":false},"frame":{"slots":0},"functions":[],"inputs":[],"lib":{"functions":[],"mani'
    'fest":1},"limits":{"history":null,"loops":2000000},"loops":[],"meta":{"format":"price"'
    ',"group":"","kind":"study","onUnconfirmed":false,"overlay":true,"precision":4,"range":'
    'null,"scale":"right","short":"Range","title":"Range"},"openscript":{"format":"1.1","la'
    'nguage":1},"outputs":{"alerts":[],"background":null,"barColor":null,"fills":[],"levels'
    '":[],"markers":[],"plots":[{"channel":0,"color":[0,255,255,1],"colorChannel":null,"key'
    '":"p0","lineStyle":"solid","offset":0,"ohlc":null,"overlay":null,"precision":null,"pri'
    'ceFormat":null,"scale":"right","title":"C","type":"line","width":1.5}],"tables":[]},"r'
    'equests":[],"requires":["core.1"],"series":[{"field":"close","id":0,"kind":"bar","name'
    '":"close"}],"source":{"file":"range.oscript","hash":"sha256:b83cb38049d524a96450b47634'
    'e4519832a6c6638bbd59342d31d7622df95f0b","lines":4},"states":[]}'
)


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
        guarded.get("/openscript/program/range.oscript"),
        guarded.post("/openscript/range.oscript", json={"source": SOURCE}),
        guarded.delete("/openscript/range.oscript"),
    ):
        assert response.status_code in (302, 401)
    assert not (Path(scripts) / "range.oscript").exists()


def _program_file(scripts, name="range.oscript"):
    """The file the route writes a compiled program to, named from the source."""
    return scripts / (name + ".program.json")


def test_a_saved_program_comes_back_byte_for_byte(client, scripts):
    """The bytes are the artifact, so nothing here may re-encode them.

    Catches the obvious implementation, parsing the program and writing it back
    out with the platform's own JSON writer. That produces different bytes for
    the same program: different spacing, a different order of keys, a different
    spelling of a number. The hash a host records is taken over the canonical
    bytes and an engine that loads a program from text refuses text that is not
    that encoding, so the re-encoded program would be refused at load, for a
    difference this route introduced and nobody could see.
    """
    saved = client.post(
        "/openscript/range.oscript", json={"source": SOURCE, "program": PROGRAM_TEXT}
    )

    assert saved.status_code == 200
    assert saved.get_json()["program"] is True
    assert _program_file(scripts).read_bytes() == PROGRAM_TEXT.encode("utf-8")

    fetched = client.get("/openscript/program/range.oscript")
    assert fetched.status_code == 200
    assert fetched.get_data() == PROGRAM_TEXT.encode("utf-8")


def test_a_program_is_never_served_as_a_module(client):
    """The same safety assertion the source route carries, for the other file.

    Catches a route that reached for a JavaScript type so the page could
    ``import()`` the program directly. A response the page can import runs with
    the page's authority, which is the whole thing compiling to data avoids, and
    the program is the more tempting of the two files to reach for because it is
    already JSON.
    """
    client.post("/openscript/range.oscript", json={"source": SOURCE, "program": PROGRAM_TEXT})
    fetched = client.get("/openscript/program/range.oscript")

    assert "javascript" not in fetched.headers["Content-Type"].lower()
    assert "ecmascript" not in fetched.headers["Content-Type"].lower()
    assert fetched.mimetype == "application/json"


def test_the_hash_a_program_records_is_the_one_this_route_computes(client, scripts):
    """The route has no compiler, so this is how it knows the two belong together.

    The compiler stamps the hash of the source into the program. This route
    recomputes it and compares, and the comparison is only as good as the
    normalisation behind it, which is the language's rule and not this
    platform's: a leading byte order mark is not part of the text and neither is
    the carriage return before a newline.

    Catches hashing the bytes as they arrived. A trader whose editor ends lines
    with a carriage return would then be refused on every save that carried a
    program, with a message telling them the program was built from different
    text, which it was not.
    """
    assert json.loads(PROGRAM_TEXT)["source"]["hash"] == openscript._source_hash(SOURCE)

    carriage_returns = SOURCE.replace("\n", "\r\n")
    saved = client.post(
        "/openscript/range.oscript", json={"source": carriage_returns, "program": PROGRAM_TEXT}
    )
    assert saved.status_code == 200
    assert _program_file(scripts).read_bytes() == PROGRAM_TEXT.encode("utf-8")

    byte_order_mark = client.post(
        "/openscript/mark.oscript", json={"source": "\ufeff" + SOURCE, "program": PROGRAM_TEXT}
    )
    assert byte_order_mark.status_code == 200


def test_a_program_built_from_different_text_is_refused_and_changes_nothing(client, scripts):
    """The state this whole design exists to prevent, arriving from the client.

    Catches a route that stores whatever it is handed. A page holding a stale
    editor buffer, or a second tab saving over the first, would leave a runner
    walking instructions compiled from text that is no longer on the disk: the
    trader reads one strategy and the server runs another.
    """
    client.post("/openscript/range.oscript", json={"source": SOURCE, "program": PROGRAM_TEXT})

    refused = client.post(
        "/openscript/range.oscript", json={"source": OTHER, "program": PROGRAM_TEXT}
    )

    assert refused.status_code == 400
    assert (scripts / "range.oscript").read_text(encoding="utf-8") == SOURCE
    assert _program_file(scripts).read_bytes() == PROGRAM_TEXT.encode("utf-8")


def test_a_save_with_no_program_takes_the_stored_one_with_it(client, scripts):
    """The deliberate decision, and the reason it is not the other one.

    A trader edits a working script into one that does not compile and saves it,
    which they are entitled to do. The source on the disk is now the new one.

    Catches writing the program only when a save carries one, which reads as the
    conservative choice and is the dangerous one: it leaves yesterday's program
    beside today's source, and a runner reading that pair executes a strategy
    whose source nobody can see any more. Gone is the only state that cannot
    mislead, and it costs one recompile.
    """
    client.post("/openscript/range.oscript", json={"source": SOURCE, "program": PROGRAM_TEXT})
    assert _program_file(scripts).exists()

    saved = client.post("/openscript/range.oscript", json={"source": OTHER})

    assert saved.status_code == 200
    assert saved.get_json()["program"] is False
    assert (scripts / "range.oscript").read_text(encoding="utf-8") == OTHER
    assert not _program_file(scripts).exists()
    assert client.get("/openscript/program/range.oscript").status_code == 404


def test_a_script_that_does_not_compile_is_still_saved(client, scripts):
    """Being half way through a thought is not a reason to lose it.

    Catches making the program mandatory, which is the natural reading of "a
    program that does not compile must not be stored" and is the wrong one: it
    turns the compiler into a gate on the editor's save key and loses work that
    was never going to run anyway.
    """
    saved = client.post("/openscript/draft.oscript", json={"source": "version 1\n"})

    assert saved.status_code == 200
    assert saved.get_json()["program"] is False
    assert (scripts / "draft.oscript").read_text(encoding="utf-8") == "version 1\n"

    listed = client.get("/openscript/index.json").get_json()
    assert [entry["program"] for entry in listed] == [False]


def test_something_that_is_not_a_program_is_refused_and_nothing_is_written(client, scripts):
    """The route stores data, so it checks that what arrived is data.

    It cannot check much: whether a program is correct, or canonical, or means
    what the source says is the engine's work, done when the program is loaded.
    It can check that the thing parses and is a JSON object carrying the source
    stamp every compiled program has, which is what separates a program from a
    note somebody pasted.

    Catches writing the body straight to the file. The bad state that produces
    is quiet: the listing says the script is runnable, a runner picks it up, and
    the failure surfaces at the moment somebody expected a position.

    The last two bodies are refused by the hash comparison as much as by the
    shape check, because a stamp that is not there cannot match. The separate
    check earns its place on the message rather than on the refusal: "this is
    not a compiled program" and "this program was built from different text"
    send a reader to two different places, and only one of them is right.
    """
    for body in (
        {"source": SOURCE, "program": 7},
        {"source": SOURCE, "program": "not a program at all"},
        {"source": SOURCE, "program": "[]"},
        {"source": SOURCE, "program": '{"openscript": {"format": "1.1", "language": 1}}'},
        {"source": SOURCE, "program": '{"source": {"lines": 4}}'},
        # JSON nested thousands deep is not a compiled program either, and the
        # reader says so by running out of stack rather than by refusing. It is
        # in this list because an uncaught one costs the request on a worker
        # there is only one of.
        {"source": SOURCE, "program": "[" * 20000 + "]" * 20000},
    ):
        refused = client.post("/openscript/range.oscript", json=body)
        assert refused.status_code == 400, body["program"]

    assert sorted(entry.name for entry in scripts.iterdir()) == []


def test_a_program_past_the_limit_is_refused_and_changes_nothing(client, scripts):
    """The ceiling is a request body limit and a latency one, and it is checked first.

    Catches a size check placed after the write, or left off the program
    entirely: the source is capped at 256 kB because the smallest deployment
    leaves the web server's body limit at its default, and a program several
    times the size of its source travelling in the same body would reach that
    limit and come back as a gateway error with no sentence in it.
    """
    client.post("/openscript/range.oscript", json={"source": SOURCE, "program": PROGRAM_TEXT})

    too_big = "x" * (openscript.MAX_PROGRAM_BYTES + 1)
    refused = client.post("/openscript/range.oscript", json={"source": SOURCE, "program": too_big})

    assert refused.status_code == 413
    assert str(openscript.MAX_PROGRAM_BYTES) in refused.get_json()["message"]
    assert _program_file(scripts).read_bytes() == PROGRAM_TEXT.encode("utf-8")


def test_a_write_that_dies_between_the_two_files_leaves_no_stale_program(
    client, scripts, monkeypatch
):
    """The reason the program is removed before the source is replaced.

    The source lands and the program does not. Catches the straightforward
    order, replacing the source and then the program: on this failure that
    leaves the new source sitting beside the program of the old one, which is
    the exact pair a runner must never be handed. Removing the program first
    makes every state a crash can leave a source with no program, which means
    not runnable and is never wrong.
    """
    client.post("/openscript/range.oscript", json={"source": SOURCE, "program": PROGRAM_TEXT})

    real_replace = os.replace
    done = []

    def die_on_the_second(source, target):
        done.append(target)
        if len(done) == 1:
            return real_replace(source, target)
        raise OSError("the disk went away")

    monkeypatch.setattr(os, "replace", die_on_the_second)
    failed = client.post(
        "/openscript/range.oscript", json={"source": SOURCE, "program": PROGRAM_TEXT}
    )

    assert failed.status_code == 500
    assert (scripts / "range.oscript").read_text(encoding="utf-8") == SOURCE
    assert not _program_file(scripts).exists()
    assert [p.name for p in scripts.iterdir() if p.suffix == ".partial"] == []


def test_deleting_a_script_takes_its_program(client, scripts):
    """A program with no source is the one file here something might still run.

    Catches a delete written against the two files that existed before the
    program did. What it leaves behind is worse than a stray file: a compiled
    strategy, on the disk, with no source anybody can read to find out what it
    does, under the name of a script the trader believes they deleted.
    """
    client.post("/openscript/range.oscript", json={"source": SOURCE, "program": PROGRAM_TEXT})
    assert _program_file(scripts).exists()

    removed = client.delete("/openscript/range.oscript")

    assert removed.status_code == 200
    assert not _program_file(scripts).exists()
    assert sorted(entry.name for entry in scripts.iterdir()) == []


def test_the_listing_says_which_scripts_have_a_program(client, scripts):
    """What a runner reads to find its work, and what a panel reads to say so.

    Catches a listing left as it was, which leaves the only way to find out
    whether a script can run a request per script, and catches a program file
    listed as though it were a source of its own.
    """
    client.post("/openscript/ready.oscript", json={"source": SOURCE, "program": PROGRAM_TEXT})
    client.post("/openscript/draft.oscript", json={"source": "version 1\n"})

    listed = client.get("/openscript/index.json").get_json()

    assert [entry["file"] for entry in listed] == ["draft.oscript", "ready.oscript"]
    assert [entry["program"] for entry in listed] == [False, True]


@pytest.mark.parametrize(
    "name",
    [
        "../../secrets.env",
        "..%2Fescape.oscript",
        "sub/dir.oscript",
        "range.oscript.program.json",
        "indicator.js",
        ".hidden.oscript",
        "x" * 80 + ".oscript",
    ],
)
def test_a_name_the_program_route_does_not_own_is_refused(client, name):
    """A route added later is a name check somebody has to remember to add.

    Refused as a bad name, which is what the status and the sentence pin here
    rather than merely "the response was not a program". ``send_from_directory``
    will not climb out of the directory whatever it is handed, so a route
    written without the check still answers safely, and answers that there is
    nothing there: a trader reading that goes looking for a missing script when
    the name was the thing wrong, and a reviewer reading the test sees a guard
    that was never being exercised.
    """
    refused = client.get(f"/openscript/program/{name}")

    assert refused.status_code == 400
    assert "Invalid script name" in refused.get_json()["message"]


def test_a_program_is_not_a_name_the_source_routes_own(client, scripts):
    """The file this module names for itself is not a file a caller may name.

    The program's name is derived here from a source name that has already been
    through ``_SAFE_NAME``, and the suffix keeps it outside that pattern, so the
    routes that take a name off the wire all refuse it. Catches relaxing the
    pattern to admit the new file, which would let a caller write a program
    directly, under any source's name, without a compile anywhere in it.
    """
    client.post("/openscript/range.oscript", json={"source": SOURCE, "program": PROGRAM_TEXT})
    name = "range.oscript.program.json"

    assert client.get(f"/openscript/{name}").status_code == 400
    assert client.post(f"/openscript/{name}", json={"source": SOURCE}).status_code == 400
    assert client.delete(f"/openscript/{name}").status_code == 400
    assert _program_file(scripts).read_bytes() == PROGRAM_TEXT.encode("utf-8")


def test_a_script_with_no_program_says_so_in_a_sentence(client):
    """A trader reads this, so it names the script and the next thing to do.

    Catches an empty body or a bare refusal. Someone who has just asked why
    their strategy is not running needs to be told that it has never compiled
    cleanly and what to do about it, not handed nothing.
    """
    client.post("/openscript/range.oscript", json={"source": SOURCE})

    answer = client.get("/openscript/program/range.oscript")

    assert answer.status_code == 404
    message = answer.get_json()["message"]
    assert "range.oscript" in message
    assert "save" in message.lower()
