"""The seam: the application, the runner routes, the runner service, the child program.

Every other file in this set tests one side of a boundary. This one tests the
boundaries themselves, and it exists because of a specific failure rather than
for symmetry.

**What went wrong.** An earlier runner blueprint could not see the service
module while it was being written, so it resolved the functions it needed by
trying a list of plausible spellings and taking whichever one existed. The list
for reading state matched nothing the service defines, so the status and stop
routes answered a refusal forever and a running strategy could not be stopped
from the page that started it. Thirty seven route tests were green throughout,
because every one of them ran against a stand in whose method names matched the
guess. Both halves agreed with each other and neither agreed with the platform.

**So nothing here is stood in for.** The checks below are of four kinds, and
each one is a way that failure could come back:

1. **The routes hold the service's own function objects**, compared by identity
   rather than by name, and every call they make is bound against the real
   signature with ``inspect.signature``. A route that calls a function with the
   wrong number of arguments fails here, at collection speed, instead of when a
   trader presses stop.
2. **The application registers the blueprint.** A blueprint nobody registers is
   a set of routes that answer "not found" on a running server while every test
   of them passes, which is the same failure wearing different clothes. The
   check reads ``app.py`` rather than importing it, because importing it starts
   the platform.
3. **The child program is where the service looks for it, ships in the image,
   and takes the arguments the service sends it.** That last one is a name
   agreement across a process boundary, which is exactly the kind that was got
   wrong before, and it is checked by reading both sides rather than by running
   anything.
4. **One test drives the real routes into the real service and a real child
   process**, with no stand in of either anywhere in it.

**Why the real child program is not executed here.** It loads the engine and
reaches the platform's own order path, so running it is a test that can place an
order. The process this file starts is a few lines that sleep, put where the
service looks; the service that spawns it, the routes that ask for it and the
settings store they read are all the real ones. What the child computes is
``test_openscript_child.py``'s subject, not this file's.

No venue, instrument or interval below is a real one. What is under test is that
a value saved is the value that reaches the service, which a placeholder proves
as well as a real symbol and without teaching anybody a symbol out of a test.
"""

import ast
import inspect
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from flask import Flask

import blueprints.openscript as openscript
import blueprints.openscript_runner as runner
import services.openscript_run_config as settings_store
import services.openscript_runner_service as service
import utils.session
from blueprints.openscript import openscript_bp
from blueprints.openscript_runner import openscript_runner_bp

#: The repository root, found from this file rather than from the working
#: directory, so the packaging checks below answer about the checkout being
#: tested whatever directory pytest was started in.
ROOT = Path(__file__).resolve().parent.parent

#: The service functions the routes are built on. Named here as well as in the
#: blueprint so that a function quietly dropped from either side fails a test
#: rather than passing unnoticed.
SERVICE_NAMES = (
    "is_running",
    "logs_for",
    "run_id_for",
    "running_runs",
    "start_run",
    "status_of",
    "stop_run",
)

#: The run settings functions the routes are built on.
SETTINGS_NAMES = (
    "all_run_configs",
    "delete_run_config",
    "read_run_config",
    "require_run_config",
    "write_run_config",
)

SERVICE_MODULE = "services.openscript_runner_service"
SETTINGS_MODULE = "services.openscript_run_config"

# Placeholder run settings.
SYMBOL = "TESTSYM"
EXCHANGE = "EXCH"
INTERVAL = "5m"
PRODUCT = "MIS"

SOURCE = 'version 1\nstudy("Seam", overlay = true)\nplot(close, "C", aqua)\n'

# A stand in for a compiled program. Nothing reads it: the routes only ask
# whether one is there, because a source with no program beside it is a script
# nothing on this server can run.
PROGRAM = '{"source": {"hash": "sha256:not-checked-here"}}'


def _source_of(module) -> str:
    return Path(module.__file__).read_text(encoding="utf-8")


def _tree_of(module) -> ast.Module:
    return ast.parse(_source_of(module), filename=module.__file__)


