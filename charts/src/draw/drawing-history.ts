/**
 * The drawing controller's undo history: the two branches of snapshots, the
 * step being recorded, and the host's own edits, which every recorded step
 * takes in so that no undo reverses them.
 *
 * Its own module because the history is the part of the controller most
 * sensitive to policy and linking, and it was interleaved with pointer
 * handling. The controller reaches it through `DrawingController._history`,
 * and it reaches the controller through `HistoryHost`; the public undo, redo
 * and history methods stay on the controller with their documentation.
 * Members the controller calls are public on this internal class; the tier
 * entry does not export it, so none of it reaches the published declarations.
 */
import type { Drawing, DrawingGroup, DrawingPatch, DrawingsDocument } from './types';
import type { DrawingChangeKind, DrawingEvent } from './controller-types';
import type { DrawingController } from './controller';
import type { InputAnchorStep } from './input-anchors';
import { migrateDrawings } from './migrate';
import { historyPatch } from './patches';
import { readOnly } from './layer';

// Shared by every controller on the page, so a chart rebuilt with a new
// controller never hands out a step a history still holds for the old one.
let nextStep = 1;

// `external` is a step of the history that is not a drawing edit, a study
// anchor's drag: its snapshots are the drawings as they stood, unchanged by it.
// `step` is the chart-wide history's number for the entry, so drawing edits
// interleave with the chart's own steps in one timeline.
export interface DrawingHistoryEntry { before: string; after: string; step: number; external?: InputAnchorStep }

/**
 * The slice of the controller the history reads and drives. The controller
 * itself is the host: each member carries the name and the type of the
 * controller's own, so the moved code reads as it did in controller.ts, and a
 * member the controller renames or retypes fails to compile here.
 */
export interface HistoryHost {
  _drawings: DrawingController['_drawings'];
  _groups: DrawingController['_groups'];
  readonly _chart: DrawingController['_chart'];
  readonly _opts: DrawingController['_opts'];
  readonly _drag: DrawingController['_drag'];
  readonly _anchorSteps: DrawingController['_anchorSteps'];
  get: DrawingController['get'];
  _pruneSelection: DrawingController['_pruneSelection'];
  _sync: DrawingController['_sync'];
  _emitChange: DrawingController['_emitChange'];
  _applyPatch: DrawingController['_applyPatch'];
  _document: DrawingController['_document'];
  _historyText: DrawingController['_historyText'];
}

export class DrawingHistory {
  private readonly _host: HistoryHost;
  /** Snapshots for undo/redo; each is a full drawing list (they are small). */
  public _undo: DrawingHistoryEntry[] = [];
  public _redo: DrawingHistoryEntry[] = [];
  public _pendingHistory: DrawingHistoryEntry | null = null;
  /** Depth of `untracked` runs, and the drawings as they were before the host's edit in progress. */
  private _untracked = 0;
  private _hostEdit: string | null = null;
  /** The host's patches the recorded steps have yet to take, merged per drawing. */
  public readonly _hostPatches = new Map<string, DrawingPatch>();

  public constructor(host: HistoryHost) {
    this._host = host;
  }

  public undo(): boolean {
    this._host._drag._onDragEnd();
    // A step that held nothing but changes to drawings now read-only does
    // nothing any more, so the press goes on to the step before it.
    for (let snap = this._undo.pop(); snap !== undefined; snap = this._undo.pop()) {
      this._redo.push(snap);
      if (snap.external ? this._external(snap.external.undo(), 'undo') : this._applyHistory(snap.after, snap.before, 'undo')) return true;
    }
    return false;
  }

  public redo(): boolean {
    this._host._drag._onDragEnd();
    for (let snap = this._redo.pop(); snap !== undefined; snap = this._redo.pop()) {
      this._undo.push(snap);
      if (snap.external ? this._external(snap.external.redo(), 'redo') : this._applyHistory(snap.before, snap.after, 'redo')) return true;
    }
    return false;
  }

  /**
   * What moving the model from one snapshot to the other changes, the policy
   * allowing: the drawings whose content or place differs (`ids`), the
   * groups, and whether the order moved. `idle` when nothing is left to
   * move, and `held` when the policy kept a change back.
   */
  private _delta(from: string, to: string) {
    const beforeDocument = migrateDrawings(JSON.parse(from));
    const afterDocument = migrateDrawings(JSON.parse(to));
    const before = beforeDocument.drawings;
    const after = afterDocument.drawings;
    const left = new Map(before.map(d => [d.id, d]));
    const right = new Map(after.map(d => [d.id, d]));
    const beforeOrder = before.filter(d => right.has(d.id)).map(d => d.id);
    const afterOrder = after.filter(d => left.has(d.id)).map(d => d.id);
    const moved = afterOrder.some(id => beforeOrder.indexOf(id) !== afterOrder.indexOf(id));
    let held = false;
    const ids = [...new Set([...left.keys(), ...right.keys()])].filter(id => {
      const a = left.get(id);
      const b = right.get(id);
      if (JSON.stringify(a) === JSON.stringify(b) && beforeOrder.indexOf(id) === afterOrder.indexOf(id)) return false;
      // History is what the user did, and a read-only drawing is not theirs
      // to change: its content stays whatever a step says. Its place in the
      // stack is outside the policy, so a step that only restacked it runs.
      if ((readOnly(a) || readOnly(b) || readOnly(this._host.get(id)))
        && !(a && b && JSON.stringify({ ...a, zIndex: 0 }) === JSON.stringify({ ...b, zIndex: 0 }))) { held = true; return false; }
      return true;
    });
    const beforeGroups = new Map((beforeDocument.groups ?? []).map(group => [group.id, group]));
    const afterGroups = new Map((afterDocument.groups ?? []).map(group => [group.id, group]));
    const changedGroups = new Set([...beforeGroups.keys(), ...afterGroups.keys()]
      .filter(id => JSON.stringify(this._place(beforeGroups.get(id), id)) !== JSON.stringify(this._place(afterGroups.get(id), id))));
    const idle = !ids.length && !changedGroups.size && !moved;
    return { left, right, after, beforeOrder, afterOrder, ids, afterGroups, changedGroups, idle, held };
  }

