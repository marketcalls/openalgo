# Workspace tier

Use the optional `openalgo-charts/workspace` entry point for named configurations.
It is DOM-free, registers nothing and imports shared chart types and alert-document
validation from the base entry. See [the host integration guide](../../../../docs/workspaces.md) for a
complete example, limits, restore ownership and account-switch requirements.

Runtime exports:

- `WORKSPACE_VERSION`: document schema version `1`.
- `parseWorkspaceDocument`, `parseWorkspacePayload`: validate/detach independent
  panes, grid slots, focus and the link settings (`WorkspaceSync`: the
  crosshair/viewport/symbol/interval flags, optional appearance, chartType, drawings
  and whenMissing, and optional named `groups` with each pane's `linkGroup`; see
  chart-linking.md, Saving links in a workspace).
  A chart state is version 1, or version 2 with `primaryPane`, the slot of a
  price pane moved below its studies; a `primaryPane` on version 1, or one that
  names no saved pane, is refused. Restoring a moved one needs a chart built with
  `movablePrimaryPane`; any other chart refuses it rather than misplace the panes.
  Optional layout `rowWeights`/`columnWeights` preserve unequal tracks: positive
  finite values up to 1,000, one per track. Missing lists mean equal tracks.
- `parseIndicatorTemplate`, `parseIndicatorTemplatePayload`, `parseIndicatorStates`: retain duplicate instances,
  settings, visibility, pane placement and unavailable custom IDs. Empty is valid.
  Chart states retain unique instanceId values for alert anchors. Layout-bearing
  and connected templates retain source IDs for their links; independent legacy
  templates omit IDs. Applying a template creates fresh incoming identities.
- `captureIndicatorTemplate(chart)`: capture studies, pane/scale configuration and
  effective plot bindings, including overlays and the actual primary scale. No bars
  or runtime formatters are stored. Save the complete payload to retain layout.
  A template is written price pane first: its pane 0 is the price pane and the study
  panes follow in chart order, whatever slot the price pane held, so a chart with its
  price pane at the bottom captures the same portable document as one with it on top.
- `planIndicatorTemplateState(chart, input, mode, options?)`: validate loaded
  descriptors and return a detached `{ indicators, panes?, primaryPane?, restoreOptions? }` plan.
  The plan is in the destination's own slots and keeps its price pane where it is;
  when that is not slot 0 it lists the panes and carries `primaryPane`, which the
  host must forward beside `panes` in a version 2 restore state. No mutation or
  data reload. Default `scalePolicy: 'copy'` gives non-primary main-pane scales fresh
  IDs while preserving source sharing; `'share'` reuses IDs and existing destination
  settings. Source primary bindings follow the destination primary scale. Positive
  pane groups stay separate, with proportional weights. Replace reserves host-series
  panes. Default `rangePolicy: 'auto'` drops copied manual views/ratio locks and
  recomputes study-owned defaults; `'preserve'` retains them with remapped owners.
  Both preserve destination primary/shared views and host fixed bands.
  Pass `plan.restoreOptions` as the second argument of `chart.restoreState` to
  retain runtime formatters on destination scales. Copied/replaced study scales
  receive descriptor formatting; no callback enters the portable document.
- `planIndicatorTemplate(current, incoming, mode, available, nextPaneIndex, primaryPaneIndex = 0)`:
  prepare detached studies before mutation. `replace` uses the incoming groups;
  `append` retains current identities and places incoming positive pane groups
  after the current pane count. Incoming overlays (pane 0) go to the price pane at
  `primaryPaneIndex`; incoming instance IDs are omitted. Repeated studies remain separate. Validate missing descriptors,
  append overlap, the 256-study limit and pane indices 0 through 31 before apply.
- `migrateWidgetWorkspace`: explicit single-widget version-1 migration; metadata
  is supplied by the host, bars and execution state are excluded.
- `WorkspaceDocumentError`: malformed/unsupported/oversized input.
- `parseWorkspaceCatalog`: validate the entire persisted catalog before mutation.
- `WorkspaceRepository`: asynchronous `load`, `createWorkspace`, `saveWorkspace`,
  `createTemplate`, `saveTemplate`, `rename`, `duplicate`, `remove`, `openWorkspace`, `setAutosave`,
  `importDocument`, `exportDocument`; immutable `namespace`; optional `now`/`id`.
  `createTemplate`/`saveTemplate` accept study arrays or complete payloads.
  `saveTemplate` retains metadata identity and captures detached inputs; saving an
  array removes prior layout metadata. Empty updates are valid; failed writes preserve old content.
  (since 2.5.10) Every change takes `WorkspaceOperationOptions` (`signal`, `expectedRevision`)
  as its last argument; a stale revision rejects with `WorkspaceConflictError` after the read
  and before any write. `subscribe(listener)` is called with a detached catalog copy after each
  commit, before that change's promise resolves, and returns the unsubscribe. It implements
  `WorkspaceStore`.