# ---------------------------------------------------------------------------
# The routes and the service are one seam
# ---------------------------------------------------------------------------


def _imported_names(tree: ast.Module, module_name: str) -> dict[str, str]:
    """What this module imports from that one, as ``{local name: real name}``."""
    found: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == module_name:
            for alias in node.names:
                found[alias.asname or alias.name] = alias.name
    return found


def test_the_routes_import_every_service_function_by_name():
    """Ordinary imports, not a lookup, and not inside a try that can fall back.

    A name that is not there has to be an error when this module loads, in the
    one place where it is cheap to notice. The alternative is what happened
    before: a missing name became a route that answered politely and did
    nothing, and nothing anywhere said so.
    """
    tree = _tree_of(runner)
    from_service = _imported_names(tree, SERVICE_MODULE)
    from_settings = _imported_names(tree, SETTINGS_MODULE)

    assert set(SERVICE_NAMES) <= set(from_service), (
        f"The routes import {sorted(from_service)} from the runner service, which is missing "
        f"{sorted(set(SERVICE_NAMES) - set(from_service))}."
    )
    assert set(SETTINGS_NAMES) <= set(from_settings), (
        f"The routes import {sorted(from_settings)} from the run settings, which is missing "
        f"{sorted(set(SETTINGS_NAMES) - set(from_settings))}."
    )

    # Imported under their own names, so the name in a traceback is the name in
    # the service.
    assert all(local == real for local, real in from_service.items())
    assert all(local == real for local, real in from_settings.items())

    # And none of it happens inside a try, which is the other shape of the same
    # mistake: an ImportError swallowed here is a dead route later.
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for inner in ast.walk(node):
                if isinstance(inner, ast.ImportFrom) and inner.module in (
                    SERVICE_MODULE,
                    SETTINGS_MODULE,
                ):
                    raise AssertionError(
                        "The runner service is imported inside a try block, so a missing "
                        "name becomes a dead route instead of an error at startup."
                    )


def test_the_routes_hold_the_services_own_function_objects():
    """Identity, not names.

    This is the check whose absence let a blueprint that reached nothing real
    pass a whole file of tests. A function that merely has the right name is
    what a stand in has; the real one is the same object the service exports.
    """
    for name in SERVICE_NAMES:
        assert getattr(runner, name) is getattr(service, name), (
            f"blueprints.openscript_runner.{name} is not the same object as "
            f"{SERVICE_MODULE}.{name}."
        )
    for name in SETTINGS_NAMES:
        assert getattr(runner, name) is getattr(settings_store, name), (
            f"blueprints.openscript_runner.{name} is not the same object as "
            f"{SETTINGS_MODULE}.{name}."
        )


def _call_shape(node: ast.Call):
    """``(positional count, keyword names)`` for one call, or None if it unpacks."""
    for argument in node.args:
        if isinstance(argument, ast.Starred):
            return None
    names = []
    for keyword in node.keywords:
        if keyword.arg is None:
            return None
        names.append(keyword.arg)
    return len(node.args), names


def test_every_call_the_routes_make_binds_against_the_real_signature():
    """Every call site, checked against the function it actually reaches.

    ``inspect.signature(...).bind`` answers the question a stand in cannot: does
    this call work against the module that will receive it. A service that gains
    a required argument, loses one or renames a keyword fails here rather than
    at the moment a strategy is started.

    The second half of the test is the one that would have caught the original
    failure: it asserts the routes really do call every function they are built
    on. Before, the status and the stop routes reached nothing at all, and a
    check that only looked at the calls that were there would have been happy.
    """
    tree = _tree_of(runner)
    real = {name: getattr(service, name) for name in _imported_names(tree, SERVICE_MODULE)}
    real.update(
        {name: getattr(settings_store, name) for name in _imported_names(tree, SETTINGS_MODULE)}
    )

    called: set[str] = set()
    checked = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        name = node.func.id
        target = real.get(name)
        if target is None or not callable(target):
            continue

        shape = _call_shape(node)
        assert shape is not None, (
            f"The call to {name} on line {node.lineno} unpacks its arguments, so what it "
            "sends cannot be checked against the real signature. Spell the arguments out."
        )
        positional, keywords = shape
        signature = inspect.signature(target)
        try:
            signature.bind(*[object()] * positional, **{key: object() for key in keywords})
        except TypeError as mismatch:
            raise AssertionError(
                f"Line {node.lineno} calls {name} with {positional} positional argument(s) and "
                f"{keywords}, which does not fit {name}{signature}: {mismatch}"
            ) from mismatch
        called.add(name)
        checked += 1

    missing = (set(SERVICE_NAMES) | set(SETTINGS_NAMES)) - called
    assert not missing, (
        f"The routes never call {sorted(missing)}. A route that reaches nothing is how "
        "status and stop answered a refusal forever while their tests passed."
    )
    assert checked >= len(SERVICE_NAMES) + len(SETTINGS_NAMES)


