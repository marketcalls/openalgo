# Workspace documents and storage implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task. Continuous native execution and local commits are authorized.

**Goal:** Provide the shared, portable document and asynchronous persistence layer for named workspaces and indicator templates.

**Architecture:** Add a DOM-free, optional `openalgo-charts/workspace` tier. Validate and project chart configuration into versioned documents, then perform serialized catalog transactions through an asynchronous storage adapter. Host integration follows this foundation and remains required by the overall spec.

**Tech Stack:** TypeScript, Vitest, Rollup, existing chart state contracts.

**Spec:** `docs/superpowers/specs/2026-09-19-production-workspace-design.md`

## Global constraints

- No comparison product names in changes, commit messages or PR material.
- UTC seconds for chart data; document creation/update metadata uses epoch milliseconds.
- Workspace files never contain credentials, orders, positions, balances or the armed flag.
- No series data or executable callbacks in exported configuration.
- Existing entry points and options retain their behaviour. New functionality is opt-in.
- Local commits only; no publishing, pushing or live orders.

## Review focus

- Imported configuration can have getters, cycles, dangerous keys or oversized arrays; reject unsafe structure without executing accessors.
- Multiple indicators with the same descriptor must retain separate settings, visibility and pane placement.
- A rejected storage write must not become a successful save in memory or prevent the next operation from succeeding.
- Queued mutations must use the latest persisted revision and retain their original account namespace.
- An imported document must create a new identity instead of replacing an unrelated saved workspace.

## Task 1: Portable documents

Files: `src/workspace/documents.ts`, `src/workspace/index.ts`, `tests/workspace-documents.test.ts`.

Produces:

```ts
interface WorkspacePane {
  id: string; symbol: string; exchange: string; interval: string; chartType: string;
  chart: WorkspaceChartState; settings: Record<string, string | number | boolean>;
  volume: boolean; magnet: 'off' | 'weak' | 'strong'; stay: boolean;
  comparisons: WorkspaceComparison[]; comparisonMode: 'price' | 'percent';
  historyPeriod?: string;
}
interface WorkspacePayload {
  layout: { rows: number; columns: number; slots: WorkspaceSlot[]; preset?: string };
  panes: WorkspacePane[]; activePaneId: string;
  sync: { crosshair: boolean; viewport: boolean; symbol: boolean; interval: boolean };
}
interface WorkspaceDocument extends WorkspacePayload {
  kind: 'workspace'; version: 1; id: string; name: string;
  createdAt: number; updatedAt: number;
}
interface IndicatorTemplateDocument {
  kind: 'indicator-template'; version: 1; id: string; name: string;
  createdAt: number; updatedAt: number; indicators: IndicatorState[];
}
```

Each slot names one pane and its integer row/column/span. A layout permits up to 16 panes, dimensions up to 8 by 8, no overlapping cells, and exactly one slot per pane. Indicator lists permit up to 256 instances. Names trim to 1-120 characters. Documents permit at most 5 MB of serialized text, depth 32 and 100,000 JSON nodes. Unknown top-level fields are not copied. Nested reserved trading/credential keys are removed; arbitrary user text is data and must never be executed.

- [x] Write fixtures containing two independent panes and repeated EMA descriptors; assert exact round trips and no shared mutable references:

```ts
const saved = parseWorkspaceDocument(input);
expect(saved.panes.map(p => p.interval)).toEqual(['5m', '1h']);
input.panes[0].chart.indicators[0].settings.period = 999;
expect(saved.panes[0].chart.indicators[0].settings.period).toBe(9);
```

