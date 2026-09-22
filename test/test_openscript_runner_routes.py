"""The routes that start, stop, report, configure and schedule an OpenScript strategy.

These drive the real blueprint through a real test client over the real routes.

**Why this file is shaped the way it is.** The version before it passed with
thirty seven green tests against a blueprint whose status and stop routes could
not work: the blueprint resolved the service by trying a list of plausible
function names and taking the first one that existed, the list for reading state
matched nothing the service defines, and the stand in these tests used happened
to answer to the guessed names. So the tests agreed with the guess and the
service disagreed with both, and the failure was invisible until a strategy was
running and could not be stopped. Two rules come out of that, and they are what
most of the machinery below is for:

- **The routes import the service by name, and one test asserts the functions
  the blueprint holds are the service's own objects.** A name that is not there
  is an import error at startup rather than a route that answers with a polite
  refusal forever.
- **Every stand in is pinned to the real thing with ``inspect.signature``.** A
  stand in that has drifted from the module it stands in for fails on
  construction, before it can make a route look like it works. For the strategy
  host, which is a module rather than a set of functions, the check is that
  every attribute this blueprint reads is there and that every call it makes
  binds against the real one.
- **The real service is exercised.** Two tests below use no stand in at all:
  one drives a start and a stop through the real service and a real child
  process, and one proves a start with nothing saved against the script is
  refused by the real settings store, in the real sentence.

Three properties then run through the rest of the file, and each is a way
somebody loses money rather than a way a response looks wrong:

- **A start answers with an identifier and never with a result.** The
  deployment gives a request five minutes and buffers the response, so a route
  that waited for a run would time out with the strategy still trading and the
  operator told nothing.
- **A name this runner does not own never reaches the part that opens
  processes.** There is a real script one directory above the scripts folder in
  these tests, so a check that is absent has something to find.
- **A stop is never reported as success unless something was stopped.** An
  operator pressing stop believes a strategy is on the market. Telling them it
  was stopped when nothing was running is the one answer that leaves them wrong
  about a live position.
"""

import inspect
import json
from datetime import datetime
from pathlib import Path

import pytest
from flask import Blueprint, Flask

import blueprints.openscript as openscript
import blueprints.openscript_runner as runner
import services.openscript_run_config as settings_store
import services.openscript_runner_service as service
import utils.session
from blueprints.openscript import openscript_bp
from blueprints.openscript_runner import openscript_runner_bp

SOURCE = 'version 1\nstudy("Range", overlay = true)\nplot(close, "C", aqua)\n'

# A stand in for the compiled program. Nothing here reads it: the runner only
# asks whether one is there, because a source with no program beside it is a
# script nothing on this server can run.
PROGRAM = json.dumps({"source": {"hash": "sha256:not-checked-here"}})

# Placeholder run settings. No real venue, instrument or interval appears in
# this file: what is under test is that whatever was saved is what comes back
# and what reaches the service, which a made up value proves as well as a real
# one and without teaching anybody a symbol from a test.
SYMBOL = "TESTSYM"
EXCHANGE = "EXCH"
INTERVAL = "5m"
PRODUCT = "MIS"

# Anything that would mean this response carried the outcome of a run rather
# than the identity of one.
RESULT_KEYS = {"result", "output", "exit_code", "returncode", "pnl", "orders", "trades"}

# Exactly the keys the service documents for one run, restated so a change to
# either side has to be a deliberate change to both.
RUN_KEYS = {
    "run",
    "script",
    "symbol",
    "exchange",
    "interval",
    "product",
    "pid",
    "started_at",
    "log_file",
    "running",
    "exit_code",
}


def assert_matches(fake, real):
    """Fail unless this stand in has the signature of the function it stands in for.

    This is the check whose absence let a blueprint that called nothing real
    pass its whole test file. Signature equality is the strict form: names,
    order, defaults, annotations and the return annotation all have to agree, so
    a service that gains an argument, renames one or changes a default breaks
    every test that leans on the stand in, which is the moment somebody should
    be looking at it.
    """
    mine = inspect.signature(fake)
    theirs = inspect.signature(real)
    assert mine == theirs, (
        f"The stand in for {real.__name__} is {mine} where the real one in "
        f"{real.__module__} is {theirs}. A stand in that has drifted from the module it "
        "stands in for is how a route that calls nothing real passes its tests."
    )


