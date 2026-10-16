/**
 * The layouts controller: which saved layout a widget or a grid holds, the
 * catalog revision its writes are checked against, whether the chart has
 * moved away from what was saved, and the autosave that writes it back. It
 * builds no DOM: a menu drives it and renders its state.
 *
 * It takes a `WorkspaceStore` (the workspace tier's `WorkspaceRepository`, or
 * a host's own) and imports that tier as types only, so a widget host loads
 * the workspace bundle only when it hands a store over.
 */
import type { WorkspaceCatalog, WorkspaceDocument, WorkspacePayload, WorkspaceStore } from 'openalgo-charts/workspace';

/** What showing a layout did: `reason` says why nothing changed. */
export interface LayoutApplyReport {
  applied: boolean;
  reason?: string;
}

/**
 * The widget or grid a controller saves and restores. A grid is
 * `{ capture: () => grid.getWorkspace(), apply: p => grid.applyWorkspace(p) }`.
 */
export interface LayoutTarget {
  /** The target as it stands, as a portable workspace payload. */
  capture(): WorkspacePayload;
  /**
   * Show a saved layout, or change nothing and say why. The controller also
   * puts the previous layout back through it when the store refuses to
   * record the new one, so a refused apply must leave the target untouched.
   */
  apply(payload: WorkspacePayload): LayoutApplyReport;
  /** Called on each change the user makes. Without it the host calls `changed()`. Returns the unsubscribe. */
  subscribe?(listener: () => void): () => void;
  /**
   * True while the target shows something other than the layout the user is
   * building, as a chart does during a replay: its bars stop at a moment in
   * the past and a replay may change the view on every step. Autosave waits
   * and `open` is refused until it turns false, which the target announces
   * through its `subscribe` listener (or the host through `changed()`). A
   * save the user asks for still goes through. Since 2.5.10.
   */
  suspended?(): boolean;
}

/**
 * `off` while the catalog's autosave preference is off or no layout is held;
 * otherwise `pending` (a change waits for the quiet period), `saving`,
 * `saved` (the stored layout matches the target) or `failed` (the last write
 * of this layout failed, or it conflicts; autosave waits for a save, a
 * reload or, for a conflict, the user's choice).
 */
export type LayoutAutosaveStatus = 'off' | 'pending' | 'saving' | 'saved' | 'failed';

export interface LayoutsState {
  /** The newest catalog the controller has seen: its own copy, to read and not change. Null until the first load. */
  catalog: WorkspaceCatalog | null;
  /** The saved layout the target was opened from or last saved to; null for none. */
  layoutId: string | null;
  /**
   * The revision the next write into the held layout is checked against;
   * null until the first load. It trails `catalog.revision` while the held
   * layout conflicts, so that write is refused rather than laid over a
   * version nobody here has seen.
   */
  revision: number | null;
  /** The target differs from its layout. Checked when changes settle and by `flush()`; false with no layout. */
  dirty: boolean;
  /** A layout operation (anything but an autosave) is queued or running. */
  busy: boolean;
  /** The target is suspended (`LayoutTarget.suspended`): autosave waits and `open` is refused. Since 2.5.10. */
  suspended: boolean;
  /**
   * The held layout was changed or deleted in another session, or by another
   * control on the page, since this controller last opened or saved it, and
   * a write into it was refused or a reload found it so. `save()` and
   * autosave are refused until `overwrite()`, `saveAs()` or `open()` settles
   * it; a reload clears it only when it finds the layout as this controller
   * left it.
   */
  conflict: boolean;
  autosave: LayoutAutosaveStatus;
  /** Why the last operation or autosave failed; null after a success. */
  error: unknown;
}

export interface LayoutsControllerOptions {
  /**
   * Quiet time in ms after the last change before the target is compared
   * with its layout and autosaved. Default 1000; a value that is not a
   * finite number takes the default.
   */
  autosaveDelay?: number;
}

/**
 * Operations run one at a time, in call order, each checked against the
 * revision the previous one left, so a burst of clicks never interleaves.
 *
 * A write the store refuses because the catalog moved (another tab, another
 * control on the page) is tried again on the newer catalog when what it acts
 * on is unchanged there: the held layout for a save, the named layout for
 * rename, duplicate, remove and open. Only a change to that is a conflict.
 */
