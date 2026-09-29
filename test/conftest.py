"""Safe environment defaults for tests collected outside an installation.

Database URLs are assigned, not defaulted. setdefault() would let an exported
DATABASE_URL or SANDBOX_DATABASE_URL win, so a developer or CI box with the
production values in its environment would run this suite against the real
databases - resetting funds and creating orders in live sandbox state. The
credentials below are still setdefault(), since those are only placeholders.
"""

import os

os.environ.setdefault("API_KEY_PEPPER", "0" * 64)
os.environ.setdefault("APP_KEY", "test-only-app-key")

# Neutralise dotenv before anything can call it.
#
# utils/config.py runs load_dotenv(override=True) at import, which re-reads the
# operator's .env and overwrites the assignments below. Whether that happens
# depends purely on which module a given test imports first, so the suite wrote
# to the isolated databases on some runs and to the real ones on others -- the
# Flow QA tests putting seven workflows into the operator's Flow Editor, needing
# manual deletion. Disabling the loader here is confined to the test harness and
# makes the isolation below hold whatever the import order turns out to be.
import dotenv

dotenv.load_dotenv = lambda *args, **kwargs: False
dotenv.main.load_dotenv = dotenv.load_dotenv

# Assigned unconditionally: test isolation must not be overridable from the
# environment.
os.environ["DATABASE_URL"] = "sqlite:///db/openalgo-test.db"
os.environ["SANDBOX_DATABASE_URL"] = "sqlite:///db/sandbox-test.db"
os.environ["LOGS_DATABASE_URL"] = "sqlite:///db/logs-test.db"
os.environ["LATENCY_DATABASE_URL"] = "sqlite:///db/latency-test.db"

# utils.logging calls setup_logging() at import time and always attaches a JSON
# handler on $LOG_DIR/errors.jsonl, so every error a test deliberately provokes
# was appended to the operator's production log -- the file CLAUDE.md names as
# the first place to look when debugging. Worse, setup_logging truncates that
# file to its last 1000 lines on startup, so a test run could evict real errors.
os.environ["LOG_DIR"] = "log/test"


# These are manual diagnostics, not pytest modules. test_bot_web.py starts the
# Telegram bot from its module body. The WebSocket scripts require a live proxy,
# operator API key and timed terminal interaction; their ``test_*`` helpers take
# ordinary arguments rather than fixtures.
#
# Keep the scripts runnable directly while preventing collection from starting
# external services or misclassifying their function parameters as fixtures.
collect_ignore = [
    "test_bot_web.py",
    "test_websocket.py",
    "test_websocket_service.py",
]


# The OpenScript state files, kept out of the operator's own.
#
# Three files under strategies/ say what each deployment runs on, which
# deployments a trader means to have running, and what has been asked of a run
# that is still going. They are the same class of thing as the databases and the
# log above: a test that writes one is writing a trader's own state.
#
# This is not hypothetical. The runner blueprint restores schedules and runs at
# import, which reads the running file, and a run recorded there whose process
# has gone is started again or dropped. A suite run on a machine with live
# strategies cleared the record of every one of them, so the next restart of the
# real application brought none of them back.
#
# Reassigned rather than configured, because these are not settings: nothing an
# operator installs should have a knob for where a trader's strategies live.
def _isolate_openscript_state() -> None:
    from pathlib import Path

    here = Path("strategies") / "test"
    here.mkdir(parents=True, exist_ok=True)

    from services import openscript_commands, openscript_run_config, openscript_running

    openscript_run_config.CONFIG_FILE = here / "openscript_run_configs.json"
    openscript_running.STATE_FILE = here / "openscript_running.json"
    openscript_commands.COMMAND_FILE = here / "openscript_commands.json"

    import blueprints.openscript_runner as runner_blueprint

    runner_blueprint.SCHEDULES_FILE = here / "openscript_runner_schedules.json"


_isolate_openscript_state()
