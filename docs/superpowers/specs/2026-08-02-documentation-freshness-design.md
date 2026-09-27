# Repository Documentation Freshness Design

**Date:** 2026-08-02

**Objective:** Refresh OpenAlgo's current documentation and root README against the
current `main` codebase after the preceding month of feature and bug-fix work, and
produce reproducible evidence for every freshness claim.

## Scope and source of truth

The current repository is authoritative. Documentation claims must be derived from
the implementation or from an explicitly identified external contract. Commit
messages identify likely change surfaces but are not evidence that a feature works
or that a document is correct.

The refresh covers:

- `README.md`, `INSTALL.md`, `CONTRIBUTING.md`, `DOCKER_README.md`, and other
  current root-level operator/developer references;
- current material under `docs/api`, `docs/design`, `docs/docker`,
  `docs/installation-guidelines`, `docs/prd`, `docs/prompt`, `docs/test`, and
  `docs/userguide`;
- current standalone references under `docs/`, including the documentation index,
  MCP, WebSocket, broker integration, health monitoring, and messaging guides;
- documentation discoverability for major features added or materially changed
  during 2026-07-02 through 2026-08-02.

The following are historical evidence and are not rewritten to describe current
behavior:

- dated release notes, audits, benchmarks, migration plans, implementation plans,
  decisions, reviews, and specifications;
- BDD feature files that describe an accepted historical contract, unless the
  current behavior deliberately supersedes that contract;
- generated benchmark datasets.

Historical files may receive a non-invasive status notice or index entry when a
reader could otherwise mistake them for current operating guidance. Their original
findings, measurements, and decisions remain intact.

## Definition of freshness

"Fresh" does not mean that every file receives today's date. A current document is
fresh only when all of the following are true:

1. Its named routes, commands, files, environment keys, versions, counts, defaults,
   runtime behavior, and supported platforms agree with current code and config.
2. Every material current feature has an indexed user, API, operator, or developer
   reference appropriate to its audience.
3. Internal Markdown links, anchors, and referenced repository paths resolve.
4. Examples use current public request and response contracts and do not expose
   internal or removed APIs.
5. Commands are either executed safely or validated structurally in the environment
   for which they are documented.
6. A generated freshness report records the evidence and any validation that cannot
   run locally, such as credentialed live-broker behavior.

No file is marked fresh merely because a search failed to find a known stale term.

## Evidence inventories

The audit derives machine-readable inventories from these authoritative surfaces:

| Inventory | Authoritative source |
| --- | --- |
| Product pages and routes | `frontend/src/App.tsx` and registered Flask blueprints |
| REST API endpoints | `restx_api/__init__.py` and namespace route declarations |
| Broker plugins | importable broker directories plus installer/frontend broker lists |
| Runtime and deployment | `app.py`, `start.sh`, `Dockerfile`, compose and `install/` scripts |
| Configuration | `.sample.env` and code-level environment lookups/defaults |
| Dependencies and versions | `pyproject.toml`, lockfiles, package manifests, `utils/version.py` |
| Databases | database modules, engine/session factories, and upgrade scripts |
| Realtime behavior | `extensions.py`, `websocket_proxy`, subscribers, and frontend clients |
| Background execution | schedulers, executors, bot services, sandbox, Flow, and `/python` |
| Last-month change set | Git history from 2026-07-02 through the audited commit |

Inventories are compared with their documentation indexes. Differences become
explicit refresh tasks rather than silent omissions.

## Refresh organization

The work is divided into independently reviewable batches:

1. **Navigation and project summary:** root README and documentation indexes.
2. **New and changed product features:** portfolio analyzer/backtester, Flow nodes
   and validation, charting improvements, search behavior, indicators and skills.
3. **Trading and broker behavior:** order-update WebSockets, funds/holdings fixes,
   SL-M handling, supported-broker inventory, and order contracts.
4. **Operations and security:** multi-architecture images, installation/update and
   backup behavior, dependency/security changes, logging, and database contention.
5. **Reference parity:** REST routes, WebSocket formats, MCP, Telegram/WhatsApp,
   sandbox, Historify, `/python`, and environment configuration.
6. **Historical classification:** indexes and notices without rewriting evidence.

Each batch updates only documents whose claims can be traced to inspected code.

## Validation model

Documentation validation has four layers:

1. **Structural documentation checks:** Markdown links, local anchors, referenced
   repository paths, duplicate/missing index entries, and generated inventory drift.
2. **Static code/config checks:** Python compilation/import-safe inventories, Ruff,
   frontend lint and TypeScript build, shell syntax, Docker Compose rendering, and
   configuration-key parity.
3. **Automated behavior checks:** the full credential-free Python test suite and
   frontend unit tests. Browser E2E and Docker smoke tests run when their required
   local dependencies are available.
4. **Explicit external boundaries:** live broker, external webhook, messaging, and
   production TLS behavior are not inferred from local tests. Their documents are
   checked against code contracts and marked as requiring credentialed/manual
   verification where appropriate.

Failures are reported rather than hidden. Existing unrelated failures do not make a
document fresh; they are recorded with the exact command and scope they prevent from
proving.

## Deliverables

- Updated `README.md` and current/reference documentation.
- Updated documentation indexes that distinguish current guidance from historical
  records.
- A dated freshness audit under `docs/audit/` containing the audited commit,
  inventories, changed surfaces, commands run, results, and residual external
  validation boundaries.
- Reproducible documentation-checking scripts or tests for claims that otherwise
  drift repeatedly, especially route, broker, environment-key, and link parity.

## Completion criteria

Completion requires all current documentation files to be classified and checked,
all discovered discrepancies to be corrected or explicitly bounded, README to agree
with current code, documentation validation to pass, and all feasible repository
validation commands to have current recorded results. Historical artifacts must be
discoverable without being misrepresented as current documentation.

The final report must not claim runtime or live-broker verification for behavior that
was only inspected statically.
