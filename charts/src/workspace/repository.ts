import type { Chart } from 'openalgo-charts';
import {
  parseIndicatorTemplatePayload, parseIndicatorTemplate, parseWorkspaceDocument, parseWorkspacePayload,
  type IndicatorTemplateDocument, type IndicatorTemplateInput, type IndicatorTemplatePayload, type WorkspaceDocument, type WorkspaceKind,
  type WorkspacePayload,
} from './documents';
import { CatalogQueue, randomId, type CatalogKind } from './catalog';
import { boolean, list, number, readJson, record, string, WorkspaceDocumentError } from './json';
import { captureIndicatorTemplate, planIndicatorTemplateState, type IndicatorTemplateApplyOptions, type IndicatorTemplatePlan } from './template-layout';
import type { IndicatorTemplateMode } from './templates';

export interface WorkspaceCatalog {
  version: 1; revision: number; workspaces: WorkspaceDocument[]; templates: IndicatorTemplateDocument[];
  recentWorkspaceIds: string[]; activeWorkspaceId: string | null; autosave: boolean;
}

export interface WorkspaceOperationOptions {
  /** Cancellation is effective until the storage transaction commits. */
  signal?: AbortSignal | undefined;
  /**
   * Refuse the change with `WorkspaceConflictError` when the catalog has moved
   * past this revision. Pass the revision the change was prepared from, so a
   * layout another session saved in the meantime is never overwritten unseen.
   */
  expectedRevision?: number;
}
export interface WorkspaceOpenOptions extends WorkspaceOperationOptions {
  /** Reject if a grid was prepared from a catalog that has since changed. */
  expectedRevision?: number;
}

/** The host must atomically reject writes whose expectedRevision is stale. */
export interface WorkspaceStorage {
  read(namespace: string): Promise<unknown | null>;
  write(namespace: string, catalog: WorkspaceCatalog, expectedRevision: number, options?: WorkspaceOperationOptions): Promise<void>;
}
export interface WorkspaceRepositoryOptions { now?: () => number; id?: () => string }

/**
 * What a layouts control calls, and nothing more. `WorkspaceRepository`
 * implements it, with `importDocument` and `exportDocument` besides; a host
 * that keeps layouts on its own server can implement it directly. The widget
 * tier takes this contract as a type, so a widget host loads the workspace
 * tier only when it passes one.
 *
 * A change given `expectedRevision` is refused with an error named
 * `WorkspaceConflictError` unless the catalog is at that revision, and a
 * change that commits moves the catalog forward by exactly one revision.
 */
export interface WorkspaceStore {
  load(): Promise<WorkspaceCatalog>;
  /**
   * Called with a detached copy of the catalog after each change this store
   * commits, before that change's promise resolves: a control learns the
   * revision its next change is checked against here. Returns the unsubscribe.
   */
  subscribe(listener: (catalog: WorkspaceCatalog) => void): () => void;
  createWorkspace(name: string, input: WorkspacePayload, options?: WorkspaceOperationOptions): Promise<WorkspaceDocument>;
  saveWorkspace(id: string, input: WorkspacePayload, options?: WorkspaceOperationOptions): Promise<WorkspaceDocument>;
  /** Record the active layout and the recent list. It restores nothing: the caller applies the document. */
  openWorkspace(id: string, options?: WorkspaceOpenOptions): Promise<WorkspaceDocument>;
  createTemplate(name: string, input: IndicatorTemplateInput, options?: WorkspaceOperationOptions): Promise<IndicatorTemplateDocument>;
  saveTemplate(id: string, input: IndicatorTemplateInput, options?: WorkspaceOperationOptions): Promise<IndicatorTemplateDocument>;
  rename(kind: WorkspaceKind, id: string, name: string, options?: WorkspaceOperationOptions): Promise<void>;
  duplicate(kind: WorkspaceKind, id: string, name: string, options?: WorkspaceOperationOptions): Promise<WorkspaceDocument | IndicatorTemplateDocument>;
  remove(kind: WorkspaceKind, id: string, options?: WorkspaceOperationOptions): Promise<void>;
  /** Store the autosave preference. It starts no timer: the control that holds a layout saves it. */
  setAutosave(enabled: boolean, options?: WorkspaceOperationOptions): Promise<void>;
  /**
   * `captureIndicatorTemplate` (since 2.5.10): a chart's studies with their
   * panes and scales, for `createTemplate`. The widget's indicator picker reads
   * it through the store it is given, so the widget tier never loads this tier
   * on its own. Without it the picker saves the plain study list.
   */
  captureIndicatorTemplate?(chart: Chart): IndicatorTemplatePayload;
  /**
   * `planIndicatorTemplateState` (since 2.5.10), for the same reason. The
   * picker offers saved templates only when the store has it: applying one
   * without a plan could lose the chart's panes and scales.
   */
  planIndicatorTemplateState?(chart: Chart, incoming: IndicatorTemplateInput, mode: IndicatorTemplateMode,
    options?: IndicatorTemplateApplyOptions): IndicatorTemplatePlan;
}

