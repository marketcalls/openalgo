/**
 * The shell's keyboard: the scopes a chord is resolved in, the pointer facts
 * those scopes read, the bindings the shell registers on its keymap (the
 * editing keys, Escape, the tool chords and the shortcuts panel), and the
 * user's own chords, saved in the widget's storage and put back at mount.
 *
 * Its own module so the keyboard can grow (rebinding, capturing a new chord,
 * saved overrides) while widget.ts stays under its line cap. The shell wires
 * these functions while it is built, calling each with itself as `this`,
 * typed `KeysHost`. Each member carries the name and the type of the shell's
 * own, so a member the shell renames or retypes fails to compile here. The
 * code keeps `this` rather than taking the shell as a parameter because it
 * then reads exactly as it did in widget.ts and compresses like the rest of
 * the shell, where the parameter form measurably grew the widget bundle.
 * The tier entry exports none of it.
 */
import { drawingShortcuts, keyToDrawingAction, type DrawingKeyContext } from 'openalgo-charts/draw';
import { historyPress } from './context';
import { drawingActionState, runDrawingAction } from './drawing-actions';
import { KEYMAP_KEY, markListOnly, openShortcutsPanel, type KeyEventLike, type KeyScope } from './keymap';
import { toolName } from './rail';
import type { WidgetImpl } from './widget';

/**
 * The slice of the shell the keyboard reads and drives. `_inChart` stays on
 * the shell because the engine's shortcut routing asks it too.
 */
export interface KeysHost {
  readonly draw: WidgetImpl['draw'];
  readonly alerts: WidgetImpl['alerts'];
  readonly context: WidgetImpl['context'];
  readonly root: WidgetImpl['root'];
  readonly _doc: WidgetImpl['_doc'];
  readonly _opts: WidgetImpl['_opts'];
  readonly _keymap: WidgetImpl['_keymap'];
  readonly _chartEl: WidgetImpl['_chartEl'];
  readonly _dataStatus: WidgetImpl['_dataStatus'];
  readonly _rail: WidgetImpl['_rail'];
  readonly _cleanups: WidgetImpl['_cleanups'];
  _pointerInside: WidgetImpl['_pointerInside'];
  _pointerInChart: WidgetImpl['_pointerInChart'];
  readonly _inChart: WidgetImpl['_inChart'];
}

/** The scopes a chord is resolved in, innermost first. The keymap asks on every key. */
export function keyScopes(this: KeysHost): KeyScope[] {
  if (this.context.overlays.size() > 0) return ['overlay'];
  const out: KeyScope[] = [];
  const active = this._doc.activeElement;
  const routed = this._opts.keyboardRoute?.();
  if (routed === false || (active !== null && this._dataStatus.el.contains(active))) return [];
  // A control that walks itself with the arrows (the drawing toolbar) names its own scope.
  const own = active !== null && this.root.contains(active) ? active.closest('[data-key-scope]')?.getAttribute('data-key-scope') : null;
  if (own) out.push(own);
  if (this._rail !== null && active !== null && this._rail.el.contains(active)) out.push('rail');
  if (routed || this._inChart()) out.push('chart');
  if (routed || this._pointerInside || (active !== null && this.root.contains(active))) out.push('widget');
  out.push('global');
  return out;
}

/**
 * Every chord the shell owns: the editing keys, Escape, the tool chords and
 * `?`. Each has a command, the name a user's rebinding is saved under; the
 * keys a convention fixes (Escape, Enter, Backspace, the arrows) and `?`,
 * the only way into the editor, are registered as not rebindable.
 */
