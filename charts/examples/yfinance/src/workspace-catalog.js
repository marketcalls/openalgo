import { WorkspaceRepository, WorkspaceConflictError, parseWorkspaceCatalog, parseWorkspaceDocument }
  from '/dist/openalgo-charts.workspace.mjs';
import { workspaceFromLayout, layoutFromWorkspace, validateReferenceWorkspace } from './workspace-document.js';

const fingerprint = payload => JSON.stringify(validateReferenceWorkspace(payload));
const errorText = error => error instanceof AggregateError
  ? `${error.message}: ${error.errors.map(errorText).join('; ')}` : String(error?.message || error);

/** Named saves have a separate owner from the recovery snapshot and recent list. */
export class ReferenceWorkspaceCatalog {
  constructor({ storage, namespace, snapshot, open, changed = () => {}, ...options }) {
    this.storage = storage;
    this.namespace = namespace;
    this.snapshot = snapshot;
    this.openChart = open;
    this.changed = changed;
    this.catalog = null;
    this.currentId = null;
    this.error = '';
    this.busy = false;
    this.changingOwner = false;
    this.autosaveBlocked = false;
    this.pendingAutosave = null;
    this.autosaveTask = null;
    this.operationSignal = undefined;
    this.repository = new WorkspaceRepository({
      read: key => storage.read(key),
      write: async (key, next, expectedRevision, operation) => {
        // The repository reads fresh data; the page must also consent to that revision.
        if (expectedRevision !== this.catalog?.revision) throw new WorkspaceConflictError();
        await storage.write(key, next, expectedRevision, { signal: operation?.signal ?? this.operationSignal });
        this.catalog = parseWorkspaceCatalog(next);
      },
    }, namespace, options);
  }

  async run(action, { changingOwner = false, recover = true } = {}) {
    if (this.busy) throw new Error('A layout operation is already in progress');
    this.busy = true;
    this.changingOwner = changingOwner;
    if (changingOwner) this.pendingAutosave = null;
    this.changed();
    try {
      const result = await action();
      if (recover) {
        this.error = '';
        this.autosaveBlocked = false;
      }
      return result;
    } catch (error) {
      this.error = errorText(error);
      this.autosaveBlocked = true;
      this.pendingAutosave = null;
      throw error;
    } finally {
      this.busy = false;
      this.changingOwner = false;
      this.changed();
      this.drainAutosave();
    }
  }

  requireCatalog() {
    if (!this.catalog) throw new Error('Reload saved layouts before continuing');
    return this.catalog;
  }

  find(id) {
    const document = this.requireCatalog().workspaces.find(item => item.id === id);
    if (!document) throw new Error('The saved layout no longer exists');
    return document;
  }

  async restoreCatalog(before, expectedRevision) {
    // Recovery is another atomic revision, never a rewind that could erase another tab.
    const next = parseWorkspaceCatalog({ ...before, revision: expectedRevision + 1 });
    await this.storage.write(this.namespace, next, expectedRevision);
    this.catalog = next;
  }

  async transaction(action, signal) {
    const before = parseWorkspaceCatalog(this.requireCatalog());
    this.operationSignal = signal;
    try {
      signal?.throwIfAborted();
      const result = await action();
      const committedRevision = this.catalog.revision;
      return { result, rollback: () => this.restoreCatalog(before, committedRevision) };
    } catch (error) {
      if (this.catalog.revision !== before.revision) {
        try { await this.restoreCatalog(before, this.catalog.revision); }
        catch (rollbackError) {
          throw new AggregateError([error, rollbackError], 'Layout operation and storage recovery failed');
        }
      }
      throw error;
    } finally { this.operationSignal = undefined; }
  }

  async initialize(legacy) {
    return this.run(async () => {
      this.catalog = await this.repository.load();
      if (this.catalog.revision === 0 && this.catalog.workspaces.length === 0 && legacy) {
        const payload = workspaceFromLayout(legacy);
        await this.transaction(async () => {
          const document = await this.repository.createWorkspace('Previous layout', payload);
          await this.repository.openWorkspace(document.id, { expectedRevision: this.catalog.revision });
          await this.repository.setAutosave(true);
        });
      }
      const document = this.catalog.workspaces.find(item => item.id === this.catalog.activeWorkspaceId);
      const layout = document ? layoutFromWorkspace(document) : null;
      this.currentId = document?.id ?? null;
      return layout;
    }, { changingOwner: true });
  }

