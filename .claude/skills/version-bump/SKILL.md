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

### Release notes are part of the bump, not a follow-up

A platform bump is only half a release. Every recent release commit also adds a
notes file — the last one was literally titled "bump platform to 2.0.1.6 **and
add release notes**" and touched four paths:

```
utils/version.py
pyproject.toml
uv.lock
docs/releases/version-2.0.1.6-released.md      <- the user-facing half
```

Create `docs/releases/version-<x.y.z.w>-released.md` following the existing
files in that directory. The established structure:

1. `# Version <x.y.z.w> Released` and `**Date: <Nth Month Year>**`
2. A one-paragraph bold summary naming the release theme
3. A prose overview stating the commit count since the previous tag and what
   changed at a system level
4. `**Highlights**` — a bullet per significant change, **each citing its commit
   SHA** (and issue number where one exists), e.g.
   `**HDFC Sky broker integration (`cb4ec7d56` + 9 follow-up fixes)** — ...`

Get the commit range with:

```bash
git log --oneline v<previous>..HEAD | wc -l        # commit count for the summary
git log --oneline v<previous>..HEAD                # source material for highlights
```

If no tags exist, diff against the previous release notes file's date.

**`docs/CHANGELOG.md` is for major releases only.** It was last written for
2.0.0.0 and is not updated per point release — do not add a stanza there for a
routine bump.

### Order of work

1. `utils/version.py` and `pyproject.toml`
2. `uv sync`
3. Write `docs/releases/version-<x.y.z.w>-released.md`
4. Verify: `uv run python -c "from utils.version import get_version; print(get_version())"`
5. Commit all four paths together — a version bump without its notes leaves the release undocumented, and the notes are what users actually read.

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