class Runner:
    """The service the routes call, recorded, with the service's own signatures.

    Every function here is checked against the real one when this is built, so a
    test can never run against a shape the service does not have. The answers
    are the service's documented shape too: a finished run is dropped before
    anything is copied, so a run that is in an answer is always running.
    """

    def __init__(self):
        self.runs: dict[str, dict] = {}
        self.started: list[tuple[tuple, dict]] = []
        self.stopped: list[str] = []
        self.refuse_start = ""
        self.refuse_stop = ""
        self.raise_on_start = None

        def start_run(
            script: str,
            symbol: str = "",
            exchange: str = "",
            interval: str = "",
            user_id: str | None = None,
            product: str = "",
            history_days: int = 5,
            poll_seconds: float = 15.0,
        ) -> tuple[bool, str]:
            self.started.append(
                (
                    (script, symbol, exchange, interval, user_id, product),
                    {"history_days": history_days, "poll_seconds": poll_seconds},
                )
            )
            if self.raise_on_start is not None:
                raise self.raise_on_start
            if self.refuse_start:
                return False, self.refuse_start
            self.runs[script] = {
                "run": service.run_id_for(script),
                "script": script,
                "symbol": SYMBOL,
                "exchange": EXCHANGE,
                "interval": INTERVAL,
                "product": PRODUCT,
                "pid": 4242,
                "started_at": runner.IST.localize(datetime(2026, 9, 22, 9, 20, 0)),
                "log_file": str(Path("log") / "strategies" / f"{service.run_id_for(script)}.log"),
                "running": True,
                "exit_code": None,
            }
            return True, f"{script} started at 09:20:00 IST"

        def stop_run(script_or_run_id: str) -> tuple[bool, str]:
            self.stopped.append(script_or_run_id)
            if self.refuse_stop:
                return False, self.refuse_stop
            if self._held(script_or_run_id) is None:
                return False, "That run is not running"
            del self.runs[self._script(script_or_run_id)]
            return True, f"{script_or_run_id} stopped"

        def is_running(script_or_run_id: str) -> bool:
            return self._held(script_or_run_id) is not None

        def status_of(script_or_run_id: str) -> dict | None:
            held = self._held(script_or_run_id)
            return dict(held) if held is not None else None

        def running_runs() -> list[dict]:
            return [dict(held) for held in self.runs.values()]

        self.functions = {
            "start_run": start_run,
            "stop_run": stop_run,
            "is_running": is_running,
            "status_of": status_of,
            "running_runs": running_runs,
        }
        for name, fake in self.functions.items():
            assert_matches(fake, getattr(service, name))

    def _script(self, given: str) -> str:
        """A caller may name the script or the run, exactly as the service allows."""
        for script in self.runs:
            if given in (script, service.run_id_for(script)):
                return script
        return given

    def _held(self, given: str):
        return self.runs.get(self._script(given))

    def install(self, monkeypatch):
        for name, fake in self.functions.items():
            monkeypatch.setattr(runner, name, fake)


class Trigger:
    """Stands in for the trigger class, recording what it was built with."""

    def __init__(self, **fields):
        self.fields = fields


class Scheduler:
    """Stands in for the one scheduler, recording the jobs put on it."""

    def __init__(self):
        self.jobs = {}

    def add_job(self, func, trigger, id, replace_existing=False, **rest):
        # **rest because the real scheduler takes the trigger's own arguments,
        # and this stands in for it. A stub narrower than the thing it replaces
        # is a stub that refuses a call the real one accepts: this one rejected
        # the reaper's interval job, which made the module look broken when it
        # was the fake that was.
        self.jobs[id] = {"func": func, "trigger": trigger, **rest}

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def remove_job(self, job_id):
        self.jobs.pop(job_id, None)


class Host:
    """Stands in for the strategy host the schedule is registered against.

    Every attribute this blueprint reads off the real module is here, and
    ``test_the_stand_in_host_carries_what_the_blueprint_reads`` is what keeps the
    two in step. It is a module rather than a set of functions, so the check
    there is presence plus a call that binds, not signature equality: the real
    calendar check has a default exchange of its own and copying it here would
    put a venue name in a test that does not need one.
    """

    CronTrigger = Trigger
    IST = runner.IST
    LOGS_DIR = Path("log") / "strategies"

    def __init__(self):
        self.SCHEDULER = Scheduler()
        self.trading_day = True
        self.asked = []

    def init_scheduler(self):
        return None

    def is_trading_day(self, exchange=None):
        self.asked.append(exchange)
        return self.trading_day


@pytest.fixture
def scripts(tmp_path, monkeypatch):
    """A scripts directory this test owns, with one runnable script in it.

    ``outside.oscript`` is deliberately one level above it, complete with its
    compiled program, so a name that climbs out of the directory has a real
    target to find. Without it the traversal tests would pass against a runner
    with no name check at all.
    """
    directory = tmp_path / "strategies" / "openscript"
    directory.mkdir(parents=True)
    monkeypatch.setattr(openscript, "SCRIPTS_DIR", directory)

    (directory / "range.oscript").write_text(SOURCE, encoding="utf-8")
    (directory / "range.oscript.program.json").write_text(PROGRAM, encoding="utf-8")

    (tmp_path / "strategies" / "outside.oscript").write_text(SOURCE, encoding="utf-8")
    (tmp_path / "strategies" / "outside.oscript.program.json").write_text(PROGRAM, encoding="utf-8")
    return directory


@pytest.fixture
def schedules(tmp_path, monkeypatch):
    """The schedule store, pointed somewhere this test owns."""
    path = tmp_path / "strategies" / "openscript_runner_schedules.json"
    monkeypatch.setattr(runner, "SCHEDULES_FILE", path)
    monkeypatch.setattr(runner, "_RESTORED", False)
    return path


@pytest.fixture
def store(tmp_path, monkeypatch):
    """The real run settings store, pointed at a file this test owns.

    The real module, not a stand in: the routes below write through it and the
    service reads back through it, and a fake between them would be a fourth
    place the shape of a saved setting is decided.
    """
    path = tmp_path / "strategies" / "openscript_run_configs.json"
    monkeypatch.setattr(settings_store, "CONFIG_FILE", path)
    return path


@pytest.fixture
def stub(monkeypatch):
    """Put the stand in where the routes look for the service."""
    fake = Runner()
    fake.install(monkeypatch)
    return fake


@pytest.fixture
def host(monkeypatch):
    """Put the stand in where the runner looks for the strategy host."""
    fake = Host()
    monkeypatch.setattr(runner, "_strategy_host", lambda: fake)
    return fake


