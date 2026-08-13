# ADR-0003 — In-tree broker model (no out-of-tree plugins)

**Status:** Accepted · 2026-07-13 · **supersedes** the out-of-tree framing in the
earlier design drafts.
**Companion:** [design](../specs/2026-07-13-global-market-architecture-design.md) ·
[roadmap](../roadmap/2026-07-13-phased-roadmap.md)

## Context

Earlier drafts assumed **out-of-tree** installable broker plugins (a published
`openalgo-broker-api` package, entry-point discovery, semver gating). The
[Codex deep audit](../reviews/2026-07-13-codex-review-2-response.md) confirmed
that model is far from the current reality: `pyproject.toml` ships
`packages = []` (non-distributable), and broker dispatch is hard-coded in several
core files. All 34 existing adapters (33 Indian + Delta) are already in-tree.

## Decision

Brokers live **in-tree** — `broker/{name}/` in the OpenAlgo repo, contributed via
**pull request** — implementing the formal `BrokerAdapter` contract as an
**internal repo module** (not a published package). OpenAlgo will **not** support
out-of-tree/installable broker plugins.

## What is KEPT (still valuable in-tree)

- **The formal `BrokerAdapter` contract** — required minimal protocol + optional
  protocols (`HistoricalData`, `Depth`, `GTT` *(experimental)*, `OptionsChain`,
  `Holdings`), typed errors, client-order-id idempotency, structured order model.
  Lives as an in-repo module (e.g. `broker/contract/`).
- **The Capability Manifest** (`plugin.json` v2), extending the existing
  `get_broker_capabilities()`.
- **A unified broker registry** — still needed to replace the hard-coded dispatch
  in `brlogin.py`, `auth_utils.py`, `websocket_proxy/__init__.py`, and
  `broker_factory.py` (and to retire the `deltaexchange_adapter.py` naming alias).
  Its purpose is now **internal decoupling + one place to register a broker**, not
  external discovery.
- **The conformance test suite** — runs in the repo's CI across all in-tree
  adapters.

## What is DROPPED

- The separate, published `openalgo-broker-api` **contract library**.
- **Entry-point discovery** / out-of-tree loader.
- **Semver `contract_version` gating** for external plugins (in-tree brokers
  version with the app; a lightweight internal contract version may remain for
  documentation, but it is not load-bearing).
- Making OpenAlgo **distributable** / publishing to PyPI.

## Consequences

- **Blocker 2 largely dissolves.** `packages = []` is no longer a blocker (nothing
  is distributed). The hard-coded broker dispatch is still worth replacing with the
  registry — but as **code hygiene + a clean contract boundary**, not a hard
  prerequisite for distribution. **P1 simplifies** to: contract module + registry +
  conformance suite (no packaging, no entry-points, no semver gate).
- **P7 changes** — no "clean-environment package installation" proof; instead a
  second crypto venue + US edge cases validated **in-tree**.
- Community contributes brokers exactly like the existing 34 — a PR into the repo,
  validated by the conformance suite.

## Rationale

Simpler, lower-risk, and matches existing practice (34 in-tree brokers). Avoids the
maintenance/versioning/publishing burden of a public package and the security
surface of loading third-party code as installed packages. **Trade-off given up:**
third parties cannot ship a broker without a PR into the repo — acceptable, since
the project already curates brokers and this is a self-hosted, single-user platform.