export class WorkspaceConflictError extends Error {
  constructor() { super('The saved workspace changed in another session. Reload and retry.'); this.name = 'WorkspaceConflictError'; }
}
type Document = WorkspaceDocument | IndicatorTemplateDocument;

/** The workspace catalog to the shared queue and memory storage (catalog.ts). Internal. */
export const WORKSPACE_CATALOG: CatalogKind<WorkspaceCatalog> = { parse: parseWorkspaceCatalog, conflict: () => new WorkspaceConflictError() };

/** Parse the complete catalog before any mutation; corrupt storage is never replaced. */
export function parseWorkspaceCatalog(input: unknown): WorkspaceCatalog {
  const source = record(readJson(input), 'workspace catalog');
  if (source.version !== 1) throw new WorkspaceDocumentError('Unsupported workspace catalog version');
  const workspaces = list(source.workspaces, 'workspaces', 100).map(parseWorkspaceDocument);
  const templates = list(source.templates, 'templates', 100).map(parseIndicatorTemplate);
  const ids = [...workspaces, ...templates].map(item => item.id);
  if (new Set(ids).size !== ids.length) throw new WorkspaceDocumentError('Duplicate document ID');
  const workspaceIds = new Set(workspaces.map(item => item.id));
  const recentWorkspaceIds = list(source.recentWorkspaceIds, 'recent workspaces', 10).map(id => string(id, 'recent workspace ID', 100));
  if (new Set(recentWorkspaceIds).size !== recentWorkspaceIds.length || recentWorkspaceIds.some(id => !workspaceIds.has(id))) {
    throw new WorkspaceDocumentError('Invalid recent workspace IDs');
  }
  const activeWorkspaceId = source.activeWorkspaceId === null ? null : string(source.activeWorkspaceId, 'active workspace ID', 100);
  if (activeWorkspaceId !== null && !workspaceIds.has(activeWorkspaceId)) throw new WorkspaceDocumentError('Active workspace is missing');
  return { version: 1, revision: number(source.revision, 'catalog revision', 0, Number.MAX_SAFE_INTEGER, true),
    workspaces, templates, recentWorkspaceIds, activeWorkspaceId, autosave: boolean(source.autosave, 'autosave') };
}

function emptyCatalog(): WorkspaceCatalog {
  return { version: 1, revision: 0, workspaces: [], templates: [], recentWorkspaceIds: [], activeWorkspaceId: null, autosave: false };
}

function documentOf(input: unknown): Document {
  const source = record(readJson(input), 'document');
  if (source.kind === 'workspace') return parseWorkspaceDocument(source);
  if (source.kind === 'indicator-template') return parseIndicatorTemplate(source);
  throw new WorkspaceDocumentError('Unsupported document kind');
}

