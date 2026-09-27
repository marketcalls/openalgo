# Repository Documentation Freshness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make OpenAlgo's current documentation and root README agree with the
2026-08-02 `main` implementation, while preserving dated historical evidence and
recording reproducible validation results.

**Architecture:** A repository-local checker derives stable inventories from code
and validates documentation structure. The refresh is split by audience and product
surface so each batch can be reviewed against authoritative implementation files.
Historical documents are classified and indexed, not rewritten.

**Tech Stack:** Python 3.12, Markdown, Git, Ruff, pytest, Biome, TypeScript/Vite,
Vitest, Playwright, POSIX shell, Docker Compose.

## Global Constraints

- Audit current `main` from 2026-07-02 through 2026-08-02; do not use commit
  messages as proof of current behavior.
- Preserve release notes, dated audits, benchmarks, migration records, plans,
  decisions, reviews, and specifications as historical evidence.
- Do not claim live-broker, messaging-provider, webhook-provider, production TLS,
  or market-hours validation from local/static checks.
- Use current code, config, manifests, tests, and safe command output as sources of
  truth.
- Every changed factual claim must name or be traceable to an authoritative source.
- README and current documentation indexes must be updated before completion.
- Completion requires a dated audit with commands, results, and explicit external
  validation boundaries.

---

### Task 1: Add a reproducible documentation freshness checker