@pytest.fixture
def client(scripts, schedules, store, host, monkeypatch):
    """An app carrying both blueprints, with a session that is valid.

    Both, because the source routes and the runner routes share the
    ``/openscript`` prefix and one of the tests below is about which of them a
    request reaches. The service is deliberately not replaced here: a test that
    wants the stand in asks for ``stub`` as well, and the two tests that drive
    the real service simply do not.
    """
    monkeypatch.setattr(utils.session, "is_session_valid", lambda: True)
    application = Flask(__name__)
    application.config["TESTING"] = True
    application.secret_key = "test-only"
    application.register_blueprint(openscript_bp)
    application.register_blueprint(openscript_runner_bp)
    return application.test_client()


def keys_of(value):
    """Every key anywhere in a JSON body."""
    found = set()
    if isinstance(value, dict):
        found.update(value)
        for item in value.values():
            found |= keys_of(item)
    elif isinstance(value, list):
        for item in value:
            found |= keys_of(item)
    return found


def save_settings(client, filename="range.oscript", **fields):
    """Save run settings through the real route and the real store."""
    body = {"symbol": SYMBOL, "exchange": EXCHANGE, "interval": INTERVAL, "product": PRODUCT}
    body.update(fields)
    return client.post(f"/openscript/runner/config/{filename}", json=body)


# ---------------------------------------------------------------------------
# The seam that broke last time
# ---------------------------------------------------------------------------


def test_the_routes_hold_the_services_own_functions_and_not_a_guessed_name():
    """The one test that would have caught the defect this file was rewritten for.

    The blueprint used to resolve each call by trying a list of plausible
    spellings against the service and taking the first that existed. The list
    for reading state matched nothing, so status and stop answered that the
    server could not run OpenScript strategies, forever, and a running strategy
    could not be stopped. Identity is what rules that out: these are not
    functions with the right names, they are the service's own objects.
    """
    assert runner.start_run is service.start_run
    assert runner.stop_run is service.stop_run
    assert runner.is_running is service.is_running
    assert runner.status_of is service.status_of
    assert runner.running_runs is service.running_runs
    assert runner.run_id_for is service.run_id_for
    assert runner.logs_for is service.logs_for

    assert runner.read_run_config is settings_store.read_run_config
    assert runner.require_run_config is settings_store.require_run_config
    assert runner.write_run_config is settings_store.write_run_config
    assert runner.delete_run_config is settings_store.delete_run_config
    assert runner.all_run_configs is settings_store.all_run_configs


def test_nothing_in_the_blueprint_resolves_a_function_by_guessing():
    """The shape of the defect, refused at the source rather than at the symptom.

    Identity above proves the names are right today. This proves the mechanism
    that got them wrong is gone: no list of candidate spellings, no attribute
    lookup by string, and no import that is allowed to fail quietly and leave
    the routes answering a refusal.
    """
    source = Path(runner.__file__).read_text(encoding="utf-8")
    assert "_NAMES" not in source
    assert "getattr(" not in source
    assert "importlib" not in source
    assert "except ImportError" not in source


def test_the_blueprint_is_importable_and_conventionally_named():
    """A later change registers this. It only has to find it."""
    assert openscript_runner_bp.name == "openscript_runner_bp"
    assert openscript_runner_bp.url_prefix == "/openscript/runner"
    assert runner.openscript_runner_bp is openscript_runner_bp


def test_every_stand_in_matches_the_function_it_stands_in_for(stub):
    """Restated as a test of its own so its failure names the drift.

    The stand in already checks this as it is built, which is what stops a
    drifted one being used. This is here so that when the service changes, one
    named test fails saying which function and how, rather than every test in
    the file failing inside a fixture.
    """
    for name, fake in stub.functions.items():
        assert_matches(fake, getattr(service, name))


def test_the_stand_in_host_carries_what_the_blueprint_reads(host):
    """The strategy host stand in, against the real module.

    A module is not a function, so this is presence plus a call that binds
    rather than signature equality: what matters is that every attribute the
    blueprint reads is really there and that the calls it makes are calls the
    real module accepts.
    """
    import blueprints.python_strategy as real_host

    for name in ("CronTrigger", "IST", "LOGS_DIR", "SCHEDULER", "init_scheduler", "is_trading_day"):
        assert hasattr(real_host, name), f"the strategy host has no {name}"
        assert hasattr(host, name), f"the stand in has no {name}"

    assert_matches(host.init_scheduler, real_host.init_scheduler)
    # The calendar check is called both ways by the blueprint, so both have to
    # bind against the real one.
    inspect.signature(real_host.is_trading_day).bind()
    inspect.signature(real_host.is_trading_day).bind(exchange=EXCHANGE)


# ---------------------------------------------------------------------------
# Starting answers with an identifier
# ---------------------------------------------------------------------------


def test_starting_answers_with_an_identifier_and_not_a_result(client, stub):
    """The constraint the deployment imposes, asserted three ways.

    Catches the obvious implementation, which is to start the run, wait for it
    and answer with what it did. That route times out after five minutes with
    the strategy still trading, and it is the reading of "start" that anybody
    would reach for first.
    """
    answer = client.post("/openscript/runner/start/range.oscript")

    assert answer.status_code == 202
    body = answer.get_json()
    assert body["status"] == "success"
    assert body["run"]["id"] == service.run_id_for("range.oscript")
    assert body["run"]["file"] == "range.oscript"
    assert body["run"]["state"] == "running"
    assert body["run"]["started_at"]
    assert body["run"]["log"]
    assert not (keys_of(body) & RESULT_KEYS)


