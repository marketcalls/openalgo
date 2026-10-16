# Named workspaces and indicator templates

The optional `openalgo-charts/workspace` entry point provides portable configuration
documents, a catalog repository and an IndexedDB storage adapter. It creates no UI,
chart or market-data subscription. Hosts own their layout controls, data loading,
template application and save notifications. The widget tier's `createChartGrid` is
one such host: `grid.getWorkspace()` writes a payload this tier accepts, and
`grid.applyWorkspace(parseWorkspacePayload(text))` applies one all or nothing.

```ts
import {
  WorkspaceRepository, createIndexedDbWorkspaceStorage,
  parseWorkspacePayload, parseWorkspaceDocument, captureIndicatorTemplate,
} from 'openalgo-charts/workspace';

// Browser initialization. Use an opaque namespace for the authenticated user.
const storage = createIndexedDbWorkspaceStorage(window.indexedDB);
const repository = new WorkspaceRepository(storage, 'user-42');
const payload = parseWorkspacePayload({
  layout: {
    rows: 1, columns: 1,
    slots: [{ paneId: 'p0', row: 0, column: 0, rowSpan: 1, columnSpan: 1 }],
  },
  panes: [{
    id: 'p0', symbol: 'RELIANCE', exchange: 'NSE', interval: '5m',
    chartType: 'candlestick', chart: chart.getState(),
    settings: {}, volume: true, magnet: 'off', stay: false,
    comparisons: [], comparisonMode: 'percent',
  }],
  activePaneId: 'p0',
  sync: { crosshair: true, viewport: true, symbol: false, interval: false },
});

const saved = await repository.createWorkspace('Morning desk', payload);
await repository.openWorkspace(saved.id);
// Capture fresh host state before saving again.
await repository.saveWorkspace(saved.id, {
  ...payload,
  panes: [{ ...payload.panes[0], chart: chart.getState() }],
});
const template = await repository.createTemplate('My studies', captureIndicatorTemplate(chart));
await repository.saveTemplate(template.id, captureIndicatorTemplate(chart));

const exported = await repository.exportDocument('workspace', saved.id);
const checked = parseWorkspaceDocument(exported);
const imported = await repository.importDocument(checked); // always a new ID
console.log(imported.id, (await repository.load()).recentWorkspaceIds);

// At host disposal, release the browser database connection.
await storage.close();
```

## Portable documents

`WORKSPACE_VERSION` is `1`. `parseWorkspaceDocument`, `parseWorkspacePayload`,
`parseIndicatorTemplate`, `parseIndicatorTemplatePayload` and `parseIndicatorStates` accept unknown input, detach
the supported configuration and reject malformed documents with
`WorkspaceDocumentError`. JSON text is accepted for complete documents and arrays.
Unsupported versions are rejected before a host changes its charts.

`WorkspaceDocument` adds `kind`, `version`, `id`, `name`, `createdAt` and `updatedAt`
to a `WorkspacePayload`. Metadata timestamps are epoch **milliseconds**. Bar and
drawing times retain the engine's UTC **seconds** convention.

A payload contains a grid, independent panes, the focused pane ID and four sync
preferences. Slots use zero-based row/column coordinates with positive spans.
Optional `layout.rowWeights` and `layout.columnWeights` preserve unequal track
sizes, such as `[1.4, 1]` for a wider left column. Each list must match its row or
column count and contain positive finite numbers no greater than 1,000. Omitted
lists mean equal tracks. Hosts render these as relative fractions; a preset name
does not override explicit geometry or weights.
Each pane retains its instrument, interval, chart type, chart snapshot, host
settings, volume preference, drawing magnet/stay preference, comparison definitions
and optional `historyPeriod`. `WorkspaceChartState` preserves `ChartState`,
`ChartSettingsState` and timezone, including drawings, repeated indicators,
indicator styles/visibility/pane placement, price scales and viewport.

`WorkspaceSettings` is a flat map of string, finite-number or boolean values.
Use namespaced host keys such as `volume.maPeriod`; do not put account data there.
Comparisons carry stable IDs, symbols, exchanges, optional colors and visibility.
Neither primary bars nor comparison bars belong in these documents.

Indicator templates contain `IndicatorState[]` and optional `IndicatorTemplateLayout`
metadata. `captureIndicatorTemplate(chart)` returns an `IndicatorTemplatePayload`
with study settings, effective per-plot scale bindings, pane weights and scale
configuration. It excludes market data and runtime formatter functions. Repeated descriptor IDs are
separate instances. Empty templates are valid. Unknown custom descriptor IDs are
retained so an export does not destroy configuration from another installation.
The applying host must load/register required studies, check availability and
report missing studies before replacing the current set. The repository does not
apply a template to a chart or choose append versus replace.