export function installKeys(this: KeysHost): void {
  const km = this._keymap;
  const draw = this.draw;
  const drawCtx = (): DrawingKeyContext => ({
    hasSelection: draw.selected() !== null,
    hasTarget: draw.hovered() !== null,
    editingText: false,
    placing: draw.activeTool() !== null,
  });
  const targets = (): string[] => {
    const sel = draw.selection();
    if (sel.length > 0) return sel.slice();
    const hov = draw.hovered();
    return hov === null ? [] : [hov];
  };
  const refresh = (): true => { this._rail?.refresh(); return true; };
  // Alert deletion is a fallback: a drawing selection, hover or active
  // tool keeps ownership even when the pointer is over an alert line.
  const removeAlert = (): boolean => {
    const alertId = this.alerts.hovered();
    if (alertId === undefined || draw.activeTool() !== null) return false;
    this.alerts.remove(alertId);
    return refresh();
  };
  // The fixed keys ask the tier what the key means for the selection or the
  // placement in hand, and a key that means nothing right now is declined so
  // the engine (an arrow pan) still gets it.
  const editing = (e: KeyEventLike): boolean => {
    const action = keyToDrawingAction(e, drawCtx());
    if (action === null) return (e.key === 'Delete' || e.key === 'Backspace') && removeAlert();
    switch (action.type) {
      // A selection whose every drawing is locked stays, as it does on every other surface.
      case 'delete': runDrawingAction(this.context, 'delete', targets()); break;
      case 'nudge': draw.nudge(targets(), action.dx, action.dy); break;
      case 'cancel': draw.cancel(); if (draw.activeTool() === null) this._rail?.setDrawLock(false); break;
      case 'finish': draw.finish(); break;
      case 'popAnchor': draw.popAnchor(); break;
      default: return false;
    }
    return refresh();
  };
  // A rebindable command cannot read the key: once moved, Undo arrives as
  // whatever chord the user chose. Each runs its own action and keeps the
  // tier's declines (with nothing to copy, the key is left to the browser).
  const hasTarget = (): boolean => { const c = drawCtx(); return c.hasSelection || c.hasTarget; };
  const onTarget = (run: (ids: string[]) => unknown) => (): boolean => {
    if (!hasTarget()) return false;
    run(targets());
    return refresh();
  };
  const G = 'Drawing';
  const bind = (combo: string, action: (e: KeyEventLike) => boolean, label: string, command: string,
    o: { group?: string; hidden?: boolean; layered?: boolean; fixed?: boolean } = {}): void => {
    km.register(combo, action, 'widget', { label, group: o.group ?? G, hidden: o.hidden, layered: o.layered, command, rebindable: o.fixed !== true });
  };
  // Undo and redo reach every step on the chart, not only drawings.
  const history = (direction: 'undo' | 'redo') => (): boolean => { historyPress(this.context, direction); return refresh(); };
  bind('Mod+Z', history('undo'), 'Undo', 'undo', { group: 'Widget' });
  bind('Mod+Shift+Z', history('redo'), 'Redo', 'redo', { group: 'Widget' });
  bind('Mod+Y', history('redo'), 'Redo', 'redo-alt', { group: 'Widget', hidden: true });
  bind('Mod+C', onTarget((ids) => draw.copy(ids)), 'Copy the selected drawing', 'copy');
  bind('Mod+X', onTarget((ids) => drawingActionState(this.context, ids).noDelete === null && draw.cut(ids)), 'Cut the selected drawing', 'cut');
  bind('Mod+V', () => { void draw.paste(); return refresh(); }, 'Paste drawings', 'paste');
  bind('Mod+D', onTarget((ids) => draw.duplicate(ids)), 'Duplicate the selected drawing', 'duplicate');
  bind('Delete', () => {
    if (!hasTarget()) return removeAlert();
    runDrawingAction(this.context, 'delete', targets());
    return refresh();
  }, 'Delete the selected drawing', 'delete');
  bind('Backspace', editing, 'Delete, or drop the last anchor while placing', 'delete-back', { fixed: true });
  bind('Enter', editing, 'Finish the drawing being placed', 'finish', { fixed: true });
  // The arrows are layered: with nothing selected they decline and the
  // engine's pan runs, so they are not a conflict with it.
  for (const [dir, key] of [['left', 'ArrowLeft'], ['right', 'ArrowRight'], ['up', 'ArrowUp'], ['down', 'ArrowDown']] as const) {
    bind(key, editing, `Nudge the selection ${dir} (Shift: ten pixels)`, `nudge-${dir}`, { layered: true, fixed: true });
  }
  for (const dir of ['left', 'right', 'up', 'down']) {
    bind(`Shift+Arrow${dir[0]!.toUpperCase()}${dir.slice(1)}`, editing, 'Nudge ten pixels', `nudge-${dir}-far`, { hidden: true, layered: true, fixed: true }); // four non-empty names
  }
  bind('Escape', (e) => {
    if (draw.activeTool() !== null) {
      if (editing(e)) return true;
      draw.setTool(null);
      this._rail?.setDrawLock(false);
      return true;
    }
    if (draw.selection().length > 0) { draw.select(null); this._rail?.refresh(); return true; }
    return false;
  }, 'Leave the tool, then clear the selection', 'leave', { fixed: true });
  for (const [id, chord] of Object.entries(drawingShortcuts())) {
    bind(chord, () => { this._rail?.setDrawLock(false); draw.setTool(id); return true; }, toolName(id), `tool:${id}`, { group: 'Drawing tools' });
  }
  const edit = this._opts.shortcutsEditor !== false;
  bind('?', () => { openShortcutsPanel(this.context, { edit }); return true; }, 'Keyboard shortcuts', 'shortcuts', { group: 'Widget', fixed: true });
  // Without the editor a user could not see or reset a saved chord, so none is applied.
  if (!edit) { markListOnly(km); return; }

  // The user's chords come back before the first key, and every change is
  // written through the widget's storage, which does nothing when the
  // widget does not persist.
  const storage = this.context.storage;
  restoreKeymap.call(this);
  this._cleanups.push(km.onChange(() => {
    const saved = km.overrides();
    if (Object.keys(saved).length === 0) storage.remove(KEYMAP_KEY);
    else storage.set(KEYMAP_KEY, saved);
  }));
}

/**
 * Make the saved chords the keymap's. The shell runs it at mount; a store
 * that fills after mount runs it again once loaded, which moves only what
 * differs and writes back the record it read.
 */
export function restoreKeymap(this: KeysHost): void {
  if (this._opts.shortcutsEditor === false) return;
  this._keymap.applyOverrides(this.context.storage.get(KEYMAP_KEY));
}

/** The pointer facts `keyScopes` and `_inChart` read; the listeners go with the shell. */
export function trackPointer(this: KeysHost): void {
  const root = this.root;
  const chartEl = this._chartEl;
  const onRootEnter = (): void => { this._pointerInside = true; };
  const onRootLeave = (): void => { this._pointerInside = false; this._pointerInChart = false; };
  const onChartEnter = (): void => { this._pointerInChart = true; };
  const onChartLeave = (): void => { this._pointerInChart = false; };
  root.addEventListener('pointerenter', onRootEnter);
  root.addEventListener('pointerleave', onRootLeave);
  chartEl.addEventListener('pointerenter', onChartEnter);
  chartEl.addEventListener('pointerleave', onChartLeave);
  this._cleanups.push(() => {
    root.removeEventListener('pointerenter', onRootEnter);
    root.removeEventListener('pointerleave', onRootLeave);
    chartEl.removeEventListener('pointerenter', onChartEnter);
    chartEl.removeEventListener('pointerleave', onChartLeave);
  });
}