def test_the_routes_resolve_nothing_by_name():
    """The shape of the original defect, refused outright.

    Name guessing leaves three traces: a module looked up at runtime, a list of
    candidate spellings, and ``getattr`` over that list. None of the three has a
    legitimate use in this file, so all three are asserted absent rather than
    left to a reviewer to notice.
    """
    source = _source_of(runner)
    tree = _tree_of(runner)

    assert "importlib" not in source, (
        "The routes look a module up at runtime. Import what they call, by name."
    )

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "getattr", (
                f"Line {node.lineno} resolves something with getattr. Every function these "
                "routes call is an ordinary import."
            )

    guessing = [name for name in vars(runner) if name.endswith("_NAMES")]
    assert not guessing, (
        f"The routes still carry candidate name lists: {sorted(guessing)}. Those are what "
        "the service was guessed from."
    )
    for gone in ("_SERVICE_MODULE", "_service", "_invoke", "RunnerUnavailable"):
        assert not hasattr(runner, gone), (
            f"{gone} is back. It is part of the lookup seam that made the routes unreachable."
        )


# ---------------------------------------------------------------------------
# The application registers the blueprint
# ---------------------------------------------------------------------------


#: Every route this blueprint owns, with the methods it answers on. Restated
#: here so that a route removed, renamed or given a method it did not have is a
#: deliberate change to two files rather than a quiet change to one.
EXPECTED_ROUTES = {
    "/openscript/runner/start/<path:filename>": {"POST"},
    # Two ways to end a run, and they are separate routes rather than one with
    # a flag: a caller that reaches the wrong one by accident should pause,
    # which costs nothing, rather than close, which cannot be taken back.
    "/openscript/runner/stop/<path:filename>": {"POST"},
    "/openscript/runner/pause/<path:filename>": {"POST"},
    "/openscript/runner/close/<path:filename>": {"POST"},
    "/openscript/runner/status": {"GET"},
    "/openscript/runner/status/<path:filename>": {"GET"},
    "/openscript/runner/config": {"GET"},
    "/openscript/runner/config/<path:filename>": {"GET", "POST", "DELETE"},
    "/openscript/runner/schedule/<path:filename>": {"POST", "DELETE"},
    # What one strategy has done. The converter is the default one and not
    # `path`, because a script name can never hold a slash and a rule that
    # claims it can turns a URL naming nothing into a refusal about a bad
    # script name rather than a plain 404.
    "/openscript/runner/orderbook/<filename>": {"GET"},
    "/openscript/runner/tradebook/<filename>": {"GET"},
    "/openscript/runner/positions/<filename>": {"GET"},
    # What a trader picks a deployment's instrument and bar from, rather than
    # typing them. Both read through the platform's own services: a symbol one
    # character wrong is a start refused a minute later in a log, or an
    # instrument that exists and is not the one meant.
    "/openscript/runner/instruments": {"GET"},
    "/openscript/runner/intervals": {"GET"},
}