### Templates with pane and scale settings

`IndicatorTemplateInput` accepts a captured payload or the existing study array.
`parseIndicatorTemplatePayload` validates and detaches either form. A layout has
`panes`, `plots: IndicatorTemplatePlotBinding[]` and an optional `primaryScaleId`.
Each plot binding names its study instance, exact plot key, pane index and scale ID.
Layout-bearing documents retain unique source study IDs to describe these links.
Applying them allocates fresh identities and remaps declared study dependencies
and saved range ownership. Opaque settings are not rewritten.

`planIndicatorTemplateState(chart, incoming, mode, options?)` returns an
`IndicatorTemplatePlan` containing `indicators`, an optional `panes` patch and
optional `restoreOptions` for retained destination formatters.
It validates the loaded descriptors and layout relationships before mutation.
The host applies the result with `chart.restoreState(state, plan.restoreOptions)`, retains current drawings
and alerts, and checks the restore report. The planner does not fetch data or
change the chart.

Forward `restoreOptions` to preserve runtime number formatting on retained
destination scales, including existing studies rebuilt during append. Copied
scales and replaced study-only panes receive their incoming descriptor formats.
Callbacks are never captured in template JSON. Later explicit settings and
formatter changes keep their normal behavior.

`IndicatorTemplateApplyOptions` controls two independent choices:

| Option | Default | Effect |
| --- | --- | --- |
| `scalePolicy` | `'copy'` | Give non-primary main-pane scales fresh IDs. Shared source plots remain together; repeated copies stay independent. |
| `scalePolicy: 'share'` | Opt in | Reuse matching main-pane scale IDs. Existing destination settings win. Study panes still get separate groups. |
| `rangePolicy` | `'auto'` | Reset copied manual ranges and ratio locks; recompute indicator-owned default bands. Host fixed bands remain. |
| `rangePolicy: 'preserve'` | Opt in | Keep copied manual ranges and ratio references, remapping study-owned range identities. |

A binding to the source's primary price scale follows the destination's actual
primary scale, including a primary scale moved to the left. Its destination view
is retained under either policy. New visible main-pane columns follow existing
columns on each side. Study pane weights retain their ratio to the main pane.
Append creates new positive pane groups; replace reuses study-only slots while
retaining panes that contain host series. Both preserve the host's source handles.

Save and apply the whole payload to retain layout metadata. Updating a saved
template with an array removes its previous layout metadata. Documents without
layout keep the legacy planner behavior below.

`planIndicatorTemplate(current, incoming, mode, available, nextPaneIndex)` prepares
a detached `IndicatorState[]` before the host changes its chart. `mode` uses the
`IndicatorTemplateMode` type: `replace` or `append`. Supply the registered descriptor
IDs as a `ReadonlySet<string>` and the current `chart.panes().length` as the append
boundary. The planner rejects missing descriptors, overlapping append boundaries,
more than 256 studies and pane indices above 31 before returning a plan.

Replacement preserves incoming pane grouping and accepts an empty study list.
Append retains current studies and their instance identities, keeps incoming
overlays on pane zero, and maps each positive incoming pane group to a separate
new pane. Repeated studies remain separate even when their settings match.
Independent incoming instance identities are discarded. Connected templates get
fresh identities and their declared dependency references are remapped, so reusable
templates cannot claim existing alert anchors. Settings, plot styles and visibility
are detached copies.

Apply the plan to the chart owner captured when the user opened the template
controls. Validate that owner again after asynchronous work. A `restoreState`
application must also supply the current drawings and alert document to retain
them; omitted fields clear those slots. Verify the restore report and indicator
count, and restore the previous studies/drawings/alerts if application fails while
the operation still owns the chart. A nested newer restore invalidates recovery
ownership even if it targets the same chart object.
Template application does not require reloading source bars or restoring a
different symbol, price series, viewport or trading state.

### Limits and excluded data

- Up to 16 charts, grid dimensions up to 8 by 8, exactly one non-overlapping slot
  per pane and a valid focused pane.
- Up to 256 study instances, 32 comparison definitions per chart, 32 internal
  chart panes and 512 series style descriptors.
- Document names of 1-120 characters; document IDs of 1-100 characters.
- At most 5 MiB of UTF-8 JSON, depth 32 and 100,000 JSON nodes. The complete
  catalog is subject to the same total size limit.
- No accessors, executable functions, cycles, class instances or non-finite
  numbers. The parser projects recognized document/chart fields and removes
  reserved credential and execution keys from nested records.