def test_starting_passes_the_file_name_and_nothing_else(client, stub):
    """Decision one, as the call the route actually makes.

    What a run is on is saved against the script and read by the service. A
    route that passed an instrument would be a second place it is decided, and
    two places differing by one typed character is an order on something nobody
    meant to trade.
    """
    client.post("/openscript/runner/start/range.oscript")

    assert len(stub.started) == 1
    positional, keyword = stub.started[0]
    script, symbol, exchange, interval, user_id, product = positional
    assert script == "range.oscript"
    assert (symbol, exchange, interval, user_id, product) == ("", "", "", None, "")
    assert keyword == {"history_days": 5, "poll_seconds": 15.0}


def test_a_run_can_be_followed_by_the_identifier_it_answered_with(client, stub):
    """The identifier is answered with because it is what the next request uses."""
    started = client.post("/openscript/runner/start/range.oscript").get_json()

    answer = client.get("/openscript/runner/status/range.oscript")
    assert answer.status_code == 200
    body = answer.get_json()
    assert body["running"] is True
    assert body["run"]["id"] == started["run"]["id"]
    assert body["run"]["log"] == started["run"]["log"]


@pytest.mark.parametrize(
    "body",
    [
        {"symbol": SYMBOL},
        {"mode": "live"},
        {"force_live": True},
        {"product": PRODUCT},
        ["not", "a", "body"],
    ],
)
def test_starting_takes_no_options_at_all(client, stub, body):
    """A body is refused rather than ignored, and the live ones are why.

    A caller that believes it chose a destination and was silently not given one
    is the worst of the three outcomes. There is no field here that could switch
    a strategy to live, and the way to be sure of that from outside is that
    every field is refused by name.
    """
    answer = client.post("/openscript/runner/start/range.oscript", json=body)

    assert answer.status_code == 400
    assert stub.started == []


def test_an_empty_body_still_starts(client, stub):
    """A client that sends an empty object has chosen nothing, so nothing is refused."""
    answer = client.post("/openscript/runner/start/range.oscript", json={})

    assert answer.status_code == 202
    assert len(stub.started) == 1


def test_a_script_with_no_compiled_program_is_not_started(client, stub, scripts):
    """A source with nothing compiled beside it is a script nothing here can run."""
    (scripts / "draft.oscript").write_text(SOURCE, encoding="utf-8")

    answer = client.post("/openscript/runner/start/draft.oscript")

    assert answer.status_code == 409
    assert "compiled" in answer.get_json()["message"]
    assert stub.started == []


def test_a_script_that_is_not_there_is_not_started(client, stub):
    answer = client.post("/openscript/runner/start/missing.oscript")

    assert answer.status_code == 404
    assert "missing.oscript" in answer.get_json()["message"]
    assert stub.started == []


def test_a_start_the_service_refuses_is_not_reported_as_success(client, stub):
    """The service's own sentence comes back, not one invented here.

    A script with nothing saved against it is refused in the settings module's
    words, which name the script and what is missing. Rewriting that sentence
    here would give a trader two different accounts of one fact.
    """
    stub.refuse_start = "range.oscript has no run settings saved on this server."

    answer = client.post("/openscript/runner/start/range.oscript")

    assert answer.status_code == 409
    assert answer.get_json()["message"] == stub.refuse_start


def test_a_run_that_ends_at_once_still_answers_with_its_identity(client, stub, monkeypatch):
    """A child that dies in the first second is still a run that was started.

    The service drops a finished run before it copies anything, so there is
    nothing to report about it a moment later. The caller is told the identity
    it asked for and pointed at the log, which is where the reason is.
    """

    def start_run(
        script: str,
        symbol: str = "",
        exchange: str = "",
        interval: str = "",
        user_id: str | None = None,
        product: str = "",
        history_days: int = 5,
        poll_seconds: float = 15.0,
    ) -> tuple[bool, str]:
        return True, f"{script} started"

    assert_matches(start_run, service.start_run)
    monkeypatch.setattr(runner, "start_run", start_run)

    answer = client.post("/openscript/runner/start/range.oscript")

    assert answer.status_code == 202
    body = answer.get_json()
    assert body["run"]["id"] == service.run_id_for("range.oscript")
    assert body["run"]["state"] == "finished"
    assert "log" in body["message"]


@pytest.mark.parametrize(
    "name",
    [
        "range.txt",
        "range",
        ".oscript",
        "-range.oscript",
        "range oscript.oscript",
        "range.oscript.program.json",
    ],
)
def test_a_name_this_runner_does_not_own_is_refused_by_name(client, stub, name):
    """One rule for a name, and it is the one the files are stored under."""
    for call in (
        client.post(f"/openscript/runner/start/{name}"),
        client.post(f"/openscript/runner/stop/{name}"),
        client.get(f"/openscript/runner/status/{name}"),
        client.get(f"/openscript/runner/config/{name}"),
        client.post(f"/openscript/runner/config/{name}", json={"symbol": SYMBOL}),
        client.delete(f"/openscript/runner/config/{name}"),
        client.post(f"/openscript/runner/schedule/{name}", json={"start_time": "09:20"}),
        client.delete(f"/openscript/runner/schedule/{name}"),
    ):
        assert call.status_code == 400, name
        assert "Invalid script name" in call.get_json()["message"]

    assert stub.started == []
    assert stub.stopped == []


@pytest.mark.parametrize(
    "name",
    [
        "../outside.oscript",
        "..%2Foutside.oscript",
        "%2e%2e/outside.oscript",
        "sub/../../outside.oscript",
    ],
)
def test_a_name_that_climbs_out_of_the_folder_never_reaches_the_runner(client, stub, name):
    """There is a real script at the other end of these, so the check has work to do."""
    answer = client.post(f"/openscript/runner/start/{name}")

    assert answer.status_code in (400, 404)
    assert stub.started == []