def test_the_blueprint_carries_the_routes_the_platform_will_serve():
    """The rules a registration puts on an application, and whose views they are.

    The view functions are checked to come from this module, because a rule that
    resolves to somebody else's view is a rule that answers for the wrong
    surface.
    """
    application = Flask(__name__)
    application.register_blueprint(openscript_runner_bp)

    # One path registered twice, once per method, is two rules on the map, so
    # the methods are gathered rather than replaced.
    found: dict[str, set[str]] = {}
    for rule in application.url_map.iter_rules():
        if rule.rule.startswith("/openscript/runner"):
            found.setdefault(rule.rule, set()).update(rule.methods - {"HEAD", "OPTIONS"})

    assert found == EXPECTED_ROUTES

    for endpoint, view in application.view_functions.items():
        if endpoint.startswith("openscript_runner_bp."):
            assert view.__module__ == "blueprints.openscript_runner"


def test_the_application_imports_and_registers_the_runner_blueprint():
    """``app.py`` wires it in, read rather than imported.

    Read, because importing ``app.py`` checks the environment, creates the
    database directory and pulls in every blueprint on the platform. What is
    being asked is a two line question about the file, and the file answers it.

    The blueprint that stores the sources is checked the same way in the same
    test. It has been registered for as long as the surface has existed, so if
    the walk below stops finding registrations it fails on that one too, rather
    than reporting the new one absent because the check itself broke.
    """
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"), filename="app.py")

    imported = _imported_names(tree, "blueprints.openscript_runner")
    assert "openscript_runner_bp" in imported, (
        "app.py does not import the runner blueprint, so none of its routes exist on a "
        "running server."
    )

    factory = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "create_app"
        ),
        None,
    )
    assert factory is not None, "app.py no longer has a create_app function to register into."

    registered = set()
    for node in ast.walk(factory):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "register_blueprint"
            and node.args
            and isinstance(node.args[0], ast.Name)
        ):
            registered.add(node.args[0].id)

    assert "openscript_bp" in registered, (
        "The check for registrations found none for the sources blueprint either, so it is "
        "the check that is broken rather than the wiring."
    )
    assert "openscript_runner_bp" in registered, (
        "app.py imports the runner blueprint and never registers it. Every route it owns "
        "answers not found on a running server."
    )


# ---------------------------------------------------------------------------
# The child program ships
# ---------------------------------------------------------------------------


def _ignore_rules(path: Path) -> list[tuple[str, bool, bool]]:
    """``(pattern, negated, directories only)`` for each rule in one ignore file."""
    rules = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        negated = stripped.startswith("!")
        if negated:
            stripped = stripped[1:]
        directories_only = stripped.endswith("/")
        rules.append((stripped.rstrip("/"), negated, directories_only))
    return rules


def _as_regex(pattern: str) -> str:
    """One ignore pattern as a regular expression over a slash separated path."""
    out = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            out.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("/**", index) and index + 3 == len(pattern):
            out.append("/.*")
            index += 3
        elif pattern[index] == "*":
            out.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            out.append("[^/]")
            index += 1
        elif pattern[index] == "[":
            closing = pattern.find("]", index)
            if closing == -1:
                out.append(re.escape(pattern[index]))
                index += 1
            else:
                out.append(pattern[index : closing + 1])
                index = closing + 1
        else:
            out.append(re.escape(pattern[index]))
            index += 1
    return "".join(out)


def _rule_matches(pattern: str, directories_only: bool, relative: str, is_dir: bool) -> bool:
    if directories_only and not is_dir:
        return False
    anchored = pattern.startswith("/") or "/" in pattern
    body = _as_regex(pattern.lstrip("/"))
    subject = relative if anchored else relative.rsplit("/", 1)[-1]
    return re.fullmatch(body, subject) is not None