Credentials, account balances, orders, positions and an armed trading state are
not workspace data. The reserved-key filter is defense in depth, not a secret
scanner: arbitrary drawing text and custom study values are user data. Hosts
must never insert secrets into those values. Keep trade execution state in a
separate store and disarm on workspace restoration. Treat imported text as text,
not HTML or executable expressions. Parsing is a data validation boundary, not
a sandbox for hostile JavaScript objects such as proxies.

## Catalog transactions and storage

`WorkspaceRepository` supports `load`, `createWorkspace`, `saveWorkspace`,
`createTemplate`, `saveTemplate`, `rename`, `duplicate`, `remove`, `openWorkspace`, `setAutosave`,
`importDocument` and `exportDocument`. The `namespace` getter is immutable.
Constructor options can supply `now` and `id` factories; the defaults are
`Date.now` and `crypto.randomUUID`.

`saveTemplate(id, input)` updates an existing template while preserving its
ID, name and creation time. It captures detached input when called, retains the
identities needed for layout/dependency links and advances the update timestamp monotonically.
Empty updates are valid. Missing template IDs, invalid input and failed atomic
writes reject without replacing the stored template.

The catalog permits 100 workspaces, 100 templates and 10 unique recent workspace
IDs. Creating or importing does not open a workspace. `openWorkspace` records
the active document and moves it to the front of the recent list; it returns the
document. Prepare the host's replacement charts before calling it. Deleting the active workspace chooses the
newest remaining recent ID or null. Duplicate/import create fresh identities
and metadata timestamps, leaving the original intact.

Each repository serializes mutations and reads the latest stored catalog before
every mutation. A mutation increments `revision` once and reports success only
after storage resolves. A rejected write leaves the existing saved catalog
intact, rejects to the caller and does not poison the queue. Invalid stored
catalogs are reported, never replaced with an empty catalog.

`openWorkspace(id, { signal, expectedRevision })` accepts optional
`WorkspaceOpenOptions`. Capture the catalog revision when preparing a grid and
pass it as `expectedRevision`: a changed catalog rejects with
`WorkspaceConflictError`, so a grid cannot open under a newer saved definition.
The signal field is shared with storage's `WorkspaceOperationOptions`.
The repository checks cancellation before queued work, after the catalog read
and before handing the write to storage. The browser adapter aborts a pending
write transaction when the signal aborts, preserving the previous active/recent
selection and revision. Abort a preparation's controller when its owner changes
or a newer open supersedes it. Cancellation cannot undo an already committed
transaction; retain host generation checks when publishing the prepared grid.

Since 2.5.10 every change (`createWorkspace`, `saveWorkspace`, `rename`, `duplicate`,
`remove`, `setAutosave`, `createTemplate`, `saveTemplate`, `importDocument`) takes the same
`expectedRevision` in its `WorkspaceOperationOptions`: a catalog that moved past it rejects
with `WorkspaceConflictError` after the read and before any write. `subscribe(listener)` is
called with a detached catalog copy after each commit, before that change's promise
resolves, and returns the unsubscribe. The repository implements `WorkspaceStore`, the
contract the widget tier's `createLayoutsController` takes. `createMemoryWorkspaceStorage(seed?)`
keeps the same compare-and-write contract in memory, for tests and previews.
`WorkspaceStore` also has two optional members since 2.5.10, `captureIndicatorTemplate(chart)`
and `planIndicatorTemplateState(chart, input, mode, options?)`, which `WorkspaceRepository`
implements; the widget's indicator picker reaches templates through them, so the widget
tier never loads this tier on its own.

`setAutosave` stores a preference. Hosts must debounce actual saves, suppress
them during restoration and replay, cancel pending timers on account changes,
and show success only after the returned promise resolves. Use a new repository
when the authenticated account changes. An in-flight save remains bound to the
old repository's namespace; guard completion notifications against stale owners.

`createIndexedDbWorkspaceStorage(indexedDB, databaseName?)` stores a catalog per
namespace in the `catalogs` object store. It compares and writes revisions in
one readwrite transaction, including across browser tabs. `close()` releases its
connection and rejects new work; existing transactions may finish. A database
version change closes the adapter automatically. Create a new adapter afterward.
Blocked opens, quota errors and aborted transactions reject to the host, with no
silent localStorage or memory fallback.

Server persistence uses the same `WorkspaceStorage` interface:

```ts
interface WorkspaceStorage {
  read(namespace: string): Promise<unknown | null>;
  write(namespace: string, catalog: WorkspaceCatalog,
        expectedRevision: number, options?: WorkspaceOperationOptions): Promise<void>;
}
```

