/**
 * The actions a drawing selection offers wherever the user reaches it: lock,
 * hide, the four order moves, duplicate and delete. The floating toolbar, the
 * right-click menu, the properties dialog, the rail, the phone bar and the
 * keys each lay them out in their own words, and every one of them reads its
 * state from `drawingActionState` and acts through `runDrawingAction`, so the
 * same press does the same thing, as one undo step, on every surface.
 *
 * The rules, one each. An edit reaches the drawings the user may edit; a
 * selection with none greys the control with the reason. Lock and hide are
 * switches over those drawings: on when every one is locked (hidden), and a
 * press sets every one the other way, so a partly locked selection locks.
 * Delete, and cut, keep a selection whose every drawing is locked; a partly
 * locked one goes. The order moves and duplicate reach every drawing, a
 * read-only one included, as the controller allows.
 */
import type { Drawing } from 'openalgo-charts/draw';
import { editableIds, historyStep, type WidgetContext } from './context';
import { widgetText } from './localization';

/** An action `runDrawingAction` performs. */
export type DrawingAction = 'lock' | 'visible' | 'front' | 'back' | 'above' | 'behind' | 'duplicate' | 'delete';

/** What the controls for a selection show, read by the one set of rules. */
interface DrawingActionState {
  /** The drawings an edit reaches: the selection without its read-only ones. */
  readonly editable: readonly string[];
  /** Why a selection has nothing to edit, else null. Null for an empty selection. */
  readonly readOnly: string | null;
  /** Every editable drawing is locked. */
  readonly locked: boolean;
  /** Some editable drawings are locked and some are not. */
  readonly partlyLocked: boolean;
  /** Every editable drawing is hidden. */
  readonly hidden: boolean;
  /** Why delete and cut are off (read-only, or every drawing locked), else null. */
  readonly noDelete: string | null;
  /** The side of the series every drawing sits on; null when they differ or one sits between studies. */
  readonly side: 'above' | 'behind' | null;
}

type Facts = Omit<DrawingActionState, 'readOnly' | 'noDelete'>;

function facts(ctx: Pick<WidgetContext, 'draw' | 'chart'>, ids: readonly string[]): Facts {
  const { draw } = ctx;
  const editable = editableIds(draw, ids);
  const mine = editable.map((id) => draw.get(id)).filter((d): d is Drawing => d !== undefined);
  const count = mine.filter((d) => d.locked === true).length;
  const sides = new Set(ids.map((id) => draw.get(id)).filter((d): d is Drawing => d !== undefined).map((d) =>
    // Placed between studies it is on neither side of the series.
    d.stackAbove !== undefined && ctx.chart.seriesStack(d.paneIndex).includes(d.stackAbove) ? null : d.zIndex < 0 ? 'behind' : 'above'));
  const [side] = sides;
  return {
    editable,
    locked: mine.length > 0 && count === mine.length,
    partlyLocked: count > 0 && count < mine.length,
    hidden: mine.length > 0 && mine.every((d) => d.visible === false),
    side: sides.size === 1 && side !== undefined ? side : null,
  };
}

/** The state every surface draws the drawing actions for `ids` from. */
export function drawingActionState(ctx: Pick<WidgetContext, 'draw' | 'chart' | 'translate'>, ids: readonly string[]): DrawingActionState {
  const f = facts(ctx, ids);
  const readOnly = ids.length > 0 && f.editable.length === 0 ? widgetText(ctx, 'read-only') : null;
  return { ...f, readOnly, noDelete: readOnly ?? (f.locked ? widgetText(ctx, 'locked') : null) };
}

/**
 * Do `action` to the drawings `ids` as one step of the chart's history, by
 * the rules above. An action the rules refuse (deleting a locked selection)
 * does nothing.
 */
export function runDrawingAction(ctx: Pick<WidgetContext, 'draw' | 'chart' | 'history'>, action: DrawingAction, ids: readonly string[]): void {
  const { draw } = ctx;
  const f = facts(ctx, ids);
  if (action === 'delete' && (f.editable.length === 0 || f.locked)) return;
  historyStep(ctx, action, () => {
    switch (action) {
      case 'lock': draw.updateMany(f.editable.map((id) => ({ id, patch: { locked: !f.locked } }))); break;
      case 'visible': draw.updateMany(f.editable.map((id) => ({ id, patch: { visible: f.hidden } }))); break;
      // The controller moves one drawing at a time (its place in the list is part of the order).
      case 'front': for (const id of ids) draw.bringToFront(id); break;
      case 'back': for (const id of ids) draw.sendToBack(id); break;
      case 'above': for (const id of ids) draw.bringAboveSeries(id); break;
      case 'behind': for (const id of ids) draw.sendBehindSeries(id); break;
      case 'duplicate': draw.duplicate(ids); break;
      case 'delete': draw.removeMany(f.editable); break;
    }
  });
}