  /**
   * Where a step leaves group `id`, the policy allowing: a read-only drawing
   * stays in the group it is in now, and that group keeps its name. The
   * `order` form is what is applied; the other puts the read-only members
   * last, so a step that differs only in them compares as doing nothing.
   */
  private _place(group: DrawingGroup | undefined, id: string, order?: boolean): DrawingGroup | undefined {
    const fixed = (member: string): boolean => readOnly(this._host.get(member));
    const now = this._host._groups.find(item => item.id === id);
    const kept = now?.members.filter(fixed) ?? [];
    if (!kept.length && !group?.members.some(fixed)) return group;
    const rest = group?.members.filter(member => !fixed(member) || (order && kept.includes(member))) ?? [];
    const members = [...new Set([...rest, ...kept])];
    return members.length ? { id, name: (kept.length ? now : group)!.name, members } : undefined;
  }

  /**
   * Move the model from one snapshot to the other; false when the policy left
   * nothing to move. A step that never did anything still runs, as it always
   * has; one the policy has emptied is skipped, so the press goes on.
   */
  private _applyHistory(from: string, to: string, kind: 'undo' | 'redo'): boolean {
    const { left, right, after, beforeOrder, afterOrder, ids, afterGroups, changedGroups, idle, held } = this._delta(from, to);
    if (idle && held) return false;
    const changed = new Set(ids);
    const previous = new Map(this._host._drawings.map(d => [d.id, d]));
    const regrouped = [...changedGroups].map(id => this._place(afterGroups.get(id), id, true));
    this._host._groups = this._host._groups.filter(group => !changedGroups.has(group.id));
    for (const group of regrouped) if (group) this._host._groups.push(group);
    // Property history patches in place. Removing and reinserting every edited
    // shape would also undo a later reorder performed on another chart.
    this._host._drawings = this._host._drawings.filter(d => !changed.has(d.id) || right.has(d.id))
      .map(d => changed.has(d.id) ? historyPatch(d, left.get(d.id), right.get(d.id)) as Drawing : d);
    for (let i = 0; i < after.length; i++) {
      const drawing = after[i]!; // i is in range
      // An edit cannot resurrect somebody else's deletion. Only history which
      // actually removed an id can restore it here.
      if (!changed.has(drawing.id) || previous.has(drawing.id) || left.has(drawing.id)) continue;
      const next = after.slice(i + 1).find(d => this._host.get(d.id) !== undefined);
      const at = next === undefined ? this._host._drawings.length : this._host._drawings.findIndex(d => d.id === next.id);
      this._host._drawings.splice(at, 0, drawing);
    }
    const reordered = afterOrder.filter(id => beforeOrder.indexOf(id) !== afterOrder.indexOf(id))
      .map(id => this._host.get(id)).filter((d): d is Drawing => d !== undefined);
    const moving = new Set(reordered.map(d => d.id));
    let position = 0;
    this._host._drawings = this._host._drawings.map(d => moving.has(d.id) ? reordered[position++]! : d); // one per moving
    this._host._pruneSelection();
    this._host._sync();
    for (const id of ids) {
      const drawing = this._host.get(id);
      const old = previous.get(id);
      if (drawing !== undefined) this._host._chart.emit(old === undefined ? 'draw:add' : 'draw:update', { drawing, history: true } satisfies DrawingEvent);
      else if (old !== undefined) this._host._chart.emit('draw:remove', { drawing: old, history: true } satisfies DrawingEvent);
    }
    this._host._emitChange(ids, kind);
    return true;
  }

  public untracked<T>(fn: () => T): T {
    this._untracked++;
    try { return fn(); }
    finally {
      // An edit a throw cut short is still the host's, and must not join the next one.
      if (--this._untracked === 0) this._takeInHostEdit();
    }
  }