def _is_ignored(relative: str, ignore_files: dict[str, list[tuple[str, bool, bool]]]) -> bool:
    """Whether this path is ignored, by the rules of the files that cover it.

    Written out rather than asked of the version control program, because this
    suite runs no such command. Every directory on the way down is decided
    first, since a file under an excluded directory cannot be brought back.
    """
    parts = relative.split("/")
    for depth in range(1, len(parts) + 1):
        current = "/".join(parts[:depth])
        is_dir = depth < len(parts)
        ignored = False
        for directory, rules in ignore_files.items():
            if directory and not current.startswith(directory + "/"):
                continue
            local = current[len(directory) + 1 :] if directory else current
            for pattern, negated, directories_only in rules:
                if _rule_matches(pattern, directories_only, local, is_dir):
                    ignored = not negated
        if ignored:
            return True
    return False


@pytest.fixture(scope="module")
def git_ignores() -> dict[str, list[tuple[str, bool, bool]]]:
    """Every ignore file in the tracked tree, keyed by the directory it governs."""
    files = {"": _ignore_rules(ROOT / ".gitignore")}
    for directory in (
        "strategies",
        "strategies/scripts",
        "strategies/openscript",
        "log/strategies",
    ):
        path = ROOT / directory / ".gitignore"
        if path.is_file():
            files[directory] = _ignore_rules(path)
    return files


def test_the_ignore_reader_finds_the_files_that_are_ignored(git_ignores):
    """The control for the test below, and it is not optional.

    A matcher that answered "not ignored" to everything would pass the next test
    without reading anything. These are paths whose state is decided in the
    ignore files as they stand: user scripts, user studies, the built frontend,
    the operator's error log, and the personal workspace whose readme is the one
    file in it that is kept.
    """
    assert _is_ignored("strategies/scripts/mine.py", git_ignores)
    assert _is_ignored("strategies/openscript/mine.oscript", git_ignores)
    assert _is_ignored("strategies/strategy_configs.json", git_ignores)
    assert _is_ignored("frontend/dist/index.js", git_ignores)
    assert _is_ignored("log/errors.jsonl", git_ignores)
    assert _is_ignored("workspace/notes.md", git_ignores)
    assert not _is_ignored("workspace/readme.md", git_ignores)

    assert not _is_ignored("app.py", git_ignores)
    assert not _is_ignored("blueprints/openscript_runner.py", git_ignores)
    assert not _is_ignored("test/test_openscript_seam.py", git_ignores)


def test_the_traders_own_run_settings_are_ignored(git_ignores):
    """What a trader saves is theirs and is never committed.

    Both files are written by the server into the folder the strategy host keeps
    its own configuration in, which is a mounted volume on a container install.
    Unlisted, a saved instrument shows up as an untracked file and is committed
    by somebody adding everything.
    """
    assert _is_ignored("strategies/openscript_run_configs.json", git_ignores)
    assert _is_ignored("strategies/openscript_runner_schedules.json", git_ignores)
    assert _is_ignored("strategies/openscript_run_configs.json.tmp", git_ignores)
    assert _is_ignored("strategies/tmpabcd1234.partial", git_ignores)


def test_the_child_program_is_tracked_and_not_ignored(git_ignores):
    """It moved out of the volume, and nothing may quietly keep it out of the tree.

    Where it used to live, two ignore files covered it: one ignores every Python
    file under the scripts folder and the other ignores every Python file in it.
    That is correct for a trader's own strategies and fatal for a file the
    platform ships, which is the whole reason it moved.
    """
    shipped = service.RUNNER_SCRIPT.as_posix()
    assert not _is_ignored(shipped, git_ignores), (
        f"{shipped} is ignored, so it is not in the repository and no install gets it."
    )
    assert not _is_ignored("openscript_host", git_ignores)

    # The old home, still ignored, which is why the file could not stay there.
    assert _is_ignored(service.LEGACY_RUNNER_SCRIPT.as_posix(), git_ignores)