- [x] Run `npm test -- tests/workspace-documents.test.ts`. Expected: FAIL because the workspace parser does not exist.
- [x] Implement `parseWorkspaceDocument(input: unknown): WorkspaceDocument`, `parseIndicatorTemplate(input: unknown): IndicatorTemplateDocument`, `parseWorkspacePayload(input: unknown): WorkspacePayload`, `parseIndicatorStates(input: unknown): IndicatorState[]`, and `WorkspaceDocumentError`. First copy bounded plain JSON through own property descriptors, rejecting accessors/functions/cycles/nonfinite values. Project only supported document and chart-state fields; validate versions, required strings, grids and references before returning.
- [x] Implement `migrateWidgetWorkspace(input: unknown, metadata: { id: string; name: string; now: number }): WorkspaceDocument` for the existing version-1 widget state. Map symbol/exchange/interval/chartType/chart into one `p0` slot, retain rail magnet/stay and theme through settings, and omit execution state. Reject other shapes without mutating them.
- [x] Exercise malformed versions, overlapping/out-of-bounds slots, duplicate pane IDs, missing focus, empty templates, unsupported custom IDs, getters, prototype keys, cycles, large/deep input and reserved fields nested in settings/drawings. Run the document tests and typecheck. Expected: PASS.
- [x] Commit the document implementation and regression evidence locally.

## Task 2: Asynchronous catalog repository

Files: `src/workspace/repository.ts`, `src/workspace/index.ts`, `tests/workspace-repository.test.ts`.

Consumes Task 1's validated documents. Produces:

```ts
interface WorkspaceCatalog {
  version: 1; revision: number; workspaces: WorkspaceDocument[];
  templates: IndicatorTemplateDocument[]; recentWorkspaceIds: string[];
  activeWorkspaceId: string | null; autosave: boolean;
}
interface WorkspaceStorage {
  read(namespace: string): Promise<unknown | null>;
  write(namespace: string, catalog: WorkspaceCatalog, expectedRevision: number): Promise<void>;
}
class WorkspaceRepository {
  constructor(storage: WorkspaceStorage, namespace: string, options?: { now?: () => number; id?: () => string });
  load(): Promise<WorkspaceCatalog>;
  createWorkspace(name: string, payload: WorkspacePayload): Promise<WorkspaceDocument>;
  saveWorkspace(id: string, payload: WorkspacePayload): Promise<WorkspaceDocument>;
  createTemplate(name: string, indicators: IndicatorState[]): Promise<IndicatorTemplateDocument>;
  rename(kind: 'workspace' | 'indicator-template', id: string, name: string): Promise<void>;
  duplicate(kind: 'workspace' | 'indicator-template', id: string, name: string): Promise<WorkspaceDocument | IndicatorTemplateDocument>;
  remove(kind: 'workspace' | 'indicator-template', id: string): Promise<void>;
  openWorkspace(id: string): Promise<WorkspaceDocument>;
  setAutosave(enabled: boolean): Promise<void>;
  importDocument(input: unknown): Promise<WorkspaceDocument | IndicatorTemplateDocument>;
  exportDocument(kind: 'workspace' | 'indicator-template', id: string): Promise<string>;
}
```

The repository serializes mutations, reads the latest catalog for every transaction, increments revision once per successful write and passes the previous revision to storage. Storage must reject a stale revision atomically; hosts choose the persistence mechanism. No success cache is updated before storage resolves. Namespace is immutable. Catalog limits: 100 workspaces, 100 templates, 10 unique recent IDs. Opening a workspace moves it to the front; deleting the active entry chooses the newest remaining recent entry or null. Import always creates a fresh ID and uses the repository clock.

- [x] Write tests with an asynchronous in-memory adapter that checks revisions, injects write failures and records namespaces:

```ts
await expect(repo.createWorkspace('Desk', payload)).rejects.toThrow('quota');
expect((await repo.load()).workspaces).toEqual([]);
await repo.createWorkspace('Desk', payload);
expect((await repo.load()).revision).toBe(1);
```

- [x] Run `npm test -- tests/workspace-repository.test.ts`. Expected: FAIL because the repository does not exist.
- [x] Implement catalog parsing, CRUD, metadata updates, recent/active selection, autosave preference, import/export and serialized transactions. A failed queue entry must not poison later entries. Reject missing IDs, ID collisions, unsupported catalog versions and stale storage writes without overwriting records.
- [x] Test concurrent saves/renames, failures followed by recovery, pending writes across two account repositories, duplicate custom studies, empty templates, import collisions, detached returned objects and malformed persisted catalogs. Run both workspace test files and typecheck. Expected: PASS.
- [x] Commit the verified repository locally.

