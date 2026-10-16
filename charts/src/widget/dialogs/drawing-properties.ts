/**
 * Properties of the selected drawing, generated from the tool's settings
 * schema (`drawingSettingsSchema`), which declares only the fields the tool's
 * `draw` reads. That is the rule the dialog leans on: a field in the schema is
 * a control with something behind it, and a field absent from it is a control
 * that is not shown. With several drawings selected the dialog edits the
 * fields their schemas share, and writes through `updateMany` so one edit is
 * one undo entry.
 *
 * Edits apply live; the controller's own undo is the way back, so there is
 * no snapshot and no Cancel, only Done. The level list and the text content
 * hand off to their own surfaces (the level editor, the inline text editor)
 * because a ladder of eight rows and a box laid over the canvas are not
 * things a form row can hold.
 *
 * A second tab lists every anchor as a date, a time and a price
 * (`drawing-coordinates.ts`). The template control bottom left saves the
 * look as the tool's default or by name, and applies a saved one, when the
 * widget was given a template store.
 */
import { widgetText } from '../localization';
import { applyDrawingSettings, drawingSettingsSchema, readDrawingSettings } from 'openalgo-charts/draw';
import type { Drawing, DrawingTool, SettingsSchema } from 'openalgo-charts/draw';
import { drawingToolOf, editableIds, type WidgetContext } from '../context';
import { drawingActionState, runDrawingAction, type DrawingAction } from '../drawing-actions';
import { commandChord } from '../keymap';
import {
  button, controlsFromFields, declinedPanel, dialogFrame, el, openPanel, placePanel, renderForm, selectionPoint, tabList,
  type ButtonSpec, type FormHandle, type PanelHandle,
} from '../form';
import { openMenu } from '../menu';
import { templateMenuRows } from '../drawing-templates';
import { mountDrawingCoordinates, type DrawingCoordinatesHandle } from './drawing-coordinates';
import { mountLevelEditor } from './level-editor';
import { mountTextEditor } from './text-editor';

export interface DrawingPropertiesOptions {
  /** The drawings to edit; they become the selection. Default: the current selection. */
  ids?: readonly string[];
  /** The tab to open on: the settings (default) or the anchors. */
  tab?: 'style' | 'coordinates';
  /** Runs once when the dialog is gone. */
  onClose?(): void;
}

/**
 * The fields every one of `toolIds` declares, with the same kind, in the
 * first tool's order. A multi-selection edits this intersection: a field one
 * tool lacks would be a control doing nothing for that drawing.
 */
export function commonSchema(toolIds: readonly string[]): SettingsSchema {
  const schemas = toolIds.map((t) => drawingSettingsSchema(t));
  if (schemas.length === 0) return { fields: [] };
  const [first, ...rest] = schemas; // not empty, checked above
  const fields = first!.fields.filter((f) => rest.every((s) => s.fields.some((g) => g.path === f.path && g.kind === f.kind)));
  return schemas.every((s) => s.textIsContent === true) ? { fields, textIsContent: true } : { fields };
}

/**
 * What the layer paints when a drawing sets nothing: the fill alpha most
 * tools fall back to, the text tool's size and wrap width, an opaque plate.
 * Shown in a control so its state is readable before the first edit.
 */
const ENGINE_FALLBACKS: Readonly<Record<string, unknown>> = {
  'style.lineWidth': 1.5,
  'style.lineStyle': 'solid',
  'style.fillOpacity': 0.12,
  'text.fontSize': 14,
  'text.wrapWidth': 220,
  'text.backgroundOpacity': 1,
  'text.align': 'left',
  'text.valign': 'top',
  'text.position': 'inside',
};

/**
 * The default of every field in `schema`: the tool's own `defaultStyle` and
 * `defaultText` first, then the layer's fallbacks, then `themeLine` for the
 * stroke colour (what the controller gives a drawing added without one).
 */
export function drawingDefaults(tool: DrawingTool | null, schema: SettingsSchema, themeLine: string): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of schema.fields) {
    const [root, key] = f.path.split('.');
    const bag = root === 'style' ? tool?.defaultStyle : root === 'text' ? tool?.defaultText : undefined;
    let v: unknown = bag === undefined || key === undefined ? undefined : (bag as Record<string, unknown>)[key];
    if (v === undefined) v = ENGINE_FALLBACKS[f.path];
    if (v === undefined && f.kind === 'boolean') v = false;
    if (v === undefined && f.path === 'style.color') v = themeLine;
    if (v !== undefined) out[f.path] = v;
  }
  return out;
}

