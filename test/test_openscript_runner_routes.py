"""The routes that start, stop, report and schedule an OpenScript strategy.

These drive the real blueprint through a real Flask client. The part that owns
processes is replaced by a stand in, because what is under test here is the
surface over it and not the running of anything: whether a start answers with an
identity rather than an outcome, whether a name that is not a script is refused
before it reaches anything, and whether a stop tells the truth about something
that was never running.

Three properties run through the file, and each is a way somebody loses money
rather than a way a response looks wrong:

- **A start answers with an identifier and never with a result.** The
  deployment gives a request five minutes and buffers the response, so a route
  that waited for a run would time out with the strategy still trading and the
  operator told nothing. The stand in below refuses to be waited on: any call
  that asks it for an outcome fails the test on the spot.
- **A name this runner does not own never reaches the part that opens
  processes.** There is a real script one directory above the scripts folder in
  these tests, so a check that is absent has something to find.
- **A stop is never reported as success unless something was stopped.** An
  operator pressing stop believes a strategy is on the market. Telling them it
  was stopped when nothing was running is the one answer that leaves them
  wrong about a live position.
"""

import json
from pathlib import Path

import pytest
from flask import Blueprint, Flask

import blueprints.openscript as openscript
import blueprints.openscript_runner as runner
import utils.session
from blueprints.openscript import openscript_bp
from blueprints.openscript_runner import openscript_runner_bp

SOURCE = 'version 1\nstudy("Range", overlay = true)\nplot(close, "C", aqua)\n'

# A stand in for the compiled program. Nothing here reads it: the runner only
# asks whether one is there, because a source with no program beside it is a
# script nothing on this server can run.
PROGRAM = json.dumps({"source": {"hash": "sha256:not-checked-here"}})

# Anything that would mean this response carried the outcome of a run rather
# than the identity of one.
RESULT_KEYS = {"result", "output", "exit_code", "returncode", "pnl", "orders", "trades"}


class Stub:
    """The part that owns processes, with every call recorded.

    Two of its methods exist only to be never called. ``wait`` and ``result``
    are what a route would reach for if somebody decided the caller of ``start``
    would rather have the answer than the identity, and they fail the test
    rather than returning one.
    """

    def __init__(self):
        self.runs = {}
        self.started = []
        self.stopped = []
        self.refuse_start = None
        self.refuse_stop = None

    def start(self, filename):
        self.started.append(filename)
        if self.refuse_start:
            return {"status": "error", "message": self.refuse_start}
        run_id = f"run-{len(self.started)}"
        self.runs[filename] = {
            "id": run_id,
            "state": "running",
            "started_at": "2026-09-22T09:20:00+05:30",
            "log": f"log/strategies/{filename}.log",
        }
        return {"status": "success", "run_id": run_id, "log": self.runs[filename]["log"]}

    def stop(self, filename):
        self.stopped.append(filename)
        if self.refuse_stop:
            return False, self.refuse_stop
        if self.runs.pop(filename, None) is None:
            return False, "Strategy not running"
        return True, "Strategy stopped"

    def status(self):
        return dict(self.runs)

    def wait(self, *args, **kwargs):
        raise AssertionError("the route waited for the run instead of answering with its identity")

    def result(self, *args, **kwargs):
        raise AssertionError("the route asked for the outcome of a run it had just started")


class Trigger:
    """Stands in for the trigger class, recording what it was built with."""

    def __init__(self, **fields):
        self.fields = fields


class Scheduler:
    """Stands in for the one scheduler, recording the jobs put on it."""

    def __init__(self):
        self.jobs = {}

    def add_job(self, func, trigger, id, replace_existing=False):
        self.jobs[id] = {"func": func, "trigger": trigger}

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def remove_job(self, job_id):
        self.jobs.pop(job_id, None)


class Host:
    """Stands in for the strategy host the schedule is registered against."""

    CronTrigger = Trigger
    IST = runner.IST
    LOGS_DIR = Path("log") / "strategies"

    def __init__(self):
        self.SCHEDULER = Scheduler()
        self.trading_day = True

    def init_scheduler(self):
        return None

    def normalize_exchange(self, exchange):
        # A placeholder code rather than a real venue, and deliberately not the
        # host's own default: what is asserted below is that the route stores
        # whatever the host normalised to, not a value spelled twice.
        return str(exchange).strip().upper() if exchange else "EXCH"

    def is_trading_day(self, exchange=None):
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
    return path


@pytest.fixture
def stub(monkeypatch):
    """Put the stand in where the runner looks for the service."""
    service = Stub()
    monkeypatch.setattr(runner, "_service", lambda: service)
    return service


@pytest.fixture
def host(monkeypatch):
    """Put the stand in where the runner looks for the strategy host."""
    fake = Host()
    monkeypatch.setattr(runner, "_strategy_host", lambda: fake)
    return fake