- `WorkspaceStore` (since 2.5.10): the contract a layouts control holds: `load`, `subscribe`,
  `createWorkspace`, `saveWorkspace`, `openWorkspace`, `createTemplate`, `saveTemplate`,
  `rename`, `duplicate`, `remove`, `setAutosave`. A host with server-side layouts can implement
  it; its conflicts must be errors named `WorkspaceConflictError`, and its listeners must run
  before the change's promise resolves. The widget's `createLayoutsController` takes one (see
  [widget](widget.md)). Two optional members (since 2.5.10), `captureIndicatorTemplate(chart)`
  and `planIndicatorTemplateState(chart, input, mode, options?)`, carry this tier's functions
  of the same names to the widget's indicator picker, which offers templates only when the
  store has the planner. `WorkspaceRepository` has both; a host store assigns them.
- `createMemoryWorkspaceStorage(seed?)` (since 2.5.10): revision-checked storage in memory for
  tests, previews and hosts without IndexedDB: the IndexedDB adapter's atomic compare-and-write,
  detached copies in and out, and nothing that outlives the page.
- `WorkspaceConflictError`: a saved revision changed; reload before retrying.
- `createIndexedDbWorkspaceStorage`: explicit `IDBFactory`, optional database name,
  atomic revision checks across tabs. `close()` releases the connection. Database
  version changes close it automatically; construct a new adapter afterward.

Types: `WorkspaceKind`, `WorkspaceSettings`, `WorkspaceChartState`,
`WorkspaceComparison`, `WorkspaceSlot`, `WorkspacePane`, `WorkspacePayload`,
`WorkspaceDocument`, `IndicatorTemplateDocument`, `WorkspaceCatalog`,
`WorkspaceStorage`, `WorkspaceStore`, `WorkspaceRepositoryOptions`, `WorkspaceOperationOptions`, `WorkspaceOpenOptions`,
`IndexedDbWorkspaceStorage`, `IndicatorTemplateMode`, `IndicatorTemplateInput`,
`IndicatorTemplatePayload`, `IndicatorTemplateLayout`, `IndicatorTemplatePlotBinding`,
`IndicatorTemplateApplyOptions`, `IndicatorTemplatePlan`.

`WorkspaceStorage.write(namespace, catalog, expectedRevision, options?)` MUST compare and
write atomically. A read/then-write localStorage adapter does not meet this
contract. The IndexedDB adapter resolves writes on transaction completion and
rejects stale/corrupt revisions; custom server adapters must do the equivalent.
`WorkspaceOperationOptions` carries an optional `signal: AbortSignal` and (since 2.5.10) an
optional `expectedRevision` on every change: pass the revision the change was prepared from,
so a layout another tab saved meanwhile is refused instead of overwritten. Without it a change
applies to the catalog as stored when it runs, as before. `WorkspaceOpenOptions` keeps the
same field for `openWorkspace`: capture the revision before preparing a grid, then pass it
with the signal.
`openWorkspace(id, { signal, expectedRevision })` checks cancellation before queued/read work and
passes the signal into storage. The browser adapter aborts its pending write
transaction, preserving active/recent IDs and revision. Custom adapters must
honor cancellation before commit, not merely stop waiting for a remote response.
Cancellation cannot undo a committed transaction; the host still guards owners.

Hosts provide controls and application semantics. `openWorkspace` records catalog
selection and returns a document; it does not load charts. `setAutosave` saves a
preference, not a timer. Template application must check custom-study availability
before replacement. Use a new repository per account and keep completion callbacks
bound to their original owner. Show a save error when storage rejects.

When applying a planned study list with `restoreState`, explicitly retain the
current drawings and alerts: omitted state slots clear them. Check the restore
report and applied study count; recover the previous list and decorations after
failure only while the same operation still owns the chart. A nested newer restore
invalidates recovery ownership, even on the same chart object. Do not reload market data or change the captured chart's source to apply
a study template.