def test_the_child_program_is_copied_into_the_image():
    """The build copies the tree and the build ignore file does not take it out."""
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines()
    last_stage = max(
        index for index, line in enumerate(dockerfile) if line.strip().startswith("FROM ")
    )
    copies_everything = [
        line
        for line in dockerfile[last_stage:]
        if re.fullmatch(r"COPY(?: --[^\s]+)* \. \.", line.strip())
    ]
    assert copies_everything, (
        "The stage the image is built from no longer copies the tree into it, so a file that "
        "is only in the repository never reaches a container install."
    )

    excluded = {"": _ignore_rules(ROOT / ".dockerignore")}
    # The control first: these are excluded from the image today.
    assert _is_ignored("db/openalgo.db", excluded)
    assert _is_ignored("workspace/notes.md", excluded)
    assert _is_ignored("blueprints/__pycache__/openscript_runner.cpython-312.pyc", excluded)
    assert not _is_ignored("app.py", excluded)

    shipped = service.RUNNER_SCRIPT.as_posix()
    assert not _is_ignored(shipped, excluded), (
        f"{shipped} is excluded from the image, so a container install has no program to run "
        "a strategy with."
    )


def test_the_child_program_is_not_under_a_mounted_volume():
    """A named volume is seeded from the image once, and only while it is empty.

    That is what happened where the file used to be: the folder is a named
    volume, so the program reached a brand new install and no existing one, and
    an upgrade delivered nothing. The mount for that folder is asserted to still
    be there, because it is the reason this check exists and a file that has
    simply been renamed would otherwise pass it.
    """
    compose = yaml.safe_load((ROOT / "docker-compose.yaml").read_text(encoding="utf-8"))
    mounts = set()
    for definition in compose.get("services", {}).values():
        for entry in definition.get("volumes", []) or []:
            if isinstance(entry, str) and ":" in entry:
                mounts.add(entry.split(":")[1])

    assert "/app/strategies" in mounts
    assert "/app" not in mounts

    inside_image = "/app/" + service.RUNNER_SCRIPT.as_posix()
    for mount in mounts:
        assert not inside_image.startswith(mount.rstrip("/") + "/"), (
            f"{inside_image} sits under the mount {mount}, so an upgrade does not deliver it."
        )


def test_the_service_points_at_the_program_that_ships(monkeypatch):
    """The file is where the service looks, and the old copy is gone.

    ``runner_program_path`` prefers the shipped location and falls back to the
    old one with a warning. Asserting on the fallback rather than on the file
    alone is the point: an install where the fallback is what answers is an
    install that stops working at its next rebuild.
    """
    assert service.RUNNER_SCRIPT == Path("openscript_host") / "openscript_runner.py"

    shipped = ROOT / service.RUNNER_SCRIPT
    assert shipped.is_file(), f"{shipped} is missing, so no strategy can be started."
    assert not (ROOT / service.LEGACY_RUNNER_SCRIPT).exists(), (
        "The child program is still in the folder it was moved out of. Two copies means the "
        "one that runs is decided by which install you are on."
    )

    monkeypatch.chdir(ROOT)
    assert service.runner_program_path() == shipped.resolve()


def test_the_child_program_takes_the_arguments_the_service_sends_it():
    """A name agreement across a process boundary, checked on both sides.

    This is the same kind of agreement that was got wrong inside the process: a
    caller and a callee that were written apart and never compared. A flag the
    service sends and the child does not define is an immediate exit with a
    usage message into a log nobody is watching, and a strategy that never runs.

    Read rather than run. Starting the real child loads the engine and reaches
    the order path, so a test that ran it is a test that can place an order.
    """
    child_path = ROOT / service.RUNNER_SCRIPT
    child_source = child_path.read_text(encoding="utf-8")
    compile(child_source, str(child_path), "exec")

    accepted = set()
    for node in ast.walk(ast.parse(child_source, filename=str(child_path))):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            accepted.add(node.args[0].value)

    # Read off the WHOLE service module rather than off one function by name.
    # The flags were in start_run when this was written and moved into the
    # helper that spawns under a claim, which made this test read an empty set
    # and pass its real assertion vacuously. A flag is a constant beginning with
    # two dashes and holding no whitespace, which no docstring or sentence is.
    sent = {
        node.value
        for node in ast.walk(_tree_of(service))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        if node.value.startswith("--") and not any(c.isspace() for c in node.value)
    }

    # The controls: both sides were actually read, and the accepted set is a
    # real list rather than everything.
    assert "--script" in sent and len(sent) >= 7, f"Only {sorted(sent)} was read off the service."
    assert "--not-an-argument" not in accepted

    assert sent <= accepted, (
        f"The service sends {sorted(sent - accepted)}, which the child program does not "
        "define. It would exit on its first line with a usage message."
    )