@pytest.fixture
def client(scripts, schedules, monkeypatch):
    """An app carrying both blueprints, with a session that is valid.

    Both, because the source routes and the runner routes share the
    ``/openscript`` prefix and one of the tests below is about which of them a
    request reaches.
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


# ---------------------------------------------------------------------------
# Starting answers with an identifier
# ---------------------------------------------------------------------------


def test_starting_answers_with_an_identifier_and_not_a_result(client, stub):
    """The constraint the deployment imposes, asserted three ways.

    Catches the obvious implementation, which is to start the run, wait for it
    and answer with what it did. That route times out after five minutes with
    the strategy still trading, and it is the reading of "start" that anybody
    writing this from scratch reaches for first. The stand in fails on any call
    that asks for an outcome, so the shape cannot pass quietly.
    """
    answer = client.post("/openscript/runner/start/range.oscript")
    payload = answer.get_json()

    assert answer.status_code == 202
    assert payload["status"] == "success"
    assert payload["run"]["id"] == "run-1"
    assert payload["run"]["file"] == "range.oscript"
    assert payload["run"]["log"] == "log/strategies/range.oscript.log"
    assert stub.started == ["range.oscript"]
    assert not keys_of(payload) & RESULT_KEYS


def test_a_run_can_be_followed_by_the_identifier_it_answered_with(client, stub):
    """An identifier nothing can be asked about is not an identifier.

    The reason ``start`` may answer before the run finishes is that the status
    route answers for it afterwards, so the two are tested together rather than
    separately.
    """
    started = client.post("/openscript/runner/start/range.oscript").get_json()

    followed = client.get("/openscript/runner/status/range.oscript").get_json()

    assert followed["running"] is True
    assert followed["run"]["id"] == started["run"]["id"]
    assert followed["run"]["log"] == started["run"]["log"]
    assert followed["log_dir"]


def test_starting_takes_no_options_at_all(client, stub):
    """The live boundary, written as a refusal rather than as a comment.

    Where an order goes is the platform's own setting, read on the order path.
    Catches a route that accepts a mode, a destination or a live flag and then
    ignores it: the caller believes it chose, and nothing chose.
    """
    for body in ({"mode": "live"}, {"live": True}, {"force_live": True}, {"anything": 1}):
        refused = client.post("/openscript/runner/start/range.oscript", json=body)
        assert refused.status_code == 400
        assert "not chosen here" in refused.get_json()["message"]

    assert stub.started == []

    # An empty body is a plain start, because that is what a browser sends.
    assert client.post("/openscript/runner/start/range.oscript", json={}).status_code == 202


def test_a_script_with_no_compiled_program_is_not_started(client, stub, scripts):
    """A source with no program beside it is a script nothing here can run.

    Catches a runner that hands the name to the service anyway and lets it fail
    somewhere the trader cannot read, instead of saying the one thing they can
    act on, which is to open it in the chart and save it again.
    """
    (scripts / "half.oscript").write_text(SOURCE, encoding="utf-8")

    refused = client.post("/openscript/runner/start/half.oscript")

    assert refused.status_code == 409
    assert "no compiled program" in refused.get_json()["message"]
    assert stub.started == []


def test_a_script_that_is_not_there_is_not_started(client, stub):
    refused = client.post("/openscript/runner/start/missing.oscript")

    assert refused.status_code == 404
    assert "no script named" in refused.get_json()["message"]
    assert stub.started == []


# ---------------------------------------------------------------------------
# A name this runner does not own
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "indicator.js",
        "range.oscript.js",
        "range.oscript.program.json",
        ".hidden.oscript",
        "range.oscript.bak",
        "x" * 80 + ".oscript",
    ],
)
def test_a_name_this_runner_does_not_own_is_refused_by_name(client, stub, name):
    """Refused for what it is called, before anything looks at a filesystem.

    Each of these reaches the view, so the answer distinguishes a runner that
    checks the name from one that only fails to find the file: the first says
    the name is invalid, the second says there is no such script. Catches a
    check that was left out, and catches one that was replaced by the existence
    test that happens to follow it.
    """
    for path in ("start", "stop"):
        refused = client.post(f"/openscript/runner/{path}/{name}")
        assert refused.status_code == 400
        assert "Invalid script name" in refused.get_json()["message"]

    assert client.get(f"/openscript/runner/status/{name}").status_code == 400
    assert (
        client.post(f"/openscript/runner/schedule/{name}", json={"start_time": "09:20"}).status_code
        == 400
    )
    assert client.delete(f"/openscript/runner/schedule/{name}").status_code == 400
    assert stub.started == []
    assert stub.stopped == []


@pytest.mark.parametrize(
    "name",
    [
        "../outside.oscript",
        "..%2Foutside.oscript",
        "..%252Foutside.oscript",
        "sub/dir.oscript",
        "../../secrets.env",
        "",
    ],
)
def test_a_name_that_climbs_out_of_the_folder_never_reaches_the_runner(client, stub, name):
    """There is a real script one level up, so an absent check has a target.

    Whether a given spelling is turned away by the router or by the name check
    is not the point and is not asserted: the point is that no spelling of it
    ends with the part that opens processes being handed a name outside the
    folder the chart writes to.
    """
    assert client.post(f"/openscript/runner/start/{name}").status_code in (308, 400, 404, 405)
    assert client.post(f"/openscript/runner/stop/{name}").status_code in (308, 400, 404, 405)

    assert stub.started == []
    assert stub.stopped == []


def test_the_runner_routes_are_not_swallowed_by_the_source_routes(client, stub):
    """Both blueprints live under ``/openscript`` and the order matters.

    The source route matches ``/openscript/<anything>``, so a runner path could
    arrive there as a file name instead, and every runner call would come back
    as an invalid script name that reads like a bug in the caller. Asserted
    against a real url map with both registered, because it is a property of
    the router rather than of either module.
    """
    started = client.post("/openscript/runner/start/range.oscript")
    assert started.status_code == 202
    assert stub.started == ["range.oscript"]

    # And the source routes still answer for themselves.
    assert client.get("/openscript/range.oscript").status_code == 200
    assert client.get("/openscript/index.json").status_code == 200


# ---------------------------------------------------------------------------
# Stopping
# ---------------------------------------------------------------------------


def test_stopping_something_that_is_not_running_says_so(client, stub):
    """The answer that keeps an operator right about a live position.

    Catches the implementation that reports success whatever happened, on the
    reasoning that the script is not running either way. It is not the same
    thing: somebody pressed stop because they believed a strategy was on the
    market, and being told it was stopped ends their checking.
    """
    answer = client.post("/openscript/runner/stop/range.oscript")
    payload = answer.get_json()

    assert answer.status_code == 404
    assert payload["status"] == "error"
    assert "is not running" in payload["message"]
    assert stub.stopped == []


def test_a_stop_the_runner_refuses_is_not_reported_as_success(client, stub):
    """The service is the truth, and its refusal is what comes back.

    Catches a route that checks whether the script is running, finds that it
    is, and then answers success without reading what the stop actually did.
    That is the same wrong answer as above, arrived at one step later.
    """
    client.post("/openscript/runner/start/range.oscript")
    stub.refuse_stop = "The process did not respond to being stopped"

    answer = client.post("/openscript/runner/stop/range.oscript")
    payload = answer.get_json()

    assert answer.status_code == 409
    assert payload["status"] == "error"
    assert payload["message"] == "The process did not respond to being stopped"


def test_stopping_something_that_is_running_stops_it(client, stub):
    client.post("/openscript/runner/start/range.oscript")

    answer = client.post("/openscript/runner/stop/range.oscript")

    assert answer.status_code == 200
    assert answer.get_json()["status"] == "success"
    assert stub.stopped == ["range.oscript"]
    assert client.get("/openscript/runner/status/range.oscript").get_json()["running"] is False


def test_a_runner_that_is_not_installed_says_so_rather_than_failing(client, monkeypatch):
    """The state this platform is in until the service lands.

    A route that raised here would put an unreadable failure in front of a
    trader for a feature that is simply not present yet.
    """
    monkeypatch.setattr(runner, "_service", lambda: None)

    assert client.post("/openscript/runner/start/range.oscript").status_code == 503
    assert client.post("/openscript/runner/stop/range.oscript").status_code == 503
    assert client.get("/openscript/runner/status").status_code == 503


# ---------------------------------------------------------------------------
# The schedule
# ---------------------------------------------------------------------------


def test_a_schedule_goes_on_the_platforms_own_scheduler(client, stub, host, schedules):
    """One scheduler, its own trigger, its own timezone, and its own job names.

    Catches a second scheduler started beside the platform's, which fires jobs
    nothing else can see, and catches job identifiers that collide with the
    strategy host's own ``start_<id>`` and ``stop_<id>``.
    """
    answer = client.post(
        "/openscript/runner/schedule/range.oscript",
        json={"start_time": "09:20", "stop_time": "15:15", "days": ["mon", "wed"]},
    )

    assert answer.status_code == 200
    jobs = host.SCHEDULER.jobs
    assert set(jobs) == {"openscript_start_range.oscript", "openscript_stop_range.oscript"}
    start_job = jobs["openscript_start_range.oscript"]
    assert start_job["trigger"].fields == {
        "hour": 9,
        "minute": 20,
        "day_of_week": "mon,wed",
        "timezone": host.IST,
    }
    assert jobs["openscript_stop_range.oscript"]["trigger"].fields["hour"] == 15

    assert json.loads(schedules.read_text(encoding="utf-8"))["range.oscript"] == {
        "start_time": "09:20",
        "stop_time": "15:15",
        "days": ["mon", "wed"],
        "exchange": "EXCH",
    }


def test_a_stored_schedule_is_put_back_after_a_restart(monkeypatch, client, stub, host, schedules):
    """A schedule that does not survive a restart is a schedule nobody can trust."""
    client.post(
        "/openscript/runner/schedule/range.oscript",
        json={"start_time": "09:20", "stop_time": "15:15"},
    )
    host.SCHEDULER.jobs.clear()

    monkeypatch.setattr(runner, "_RESTORED", False)
    runner.restore_schedules()

    assert set(host.SCHEDULER.jobs) == {
        "openscript_start_range.oscript",
        "openscript_stop_range.oscript",
    }


def test_removing_a_schedule_takes_the_jobs_with_it(client, stub, host, schedules):
    client.post(
        "/openscript/runner/schedule/range.oscript",
        json={"start_time": "09:20", "stop_time": "15:15"},
    )

    removed = client.delete("/openscript/runner/schedule/range.oscript")

    assert removed.status_code == 200
    assert host.SCHEDULER.jobs == {}
    assert json.loads(schedules.read_text(encoding="utf-8")) == {}
    # Asked for twice, gone both times.
    assert client.delete("/openscript/runner/schedule/range.oscript").status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"start_time": "9:20"},
        {"start_time": "25:00"},
        {"start_time": "09:20", "stop_time": "09:00"},
        {"start_time": "09:20", "days": ["mon", "someday"]},
        {"start_time": "09:20", "days": []},
        {"start_time": "09:20", "live": True},
    ],
)
def test_a_schedule_that_does_not_read_is_refused(client, stub, host, schedules, body):
    """Including one that carries a field this route does not know.

    The last case is the live boundary again: a schedule that quietly ignored
    an unknown field would let a caller believe it had configured something.
    """
    refused = client.post("/openscript/runner/schedule/range.oscript", json=body)

    assert refused.status_code == 400
    assert host.SCHEDULER.jobs == {}
    assert not schedules.exists()


def test_a_scheduled_start_is_skipped_when_the_market_is_closed(client, stub, host, schedules):
    """The calendar the rest of the platform already keeps, asked rather than rebuilt."""
    client.post("/openscript/runner/schedule/range.oscript", json={"start_time": "09:20"})

    host.trading_day = False
    runner._scheduled_start("range.oscript")
    assert stub.started == []

    host.trading_day = True
    runner._scheduled_start("range.oscript")
    assert stub.started == ["range.oscript"]


def test_a_scheduled_job_never_raises_into_the_scheduler(client, stub, host, schedules):
    """A job that raises is a job the scheduler may stop running.

    A schedule that silently stops firing is worse than one that logs a failure
    and fires again tomorrow, so both jobs swallow everything.
    """
    client.post("/openscript/runner/schedule/range.oscript", json={"start_time": "09:20"})

    def explode(filename):
        raise RuntimeError("the runner fell over")

    stub.start = explode
    stub.stop = explode

    runner._scheduled_start("range.oscript")
    runner._scheduled_stop("range.oscript")


def test_the_schedule_is_reported_beside_what_is_running(client, stub, host, schedules):
    client.post(
        "/openscript/runner/schedule/range.oscript",
        json={"start_time": "09:20", "stop_time": "15:15", "days": ["fri"]},
    )
    client.post("/openscript/runner/start/range.oscript")

    reported = client.get("/openscript/runner/status").get_json()

    assert [entry["file"] for entry in reported["running"]] == ["range.oscript"]
    assert reported["running"][0]["log"] == "log/strategies/range.oscript.log"
    assert reported["scheduled"] == [
        {
            "file": "range.oscript",
            "start_time": "09:20",
            "stop_time": "15:15",
            "days": ["fri"],
            "exchange": "EXCH",
        }
    ]
    assert reported["log_dir"]


# ---------------------------------------------------------------------------
# The scheduler this runner uses is the platform's, not one of its own
# ---------------------------------------------------------------------------


def test_the_runner_schedules_against_the_one_real_scheduler(schedules, stub, monkeypatch):
    """The only test here that touches the real strategy host.

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

    entry = {
        "start_time": "09:20",
        "stop_time": "15:15",
        "days": ["mon"],
        "exchange": "EXCH",
    }
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
# The session guard
# ---------------------------------------------------------------------------


def test_every_route_is_behind_the_session_guard(scripts, schedules, monkeypatch):
    """No route here starts, stops or schedules anything without a session."""
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
        guarded.post("/openscript/runner/schedule/range.oscript", json={"start_time": "09:20"}),
        guarded.delete("/openscript/runner/schedule/range.oscript"),
    ]

    for answer in calls:
        assert answer.status_code in (302, 401)
