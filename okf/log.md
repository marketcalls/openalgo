# Update Log

## 2026-07-03
* **Refactor**: Converted the bundle to **mapping-only** — every concept is now a thin pointer to its source doc (under `docs/` or docs.openalgo.in), with no duplicated bodies. OKF serves purely as a tagged, cross-linked index/graph over the single-source-of-truth docs; see [`docs/INDEX.md`](../docs/INDEX.md).
* **Creation**: Added the [skills](skills/index.md) section (agentic execution / indicator / backtesting skill packages), the [installation](installation/index.md) section (upgrade, SMTP, TOTP, forgot-password), and the [user responsibilities](responsibilities.md) concept.
* **Creation**: Added the [tools](tools/index.md) section — the [Scalping Terminal](tools/scalping.md) (`/scalping`) and [Options Trading Suite](tools/options-suite.md) (`/tools`) — and surfaced both in the platform [overview](overview.md).
* **Update**: Corrected the [Python SDK](sdk/python-sdk.md) install to a single `pip install openalgo`, and documented the [indicator library](indicators/introduction.md) as a Rust-backed PyO3 extension bundled in the base package (no `openalgo[indicators]` extra / no optional dependencies).
* **Initialization**: Built the OpenAlgo OKF bundle from the project docs — converted the REST API reference (`docs/api/`), the SDK & format references and indicator library (`docs/prompt/`), and the platform [overview](overview.md) (`CLAUDE.md`) into OKF concepts.
* **Creation**: Established the top-level structure — [api](api/index.md), [sdk](sdk/index.md), and [indicators](indicators/index.md) — with an auto-generated index at each level.
