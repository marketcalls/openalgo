/** Optional, DOM-free contracts for named workspaces, indicator templates, watchlists and drawing templates. */
export {
  WORKSPACE_VERSION, WorkspaceDocumentError, parseWorkspaceDocument, parseWorkspacePayload,
  parseIndicatorTemplate, parseIndicatorTemplatePayload, parseIndicatorStates, migrateWidgetWorkspace,
} from './documents';
export { WorkspaceRepository, WorkspaceConflictError, parseWorkspaceCatalog } from './repository';
export type { WorkspaceCatalog, WorkspaceStorage, WorkspaceStore, WorkspaceRepositoryOptions, WorkspaceOperationOptions, WorkspaceOpenOptions } from './repository';
export { createMemoryWorkspaceStorage } from './memory';
export { createIndexedDbWorkspaceStorage } from './indexed-db';
export type { IndexedDbWorkspaceStorage, IndexedDbCatalogStorage } from './indexed-db';
export {
  WatchlistRepository, WatchlistConflictError, parseWatchlistCatalog, watchlistKey,
  createMemoryWatchlistStorage, createIndexedDbWatchlistStorage,
} from './watchlists';
export type {
  Watchlist, WatchlistEntry, WatchlistCatalog, WatchlistStorage, WatchlistStore, WatchlistOperationOptions,
  WatchlistRepositoryOptions, IndexedDbWatchlistStorage,
} from './watchlists';
export {
  DrawingTemplateRepository, DrawingTemplateConflictError, parseDrawingTemplateCatalog, parseDrawingTemplateValues,
  createMemoryDrawingTemplateStorage, createIndexedDbDrawingTemplateStorage,
} from './drawing-templates';
export type {
  DrawingTemplate, DrawingTemplateLevel, DrawingTemplateValue, DrawingTemplateValues, DrawingToolDefault,
  DrawingTemplateCatalog, DrawingTemplateStorage, DrawingTemplateStore, DrawingTemplateOperationOptions,
  DrawingTemplateRepositoryOptions, IndexedDbDrawingTemplateStorage,
} from './drawing-templates';
export { planIndicatorTemplate } from './templates';
export type { IndicatorTemplateMode } from './templates';
export { captureIndicatorTemplate, planIndicatorTemplateState } from './template-layout';
export type { IndicatorTemplateApplyOptions, IndicatorTemplatePlan } from './template-layout';
export type {
  WorkspaceKind, WorkspaceSettings, WorkspaceChartState, WorkspaceComparison, WorkspaceSlot, WorkspacePane,
  WorkspacePayload, WorkspaceSync, WorkspaceLinkChannels, WorkspaceLinkGroup, WorkspaceDocument,
  IndicatorTemplateDocument, IndicatorTemplateInput,
  IndicatorTemplatePayload, IndicatorTemplateLayout, IndicatorTemplatePlotBinding,
} from './documents';