/** A drawing's settings with every unset field filled from its defaults, so no control is blank. */
export function resolvedDrawingValues(d: Drawing, schema: SettingsSchema, tool: DrawingTool | null, themeLine: string): Record<string, unknown> {
  const out = drawingDefaults(tool, schema, themeLine);
  for (const [k, v] of Object.entries(readDrawingSettings(d, schema))) if (v !== undefined) out[k] = v;
  // The tier strokes text and fills in the line colour when they set none.
  for (const path of ['text.color', 'style.fillColor', 'text.borderColor']) {
    if (out[path] === undefined && schema.fields.some((f) => f.path === path)) out[path] = out['style.color'];
  }
  return out;
}

const sameIds = (a: readonly string[], b: readonly string[]): boolean => a.length === b.length && a.every((x, i) => x === b[i]);

/**
 * Open the properties dialog for the selection, below `anchor` when there is
 * one (a toolbar button), else beside the drawing.
 */
export function mountDrawingProperties(ctx: WidgetContext, anchor?: HTMLElement, opts: DrawingPropertiesOptions = {}): PanelHandle {
  const { draw, chart } = ctx;
  const doc = ctx.document;
  if (opts.ids !== undefined && opts.ids.length > 0 && !sameIds(opts.ids, draw.selection())) draw.select(opts.ids.slice());
  let ids = draw.selection().slice();
  const drawingsOf = (): Drawing[] => ids.map((id) => draw.get(id)).filter((d): d is Drawing => d !== undefined);
  // Never empty while the dialog is open: every assignment closes it on an
  // empty selection, so live[0] is read with `!` throughout.
  let live = drawingsOf();
  if (live.length === 0) return declinedPanel(ctx, widgetText(ctx, 'Select a drawing first'));
  let schema = commonSchema(live.map((d) => d.tool));
  let tool = drawingToolOf(live[0]!.tool);
  let form: FormHandle | null = null;
  let shownWhy: string | null = null;

  const titleOf = (): string => (live.length === 1 ? widgetText(ctx, `schema.drawing.${live[0]!.tool}.name`, {}, tool?.name ?? live[0]!.tool) : widgetText(ctx, '{count} drawings', { count: live.length }));
  // A selection the user may not edit opens read-only: every value stays
  // readable, and every control that would change one is greyed with why.
  const lockedOut = (): string | null => editableIds(draw, ids).length === 0 ? widgetText(ctx, 'read-only') : null;
  const values = (): Record<string, unknown> => resolvedDrawingValues(live[0]!, schema, tool, ctx.chartTheme.lineColor);

  /** Write `{ path: value }` to every selected drawing as one undo entry. */
  function apply(patch: Record<string, unknown>): void {
    const patches: Array<{ id: string; patch: Partial<Drawing> }> = [];
    for (const d of live) {
      const cur = draw.get(d.id);
      if (cur === undefined) continue;
      const p = applyDrawingSettings(cur, patch, schema);
      if (Object.keys(p).length > 0) patches.push({ id: d.id, patch: p });
    }
    if (patches.length > 0) draw.updateMany(patches);
    // The controller converts nothing on a pane that is folded or hidden
    // behind a maximized one; the row reads the model back, so say why it
    // did not move.
    if (typeof patch.space === 'string' && live.some((d) => (draw.get(d.id)?.space ?? 'data') !== patch.space)) {
      ctx.toast(widgetText(ctx, "The anchor changes only while the drawing's pane is on screen"), 'info');
    }
  }

  const frame = dialogFrame(doc, { translate: ctx.translate, title: titleOf(), className: 'oac-props', onClose: () => handle.close() });
  const tools = el(doc, 'div', 'oac-props__tools');
  tools.setAttribute('role', 'toolbar');
  tools.setAttribute('aria-label', widgetText(ctx, 'Drawing actions'));
  frame.el.insertBefore(tools, frame.body);
  const pane = el(doc, 'div', 'oac-props__pane');
  const anchors = el(doc, 'div', 'oac-props__pane oac-props__anchors');
  let tab: 'style' | 'coordinates' = opts.tab ?? 'style';
  const tabs = tabList(doc, [
    { id: 'style', label: widgetText(ctx, 'Style'), icon: 'brush' },
    { id: 'coordinates', label: widgetText(ctx, 'Coordinates'), icon: 'coordinates' },
  ], tab, 'row', (next) => { tab = next as 'style' | 'coordinates'; showTab(); });
  frame.body.append(tabs.el, pane, anchors);
  let coords: DrawingCoordinatesHandle | null = null;
  function showTab(): void {
    pane.hidden = tab !== 'style';
    anchors.hidden = tab !== 'coordinates';
    // Built on first view: most edits never open it.
    if (tab === 'coordinates' && coords === null) coords = mountDrawingCoordinates(ctx, anchors, () => ids, lockedOut);
  }

  function renderTools(): void {
    tools.innerHTML = '';
    // The rules every drawing surface keeps (drawing-actions.ts): one press is
    // one undo step, and a switch reads the whole selection.
    const state = drawingActionState(ctx, ids);
    /** A button for one shared action, greyed with `off` when it has a reason to be. */
    const add = (spec: Omit<ButtonSpec, 'onClick'>, act: DrawingAction, pressed?: boolean, off: string | null = null): void => {
      const b = button(doc, { ...spec, iconOnly: true, onClick: () => { runDrawingAction(ctx, act, ids); } });
      b.dataset.act = act;
      if (pressed !== undefined) b.setAttribute('aria-pressed', pressed ? 'true' : 'false');
      if (off !== null) { b.disabled = true; b.title += ` (${off})`; }
      tools.appendChild(b);
    };
    const sep = (): void => { tools.appendChild(el(doc, 'span', 'oac-sep')); };
    // The toggles keep one name each; the pressed state and the icon say locked or hidden.
    add({ label: widgetText(ctx, 'Lock'), icon: state.locked ? 'lock' : 'unlock' }, 'lock', state.locked, state.readOnly);
    add({ label: widgetText(ctx, 'Hide'), icon: state.hidden ? 'eye-off' : 'eye' }, 'visible', state.hidden, state.readOnly);
    sep();
    add({ label: widgetText(ctx, 'Bring to front'), icon: 'front' }, 'front');
    add({ label: widgetText(ctx, 'Send to back'), icon: 'back' }, 'back');
    // Between studies it is on neither side of the series, so neither toggle is pressed.
    add({ label: widgetText(ctx, 'In front of the series'), icon: 'above-series' }, 'above', state.side === 'above');
    add({ label: widgetText(ctx, 'Behind the series'), icon: 'behind-series' }, 'behind', state.side === 'behind');
    sep();
    add({ label: widgetText(ctx, 'Duplicate'), icon: 'duplicate', chord: commandChord(ctx.keymap, 'duplicate', 'Mod+D') }, 'duplicate');
    add({ label: widgetText(ctx, 'Delete'), icon: 'trash', chord: commandChord(ctx.keymap, 'delete', 'Delete'), variant: 'danger' }, 'delete', undefined, state.noDelete);
    restore.disabled = state.readOnly !== null;
  }

  function renderPane(): void {
    form?.destroy();
    pane.innerHTML = '';
    const controls = controlsFromFields(schema.fields, { translate: ctx.translate, scope: `drawing.${live[0]!.tool}` });
    if (controls.length === 0) {
      pane.appendChild(el(doc, 'div', 'oac-empty', widgetText(ctx, 'These drawings share no settings.')));
      form = null;
      return;
    }
    const why = shownWhy = lockedOut();
    form = renderForm(pane, controls, {
      values: values(), translate: ctx.translate, openOverlay: ctx.openOverlay,
      idPrefix: 'oac-props',
      unavailable: () => why,
      onChange: (key, value) => { apply({ [key]: value }); form?.sync(values()); },
      custom: (c) => {
        if (c.custom !== 'levels') return null;
        const b = button(doc, { label: widgetText(ctx, 'Edit levels...'), onClick: (e) => { mountLevelEditor(ctx, e.currentTarget as HTMLElement, { ids }); } });
        b.dataset.act = 'edit-levels';
        b.disabled = why !== null;
        return b;
      },
    });
    // The text tool's content is edited where it is painted as well as here:
    // the box on the canvas shows the wrap and the face the row cannot.
    if (schema.textIsContent === true && live.length === 1) {
      const row = pane.querySelector('[data-key="text.value"]');
      if (row !== null) {
        const b = button(doc, { label: widgetText(ctx, 'Edit text'), icon: 'text', onClick: () => { mountTextEditor(ctx, undefined, { id: live[0]!.id }); } });
        b.dataset.act = 'edit-text';
        b.disabled = why !== null;
        row.appendChild(b);
      }
    }
  }

  const restore = frame.lead.appendChild(button(doc, {
    label: widgetText(ctx, 'Restore defaults'),
    onClick: () => {
      // The tool's own defaults where it has them; a field it leaves unset is
      // removed, which puts the layer's fallback back.
      const patch: Record<string, unknown> = {};
      const own = drawingDefaults(tool, { fields: schema.fields }, ctx.chartTheme.lineColor);
      for (const f of schema.fields) {
        if (f.kind === 'levels') continue;
        const [root, key] = f.path.split('.');
        const bag = root === 'style' ? tool?.defaultStyle : root === 'text' ? tool?.defaultText : undefined;
        const declared = bag === undefined || key === undefined ? undefined : (bag as Record<string, unknown>)[key];
        patch[f.path] = declared === undefined ? undefined : own[f.path];
      }
      apply(patch);
      form?.sync(values());
    },
  }));
  // The template picker sits with Restore defaults, bottom left: both set the look as a whole.
  const saved = ctx.drawingTemplates;
  if (saved !== undefined) {
    const picker = frame.lead.appendChild(button(doc, { label: widgetText(ctx, 'Templates'), onClick: () => {
      openMenu(ctx, picker, templateMenuRows(ctx, saved, ids, picker), { ariaLabel: widgetText(ctx, 'Templates') });
    } }));
    picker.dataset.act = 'templates';
    picker.setAttribute('aria-haspopup', 'menu');
  }
  frame.actions.appendChild(button(doc, { label: widgetText(ctx, 'Done'), variant: 'primary', onClick: () => handle.close() }));
  renderTools();
  renderPane();
  showTab();

  /** Follow the selection: the same one refreshes in place, a new one rebuilds, none closes. */
  function refresh(): void {
    if (!handle.isOpen()) return;
    const next = draw.selection().slice();
    if (next.length === 0) { handle.close(); return; }
    if (sameIds(next, ids)) {
      live = drawingsOf();
      if (live.length === 0) { handle.close(); return; }
      // A host that makes the selection read-only, or lifts that, mid-dialog
      // gets the form redrawn to match rather than controls that lie.
      if (lockedOut() !== shownWhy) renderPane();
      else form?.sync(values());
      renderTools();
      coords?.refresh();
      return;
    }
    ids = next;
    live = drawingsOf();
    if (live.length === 0) { handle.close(); return; }
    schema = commonSchema(live.map((d) => d.tool));
    tool = drawingToolOf(live[0]!.tool);
    frame.setTitle(titleOf());
    renderTools();
    renderPane();
    coords?.refresh();
  }
  const off = [
    chart.on('draw:update', refresh),
    chart.on('draw:select', refresh),
    chart.on('draw:remove', refresh),
  ];

  let closedOnce = false;
  const cleanup = (): void => {
    if (closedOnce) return;
    closedOnce = true;
    form?.destroy();
    coords?.destroy();
    for (const dispose of off) dispose();
    opts.onClose?.();
  };
  const session = openPanel(
    ctx, frame.el,
    { ...(anchor === undefined ? { placement: 'below' as const, dismissOnOutside: true } : { anchor, placement: 'below' as const }), onClose: cleanup },
    cleanup,
  );
  if (anchor === undefined) placePanel(ctx.root, frame.el, { point: selectionPoint(ctx.root, chart, live, (id) => draw.screenPoints(id)) });
  const handle: PanelHandle = {
    el: frame.el,
    isOpen: session.isOpen,
    close: () => { form?.destroy(); session.close(); cleanup(); },
  };
  return handle;
}
