---
name: version-bump
description: Bump a version in the OpenAlgo repo. Use when releasing a new OpenAlgo platform version, or when updating the pinned openalgo Python SDK dependency. These are two independent version numbers that live in different files and are frequently confused.
---

# Version bumping

There are **two independent versions** in this repo. Identify which one is being asked for before editing anything.

| Ask | Version | Source of truth |
| --- | --- | --- |
| "Release OpenAlgo 2.0.2", "bump the platform version" | Platform | `utils/version.py` |
| "Update the SDK", "new openalgo on PyPI", "bump openalgo to 1.0.50" | SDK pin | dependency lists |

They are unrelated and never move together. If the request is ambiguous, ask.

## 1. Platform version (e.g. `2.0.1.0`)

OpenAlgo itself. Touches **two files** plus the lockfile. **Never** touch `requirements.txt` or `requirements-nginx.txt` for a platform bump — the platform version does not appear there.

1. `utils/version.py` — `VERSION = "x.y.z.w"` (runtime source of truth, read by `get_version()`)
2. `pyproject.toml` — `version = "x.y.z.w"` (line 4, package metadata)
3. `uv sync` to regenerate `uv.lock`

```bash
# Example: 2.0.1.0 -> 2.0.1.1
# 1. Edit utils/version.py      -> VERSION = "2.0.1.1"
# 2. Edit pyproject.toml line 4 -> version = "2.0.1.1"
uv sync

# Verify
uv run python -c "from utils.version import get_version; print(get_version())"
# -> 2.0.1.1
```

Both files must agree. `utils/version.py` is what the running app reports; `pyproject.toml` is what packaging and CI read. A mismatch means the UI footer and the Docker tag disagree.

The platform version surfaces in the UI footer / about page (via `get_version()`), API responses carrying version metadata, and Docker image tags built by CI.

## 2. OpenAlgo Python SDK pin (e.g. `openalgo==1.0.49`)

A **separate** client library published on PyPI (https://pypi.org/project/openalgo/) that the platform consumes internally. It has its own release cycle. Touches the dependency lists, **not** `utils/version.py`.

1. `pyproject.toml` — the `openalgo==X.Y.Z` entry in the `dependencies` list
2. `requirements.txt` — the `openalgo==X.Y.Z` line
3. `requirements-nginx.txt` — the `openalgo==X.Y.Z` line
4. `uv sync` to regenerate `uv.lock`

All three files must be updated together. Missing one means a deploy path installs a different SDK version than the others — `requirements-nginx.txt` is the one most often forgotten.

## Committing

Use a Conventional Commit. No emojis or icons anywhere in the message.

```
chore(release): bump platform to 2.0.1.1
```
```
chore(deps): bump openalgo SDK to 1.0.50
```

Do not commit or push unless the user asked for it.
