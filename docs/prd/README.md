# OpenAlgo PRD Index

The current-state PRD for this codebase is:

- [PRD.md](./PRD.md)
- [PRD_TRACEABILITY.md](./PRD_TRACEABILITY.md)
- [CONFLICTS.md](./CONFLICTS.md)

Use `PRD.md` and the linked module contracts for current behavior. Requirements cite code ownership and the BDD documentation specifications. The root phase-1 discovery map is historical provenance; registered routes and current implementation take precedence.

## Inventory Verified On 2026-11-06

- RESTX `/api/v1` method/path pairs: 74 (static registration parity with the API and BDD inventories)
- Broker plugins: 38 (metadata inventory, including Rupeezy and Sahi)
- Tools: 20 (from `frontend/src/lib/tools.ts`)
- RESTX Swagger UI: deliberately disabled (`doc=False`)
- BDD files / scenario definitions / expanded cases: 18 / 138 / 266

The older 500-endpoint/442-blueprint-route totals and dependency versions came from phase-1 discovery and are not maintained runtime counts. Session and feature routes include conditional surfaces such as Remote MCP. Read current application/SDK dependencies from `pyproject.toml`, frontend dependencies from `frontend/package.json`, and acceptance inventory totals from [BDD Coverage](../bdd/README.md).

## Existing Module PRDs

The files below are module-level PRDs. Treat historical modules as secondary
references until reconciled against the current-state PRD. The Strategy Module
and RMS PRD is actively maintained as the current contract for that isolated
surface; if it conflicts with the global PRD, record and resolve the conflict
rather than silently choosing one.

- [Flow](./flow.md)
- [Flow Execution](./flow-execution.md)
- [Flow Node Creation](./flow-node-creation.md)
- [Flow Node Reference](./flow-node-reference.md)
- [Flow UI Components](./flow-ui-components.md)
- [Sandbox](./sandbox.md)
- [Sandbox Architecture](./sandbox-architecture.md)
- [Sandbox Execution Engine](./sandbox-execution-engine.md)
- [Sandbox Margin System](./sandbox-margin-system.md)
- [Strategy Module and RMS](./strategy-module-rms.md)
- [Python Strategies](./python-strategies.md)
- [Python Strategies API Reference](./python-strategies-api-reference.md)
- [Python Strategies Process Management](./python-strategies-process-management.md)
- [Python Strategies Scheduling](./python-strategies-scheduling.md)
- [Historify](./historify.md)
- [Historify API Reference](./historify-api-reference.md)
- [Historify Data Model](./historify-data-model.md)
- [Historify Download Engine](./historify-download-engine.md)
- [WebSocket Proxy](./websocket-proxy.md)
- [Event Bus](./event-bus.md)
- [Remote MCP](./remote-mcp.md)
- [Session Lifecycle](./session-lifecycle.md)
- [Scalping Terminal](./scalping.md)
- [Analytics Tools](./analytics-tools.md)
- [CI/CD](./ci-cd.md)
- [CI/CD Workflows](./ci-cd-workflows.md)
- [CI/CD Security](./ci-cd-security.md)
- [CI/CD Local Development](./ci-cd-local-development.md)