Metadata is epoch milliseconds; chart/drawing times stay UTC seconds. Import
always creates a fresh document ID. Never include credentials or trading execution
state. Reserved keys are filtered, except inside an opaque alert payload, where
they cause rejection to avoid silently changing routing data. Other payload data
must survive JSON without losing symbols, accessors or extra array properties.
Arbitrary free text is not secret-scanned.
Do not execute imported text or assume namespace names provide authorization.

## Study policies in documents

Workspace chart states keep each study's `policy` (validated, restrictions only) and a
moved source's `sourceAbove`. A portable indicator template is the user's own copy of the
user's own studies: parsing and `captureIndicatorTemplate` leave out every study the host
keeps from the user (policy not `removable` or not `listed`), every study reading the
output of one, their plot bindings and the scale ranges they owned, and drop `policy` from
the rest. `planIndicatorTemplate` and `planIndicatorTemplateState` in `replace` mode keep
every current host study (not `removable` or not `listed`), with its identity and policy,
and give the template's pane groups the free slots around its pane, so a replace neither
copies nor removes one.
## Data variants in workspaces (2.5.6)

`WorkspacePane.variant?: DataVariant` names the provider series a chart showed (extended
hours, raw prices, a currency or a unit). The parser keeps a pane's variant as the
frozen canonical copy `normalizeDataVariant` returns, stores the default (`{}`) as no
field at all, and refuses the document with `WorkspaceDocumentError` for a variant this
build cannot name, because it would reopen as some other series. `migrateWidgetWorkspace`
carries a widget state's `variant`. `createChartGrid` saves each cell's variant in
`getWorkspace()`, reopens it through `applyWorkspace()` (a payload whose variant cannot
be read is refused and the grid keeps its charts), gives a new cell from `setPreset`
the active chart's variant, and saves when a cell's variant changes. Comparisons have no
variant of their own: a host asks for them in their chart's session and adjustment
(`inheritedDataVariant`). See [feeds-and-live](feeds-and-live.md).

## Named watchlists (2.5.5)

DOM-free named symbol lists in the same tier and with the same storage discipline as
workspaces. Source of truth: `src/workspace/watchlists.ts`.

```ts
import { WatchlistRepository, createIndexedDbWatchlistStorage } from 'openalgo-charts/workspace';

const lists = new WatchlistRepository(createIndexedDbWatchlistStorage(indexedDB), 'account-7');
const tech = await lists.createList('Tech', [{ symbol: 'INFY', exchange: 'NSE' }]);
await lists.addEntry(tech.id, { symbol: 'RELIANCE', exchange: 'BSE' });
await lists.setActiveList(tech.id);
```

- Identity is the exact `{ symbol, exchange }` pair (`InstrumentKey` from the base entry):
  never case-folded or parsed, so one ticker on NSE and BSE is two entries.
  `watchlistKey(entry)` is that identity as one string (JSON of the pair, so a separator
  inside a symbol cannot make two instruments collide). An exact repeat in one list is
  rejected; up to 100 lists per namespace and 500 entries per list.
- `WatchlistRepository(storage, namespace, { now?, id? })`: `load`, `createList(name, entries?)`,
  `renameList`, `duplicateList`, `removeList` (clears `activeListId` when it pointed there),
  `setActiveList(id | null)`, `addEntry(id, entry, { index? })`, `removeEntry`,
  `moveEntry(id, entry, index)`, and `subscribe(listener)`, called with a detached copy
  after every change this repository commits. It implements the `WatchlistStore`
  contract, which is what the widget's panel takes: every member above except
  `duplicateList`, which the panel never calls. A host with server-side lists can
  implement `WatchlistStore` itself. Its `subscribe` listeners must run before the
  change's own promise resolves, as the repository's do: the panel computes a queued
  move (a held Alt+Arrow) from the catalog they deliver.
- Writes are queued and each one is applied to the catalog as stored at that moment, so a
  change made in another session survives. Every mutation takes
  `WatchlistOperationOptions` (`signal`, `expectedRevision`): pass the revision a
  position-based edit was computed from and the change is refused with
  `WatchlistConflictError` if the catalog moved. A storage write that loses a race is the
  same error; reload and retry. Nothing is written for a refused or invalid change.
- `parseWatchlistCatalog` validates the whole catalog (`version` 1, `revision`, `lists`,
  `activeListId`) before any mutation; corrupt storage raises `WorkspaceDocumentError`
  and is never replaced.