  /** Give every recorded step the host's edit, drawing by drawing and group by group. */
  public _takeInHostEdit(): void {
    const from = this._hostEdit;
    if (from === null) return;
    this._hostEdit = null;
    const was = migrateDrawings(JSON.parse(from));
    const now = this._host._document(this._host._drawings);
    const take = <T extends { id: string }>(list: T[], before: readonly T[], after: readonly T[]): T[] => {
      const left = new Map(before.map(item => [item.id, JSON.stringify(item)]));
      const right = new Map(after.map(item => [item.id, item]));
      const changed = new Set([...left.keys(), ...right.keys()]
        .filter(id => left.get(id) !== (right.has(id) ? JSON.stringify(right.get(id)) : undefined)));
      // Changed where a step has it, gone everywhere, and made everywhere: a
      // drawing the host changed is not put into a step from before it existed.
      const out = list.filter(item => !changed.has(item.id) || right.has(item.id)).map(item => (changed.has(item.id) ? right.get(item.id)! : item));
      for (const id of changed) if (!left.has(id) && !out.some(item => item.id === id)) out.push(right.get(id)!);
      return out;
    };
    this._rebase(document => {
      document.drawings = take(document.drawings, was.drawings, now.drawings);
      document.groups = take(document.groups ?? [], was.groups ?? [], now.groups ?? []);
    });
  }

  /**
   * Record a step that is not a drawing edit, a study anchor's move, in the
   * same history, so Undo walks it and the drawings in the order they were
   * made. Like any new edit it clears the redo branch. An `outside` move was
   * written to the settings by someone else (a settings dialog's Pick point):
   * it ends no drawing drag, and a host timeline the steps are handed to saw
   * that write itself, so only this history takes it.
   */
  public _recordStep(step: InputAnchorStep, outside = false): void {
    if (!outside) this._host._drag._onDragEnd();
    // The host's own act, like any edit inside `untracked`: a step nowhere.
    if (this._untracked > 0) return;
    const owner = this._host._anchorSteps;
    if (owner !== null) { if (!outside) owner(step); return; }
    const text = this._host._historyText();
    this._undo.push({ before: text, after: text, step: nextStep++, external: step });
    if (this._undo.length > this._host._opts.historyLimit) this._undo.shift();
    this._redo = [];
    this._external(true, 'update');
  }

  /**
   * Announce a move of the history that changed no drawing, with no ids, so
   * a host's Undo and Redo controls, which refresh on `drawing:change`,
   * follow it. Passes `applied` through.
   */
  private _external(applied: boolean, kind: DrawingChangeKind): boolean {
    if (applied) this._host._chart.emit('drawing:change', { ids: [], kind });
    return applied;
  }

  public _pushUndo(): void {
    this._host._drag._onDragEnd();
    const before = this._host._historyText();
    // The host's own act: no step, both branches kept, and the recorded
    // steps take the change in once it is made.
    if (this._untracked > 0) { this._hostEdit ??= before; return; }
    this._pendingHistory = { before, after: before, step: nextStep++ };
    this._undo.push(this._pendingHistory);
    if (this._undo.length > this._host._opts.historyLimit) this._undo.shift();
    this._redo = []; // a new edit invalidates the redo branch
  }

  /**
   * Open an edit: recorded, or, for a change the history does not hold (a
   * host placing or moving a read-only drawing), not recorded and leaving
   * both branches alone. Either way a drag in progress ends first.
   */
  public _begin(record: boolean): void {
    if (record) this._pushUndo();
    else this._host._drag._onDragEnd();
  }

  /**
   * What the host does (a policy, a forced call) is its own act and never
   * history's to reverse: `edit` makes the same change to every recorded
   * snapshot, as if it had always been so, and a step left with nothing to do
   * is dropped, so `canUndo` and `canRedo` match what a press would do. The
   * step still being recorded stays whatever it holds so far. `edit` may
   * share live objects, since each snapshot is serialised at once. The
   * host's patches still held back go in first, being older. Both snapshots
   * of every step are parsed and written, which is why a forced move of a
   * read-only drawing is held back rather than paying for this.
   */
  public _rebase(edit?: (document: DrawingsDocument) => void): void {
    const rewrite = (text: string): string => {
      const document = JSON.parse(text) as DrawingsDocument;
      for (const d of document.drawings) {
        const { points, ...rest } = this._hostPatches.get(d.id) ?? {};
        this._host._applyPatch(d, rest);
        if (points) d.points = points;
      }
      edit?.(document);
      return JSON.stringify(document);
    };
    const keep = (entry: DrawingHistoryEntry): boolean => {
      entry.before = rewrite(entry.before);
      entry.after = rewrite(entry.after);
      // A step outside the drawings keeps whatever the host did to them.
      return entry === this._pendingHistory || entry.external !== undefined || !this._delta(entry.before, entry.after).idle;
    };
    // A drag holds the branches as they were when it began, for a cancel to
    // put back. They share their steps with the live ones, and taking an
    // edit twice changes nothing, since a snapshot is read through the
    // migration.
    const drag = this._host._drag._dragStart;
    if (drag) {
      drag.undo = drag.undo.filter(keep);
      drag.redo = drag.redo.filter(keep);
    }
    this._undo = this._undo.filter(keep);
    this._redo = this._redo.filter(keep);
    this._hostPatches.clear();
  }
}