  async refresh() {
    return this.run(async () => {
      this.catalog = await this.repository.load();
      if (!this.catalog.workspaces.some(item => item.id === this.currentId)) this.currentId = null;
      return this.catalog;
    }, { changingOwner: true });
  }

  async create(name) {
    return this.run(async () => {
      const payload = validateReferenceWorkspace(this.snapshot());
      const receipt = await this.transaction(async () => {
        const document = await this.repository.createWorkspace(name, payload);
        await this.repository.openWorkspace(document.id, { expectedRevision: this.catalog.revision });
        return document;
      });
      this.currentId = receipt.result.id;
      return receipt.result;
    }, { changingOwner: true });
  }

  async save() {
    return this.run(async () => {
      this.find(this.currentId);
      return this.repository.saveWorkspace(this.currentId, validateReferenceWorkspace(this.snapshot()));
    });
  }

  async open(id) {
    return this.run(async () => {
      const document = this.find(id);
      validateReferenceWorkspace(document);
      await this.openChart(document, signal => this.transaction(() => this.repository.openWorkspace(id,
        { signal, expectedRevision: this.catalog.revision }), signal));
      this.currentId = id;
      return document;
    }, { changingOwner: true });
  }

  rename(id, name) { return this.run(() => this.repository.rename('workspace', id, name), { recover: false }); }
  duplicate(id, name) { return this.run(() => this.repository.duplicate('workspace', id, name), { recover: false }); }

  async remove(id) {
    return this.run(async () => {
      await this.repository.remove('workspace', id);
      if (id === this.currentId) this.currentId = null;
    }, { changingOwner: true, recover: false });
  }

  setAutosave(enabled) {
    return this.run(() => this.repository.setAutosave(enabled), { recover: false });
  }

  export(id) {
    return this.run(() => JSON.stringify(parseWorkspaceDocument(this.find(id)), null, 2), { recover: false });
  }

  async import(text) {
    return this.run(async () => {
      const source = parseWorkspaceDocument(text);
      validateReferenceWorkspace(source);
      let document;
      await this.openChart(source, signal => this.transaction(async () => {
        document = await this.repository.importDocument(source);
        await this.repository.openWorkspace(document.id, { signal, expectedRevision: this.catalog.revision });
      }, signal));
      this.currentId = document.id;
      return document;
    }, { changingOwner: true });
  }

  requestAutosave() {
    if (!this.catalog?.autosave || !this.currentId || this.autosaveBlocked || this.changingOwner) return;
    try {
      const payload = validateReferenceWorkspace(this.snapshot());
      this.pendingAutosave = { id: this.currentId, payload, fingerprint: fingerprint(payload) };
      this.drainAutosave();
    } catch (error) {
      this.error = errorText(error);
      this.autosaveBlocked = true;
      this.pendingAutosave = null;
      this.changed();
    }
  }

  drainAutosave() {
    if (this.busy || this.autosaveTask || !this.pendingAutosave) return;
    // Defer the first write so several synchronous changes become one snapshot.
    this.autosaveTask = Promise.resolve().then(async () => {
      while (this.pendingAutosave && !this.busy && !this.autosaveBlocked) {
        const pending = this.pendingAutosave;
        this.pendingAutosave = null;
        if (!this.catalog.autosave || pending.id !== this.currentId) continue;
        if (fingerprint(this.find(pending.id)) === pending.fingerprint) continue;
        try { await this.run(() => this.repository.saveWorkspace(pending.id, pending.payload)); }
        catch { break; }
      }
    }).finally(() => {
      this.autosaveTask = null;
      this.drainAutosave();
    });
  }

  async flushAutosave() {
    this.drainAutosave();
    while (this.autosaveTask) await this.autosaveTask;
  }
}