def test_the_runner_routes_are_not_swallowed_by_the_source_routes(client, stub):
    """Both blueprints live under one prefix, and the source route takes a path.

    ``/openscript/<path:filename>`` would match every runner path if the more
    specific rules did not win, and the symptom would be a start that answered
    with the text of a script.
    """
    assert client.get("/openscript/runner/status").status_code == 200
    assert client.get("/openscript/runner/config").status_code == 200
    assert client.post("/openscript/runner/start/range.oscript").status_code == 202


# ---------------------------------------------------------------------------
# Stopping tells the truth
# ---------------------------------------------------------------------------


def test_stopping_something_that_is_not_running_says_so(client, stub):
    """The answer an operator acts on. Success here leaves them wrong about a position."""
    answer = client.post("/openscript/runner/stop/range.oscript")

    assert answer.status_code == 404
    assert "not running" in answer.get_json()["message"]
    assert stub.stopped == []


def test_a_stop_the_service_refuses_is_not_reported_as_success(client, stub):
    """A run that outlived both signals is still out there, and the answer says so."""
    client.post("/openscript/runner/start/range.oscript")
    stub.refuse_stop = "That run did not stop. It is still running."

    answer = client.post("/openscript/runner/stop/range.oscript")

    assert answer.status_code == 409
    assert answer.get_json()["message"] == stub.refuse_stop


def test_stopping_something_that_is_running_stops_it(client, stub):
    client.post("/openscript/runner/start/range.oscript")

    answer = client.post("/openscript/runner/stop/range.oscript")

    assert answer.status_code == 200
    assert answer.get_json()["status"] == "success"
    assert stub.stopped == ["range.oscript"]
    assert client.get("/openscript/runner/status/range.oscript").get_json()["running"] is False


# ---------------------------------------------------------------------------
# What is running, and what it is running on
# ---------------------------------------------------------------------------


def test_status_reports_what_is_running_with_what_it_is_running_on(client, stub, host):
    client.post("/openscript/runner/start/range.oscript")

    body = client.get("/openscript/runner/status").get_json()

    assert body["status"] == "success"
    assert len(body["running"]) == 1
    entry = body["running"][0]
    assert entry["file"] == "range.oscript"
    assert entry["symbol"] == SYMBOL
    assert entry["exchange"] == EXCHANGE
    assert entry["interval"] == INTERVAL
    assert entry["product"] == PRODUCT
    assert entry["pid"] == 4242
    assert entry["started_at"].startswith("2026-09-22T09:20:00")
    assert body["log_dir"] == str(host.LOGS_DIR)
    assert not (keys_of(body) & RESULT_KEYS)


def test_status_for_a_script_that_is_not_running_says_so_plainly(client, stub):
    body = client.get("/openscript/runner/status/range.oscript").get_json()

    assert body["running"] is False
    assert body["run"] is None
    assert body["file"] == "range.oscript"


# ---------------------------------------------------------------------------
# The run settings, through the real store
# ---------------------------------------------------------------------------


def test_saving_run_settings_is_what_a_later_start_runs_on(client, store):
    """Written by the route, read back by the settings module the service reads."""
    answer = save_settings(client)

    assert answer.status_code == 200
    saved = answer.get_json()["settings"]
    assert saved["file"] == "range.oscript"
    assert saved["symbol"] == SYMBOL
    assert saved["exchange"] == EXCHANGE
    assert saved["interval"] == INTERVAL
    assert saved["product"] == PRODUCT

    # The real store, not the answer, is what a start will read.
    assert settings_store.read_run_config("range.oscript")["symbol"] == SYMBOL
    assert settings_store.require_run_config("range.oscript")[1] == ""


def test_the_store_normalises_the_case_the_platform_states(client, store):
    """A trader typing an exchange or a product in lower case means the same thing."""
    save_settings(client, exchange=EXCHANGE.lower(), product=PRODUCT.lower())

    saved = settings_store.read_run_config("range.oscript")
    assert saved["exchange"] == EXCHANGE
    assert saved["product"] == PRODUCT
    # The instrument is stored exactly as typed: it is the one string a broker
    # mapping matches on.
    assert saved["symbol"] == SYMBOL


@pytest.mark.parametrize(
    "field",
    ["mode", "force_live", "destination", "live", "sandbox", "history_days"],
)
def test_a_field_these_settings_do_not_have_is_refused_by_name(client, store, field):
    """The body a caller would invent a destination in.

    Refused rather than dropped, and nothing is saved. Being told no is the only
    answer that leaves the caller knowing where the destination is actually
    decided, which is the platform's own setting on the order path.
    """
    answer = client.post(
        "/openscript/runner/config/range.oscript",
        json={"symbol": SYMBOL, "exchange": EXCHANGE, "interval": INTERVAL, field: "live"},
    )

    assert answer.status_code == 400
    assert field in answer.get_json()["message"]
    assert settings_store.read_run_config("range.oscript") is None


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"symbol": SYMBOL},
        {"symbol": SYMBOL, "exchange": EXCHANGE},
        {"symbol": "", "exchange": EXCHANGE, "interval": INTERVAL},
        {"symbol": SYMBOL, "exchange": EXCHANGE, "interval": INTERVAL, "product": "SOMETHING"},
        {"symbol": "a b", "exchange": EXCHANGE, "interval": INTERVAL},
    ],
)
def test_settings_that_could_never_start_a_run_are_refused_while_they_are_being_typed(
    client, store, body
):
    """Checked where the trader is looking, not a minute later in a log."""
    answer = client.post("/openscript/runner/config/range.oscript", json=body)

    assert answer.status_code == 400
    assert settings_store.read_run_config("range.oscript") is None