def test_both_sides_of_the_boundary_send_the_same_products():
    """One vocabulary for the product, not two.

    The service refuses a product before a run starts and the child refuses one
    when it loads. Two lists that drifted would mean a product accepted by the
    route and refused a second later inside a process, which reads to a trader
    as the platform losing its own setting.
    """
    child_source = (ROOT / service.RUNNER_SCRIPT).read_text(encoding="utf-8")
    in_child = None
    for node in ast.walk(ast.parse(child_source)):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "PRODUCTS"
        ):
            in_child = tuple(ast.literal_eval(node.value))
    assert in_child is not None, "The child program no longer states the products it accepts."
    assert in_child == settings_store.PRODUCTS


# ---------------------------------------------------------------------------
# The real routes, the real service, a real process
# ---------------------------------------------------------------------------


@pytest.fixture
def seam(tmp_path, monkeypatch):
    """Everything real except the file the child process happens to be.

    The routes, the service, the settings store and the schedule store are the
    ones the platform runs. What is redirected is only where each of them keeps
    its files, so a test never writes into the operator's own strategies folder
    or log directory.
    """
    scripts = tmp_path / "strategies" / "openscript"
    scripts.mkdir(parents=True)
    (scripts / "seam.oscript").write_text(SOURCE, encoding="utf-8")
    (scripts / "seam.oscript.program.json").write_text(PROGRAM, encoding="utf-8")
    monkeypatch.setattr(openscript, "SCRIPTS_DIR", scripts)

    monkeypatch.setattr(
        settings_store, "CONFIG_FILE", tmp_path / "strategies" / "openscript_run_configs.json"
    )
    monkeypatch.setattr(
        runner, "SCHEDULES_FILE", tmp_path / "strategies" / "openscript_runner_schedules.json"
    )
    monkeypatch.setattr(runner, "_RESTORED", False)

    # A child that sleeps, where the service looks for the program. The real one
    # is not run here for the reason given at the top of this file.
    program = tmp_path / "openscript_host" / "openscript_runner.py"
    program.parent.mkdir(parents=True, exist_ok=True)
    program.write_text("import time\n\ntime.sleep(30)\n", encoding="utf-8")
    logs = tmp_path / "log" / "strategies"
    monkeypatch.setattr(service, "RUNNER_SCRIPT", program)
    monkeypatch.setattr(service, "LEGACY_RUNNER_SCRIPT", tmp_path / "gone" / "openscript_runner.py")
    monkeypatch.setattr(service, "LOGS_DIR", logs)

    # The strategy host is neither the routes nor the service. It is stood in
    # for so that importing it, which starts the platform scheduler, is not a
    # side effect of asking the status route where logs go.
    monkeypatch.setattr(runner, "_strategy_host", lambda: SimpleNamespace(LOGS_DIR=logs))
    monkeypatch.setattr(utils.session, "is_session_valid", lambda: True)

    application = Flask(__name__)
    application.config["TESTING"] = True
    application.secret_key = "test-only"
    application.register_blueprint(openscript_bp)
    application.register_blueprint(openscript_runner_bp)
    return application.test_client()