## Task 3: Optional tier and integration contract

Files: `package.json`, `tsconfig.json`, `rollup.config.js`, `scripts/check-dts.mjs`, `.size-limit.json`, `src/all.ts`, API documentation and skill reference indexes as required by the coverage check.

- [x] Add `workspace` alongside the existing tier entries and mappings, with package export `./workspace`, declaration `dist/workspace/index.d.ts` and bundle `dist/openalgo-charts.workspace.mjs`. Keep shared chart types imported from `openalgo-charts` and keep this tier free of DOM and module side effects.
- [x] Document the adapter's atomic revision requirement, namespace lifetime, failure semantics, limits, migration and the host's responsibility to keep credentials out of free-text chart input. Include a create/save/template/import example using the exact APIs above.
- [x] Build, then run `npm run check:dts`, the workspace tests, package size and tree-shaking checks, and public-reference coverage. Expected: PASS; any intentional size budget adjustment is measured and recorded.
- [x] Pack a candidate and validate that `openalgo-charts/workspace` loads from the package with one shared Chart type. Record the exact candidate source and integrity before migrating the consumer.
- [x] Commit locally and continue to the consumer/reference-host workspace controls plan. This foundation does not complete F1, F2 or P4 by itself.

## Preflight

The spec covers F1-F9/P1-P6. This phase supplies only the reusable F1/F2/P4 contracts; host controls, autosave orchestration, template application, comparisons, replay and the remaining readiness work remain in the master ledger. No existing public API is renamed. The adapter owns atomic writes so the repository does not falsely promise cross-tab safety from a read/then-write localStorage sequence.

Task 1: Ruling: use the drawing tier's off/weak/strong magnet modes rather than a boolean. The existing widget can distinguish weak and strong; its migration must preserve that choice. Hosts with a boolean map false to off and true to weak.

Task 1: Ruling: preserve `ChartSettingsState` and timezone alongside `ChartState`. An actual `Chart.getState()` regression exposed valid auto precision (`minMove: 0`) and settings slices absent from the original minimal fixture. Preserve these before hosts adopt the format.

Task 2: Ruling: supply an optional IndexedDB adapter before host integration. A storage interface alone leaves each host implementing the same atomic revision requirement. The factory takes an `IDBFactory` explicitly and never accesses the DOM or browser globals at import time. Server hosts retain their own asynchronous adapters.

### Task 2 addition: Browser persistence adapter

Files: `src/workspace/indexed-db.ts`, barrel export, `tests/e2e/workspace-storage.spec.ts`, three-browser project matching.

Produces `createIndexedDbWorkspaceStorage(factory: IDBFactory, databaseName?: string): IndexedDbWorkspaceStorage`, where the returned interface extends `WorkspaceStorage` with `close(): Promise<void>`. One catalog per namespace in the `catalogs` object store. Reads resolve after the readonly transaction completes; writes compare the stored revision and put the next catalog in one readwrite transaction, resolving only on commit. Reject malformed existing catalogs, skipped revisions and stale revisions without overwriting. Closing releases the connection and rejects new operations. A version-change notification closes the connection so upgrades are not blocked; create a new adapter afterward. Failed/blocked opens reject, and any delayed success closes its unused connection.

- [x] Write real-browser regressions for reload persistence, separate accounts, simultaneous writes from two tabs (exactly one winner), stale/corrupt storage preservation, and close/version-change lifecycle. Run first against the missing factory; expected RED.
- [x] Implement the adapter with no localStorage fallback or swallowed storage errors.
- [x] Build and run these regressions on Chromium, Firefox and WebKit; expected GREEN. Include the factory and lifecycle semantics in public references and measured budgets.