def test_a_script_with_no_settings_is_asked_about_in_the_sentence_a_start_refuses_it_with(
    client, store
):
    answer = client.get("/openscript/runner/config/range.oscript")

    assert answer.status_code == 404
    message = answer.get_json()["message"]
    assert message == settings_store.require_run_config("range.oscript")[1]
    assert "range.oscript" in message


def test_the_settings_answer_never_carries_the_owning_user(client, store):
    """Stored so a scheduled run can find its key, and not something a page needs back."""
    save_settings(client)

    one = client.get("/openscript/runner/config/range.oscript").get_json()
    every = client.get("/openscript/runner/config").get_json()

    assert "user_id" not in keys_of(one)
    assert "user_id" not in keys_of(every)
    assert "user_id" in settings_store.read_run_config("range.oscript")


def test_settings_can_be_listed_and_removed(client, store):
    save_settings(client)

    listed = client.get("/openscript/runner/config").get_json()
    assert [entry["file"] for entry in listed["settings"]] == ["range.oscript"]
    assert listed["products"] == list(settings_store.PRODUCTS)

    removed = client.delete("/openscript/runner/config/range.oscript")
    assert removed.status_code == 200
    assert settings_store.read_run_config("range.oscript") is None

    again = client.delete("/openscript/runner/config/range.oscript")
    assert again.status_code == 404


def test_the_settings_are_reported_beside_what_is_running(client, stub, store):
    save_settings(client)

    body = client.get("/openscript/runner/status").get_json()

    assert [entry["file"] for entry in body["settings"]] == ["range.oscript"]
    assert body["settings"][0]["interval"] == INTERVAL


# ---------------------------------------------------------------------------
# The schedule, on the platform's one scheduler
# ---------------------------------------------------------------------------


def test_a_schedule_goes_on_the_platforms_own_scheduler(client, stub, host, schedules):
    answer = client.post(
        "/openscript/runner/schedule/range.oscript",
        json={"start_time": "09:20", "stop_time": "15:15", "days": ["mon", "tue"]},
    )

    assert answer.status_code == 200
    start_job = host.SCHEDULER.get_job("openscript_start_range.oscript")
    stop_job = host.SCHEDULER.get_job("openscript_stop_range.oscript")
    assert start_job is not None
    assert stop_job is not None
    assert start_job["trigger"].fields["hour"] == 9
    assert start_job["trigger"].fields["minute"] == 20
    assert start_job["trigger"].fields["day_of_week"] == "mon,tue"
    assert start_job["trigger"].fields["timezone"] is host.IST
    assert json.loads(schedules.read_text(encoding="utf-8"))["range.oscript"]["days"] == [
        "mon",
        "tue",
    ]


def test_a_schedule_does_not_carry_an_exchange_of_its_own(client, stub, host, schedules, store):
    """One place a venue is typed, which is the script's own run settings.

    A schedule with its own copy is a second thing to keep in step, and a trader
    moving a script from one venue to another would leave the schedule checking
    a calendar the script no longer trades on.
    """
    refused = client.post(
        "/openscript/runner/schedule/range.oscript",
        json={"start_time": "09:20", "exchange": EXCHANGE},
    )
    assert refused.status_code == 400
    assert "exchange" in refused.get_json()["message"]

    save_settings(client)
    client.post("/openscript/runner/schedule/range.oscript", json={"start_time": "09:20"})
    stored = json.loads(schedules.read_text(encoding="utf-8"))["range.oscript"]
    assert "exchange" not in stored

    runner._scheduled_start("range.oscript")
    assert host.asked == [EXCHANGE]


def test_a_stored_schedule_is_put_back_after_a_restart(monkeypatch, client, stub, host, schedules):
    schedules.parent.mkdir(parents=True, exist_ok=True)
    schedules.write_text(
        json.dumps({"range.oscript": {"start_time": "09:20", "stop_time": None, "days": ["mon"]}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "_RESTORED", False)

    runner.restore_schedules()

    assert host.SCHEDULER.get_job("openscript_start_range.oscript") is not None
    assert host.SCHEDULER.get_job("openscript_stop_range.oscript") is None


def test_removing_a_schedule_takes_the_jobs_with_it(client, stub, host, schedules):
    client.post("/openscript/runner/schedule/range.oscript", json={"start_time": "09:20"})

    answer = client.delete("/openscript/runner/schedule/range.oscript")

    assert answer.status_code == 200
    assert host.SCHEDULER.get_job("openscript_start_range.oscript") is None
    assert json.loads(schedules.read_text(encoding="utf-8")) == {}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"start_time": "9:20"},
        {"start_time": "25:00"},
        {"start_time": "09:20", "stop_time": "09:00"},
        {"start_time": "09:20", "days": []},
        {"start_time": "09:20", "days": ["funday"]},
        {"start_time": "09:20", "unknown": 1},
    ],
)
def test_a_schedule_that_does_not_read_is_refused(client, stub, host, schedules, body):
    answer = client.post("/openscript/runner/schedule/range.oscript", json=body)

    assert answer.status_code == 400
    assert not schedules.exists()


def test_a_scheduled_start_is_skipped_when_the_market_is_closed(client, stub, host, schedules):
    client.post("/openscript/runner/schedule/range.oscript", json={"start_time": "09:20"})
    host.trading_day = False

    runner._scheduled_start("range.oscript")

    assert stub.started == []