**Files:**
- Create: `scripts/check_docs_freshness.py`
- Create: `test/test_docs_freshness.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: repository root, Markdown files, `frontend/src/App.tsx`,
  `restx_api/__init__.py`, `.sample.env`, and broker directories.
- Produces: `python scripts/check_docs_freshness.py` with exit code 0 on a clean
  inventory/link/path audit and nonzero on drift; importable pure functions for
  pytest.

- [ ] **Step 1: Write failing unit tests for path and anchor validation**

  Add fixtures that cover a valid relative link, a missing local file, a valid
  heading anchor, a missing anchor, an external URL exclusion, and links containing
  spaces or fragments. Assert diagnostics contain the source file and line.

- [ ] **Step 2: Write failing inventory tests**

  Assert the checker extracts `/portfolio-backtester`, `/portfolio-analyzer`,
  `/flow`, `/python`, `/historify`, and `/trading` from `frontend/src/App.tsx`;
  extracts every `api.add_namespace(..., path=...)` path; lists only importable
  broker plugin directories; and extracts keys from `.sample.env` without values.

- [ ] **Step 3: Run the tests and confirm failure**

  Run: `uv run pytest test/test_docs_freshness.py -v`

  Expected: failures because `scripts/check_docs_freshness.py` does not exist.

- [ ] **Step 4: Implement the checker**

  Use `pathlib`, `ast`, and regular expressions from the standard library. Avoid
  importing the Flask app or broker SDKs. Validate Markdown links and repository
  paths, expose the four inventory functions used by the tests, and print a concise
  summary plus actionable diagnostics.

- [ ] **Step 5: Make freshness checks a CI gate**

  Add a non-optional `docs-freshness` job that runs `uv sync`,
  `uv run pytest test/test_docs_freshness.py -v`, and
  `uv run python scripts/check_docs_freshness.py`.

- [ ] **Step 6: Verify Task 1**

  Run:

  ```bash
  uv run pytest test/test_docs_freshness.py -v
  uv run python scripts/check_docs_freshness.py
  ```

  Expected: tests pass; the checker may report existing documentation drift for
  later tasks, but its self-tests prove that drift causes a nonzero exit.

### Task 2: Create the freshness classification and evidence ledger

**Files:**
- Create: `docs/audit/2026-08-02-documentation-freshness.md`
- Modify: `docs/INDEX.md`
- Modify: `docs/audit/README.md`

**Interfaces:**
- Consumes: Task 1 inventories, `git log --since=2026-07-02`, and all 302 files
  under `docs/`.
- Produces: a complete file classification (`current`, `historical`, `generated`,
  or `contract`) and an evidence ledger for every current documentation family.

- [ ] **Step 1: Record audit identity and boundaries**

  Include the audited commit, date range, repository status, file totals by family,
  and the distinction between local verification and credentialed/manual behavior.

- [ ] **Step 2: Classify every documentation family**

  Classify root references and each top-level `docs/` family. Enumerate standalone
  files individually. For historical families, state that contents remain
  point-in-time evidence. For current families, name their authoritative code
  sources and validation method.

- [ ] **Step 3: Add recent-change coverage**

  Map the material July/August surfaces: portfolio, Flow, trading charts, search,
  indicators/skills, order-update WebSockets, broker funds/holdings and SL-M fixes,
  multi-architecture Docker, backups, security dependency changes, logging, and
  database contention.

- [ ] **Step 4: Update documentation navigation**

  Make `docs/INDEX.md` the entry point for current references and historical
  records. Update `docs/audit/README.md` so dated audit findings are not presented as
  the current global security posture.

- [ ] **Step 5: Verify Task 2**

  Run the checker and confirm every top-level docs family and standalone file is
  classified exactly once.

### Task 3: Refresh the root README and primary navigation

**Files:**
- Modify: `README.md`
- Modify: `INSTALL.md`
- Modify: `CONTRIBUTING.md`
- Modify: `DOCKER_README.md`
- Modify: `DISCOVERY_MAP.md`
- Modify: `docs/design/README.md`
- Modify: `docs/userguide/README.md`
- Modify: `docs/api/README.md`
- Modify: `docs/prd/README.md`

**Interfaces:**
- Consumes: current frontend/API/broker/config/dependency inventories.
- Produces: accurate project overview, feature navigation, supported-platform and
  development instructions.

- [ ] **Step 1: Reconcile README counts and feature list**

  Replace hand-maintained broker, tool, route, and feature counts with verified
  values or wording that does not drift. Add Portfolio Backtester/Analyzer, current
  Flow capabilities, trading chart improvements, order-update feeds, indicator
  analysis tooling, and current security/operations behavior.

- [ ] **Step 2: Reconcile technology and version claims**

  Check Python, Flask, React, TypeScript, database, WebSocket, Docker, SDK, and
  testing statements against manifests and runtime files. Do not list transitive
  dependencies as intentional architecture.

- [ ] **Step 3: Refresh installation and contributor commands**

  Match `uv`, Python, Node, Docker, environment setup, frontend build, test, lint,
  and upgrade commands to current manifests and scripts. Mark commands that require
  credentials or platform services.

- [ ] **Step 4: Refresh primary indexes**

  Add all current major surfaces and eliminate duplicate, missing, or misleading
  navigation. Link historical design/PRD material through its classification.

- [ ] **Step 5: Verify Task 3**

  Compare README routes, brokers, platform support, and commands to the generated
  inventories; run the docs checker.

### Task 4: Document Portfolio Backtester and Analyzer

**Files:**
- Create: `docs/userguide/32-portfolio-backtester/README.md`
- Create: `docs/design/55-portfolio-analytics/README.md`
- Create: `docs/api/portfolio.md`
- Modify: `docs/userguide/README.md`
- Modify: `docs/design/README.md`
- Modify: `docs/api/README.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: `portfolio/`, `services/portfolio_service.py`,
  `restx_api/portfolio.py`, `frontend/src/pages/PortfolioBacktester.tsx`,
  `PortfolioBacktestResults.tsx`, and `PortfolioAnalyzer.tsx`.
- Produces: user workflow, public API contract, architecture/data-source/cost model,
  and limitations.

- [ ] **Step 1: Trace the public request/response contract**

  Document `/api/v1/portfolio/benchmarks`, `/backtest`, `/tearsheet`, and
  `/holdings` from models and serialization code, including validation and error
  status behavior.