- Storage: `WatchlistStorage.write(namespace, catalog, expectedRevision, options?)` must
  compare and write atomically, like `WorkspaceStorage`. `createIndexedDbWatchlistStorage(factory,
  name = 'openalgo-chart-watchlists')` does it in one IndexedDB transaction across tabs
  (`IndexedDbWatchlistStorage`, with `close()`; the shared shape is `IndexedDbCatalogStorage`).
  `createMemoryWatchlistStorage(seed?)` is revision-checked memory for tests, previews
  and hosts without IndexedDB; nothing outlives the page.

Types: `Watchlist`, `WatchlistEntry`, `WatchlistCatalog`, `WatchlistStorage`, `WatchlistStore`,
`WatchlistOperationOptions`, `WatchlistRepositoryOptions`, `IndexedDbWatchlistStorage`,
`IndexedDbCatalogStorage`.

## Drawing style templates (since 2.5.9)

DOM-free saved drawing looks, in the same tier and with the same storage discipline as
workspaces and watchlists: a tool's default ("save as default") and named templates.
Source of truth: `src/workspace/drawing-templates.ts`. The widget takes one as
`WidgetOptions.drawingTemplates` (see [widget](widget.md)).

```ts
import { DrawingTemplateRepository, createIndexedDbDrawingTemplateStorage } from 'openalgo-charts/workspace';

const templates = new DrawingTemplateRepository(createIndexedDbDrawingTemplateStorage(indexedDB), 'account-7');
await templates.saveTemplate('Swing low support', 'trend-line', { 'style.color': '#f0a020', 'style.lineWidth': 2 });
await templates.setDefault('rectangle', { 'style.fill': true, 'style.fillOpacity': 0.1 });
const { templates: saved, defaults } = await templates.load();
```

- A template's `values` are settings by the dot paths of the tool's settings schema (the
  keys `readDrawingSettings` returns and `applyDrawingSettings` takes): a key under `style`,
  `text` or `props`, never `text.value` (what a drawing says is not its look), and never
  anchors, a lock, a pane or a space. A value is a string (up to 256 characters), a finite
  number, a boolean, or a list of up to 64 levels (`{ ratio, color?, enabled?, label? }`);
  up to 64 values per template. `parseDrawingTemplateValues` validates a values object. The
  tier knows no tool: the host applies a template through the drawing's own schema, which
  drops a path the tool no longer declares and coerces each value.
- `DrawingTemplateRepository(storage, namespace, { now?, id? })`: `load`,
  `saveTemplate(name, tool, values)` (the same name on the same tool, ignoring case and outer
  spaces, takes the new values and keeps its id), `renameTemplate(id, name)` (refuses a name
  another template of the tool has), `removeTemplate(id)`, `setDefault(tool, values | null)`
  (one default per tool; null forgets it) and `subscribe(listener)`, called with a detached
  copy after every commit and before that change's promise resolves. It implements the
  `DrawingTemplateStore` contract the widget takes; a host with server-side templates can
  implement it directly. Up to 200 templates and 200 defaults per namespace.
- Writes are queued and applied to the catalog as stored at that moment. Every mutation
  takes `DrawingTemplateOperationOptions` (`signal`, `expectedRevision`); a stale revision or
  a lost storage race is `DrawingTemplateConflictError`. Nothing is written for a refused or
  invalid change.
- `parseDrawingTemplateCatalog` validates the whole catalog (`version` 1, `revision`,
  `templates`, `defaults`, unique template ids and one default per tool) before any
  mutation; corrupt storage raises `WorkspaceDocumentError` and is never replaced.
- Storage: `DrawingTemplateStorage.write(namespace, catalog, expectedRevision, options?)`
  compares and writes atomically. `createIndexedDbDrawingTemplateStorage(factory,
  name = 'openalgo-chart-drawing-templates')` does it in one IndexedDB transaction
  (`IndexedDbDrawingTemplateStorage`, with `close()`), and
  `createMemoryDrawingTemplateStorage(seed?)` is revision-checked memory for tests and hosts
  without IndexedDB.

Types: `DrawingTemplate`, `DrawingTemplateLevel`, `DrawingTemplateValue`,
`DrawingTemplateValues`, `DrawingToolDefault`, `DrawingTemplateCatalog`,
`DrawingTemplateStorage`, `DrawingTemplateStore`, `DrawingTemplateOperationOptions`,
`DrawingTemplateRepositoryOptions`, `IndexedDbDrawingTemplateStorage`.