/**
 * Named configuration with serialized, revision-checked writes. Each change is
 * applied to the catalog as stored at that moment, so an edit made in another
 * session survives; a change given `expectedRevision`, or a write racing
 * another session, is refused as a conflict instead. Create a new repository
 * when the account changes; an in-flight operation keeps its owner.
 */
export class WorkspaceRepository implements WorkspaceStore {
  private readonly _catalog: CatalogQueue<WorkspaceCatalog>;
  private readonly _now: () => number;
  private readonly _id: () => string;

  constructor(storage: WorkspaceStorage, namespace: string, options: WorkspaceRepositoryOptions = {}) {
    this._catalog = new CatalogQueue(storage, namespace, WORKSPACE_CATALOG, emptyCatalog);
    this._now = options.now ?? Date.now;
    this._id = options.id ?? randomId;
  }

  get namespace(): string { return this._catalog.namespace; }

  load(): Promise<WorkspaceCatalog> { return this._catalog.load(); }

  subscribe(listener: (catalog: WorkspaceCatalog) => void): () => void { return this._catalog.subscribe(listener); }

  async createWorkspace(name: string, input: WorkspacePayload, options?: WorkspaceOperationOptions): Promise<WorkspaceDocument> {
    const payload = parseWorkspacePayload(input);
    const title = string(name, 'name', 120);
    return this._catalog.transact(catalog => {
      const now = this._now();
      const doc = parseWorkspaceDocument({ ...payload, kind: 'workspace', version: 1, id: this._newId(catalog), name: title, createdAt: now, updatedAt: now });
      catalog.workspaces.push(doc);
      return doc;
    }, options);
  }

  async saveWorkspace(id: string, input: WorkspacePayload, options?: WorkspaceOperationOptions): Promise<WorkspaceDocument> {
    const payload = parseWorkspacePayload(input);
    return this._catalog.transact(catalog => {
      const existing = this._find(catalog, 'workspace', id) as WorkspaceDocument;
      const doc = parseWorkspaceDocument({ ...existing, ...payload, updatedAt: this._updatedAt(existing) });
      catalog.workspaces[catalog.workspaces.indexOf(existing)] = doc;
      return doc;
    }, options);
  }

  async createTemplate(name: string, input: IndicatorTemplateInput, options?: WorkspaceOperationOptions): Promise<IndicatorTemplateDocument> {
    const payload = parseIndicatorTemplatePayload(input);
    const title = string(name, 'name', 120);
    return this._catalog.transact(catalog => {
      const now = this._now();
      const doc = parseIndicatorTemplate({ kind: 'indicator-template', version: 1, id: this._newId(catalog), name: title,
        createdAt: now, updatedAt: now, ...payload });
      catalog.templates.push(doc);
      return doc;
    }, options);
  }

  /** Update reusable study settings without changing the saved template identity. */
  async saveTemplate(id: string, input: IndicatorTemplateInput, options?: WorkspaceOperationOptions): Promise<IndicatorTemplateDocument> {
    const payload = parseIndicatorTemplatePayload(input);
    return this._catalog.transact(catalog => {
      const existing = this._find(catalog, 'indicator-template', id) as IndicatorTemplateDocument;
      const doc = parseIndicatorTemplate({ kind: 'indicator-template', version: existing.version,
        id: existing.id, name: existing.name, createdAt: existing.createdAt, updatedAt: this._updatedAt(existing), ...payload });
      catalog.templates[catalog.templates.indexOf(existing)] = doc;
      return doc;
    }, options);
  }

  async rename(kind: WorkspaceKind, id: string, name: string, options?: WorkspaceOperationOptions): Promise<void> {
    const title = string(name, 'name', 120);
    return this._catalog.transact(catalog => {
      const doc = this._find(catalog, kind, id);
      doc.name = title;
      doc.updatedAt = this._updatedAt(doc);
    }, options);
  }

