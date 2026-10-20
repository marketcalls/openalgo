# Chart and MCP dependency upgrade implementation plan

> For agentic workers: use superpowers:executing-plans to implement this plan in the current session.

**Goal:** Upgrade `/trading` and Historify charts to 2.6.6 and resolve the open MCP dependency advisory, then validate, commit and push directly to main.

**Architecture:** Both chart pages consume the same pinned package. Keep their existing hosts and order permissions. Upgrade the MCP SDK within its 1.x line and synchronize all Python installation paths.

**Tech stack:** React, TypeScript, Vite, openalgo-charts, Python, uv, MCP SDK.

**Spec:** User request of 2026-10-17 and the repository's `CLAUDE.md`.

## Constraints and review focus

- Direct commit and push to main, no pull request; no platform version bump.
- Preserve order authority, quantity units, replay restrictions and saved layouts.
- Historify remains read-only and uses downloaded history.
- Check changing and missing indicator readings, narrow charts, Settings, visibility and deletion.
- Preserve MCP tool registration, scope checks, session cleanup and eventlet/gthread compatibility.
- Keep generated metadata exact; exclude locally built `frontend/dist` from the source commit.

## Task 1: Chart package and host validation

Files: `frontend/package.json`, `frontend/package-lock.json`, chart-indicator skill references, generated chart metadata if changed, chart browser validation and `docs/CHANGELOG.md`.

- [x] Confirm the baseline dependency and main CI; test current chart-related code.
- [x] Pin `openalgo-charts` to 2.6.6, regenerate the API index and chart glyph metadata, and update the skill's version teaching.
- [x] Run chart/Historify tests, typecheck, generated-file checks, skill coverage and production build.
- [x] Run actual `/trading` and Historify browser checks across Chromium, Firefox and WebKit, including light, dark and Analyze views where applicable. Inspect screenshots.

## Task 2: MCP advisory and publication

Files: `pyproject.toml`, `requirements.txt`, `requirements-nginx.txt`, `uv.lock`, relevant dependency regression coverage and `docs/CHANGELOG.md`.

- [x] Upgrade `mcp` from 1.28.1 to the patched 1.30.0 across all manifests and the lockfile.
- [x] Review upstream behavior changes and the application's transport usage; verify MCP integrity, scope checks and requirements parity.
- [x] Run the complete gthread suite on Linux before committing; audit resource lifecycle changes.
- [ ] Obtain an independent final diff review, commit source changes on main and push main.
- [ ] Verify CI, the automated frontend build commit and closure of Dependabot alerts 462 through 465; synchronize the local checkout.