export interface LayoutsController {
  readonly store: WorkspaceStore;
  state(): LayoutsState;
  /** Called after the state changes. Returns the unsubscribe. */
  subscribe(listener: (state: LayoutsState) => void): () => void;
  /**
   * Read the catalog again, and resolve with a copy of it. The target is not
   * touched. A paused autosave resumes, unless the held layout conflicts.
   * After a page load, `open(catalog.activeWorkspaceId)` continues on the
   * layout that was active.
   */
  reload(): Promise<WorkspaceCatalog>;
  /**
   * Show a saved layout and record it as active and recent, unless it already
   * is. A change still waiting for the quiet period is autosaved into the
   * layout being left first; when that write fails this rejects and changes
   * nothing, and opening again goes ahead without it. A refused apply
   * resolves with its report and leaves the target and the held layout as
   * they were; when the store refuses the record, the previous layout goes
   * back on the target and this rejects. It rejects too while the target is
   * suspended.
   */
  open(id: string): Promise<LayoutApplyReport>;
  /** Write the target into the held layout. Rejects when no layout is held, and while it conflicts. */
  save(): Promise<WorkspaceDocument>;
  /** Save the target as a new layout, which becomes the held, active one. */
  saveAs(name: string): Promise<WorkspaceDocument>;
  /** Reload, then write the target over the held layout, whatever another session saved there. */
  overwrite(): Promise<WorkspaceDocument>;
  rename(id: string, name: string): Promise<void>;
  duplicate(id: string, name: string): Promise<WorkspaceDocument>;
  /** Delete a saved layout. Deleting the held one leaves the target as it is, holding none. */
  remove(id: string): Promise<void>;
  setAutosave(enabled: boolean): Promise<void>;
  /** Tell the controller the target may have changed, for a target without `subscribe`. */
  changed(): void;
  /** Compare the target with its layout now, autosave if due, and wait for every queued operation. */
  flush(): Promise<void>;
  /** Stop listening. A queued operation rejects; a pending autosave is dropped, so `flush()` first to keep it. */
  destroy(): void;
}

/** Attempts after the first when the catalog moved but the subject did not: bounds a burst of other writers. */
const RETRIES = 3;
/** The longest delay a timer keeps: past it, as with NaN, a timer fires at once, the opposite of a quiet period. */
const MAX_DELAY = 2147483647;
const noop = (): void => {};
// Matched by name: a class check would load the workspace tier into the widget.
const isConflict = (error: unknown): boolean => error instanceof Error && error.name === 'WorkspaceConflictError';
const find = (catalog: WorkspaceCatalog | null, id: string): WorkspaceDocument | undefined => catalog?.workspaces.find(doc => doc.id === id);
/** What a stored layout shows, without its name or times: a rename elsewhere changes nothing the target holds. */
const shown = (doc: WorkspaceDocument | undefined): string => doc === undefined ? '' : JSON.stringify([doc.layout, doc.panes, doc.activePaneId, doc.sync]);
/** A detached payload: the target may keep what it is given, and the catalog stays as read. */
const payloadOf = (doc: WorkspaceDocument): WorkspacePayload =>
  JSON.parse(JSON.stringify({ layout: doc.layout, panes: doc.panes, activePaneId: doc.activePaneId, sync: doc.sync })) as WorkspacePayload;