  async duplicate(kind: WorkspaceKind, id: string, name: string, options?: WorkspaceOperationOptions): Promise<WorkspaceDocument | IndicatorTemplateDocument> {
    const title = string(name, 'name', 120);
    return this._catalog.transact(catalog => this._insert(catalog, this._find(catalog, kind, id), title), options);
  }

  async remove(kind: WorkspaceKind, id: string, options?: WorkspaceOperationOptions): Promise<void> {
    return this._catalog.transact(catalog => {
      this._find(catalog, kind, id);
      if (kind === 'indicator-template') catalog.templates = catalog.templates.filter(item => item.id !== id);
      else {
        catalog.workspaces = catalog.workspaces.filter(item => item.id !== id);
        catalog.recentWorkspaceIds = catalog.recentWorkspaceIds.filter(item => item !== id);
        if (catalog.activeWorkspaceId === id) catalog.activeWorkspaceId = catalog.recentWorkspaceIds[0] ?? null;
      }
    }, options);
  }

  async openWorkspace(id: string, options?: WorkspaceOpenOptions): Promise<WorkspaceDocument> {
    return this._catalog.transact(catalog => {
      const doc = this._find(catalog, 'workspace', id) as WorkspaceDocument;
      catalog.activeWorkspaceId = doc.id;
      catalog.recentWorkspaceIds = [doc.id, ...catalog.recentWorkspaceIds.filter(item => item !== doc.id)].slice(0, 10);
      return doc;
    }, options);
  }

  async setAutosave(enabled: boolean, options?: WorkspaceOperationOptions): Promise<void> {
    const value = boolean(enabled, 'autosave');
    return this._catalog.transact(catalog => { catalog.autosave = value; }, options);
  }

  async importDocument(input: unknown, options?: WorkspaceOperationOptions): Promise<WorkspaceDocument | IndicatorTemplateDocument> {
    const doc = documentOf(input);
    return this._catalog.transact(catalog => this._insert(catalog, doc, doc.name), options);
  }

  /** `captureIndicatorTemplate`, as the store member a widget reaches it through. */
  captureIndicatorTemplate(chart: Chart): IndicatorTemplatePayload { return captureIndicatorTemplate(chart); }

  /** `planIndicatorTemplateState`, as the store member a widget reaches it through. */
  planIndicatorTemplateState(chart: Chart, incoming: IndicatorTemplateInput, mode: IndicatorTemplateMode,
    options?: IndicatorTemplateApplyOptions): IndicatorTemplatePlan {
    return planIndicatorTemplateState(chart, incoming, mode, options);
  }

  async exportDocument(kind: WorkspaceKind, id: string): Promise<string> {
    const catalog = await this.load();
    return JSON.stringify(this._find(catalog, kind, id), null, 2);
  }

  private _find(catalog: WorkspaceCatalog, kind: WorkspaceKind, id: string): Document {
    if (kind !== 'workspace' && kind !== 'indicator-template') throw new WorkspaceDocumentError('Unsupported document kind');
    const key = string(id, 'document ID', 100);
    const doc = (kind === 'workspace' ? catalog.workspaces : catalog.templates).find(item => item.id === key);
    if (!doc) throw new WorkspaceDocumentError(`Saved ${kind} does not exist`);
    return doc;
  }

  private _updatedAt(doc: Document): number {
    return Math.max(doc.updatedAt, number(this._now(), 'current time', 0));
  }

  private _newId(catalog: WorkspaceCatalog): string {
    const id = string(this._id(), 'generated document ID', 100);
    if ([...catalog.workspaces, ...catalog.templates].some(item => item.id === id)) throw new WorkspaceDocumentError('Generated document ID collision');
    return id;
  }

  private _insert(catalog: WorkspaceCatalog, source: Document, name: string): Document {
    const now = this._now();
    const doc = documentOf({ ...source, name, id: this._newId(catalog), createdAt: now, updatedAt: now });
    if (doc.kind === 'workspace') catalog.workspaces.push(doc);
    else catalog.templates.push(doc);
    return doc;
  }
}