The adapter must compare the current revision and write **atomically**, rejecting
stale writes with `WorkspaceConflictError`. A localStorage get/set pair is not
atomic across tabs. For remote persistence, authorize the namespace server-side
and use a database transaction or conditional version update. Namespace separation
alone is not authorization. After a conflict, reload and let the user decide
whether to retry; do not silently overwrite another session's changes.
When a write receives an abort signal, a custom adapter must reject cancellation
before commit without changing storage. Do not acknowledge cancellation after
committing a write. A remote adapter needs an explicit transactional cancellation
protocol to provide this guarantee; aborting only its HTTP response is insufficient.

## Named watchlists

The same tier keeps named symbol lists with the same storage discipline as the
workspace catalog. It is DOM-free; the widget tier's Watchlist panel, or a host's own
view, reads it. Added in 2.5.5.

```ts
import {
  WatchlistRepository, WatchlistConflictError, createIndexedDbWatchlistStorage, watchlistKey,
} from 'openalgo-charts/workspace';

const lists = new WatchlistRepository(createIndexedDbWatchlistStorage(window.indexedDB), 'user-42');
const tech = await lists.createList('Tech', [{ symbol: 'INFY', exchange: 'NSE' }]);
await lists.addEntry(tech.id, { symbol: 'RELIANCE', exchange: 'BSE' });
await lists.setActiveList(tech.id);
const off = lists.subscribe(catalog => render(catalog));

// A move is computed from a position, so it carries the revision it was computed from.
const { revision } = await lists.load();
try {
  await lists.moveEntry(tech.id, { symbol: 'RELIANCE', exchange: 'BSE' }, 0, { expectedRevision: revision });
} catch (error) {
  if (error instanceof WatchlistConflictError) render(await lists.load());
}
```

An entry is the exact `{ symbol, exchange }` pair (`InstrumentKey` from the base
entry). Neither part is parsed or case-folded, so one ticker on NSE and BSE is two
entries. `watchlistKey(entry)` is that identity as one string: JSON of the pair, so a
separator inside a symbol cannot make two instruments collide. An exact repeat in one
list is refused. A namespace holds up to 100 lists and a list up to 500 entries.

`WatchlistRepository(storage, namespace, { now?, id? })` supports `load`,
`createList(name, entries?)`, `renameList`, `duplicateList`, `removeList` (which clears
`activeListId` when it pointed there), `setActiveList(id | null)`,
`addEntry(id, entry, { index? })`, `removeEntry`, `moveEntry(id, entry, index)` and
`subscribe(listener)`. Writes are queued like the workspace repository's, and each
change is applied to the catalog as stored at that moment, so an edit made in another
tab survives. Every mutation takes `WatchlistOperationOptions` (`signal`,
`expectedRevision`); a stale revision, or a storage write that loses a race, rejects
with `WatchlistConflictError` and writes nothing. `parseWatchlistCatalog` validates a
whole catalog before any mutation, and corrupt storage raises `WorkspaceDocumentError`
and is never replaced.

`createIndexedDbWatchlistStorage(indexedDB, databaseName?)` compares and writes in one
IndexedDB transaction across tabs, as the workspace adapter does, and has `close()`.
`createMemoryWatchlistStorage(seed?)` is revision-checked memory for tests, previews
and hosts without IndexedDB. A server adapter implements `WatchlistStorage`, with the
same atomic compare-and-write rule as `WorkspaceStorage` above.

The widget's panel takes a `WatchlistStore`: the repository's members without
`duplicateList`, which the panel never calls. A host with server-side lists can
implement that contract directly. Its `subscribe` listeners must run after a change
commits and before that change's promise resolves, as the repository's do: the panel
computes a queued move, such as a held Alt+ArrowDown, from the catalog they deliver.

## Migration and restoration

`migrateWidgetWorkspace(widgetState, { id, name, now })` converts the existing
version-1 single-widget envelope into a one-pane workspace. It retains the chart
snapshot, instrument, interval, chart type, theme (`settings['widget.theme']`)
and magnet/stay preferences. Widget rail favorites and last-used tool choices
remain application preferences. This function does not migrate a host's other
storage schemas or delete the old entry.

Before restoration, validate the document and host capabilities: grid capacity,
supported intervals/chart types, custom studies and comparison support. Obtain
fresh market data from the host's adapter and restore configuration only after
the appropriate series exist. Apply focused pane and sync settings deliberately;
never let construction-time synchronization overwrite independently saved panes.
Keep the previous workspace recoverable if loading fails, and hold trading
disabled throughout the transition. Loading a layout must not import orders,
positions, API keys or an armed flag.
