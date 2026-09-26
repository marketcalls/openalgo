"""Decide which web server OpenAlgo's launcher starts, from the install's .env.

Run with the install's own Python by ``install/openalgo-gunicorn.sh`` at every
start, by ``start.sh`` inside the Docker image, and by
``install/switch-worker.sh``. It never imports the app and never imports
eventlet: it only reads one setting and checks what is installed.

**One setting.** ``OPENALGO_WORKER_CLASS`` is ``eventlet`` (the default, used
when the line is absent, commented out or empty) or ``gthread``. Anything else
is reported and the default is used. The gthread thread count is not a
setting: the launcher owns it.

**Parsed the way the app parses it.** The app loads ``.env`` with
python-dotenv, where the last assignment of a key wins and ``export``, quotes,
inline comments and Windows line endings are all understood. This module uses
the same parser, so the launcher and the running app can never disagree about
what the file says. A key absent from ``.env`` falls back to the process
environment, which is how a platform such as Railway sets it; ``.env`` wins
when both are set, as it does for the app (``load_dotenv(override=True)``).

**What it prints.** With ``--shell`` it prints ``KEY=value`` lines whose values
are lower case letters, digits, dots, dashes and underscores only, so a shell
can read them without evaluating anything. With ``--print worker`` it prints
the one word. Advice for the operator goes to stderr in plain sentences, and
nothing at all is printed when the setting is absent or valid.

Only the standard library and python-dotenv are used, because this runs
before the app and must work on any install the launcher can start.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import sys

KEY = "OPENALGO_WORKER_CLASS"
DEFAULT_WORKER = "eventlet"
SUPPORTED_WORKERS = ("eventlet", "gthread")

#: Characters allowed in a value handed back to the shell.
_SAFE_VALUE = re.compile(r"[^a-z0-9_.-]")

#: Matches an assignment of KEY the way python-dotenv does: optional leading
#: space, an optional ``export``, the key, optional space, then ``=``.
_ASSIGNMENT = re.compile(rf"^[ \t]*(?:export[ \t]+)?{KEY}[ \t]*=")


def _safe(value: str, limit: int = 32) -> str:
    """Lower-case ``value`` and drop anything a shell could misread."""
    return _SAFE_VALUE.sub("", value.strip().lower())[:limit]


def _fallback_value(env_file: str) -> str | None:
    """Read KEY without python-dotenv, following its rules closely enough.

    Used only when python-dotenv cannot be imported. The last assignment
    wins; ``export``, surrounding quotes, a trailing ``#`` comment and a
    carriage return are removed.
    """
    try:
        with open(env_file, encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return None
    value = None
    for line in lines:
        if not _ASSIGNMENT.match(line):
            continue
        raw = line.split("=", 1)[1].strip().rstrip("\r")
        if raw[:1] in ("'", '"'):
            quote = raw[0]
            end = raw.find(quote, 1)
            raw = raw[1:end] if end > 0 else raw[1:]
        else:
            raw = raw.split(" #", 1)[0].split("\t#", 1)[0].strip()
        value = raw
    return value


def read_requested(env_file: str | None, environ: dict | None = None) -> str | None:
    """Return the raw value of KEY the app would see, or None when it is unset.

    Args:
        env_file: Path of the install's ``.env``. A missing file is not an
            error: the process environment is consulted instead.
        environ: The process environment, for tests. Defaults to os.environ.

    Returns:
        The raw string from ``.env`` when the key is assigned there (which may
        be empty), else the process environment's value, else None.
    """
    environ = os.environ if environ is None else environ
    if env_file and os.path.isfile(env_file):
        try:
            from dotenv import dotenv_values
        except ImportError:
            value = _fallback_value(env_file)
        else:
            try:
                value = dotenv_values(env_file).get(KEY)
            except Exception:
                value = _fallback_value(env_file)
        if value is not None:
            return value
    return environ.get(KEY)


def module_available(name: str) -> bool:
    """Return True when ``name`` can be imported, without importing it."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def package_version(name: str) -> str:
    """Return the installed version of ``name`` as ``X.Y.Z``, or ``0`` when absent."""
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:
        return "0"
    try:
        found = version(name)
    except (PackageNotFoundError, ValueError):
        return "0"
    match = re.match(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", found)
    if not match:
        return "0"
    return ".".join(part or "0" for part in match.groups())


def resolve(raw: str | None, eventlet_available: bool) -> tuple[str, str, list[str]]:
    """Choose the web server for one start.

    Args:
        raw: The value from :func:`read_requested`, or None when unset.
        eventlet_available: Whether eventlet can be imported by this Python.

    Returns:
        ``(effective, requested, warnings)``: the worker class to start, what
        the operator asked for (``"default"`` when nothing), and plain
        sentences for the operator.
    """
    warnings: list[str] = []
    cleaned = (raw or "").strip().strip("'\"").strip().lower()
    if not cleaned:
        requested = "default"
        effective = DEFAULT_WORKER
    elif cleaned in SUPPORTED_WORKERS:
        requested = cleaned
        effective = cleaned
    else:
        requested = _safe(cleaned) or "unrecognised"
        effective = DEFAULT_WORKER
        shown = raw.strip()[:40] if raw else ""
        warnings.append(
            f"{KEY} is set to '{shown}' in .env, which OpenAlgo does not recognise, "
            f"so it is starting the default {DEFAULT_WORKER} web server. "
            "Use 'eventlet' or 'gthread'."
        )

    if effective == "eventlet" and not eventlet_available:
        effective = "gthread"
        warnings.append(
            "The eventlet web server is not installed for this OpenAlgo, so it is "
            "starting on the gthread web server instead. Run the updater to "
            "reinstall the dependencies if you want eventlet."
        )
    return effective, requested, warnings


def pids_max_files(
    proc_cgroup: str = "/proc/self/cgroup", cgroup_root: str = "/sys/fs/cgroup"
) -> list[str]:
    """Every pids.max file that can limit this process, nearest first.

    A systemd service's TasksMax lives in its own cgroup, for example
    /sys/fs/cgroup/system.slice/openalgo.service/pids.max, and a slice's limit
    in the folders above it. Only a container with its own cgroup namespace
    sees its limit at the root. So the process's own cgroup is read from
    /proc/self/cgroup and every folder from it up to the root is checked, with
    the two root files kept for cgroup v1 and container namespaces.

    Args:
        proc_cgroup: The process's cgroup membership file.
        cgroup_root: Where the cgroup file system is mounted.

    Returns:
        Candidate file paths; the caller skips the ones that do not exist.
    """
    candidates: list[str] = []
    try:
        with open(proc_cgroup, encoding="ascii") as handle:
            lines = handle.read().splitlines()
    except OSError:
        lines = []
    for line in lines:
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        hierarchy, controllers, path = parts
        if hierarchy == "0" and controllers == "":
            base = cgroup_root  # cgroup v2, one unified hierarchy
        elif "pids" in controllers.split(","):
            base = os.path.join(cgroup_root, "pids")  # cgroup v1 pids controller
        else:
            continue
        segments = [segment for segment in path.split("/") if segment]
        for depth in range(len(segments), -1, -1):
            candidates.append(os.path.join(base, *segments[:depth], "pids.max"))
    for fallback in (
        os.path.join(cgroup_root, "pids.max"),
        os.path.join(cgroup_root, "pids", "pids.max"),
    ):
        if fallback not in candidates:
            candidates.append(fallback)
    return candidates


def thread_limit_warnings(
    threads: int, proc_cgroup: str = "/proc/self/cgroup", cgroup_root: str = "/sys/fs/cgroup"
) -> list[str]:
    """Warn when the operating system would not let the worker start its threads.

    Args:
        threads: The number of request threads the launcher will start.
        proc_cgroup: The process's cgroup membership file (tests only).
        cgroup_root: Where the cgroup file system is mounted (tests only).

    Returns:
        Plain sentences, empty when the limits are comfortably above what
        OpenAlgo needs (the threads plus room for its own background work).
    """
    needed = threads + 256
    notes: list[str] = []
    try:
        import resource

        soft, _hard = resource.getrlimit(resource.RLIMIT_NPROC)
        if soft != resource.RLIM_INFINITY and 0 < soft < needed:
            notes.append(
                f"This user may run at most {soft} processes and threads, and the gthread "
                f"web server needs about {needed}. Raise the limit (LimitNPROC in the "
                "service file) or switch back to eventlet."
            )
    except (ImportError, OSError, ValueError):
        pass
    limits = []
    for path in pids_max_files(proc_cgroup, cgroup_root):
        try:
            with open(path, encoding="ascii") as handle:
                text = handle.read().strip()
        except OSError:
            continue
        if text.isdigit():
            limits.append(int(text))
    if limits and min(limits) < needed:
        notes.append(
            f"This service may run at most {min(limits)} tasks, and the gthread web server "
            f"needs about {needed}. Raise TasksMax in the service file, or the "
            "container's pids limit, or switch back to eventlet."
        )
    return notes


def set_requested(env_file: str, value: str) -> None:
    """Write ``KEY = 'value'`` into ``env_file``, in place.

    Every uncommented assignment of the key is replaced, so python-dotenv's
    last-wins rule sees the new value, and the key is appended when absent.
    Line endings are kept, and the file is rewritten in place so its owner and
    permissions stay exactly as they were.

    Args:
        env_file: The install's ``.env``.
        value: ``eventlet`` or ``gthread``.

    Raises:
        ValueError: ``value`` is not a supported web server.
        OSError: The file could not be read or written.
    """
    if value not in SUPPORTED_WORKERS:
        raise ValueError(f"Unsupported web server: {value!r}")
    with open(env_file, encoding="utf-8", newline="") as handle:
        content = handle.read()
    eol = "\r\n" if "\r\n" in content else "\n"
    new_line = f"{KEY} = '{value}'"
    lines = content.splitlines(keepends=True)
    replaced = False
    for index, line in enumerate(lines):
        if _ASSIGNMENT.match(line):
            ending = line[len(line.rstrip("\r\n")) :]
            lines[index] = new_line + ending
            replaced = True
    if not replaced:
        if lines and not lines[-1].endswith(("\n", "\r")):
            lines[-1] += eol
        lines.append(new_line + eol)
    with open(env_file, "r+", encoding="utf-8", newline="") as handle:
        handle.seek(0)
        handle.write("".join(lines))
        handle.truncate()


def main(argv: list[str] | None = None) -> int:
    """Command line entry point. See the module docstring."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--threads", type=int, default=0)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--shell", action="store_true", help="print KEY=value lines")
    group.add_argument("--print", dest="print_field", choices=("worker", "requested"))
    group.add_argument("--set", dest="set_value", choices=SUPPORTED_WORKERS)
    args = parser.parse_args(argv)

    if args.set_value:
        try:
            set_requested(args.env_file, args.set_value)
        except (OSError, ValueError) as error:
            print(f"Could not update {args.env_file}: {error}", file=sys.stderr)
            return 1
        return 0

    raw = read_requested(args.env_file)
    # Asked only what the operator requested (start.sh), whether eventlet is
    # installed is not this call's business, so it is not reported.
    eventlet_available = args.print_field == "requested" or module_available("eventlet")
    effective, requested, warnings = resolve(raw, eventlet_available)
    if effective == "gthread" and args.threads > 0:
        warnings.extend(thread_limit_warnings(args.threads))
    for line in warnings:
        print(f"[OpenAlgo] {line}", file=sys.stderr)

    if args.print_field == "worker":
        print(effective)
    elif args.print_field == "requested":
        print(requested)
    else:
        print(f"WORKER_CLASS={effective}")
        print(f"REQUESTED={requested}")
        print(f"EVENTLET_AVAILABLE={1 if module_available('eventlet') else 0}")
        print(f"GUNICORN_AVAILABLE={1 if module_available('gunicorn') else 0}")
        print(f"GUNICORN_VERSION={package_version('gunicorn')}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as error:  # the launcher falls back to its own parser
        print(f"[OpenAlgo] Could not read the web server setting: {error}", file=sys.stderr)
        sys.exit(2)