def test_the_real_routes_start_and_stop_a_real_run_through_the_real_service(seam):
    """The seam, end to end, with no stand in of the routes or the service.

    This is the test whose absence let the last attempt report thirty seven
    passes over a blueprint that could not reach the service. Every assertion
    below is about one of the three things that were broken then: a start that
    answers with an identity, a status route that can see the run, and a stop
    that actually stops it.
    """
    saved = seam.post(
        "/openscript/runner/config/seam.oscript",
        json={"symbol": SYMBOL, "exchange": EXCHANGE, "interval": INTERVAL, "product": PRODUCT},
    )
    assert saved.status_code == 200, saved.get_json()
    assert settings_store.read_run_config("seam.oscript")["symbol"] == SYMBOL

    # A run's id is its deployment's: the script, the instrument and the bar
    # together, which is what the settings saved just above name.
    # A run wears its deployment's own id, read back rather than worked out:
    # a deployment carries a token so that one made where another was removed
    # does not inherit that one's orders, fills and position.
    run_id = settings_store.read_run_config("seam.oscript")["deployment"]
    try:
        started = seam.post("/openscript/runner/start/seam.oscript")
        assert started.status_code == 202, started.get_json()

        body = started.get_json()
        assert body["run"]["id"] == run_id
        assert body["run"]["state"] == "running"
        assert body["run"]["symbol"] == SYMBOL
        assert body["run"]["exchange"] == EXCHANGE
        assert body["run"]["interval"] == INTERVAL
        assert body["run"]["product"] == PRODUCT

        # The answer is an identifier, never an outcome: at the moment it is
        # written the strategy has not done anything yet.
        assert not {"result", "output", "exit_code", "pnl", "orders", "trades"} & set(body["run"])

        # The registry the routes reported is the service's own, and the process
        # in it is a real one.
        assert run_id in service.RUNNING_RUNS
        held = service.status_of("seam.oscript")
        assert held["pid"] == body["run"]["pid"] > 0
        assert Path(held["log_file"]).is_file()

        # The status route, which is the one that answered a refusal forever.
        listed = seam.get("/openscript/runner/status")
        assert listed.status_code == 200, listed.get_json()
        assert [entry["file"] for entry in listed.get_json()["running"]] == ["seam.oscript"]

        one = seam.get("/openscript/runner/status/seam.oscript").get_json()
        assert one["running"] is True
        assert one["run"]["id"] == run_id
        assert one["settings"]["symbol"] == SYMBOL

        # The stop route, which is the other one.
        stopped = seam.post("/openscript/runner/stop/seam.oscript")
        assert stopped.status_code == 200, stopped.get_json()
        assert service.is_running("seam.oscript") is False
        assert service.status_of("seam.oscript") is None
        assert seam.get("/openscript/runner/status").get_json()["running"] == []
    finally:
        # Nothing this test started may outlive it. A child outlives its parent,
        # and one left behind here is a process running for the rest of the
        # session with nothing that knows about it.
        if run_id in service.RUNNING_RUNS:
            service.stop_run(run_id)


def test_a_script_with_no_run_settings_is_refused_by_the_real_settings_store(seam):
    """Nothing is started for a script nobody has said what to run on.

    The refusal is the settings module's own sentence, so a trader reads the
    same words wherever they meet this, and it names the script and what is
    missing. No process is started, which is the part that matters.
    """
    assert settings_store.read_run_config("seam.oscript") is None
    before = dict(service.RUNNING_RUNS)

    refused = seam.post("/openscript/runner/start/seam.oscript")

    assert refused.status_code == 409
    message = refused.get_json()["message"]
    assert message == settings_store.require_run_config("seam.oscript")[1]
    assert "seam.oscript" in message
    assert service.RUNNING_RUNS == before


def test_no_route_on_this_surface_offers_a_way_to_reach_a_live_destination(seam):
    """Where an order goes is decided in one place, and it is not here.

    A field invented in this body is refused by name rather than dropped. Being
    told no is the only answer that leaves a caller knowing the destination was
    not theirs to choose; ignoring it silently leaves them believing they chose.
    """
    for invented in ("mode", "force_live", "destination", "live", "sandbox"):
        answer = seam.post(
            "/openscript/runner/config/seam.oscript",
            json={
                "symbol": SYMBOL,
                "exchange": EXCHANGE,
                "interval": INTERVAL,
                invented: "anything",
            },
        )
        assert answer.status_code == 400, invented
        assert invented in answer.get_json()["message"]
        assert settings_store.read_run_config("seam.oscript") is None

    source = _source_of(runner)
    assert "force_live" not in source