def test_a_scheduled_stop_runs_whatever_the_calendar_says(client, stub, host, schedules):
    """A stop that is skipped leaves a position with nothing watching it."""
    client.post("/openscript/runner/start/range.oscript")
    host.trading_day = False

    runner._scheduled_stop("range.oscript")

    assert stub.stopped == ["range.oscript"]


def test_a_scheduled_job_never_raises_into_the_scheduler(client, stub, host, schedules):
    """A job that raises is a job the scheduler may stop running, silently."""
    client.post("/openscript/runner/schedule/range.oscript", json={"start_time": "09:20"})
    stub.raise_on_start = RuntimeError("the service fell over")

    runner._scheduled_start("range.oscript")
    runner._scheduled_stop("range.oscript")


def test_the_schedule_is_reported_beside_what_is_running(client, stub, host, schedules):
    client.post("/openscript/runner/schedule/range.oscript", json={"start_time": "09:20"})

    body = client.get("/openscript/runner/status").get_json()

    assert [entry["file"] for entry in body["scheduled"]] == ["range.oscript"]
    assert body["scheduled"][0]["start_time"] == "09:20"


def test_the_runner_schedules_against_the_one_real_scheduler(schedules, stub, monkeypatch):
    """The only scheduling test that touches the real strategy host.

    Everything above uses a stand in for it, which proves the shape of the call
    and not the identity of the object. This proves the identity: the scheduler
    the runner reaches for is the object the strategy host started, the trigger
    is that module's trigger, and the job goes on and comes off that scheduler
    rather than a second one nothing else can see.
    """
    import blueprints.python_strategy as host

    assert runner._strategy_host() is host
    assert runner._scheduler(host) is host.SCHEDULER
    assert runner.IST is host.IST

    entry = {"start_time": "09:20", "stop_time": "15:15", "days": ["mon"]}
    try:
        runner._register_jobs("range.oscript", entry)
        job = host.SCHEDULER.get_job("openscript_start_range.oscript")
        assert job is not None
        assert str(job.trigger.timezone) == "Asia/Kolkata"
        # And it did not land on top of a strategy host job of the same name.
        assert host.SCHEDULER.get_job("start_range.oscript") is None
    finally:
        runner._remove_jobs("range.oscript")

    assert host.SCHEDULER.get_job("openscript_start_range.oscript") is None
    assert host.SCHEDULER.get_job("openscript_stop_range.oscript") is None


# ---------------------------------------------------------------------------
# The real service, with no stand in anywhere
# ---------------------------------------------------------------------------


@pytest.fixture
def real_runner_program(tmp_path, monkeypatch):
    """A child program this test owns, where the real service looks for one.

    The real runner is not used, for two reasons: it loads an engine this
    checkout may not have, and what is under test here is the seam between the
    route and the service rather than what a strategy computes. It is a real
    process all the same, spawned by the real service, which is the part that
    could not be proved with a stand in.
    """
    program = tmp_path / "openscript_host" / "openscript_runner.py"
    program.parent.mkdir(parents=True, exist_ok=True)
    program.write_text("import time\n\ntime.sleep(30)\n", encoding="utf-8")

    monkeypatch.setattr(service, "RUNNER_SCRIPT", program)
    monkeypatch.setattr(service, "LEGACY_RUNNER_SCRIPT", tmp_path / "gone" / "openscript_runner.py")
    monkeypatch.setattr(service, "LOGS_DIR", tmp_path / "log" / "strategies")
    return program


def test_the_real_service_starts_and_stops_a_run_through_these_routes(
    client, store, real_runner_program
):
    """No stand in anywhere: the real routes, the real service, a real child process.

    This is the test the last attempt did not have, and its absence is why
    thirty seven passing tests sat on top of a blueprint whose stop route could
    not reach the service at all. It also pins the shape both sides agree on:
    the keys the real service answers with are the keys the stand in above
    carries, so a change to one fails here rather than silently in production.
    """
    assert save_settings(client).status_code == 200

    run_id = service.run_id_for("range.oscript")
    try:
        answer = client.post("/openscript/runner/start/range.oscript")
        assert answer.status_code == 202, answer.get_json()

        body = answer.get_json()
        assert body["run"]["id"] == run_id
        assert body["run"]["state"] == "running"
        assert body["run"]["symbol"] == SYMBOL
        assert body["run"]["exchange"] == EXCHANGE

        held = service.status_of("range.oscript")
        assert held is not None
        assert set(held) == RUN_KEYS
        assert held["pid"] > 0
        assert Path(held["log_file"]).is_file()
        assert service.is_running("range.oscript") is True

        listed = client.get("/openscript/runner/status").get_json()
        assert [entry["file"] for entry in listed["running"]] == ["range.oscript"]

        # A second start is refused while the first is on the market.
        again = client.post("/openscript/runner/start/range.oscript")
        assert again.status_code == 409
        assert "already running" in again.get_json()["message"]

        stopped = client.post("/openscript/runner/stop/range.oscript")
        assert stopped.status_code == 200, stopped.get_json()
        assert service.is_running("range.oscript") is False
        assert service.status_of("range.oscript") is None

        # And the stop route tells the truth the second time.
        assert client.post("/openscript/runner/stop/range.oscript").status_code == 404
    finally:
        # Nothing this test started may outlive it. A child outlives its parent,
        # and a leaked one here is a process polling for the rest of the session.
        if run_id in service.RUNNING_RUNS:
            service.stop_run(run_id)