- [ ] **Step 2: Document user workflows**

  Cover backtest configuration, benchmark and data-source choice, results page,
  tearsheet export, broker-holdings analysis, costs, rebalancing, walk-forward,
  Monte Carlo, crisis, attribution, health score, correlation, seasonality, and the
  limitations surfaced by the UI.

- [ ] **Step 3: Document architecture and safety boundaries**

  Explain Historify versus broker history, DuckDB/cache behavior, holdings data,
  charge schedules, clean-install dependencies, and why analysis does not place
  orders.

- [ ] **Step 4: Verify Task 4**

  Run:

  ```bash
  uv run pytest test/test_portfolio_engine.py test/test_portfolio_service.py test/test_portfolio_api.py -v
  uv run python scripts/check_docs_freshness.py
  ```

### Task 5: Refresh Flow documentation

**Files:**
- Modify: `docs/userguide/21-flow-visual-builder/README.md`
- Modify: `docs/design/10-flow-architecture/README.md`
- Modify: `docs/prd/flow.md`
- Modify: `docs/prd/flow-execution.md`
- Modify: `docs/prd/flow-node-reference.md`
- Modify: `docs/prompt/flow-import-format.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: Flow frontend node registry/config, workflow validator, executor,
  scheduler, price/order monitors, strategy book/P&L service, and JSON updater.
- Produces: exact node inventory, import/replace contract, validation semantics,
  scheduling/calendar behavior, execution guards, and strategy P&L shape.

- [ ] **Step 1: Generate and reconcile node inventory**

  Compare node types, handles, defaults, and configuration fields across frontend
  types/constants/palette/panels and backend validator/executor.

- [ ] **Step 2: Refresh import and replacement contracts**

  Document output-first JSON shape, replace-workflow behavior, complex patterns,
  response/error semantics, and the intentional single-trigger rule.

- [ ] **Step 3: Refresh execution behavior**

  Document central validation, one-evaluation logic gates, price-alert lifecycle,
  special sessions, calendar nodes, history series/lookback ceilings, order-update
  nodes, per-strategy books, and P&L output.

- [ ] **Step 4: Verify Task 5**

  Run:

  ```bash
  uv run pytest test/test_flow_workflow_validator.py -v
  uv run python scripts/check_docs_freshness.py
  ```

### Task 6: Refresh trading, broker, and realtime documentation

**Files:**
- Modify: `docs/userguide/06-broker-connection/README.md`
- Modify: `docs/userguide/10-placing-first-order/README.md`
- Modify: `docs/userguide/11-order-types/README.md`
- Modify: `docs/userguide/31-tools/README.md`
- Modify: `docs/design/06-websockets/README.md`
- Modify: `docs/design/17-connection-pooling/README.md`
- Modify: `docs/design/19-placeorder-flow/README.md`
- Modify: `docs/design/33-broker-folder/README.md`
- Modify: `docs/design/46-search/README.md`
- Modify: `docs/design/52-broker-factory/README.md`
- Modify: `docs/websocket-architecture.md`
- Modify: `docs/websocket-quote-feed.md`
- Modify: `docs/broker-integration-guide.md`
- Modify: relevant current `docs/api/` order, account, market-data, and WebSocket files
- Modify: `README.md`

**Interfaces:**
- Consumes: broker plugins/mappings/streaming adapters, order-update service,
  WebSocket proxy, trading frontend, search ranking, and public REST models.
- Produces: current broker inventory, supported order/update behavior, chart/search
  features, and accurate realtime topology/protocol.

- [ ] **Step 1: Reconcile broker inventory everywhere**

  Compare broker directories with app imports, frontend broker names, installer
  lists, and documentation. Explain sandbox-only plugins separately.

- [ ] **Step 2: Refresh broker behavior changed in the last month**

  Cover live order-update feeds, token refresh, funds and holdings semantics,
  resting SL modify/cancel, protective SL-LMT handling, price tick rounding, and
  connection cleanup only where supported by inspected adapters.

- [ ] **Step 3: Refresh chart, tools, and search behavior**

  Document current `/trading` drawing/indicator/text/volume controls, history
  backfill, route and tool inventory, relevance-ranked symbol search, and index
  labeling.

- [ ] **Step 4: Refresh realtime topology and contracts**

  Reconcile Socket.IO, raw WebSocket port 8765, ZeroMQ roles, subscription modes,
  order updates, pooling, reconnect, frontend ownership, and verbose-control docs
  against code.

- [ ] **Step 5: Verify Task 6**

  Run broker-independent mapping/order/WebSocket tests, including
  `test/test_order_update_adapters.py`, `test/test_smartorder_logic.py`, and current
  search/navigation tests, followed by the docs checker.

### Task 7: Refresh operations, security, and environment documentation

**Files:**
- Modify: `docs/design/05-security-architecture/README.md`
- Modify: `docs/design/11-docker/README.md`
- Modify: `docs/design/12-ubuntu-server/README.md`
- Modify: `docs/design/28-environment-config/README.md`
- Modify: `docs/design/30-upgrade-procedure/README.md`
- Modify: `docs/design/34-app-startup/README.md`
- Modify: `docs/design/35-development-testing/README.md`
- Modify: `docs/docker/*.md`
- Modify: `docs/installation-guidelines/getting-started/ubuntu-server-installation.md`
- Modify: `docs/userguide/04-installation/README.md`
- Modify: `docs/userguide/27-security-settings/README.md`
- Modify: `docs/userguide/29-troubleshooting/README.md`
- Modify: `INSTALL.md`
- Modify: `DOCKER_README.md`

**Interfaces:**
- Consumes: Dockerfile, CI workflow, compose, start/install/update/backup scripts,
  `.sample.env`, security middleware, dependency manifests, database setup, and
  runtime logging.
- Produces: current installation, upgrade, backup, runtime, security, troubleshooting,
  and configuration guidance.

- [ ] **Step 1: Reconcile multi-architecture Docker behavior**

  Document native amd64/arm64 CI builds, manifest tags, image smoke tests, and the
  difference between image health and credentialed broker health.

- [ ] **Step 2: Refresh installation, update, and backup behavior**

  Trace every supported Docker/native script. Document volume discovery and backup
  failure behavior from current code; remove stale commands and path assumptions.

- [ ] **Step 3: Reconcile environment keys and defaults**

  Compare `.sample.env` with code lookups and current docs. Document security-sensitive
  keys without values and distinguish required, optional, Docker-only, and
  integration-specific settings.

- [ ] **Step 4: Refresh security and dependency statements**

  Record current session/CSRF/CSP/rate-limit/TOTP behavior and supported dependency
  versions. Do not copy historical audit ratings into current guidance.

- [ ] **Step 5: Verify Task 7**

  Run shell syntax checks for maintained scripts, `docker compose config`, relevant
  install/backup tests, environment inventory parity, and the docs checker.

### Task 8: Refresh remaining current references

**Files:**
- Modify: current files under `docs/api/`, `docs/prd/`, `docs/prompt/`,
  `docs/test/`, and `docs/userguide/` not completed in Tasks 3-7
- Modify: `docs/mcp-tool-reference.md`
- Modify: `docs/telegram-chart-rendering.md`
- Modify: `docs/whatsapp.md`
- Modify: `docs/HEALTH_MONITORING_IMPLEMENTATION.md`
- Modify: `docs/HEALTH_MONITOR_REACT_FRONTEND.md`
- Modify: `docs/scanner-architecture.md`
- Modify: `docs/xtsapi.md`

**Interfaces:**
- Consumes: MCP OAuth/HTTP/tools, Telegram/WhatsApp services and APIs, health and
  diagnostics, sandbox, Historify, `/python`, scalping, scanner, and XTS code.
- Produces: current contracts and user/developer guidance for all remaining active
  surfaces.

- [ ] **Step 1: Reconcile REST documentation with registered namespaces**

  Every registered public namespace must be indexed once. Document the Portfolio,
  chart workspace, multi-option-greeks, GTT, market calendar, P&L symbols,
  messaging, and preference endpoints from current models.

- [ ] **Step 2: Reconcile MCP and messaging**

  Compare MCP enablement, OAuth, SSE, quotas, audit, and tool inventory to code.
  Compare Telegram/WhatsApp configuration, lifecycle, alerts, chart rendering, and
  public API routes to services and models.

- [ ] **Step 3: Reconcile background and analytical features**

  Refresh sandbox, Historify, `/python`, strategy scheduling, scalping risk,
  scanner, health/diagnostics, and XTS guidance. State process/thread/session and
  external-service boundaries accurately.

- [ ] **Step 4: Verify Task 8**

  Run the corresponding credential-free tests by surface and the docs checker.

### Task 9: Resolve every structural documentation finding

**Files:**
- Modify: any current Markdown file reported by `scripts/check_docs_freshness.py`
- Modify: `scripts/check_docs_freshness.py` only when a demonstrated valid Markdown
  construct is falsely rejected
- Modify: `test/test_docs_freshness.py` for every checker correction

**Interfaces:**
- Consumes: all refreshed documentation.
- Produces: zero unresolved internal link, anchor, repository path, route-index,
  broker-index, or environment-key freshness errors.

- [ ] **Step 1: Run the checker and save the complete diagnostic list**

  Do not truncate findings. Group by broken links, anchors, paths, inventories, and
  historical classification.

- [ ] **Step 2: Fix current documentation findings**

  Correct source links or factual references. Do not create fake files or weaken
  validation to make stale documentation pass.

- [ ] **Step 3: Handle historical findings without rewriting history**

  Exclude dated historical contents from current-contract parity, but keep their
  repository links valid when practical and document unavoidable references to
  removed historical files in the audit.

- [ ] **Step 4: Verify Task 9**

  Run:

  ```bash
  uv run pytest test/test_docs_freshness.py -v
  uv run python scripts/check_docs_freshness.py
  ```

  Expected: both exit 0 with zero unclassified current documentation findings.

### Task 10: Run repository-wide validation and close the evidence ledger

**Files:**
- Modify: `docs/audit/2026-08-02-documentation-freshness.md`
- Modify: `README.md` and current docs only if validation exposes a discrepancy

**Interfaces:**
- Consumes: completed documentation refresh and current repository.
- Produces: final evidence for each explicit objective and a precise residual
  external/manual validation list.

- [ ] **Step 1: Run backend structural validation**

  ```bash
  uv run python -m compileall -q .
  uv run ruff check .
  uv run ruff format --check .
  uv run pytest -v
  ```

  Record exact exit codes, counts, skips, failures, and known credential/platform
  boundaries. Do not describe Ruff's existing non-gating CI state as passing.

- [ ] **Step 2: Run frontend validation**

  ```bash
  cd frontend
  npm run lint
  npm run build
  npm run test:run
  npm run test:coverage
  ```

  Run Playwright Chromium E2E when browsers and required local services are
  available; otherwise record the exact unmet prerequisite.

- [ ] **Step 3: Run deployment/config validation**

  Validate maintained shell scripts with `bash -n`, render `docker compose config`,
  build or inspect the Docker image when the daemon is available, and execute the
  repository's existing installer/backup smoke tests.

- [ ] **Step 4: Run final documentation validation**

  ```bash
  uv run pytest test/test_docs_freshness.py -v
  uv run python scripts/check_docs_freshness.py
  git diff --check
  ```

- [ ] **Step 5: Perform requirement-by-requirement completion audit**

  In the freshness audit, map: updated `docs/`, updated README, last-month feature
  coverage, code validation, current-file classification, historical preservation,
  and external validation boundaries to authoritative evidence.

- [ ] **Step 6: Commit coherent documentation batches**

  Keep checker, indexes/README, feature docs, operations docs, remaining references,
  and final audit in reviewable commits. Each commit must pass its scoped checks.