/** Drive `target`'s saved layouts through `store`. Call `reload()` or any operation to load the catalog. */
export function createLayoutsController(store: WorkspaceStore, target: LayoutTarget, options: LayoutsControllerOptions = {}): LayoutsController {
  const delay = Number.isFinite(options.autosaveDelay) ? Math.min(Math.max(0, options.autosaveDelay as number), MAX_DELAY) : 1000;
  let view: WorkspaceCatalog | null = null;
  let held: number | null = null;
  let layoutId: string | null = null;
  /** The target's capture when it last matched its layout; null when it has not since the layout changed elsewhere. */
  let savedKey: string | null = null;
  /** What the store held for the layout when this controller last opened or saved it. */
  let storedKey = '';
  let dirty = false;
  let conflict = false;
  let failed = false;
  let error: unknown = null;
  let saving = false;
  let applying = false;
  let destroyed = false;
  let ops = 0;
  let changes = 0;
  let queue: Promise<void> = Promise.resolve();
  let passQueued = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let last = '';
  const listeners = new Set<(state: LayoutsState) => void>();

  const status = (): LayoutAutosaveStatus => {
    if (!view?.autosave || layoutId === null) return 'off';
    if (saving) return 'saving';
    if (failed || conflict) return 'failed';
    return timer !== undefined || passQueued || dirty ? 'pending' : 'saved';
  };
  const suspended = (): boolean => {
    // A target that cannot say is not suspended: autosave is what it risks.
    try { return target.suspended?.() === true; } catch { return false; }
  };
  const state = (): LayoutsState => ({
    catalog: view, layoutId, revision: held, dirty, busy: ops > 0, suspended: suspended(), conflict, autosave: status(), error,
  });
  const emit = (): void => {
    if (destroyed) return;
    const next = state();
    // A pan reports a change every frame; the menu hears only what it shows.
    const key = JSON.stringify([view?.revision, held, layoutId, dirty, next.busy, next.suspended, conflict, next.autosave, error === null]);
    if (key === last) return;
    last = key;
    for (const listener of Array.from(listeners)) {
      try { listener(next); } catch (failure) { queueMicrotask(() => { throw failure; }); }
    }
  };
  /** The newest catalog shows the held layout otherwise than this controller left it (or not at all). */
  const heldMoved = (): boolean => layoutId !== null && shown(find(view, layoutId)) !== storedKey;
  const fail = (reason: unknown): void => {
    error = reason;
    // Only a changed error re-renders; the same failure twice still says so.
    last = '';
  };

  /**
   * Hold the newest catalog's revision when it shows the held layout as this
   * controller left it: nothing a write of its own could overwrite has
   * changed. A change to that layout keeps the old revision, and the next
   * write is refused rather than laid over a version nobody here has seen.
   */
  const settle = (): boolean => {
    if (view === null || held === null || view.revision <= held || heldMoved()) return false;
    held = view.revision;
    return true;
  };

  const detach = (): void => {
    layoutId = null;
    savedKey = null;
    storedKey = '';
    dirty = false;
    conflict = false;
  };
  /** The target no longer shows what is stored, and nothing is written over the other version until the user chooses. */
  const diverge = (): void => {
    conflict = true;
    savedKey = null;
    dirty = true;
  };

  /**
   * Take a newer catalog in the middle of an operation. It only ever adds a
   * conflict: clearing one, or letting go of a layout deleted elsewhere, is
   * the user's `reload()`.
   */
  async function refresh(): Promise<void> {
    const catalog = await store.load();
    if (view === null || catalog.revision > view.revision) view = catalog;
    if (heldMoved()) diverge();
    settle();
    emit();
  }

  /**
   * One store write. Without `subject` it writes into the held layout and is
   * checked against the held revision. With one it acts on the list the user
   * sees (open, rename, remove, a new layout, the preference) and is checked
   * against that catalog; `subject` fingerprints what it acts on there.
   *
   * Refused because the catalog moved, it reads the catalog again and tries
   * again at the newer revision when what it acts on is as it was: an
   * unrelated change in another tab (a rename of another layout, the recent
   * list) is not a conflict. Any other failure is final, and so is a change
   * to the subject itself or a catalog still moving after `RETRIES` reads.
   */
  async function write<T>(run: (expectedRevision: number) => Promise<T>, subject?: () => string): Promise<T> {
    const before = subject?.();
    for (let attempt = 0; ; attempt++) {
      const expected = subject === undefined ? held as number : (view as WorkspaceCatalog).revision;
      try {
        const result = await run(expected);
        if (subject === undefined) held = Math.max(held as number, expected + 1);
        failed = false;
        settle();
        return result;
      } catch (reason) {
        if (!isConflict(reason) || attempt === RETRIES) throw reason;
        await refresh();
        // For the held layout, settle() has moved `held` on exactly when it is unchanged.
        if (subject === undefined ? held === expected : subject() !== before) throw reason;
      }
    }
  }
  /** Fingerprints for `write`: the whole document, or only what it shows. */
  const whole = (id: string) => (): string => JSON.stringify(find(view, id) ?? null);
  const content = (id: string) => (): string => shown(find(view, id));
  const nothing = (): string => '';

  async function load(): Promise<WorkspaceCatalog> {
    const catalog = await store.load();
    if (view === null || catalog.revision >= view.revision) view = catalog;
    failed = false;
    if (layoutId !== null && find(view, layoutId) === undefined) detach();
    // `held` stays behind a moved layout, so a write into it keeps being refused.
    if (heldMoved()) diverge();
    else {
      conflict = false;
      held = view.revision;
    }
    return catalog;
  }
  const ensure = async (): Promise<void> => { if (held === null) await load(); };

  const apply = (payload: WorkspacePayload): LayoutApplyReport => {
    applying = true;
    try { return target.apply(payload); } catch (reason) {
      return { applied: false, reason: reason instanceof Error ? reason.message : String(reason) };
    } finally { applying = false; }
  };

  /**
   * The target matches the stored layout `doc` as of change count `at`, with
   * `key` its capture then. A change made since, while the write was in
   * flight, is still to be saved; with none, a pending check is moot.
   */
  const matched = (doc: WorkspaceDocument, key: string, at: number): void => {
    storedKey = shown(doc);
    savedKey = key;
    dirty = changes !== at;
    if (!dirty && timer !== undefined) {
      clearTimeout(timer);
      timer = undefined;
    }
    conflict = false;
    error = null;
    settle();
  };

  async function commitSave(id: string): Promise<WorkspaceDocument> {
    const payload = target.capture();
    const key = JSON.stringify(payload);
    const at = changes;
    saving = true;
    emit();
    try {
      const doc = await write(expectedRevision => store.saveWorkspace(id, payload, { expectedRevision }));
      matched(doc, key, at);
      return doc;
    } catch (reason) {
      failed = true;
      throw reason;
    } finally { saving = false; }
  }

  function op<T>(task: () => Promise<T>): Promise<T> {
    if (destroyed) return Promise.reject(new Error('The layouts controller is destroyed'));
    ops++;
    emit();
    const result = queue.then(() => {
      if (destroyed) throw new Error('The layouts controller is destroyed');
      return task();
    });
    queue = result.then(noop, noop);
    return result.then(value => {
      ops--;
      error = null;
      resume();
      emit();
      return value;
    }, (reason: unknown) => {
      ops--;
      fail(reason);
      resume();
      emit();
      throw reason;
    });
  }

  /** Compare the target with its layout, and autosave it when that is on and nothing holds it back. */
  async function pass(): Promise<void> {
    passQueued = false;
    if (destroyed || layoutId === null) return emit();
    const id = layoutId;
    try {
      const payload = target.capture();
      const key = JSON.stringify(payload);
      const at = changes;
      dirty = key !== savedKey;
      // Held, not dropped: the change is written once the target says it is back.
      if (!dirty || !view?.autosave || conflict || failed || suspended()) return emit();
      saving = true;
      emit();
      const doc = await write(expectedRevision => store.saveWorkspace(id, payload, { expectedRevision }));
      saving = false;
      if (layoutId === id) matched(doc, key, at);
    } catch (reason) {
      saving = false;
      failed = true;
      fail(reason);
    }
    emit();
  }
  const queuePass = (): void => {
    if (passQueued || destroyed) return;
    passQueued = true;
    queue = queue.then(pass).then(noop, noop);
  };
  /**
   * Queue the autosave an unsaved target is owed when no change will: an
   * operation has cleared a failure (a reload, or any write that went
   * through) or a conflict, or the preference came on elsewhere. Without it
   * the status reads `pending` with nothing to run it. A write of the held
   * layout in flight settles `dirty` itself when it lands.
   */
  function resume(): void {
    if (view?.autosave && layoutId !== null && dirty && !conflict && !failed && !saving && timer === undefined) queuePass();
  }
  /** Run a comparison that is waiting, now: the change belongs to the layout the target still holds. */
  const due = async (): Promise<void> => {
    if (timer === undefined && !passQueued) return;
    if (timer !== undefined) { clearTimeout(timer); timer = undefined; }
    await pass();
  };

  const changed = (): void => {
    if (destroyed || applying) return;
    changes++;
    if (timer !== undefined) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = undefined;
      queuePass();
    }, delay);
    emit();
  };
  const offTarget = target.subscribe?.(changed);
  const offStore = store.subscribe(catalog => {
    if (destroyed || (view !== null && catalog.revision <= view.revision)) return;
    view = catalog;
    settle();
    resume();
    emit();
  });

  return {
    store,
    state,
    subscribe(listener) {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
    // A detached copy: a caller sorting or trimming the list cannot reach the one held here.
    reload: () => op(async () => JSON.parse(JSON.stringify(await load())) as WorkspaceCatalog),
    open: id => op(async () => {
      // A replay owns the bars on screen: a layout landing now would load its own under it.
      if (suspended()) throw new Error('A layout cannot open while the chart is suspended, as during a replay');
      const stopped = failed;
      await due();
      // The change could not be saved into the layout being left, so it stays on
      // the target and the user hears why, instead of losing it to the next
      // layout unseen. Opening again goes ahead: autosave is paused by then.
      if (failed && !stopped) throw error;
      // The newest version is the one shown: a layout another tab saved opens as saved there.
      await load();
      const doc = find(view, id);
      if (doc === undefined) throw new Error('The saved layout no longer exists');
      const previous = target.capture();
      const at = changes;
      const report = apply(payloadOf(doc));
      if (!report.applied) return report;
      const key = JSON.stringify(target.capture());
      const catalog = view as WorkspaceCatalog;
      let opened = doc;
      // Reopening the active layout on a page load records nothing: a write
      // would move the revision every other tab's next save is checked against.
      if (catalog.activeWorkspaceId !== id || catalog.recentWorkspaceIds[0] !== id) {
        try {
          opened = await write(expectedRevision => store.openWorkspace(id, { expectedRevision }), content(id));
        } catch (reason) {
          // The catalog still names the old layout, so the target goes back to it;
          // one that cannot is held to no layout, and nothing autosaves over the wrong one.
          if (!apply(previous).applied) detach();
          throw reason;
        }
      }
      layoutId = opened.id;
      matched(opened, key, at);
      return report;
    }),
    save: () => op(async () => {
      await ensure();
      if (layoutId === null) throw new Error('No saved layout is held: save it under a name first');
      return commitSave(layoutId);
    }),
    saveAs: name => op(async () => {
      // A new layout overwrites nothing, so it is checked against the newest
      // catalog: this is also the way out of a conflict that keeps both versions.
      await load();
      const payload = target.capture();
      const key = JSON.stringify(payload);
      const at = changes;
      const doc = await write(expectedRevision => store.createWorkspace(name, payload, { expectedRevision }), nothing);
      // The target is this layout now, whatever becomes of recording it as active.
      layoutId = doc.id;
      matched(doc, key, at);
      await write(expectedRevision => store.openWorkspace(doc.id, { expectedRevision }), content(doc.id));
      return doc;
    }),
    overwrite: () => op(async () => {
      await load();
      if (layoutId === null) throw new Error('The saved layout no longer exists: save it under a name');
      // The user chose this chart over the stored version: take that version,
      // as of this read, as the one being replaced.
      storedKey = shown(find(view, layoutId));
      held = (view as WorkspaceCatalog).revision;
      return commitSave(layoutId);
    }),
    rename: (id, name) => op(async () => {
      await ensure();
      await write(expectedRevision => store.rename('workspace', id, name, { expectedRevision }), whole(id));
    }),
    duplicate: (id, name) => op(async () => {
      await ensure();
      return await write(expectedRevision => store.duplicate('workspace', id, name, { expectedRevision }), whole(id)) as WorkspaceDocument;
    }),
    remove: id => op(async () => {
      await ensure();
      await write(expectedRevision => store.remove('workspace', id, { expectedRevision }), whole(id));
      if (id === layoutId) {
        detach();
        settle();
      }
    }),
    setAutosave: enabled => op(async () => {
      await ensure();
      await write(expectedRevision => store.setAutosave(enabled, { expectedRevision }), nothing);
      // Turning it on saves what is already unsaved, without waiting for another change.
      if (enabled) queuePass();
    }),
    changed,
    async flush() {
      if (destroyed) return;
      if (timer !== undefined) { clearTimeout(timer); timer = undefined; }
      queuePass();
      await queue;
    },
    destroy() {
      if (destroyed) return;
      destroyed = true;
      if (timer !== undefined) clearTimeout(timer);
      offStore();
      offTarget?.();
      listeners.clear();
    },
  };
}