def test_the_real_service_refuses_a_start_for_a_script_with_nothing_saved_against_it(
    client, store, real_runner_program
):
    """Decision one, proved against the real settings store and the real service.

    Nothing is saved for this script, so nothing says what to run it on, and the
    refusal is the settings module's own sentence: it names the script, names
    what is absent and names what to do. No process is started.
    """
    assert settings_store.read_run_config("range.oscript") is None
    before = dict(service.RUNNING_RUNS)

    answer = client.post("/openscript/runner/start/range.oscript")

    assert answer.status_code == 409
    message = answer.get_json()["message"]
    assert message == settings_store.require_run_config("range.oscript")[1]
    assert "range.oscript" in message
    assert "instrument" in message
    assert service.RUNNING_RUNS == before


# ---------------------------------------------------------------------------
# The session guard
# ---------------------------------------------------------------------------


def test_every_route_is_behind_the_session_guard(scripts, schedules, store, monkeypatch):
    """No route here starts, stops, configures or schedules anything without a session."""
    monkeypatch.setattr(utils.session, "is_session_valid", lambda: False)
    monkeypatch.setattr(utils.session, "revoke_user_tokens", lambda: None)
    application = Flask(__name__)
    application.config["TESTING"] = True
    application.secret_key = "test-only"
    application.register_blueprint(openscript_runner_bp)

    # The guard redirects a plain request to the login endpoint, so that
    # endpoint has to exist for the redirect to build. Registering it here
    # rather than sending JSON headers keeps both of the guard's two answers in
    # play: a fetch gets 401 and a plain navigation gets the redirect.
    auth = Blueprint("auth", __name__)
    auth.add_url_rule("/login", "login", lambda: "login")
    application.register_blueprint(auth)

    guarded = application.test_client()

    calls = [
        guarded.post("/openscript/runner/start/range.oscript"),
        guarded.post("/openscript/runner/stop/range.oscript"),
        guarded.get("/openscript/runner/status"),
        guarded.get("/openscript/runner/status/range.oscript"),
        guarded.get("/openscript/runner/config"),
        guarded.get("/openscript/runner/config/range.oscript"),
        guarded.post("/openscript/runner/config/range.oscript", json={"symbol": SYMBOL}),
        guarded.delete("/openscript/runner/config/range.oscript"),
        guarded.post("/openscript/runner/schedule/range.oscript", json={"start_time": "09:20"}),
        guarded.delete("/openscript/runner/schedule/range.oscript"),
    ]

    for answer in calls:
        assert answer.status_code in (302, 401)


# ---------------------------------------------------------------------------
# The sweep, and the flag that used to burn its only attempt
# ---------------------------------------------------------------------------


def test_the_reaper_is_registered_so_a_finished_run_is_swept_with_nobody_watching(
    monkeypatch, client, stub, host, schedules
):
    # Catches the reaper going unregistered, which is how it was: nothing in the
    # application called reap_finished_runs, so on a headless deployment a run
    # that ended by itself stayed in the registry and that script could never be
    # started again for the life of the worker.
    monkeypatch.setattr(runner, "_RESTORED", False)

    runner.restore_schedules()

    job = host.SCHEDULER.get_job(runner.REAP_JOB_ID)
    assert job is not None, "nothing sweeps finished runs"
    assert job["trigger"] == "interval"
    assert job["minutes"] == runner.REAP_MINUTES


def test_a_scheduler_that_is_not_ready_leaves_the_attempt_to_be_made_again(
    monkeypatch, client, stub, host, schedules
):
    # Catches the flag being set before the work. It was, so a worker that
    # imported this module before the platform scheduler was running burned the
    # only attempt: every schedule failed into the log and nothing tried again,
    # and a scheduled strategy simply never ran.
    schedules.parent.mkdir(parents=True, exist_ok=True)
    schedules.write_text(
        json.dumps({"range.oscript": {"start_time": "09:20", "stop_time": None, "days": ["mon"]}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "_RESTORED", False)

    real_scheduler = runner._scheduler

    def no_scheduler(_host):
        raise runner.SchedulerUnavailable("not running yet")

    monkeypatch.setattr(runner, "_scheduler", no_scheduler)
    runner.restore_schedules()

    assert runner._RESTORED is False, "the failed attempt was recorded as done"
    assert host.SCHEDULER.get_job("openscript_start_range.oscript") is None

    # The scheduler arrives, and the second attempt is allowed to happen. Put
    # back only this one patch: monkeypatch.undo() would take the fixtures with
    # it and the second call would run against a different world entirely.
    monkeypatch.setattr(runner, "_scheduler", real_scheduler)
    runner.restore_schedules()

    assert host.SCHEDULER.get_job("openscript_start_range.oscript") is not None


def test_a_reaper_that_cannot_be_registered_does_not_cost_the_schedules(
    monkeypatch, client, stub, host, schedules
):
    # The two are registered on one scheduler and must not share a fate. A run
    # left in the registry is cleared by the next read of it; a schedule that was
    # never restored is a strategy that never runs, so the second must survive
    # the first failing.
    schedules.parent.mkdir(parents=True, exist_ok=True)
    schedules.write_text(
        json.dumps({"range.oscript": {"start_time": "09:20", "stop_time": None, "days": ["mon"]}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "_RESTORED", False)

    real_add = host.SCHEDULER.add_job

    def refuse_the_interval(func, trigger, id, replace_existing=False, **rest):
        if trigger == "interval":
            raise RuntimeError("this scheduler will not take an interval job")
        return real_add(func, trigger, id, replace_existing=replace_existing, **rest)

    monkeypatch.setattr(host.SCHEDULER, "add_job", refuse_the_interval)
    runner.restore_schedules()

    assert host.SCHEDULER.get_job(runner.REAP_JOB_ID) is None
    assert host.SCHEDULER.get_job("openscript_start_range.oscript") is not None
