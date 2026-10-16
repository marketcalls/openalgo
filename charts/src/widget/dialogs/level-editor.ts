/**
 * The level editor: a popover listing a ladder tool's levels (retracement,
 * extension, channel, fan, time zone, the Gann pair) one row each, with the
 * enable switch, the ratio, the colour and the label the tier's `FibLevel`
 * carries, plus add, remove and reset to the tool's own defaults.
 *
 * The list is edited as a whole and written back through
 * `applyDrawingSettings` and `updateMany`, so every edit is one undo entry
 * per selected drawing and the editor never touches a drawing directly. A
 * multi-selection of ladder tools edits every one of them at once.
 */
import { widgetText } from '../localization';
import {
  DEFAULT_FIB, LEVEL_NEUTRAL, applyDrawingSettings, cloneLevels, drawingSettingsSchema, formatRatio, gannLabel,
  levelColor, readDrawingSetting,
} from 'openalgo-charts/draw';
import type { Drawing, FibLevel, SettingsSchema } from 'openalgo-charts/draw';
import { drawingToolOf, type WidgetContext } from '../context';
import { button, chromeGlyph, declinedPanel, el, openPanel, placePanel, selectionPoint, stopOwnKeys, type PanelHandle } from '../form';
import { createColorPicker, type ColorPickerHandle } from '../color-picker';

export interface LevelEditorOptions {
  /** The drawings to edit. Default: the controller's selection. */
  ids?: readonly string[];
}

/** The ladder a new level is drawn from: the conventional ratios, in order. */
export const FIB_SEQUENCE: readonly number[] = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1, 1.272, 1.414, 1.618, 2, 2.618, 3.618, 4.236];

const RATIO_EPS = 1e-6;
const has = (levels: readonly FibLevel[], ratio: number): boolean =>
  levels.some((l) => Math.abs(l.ratio - ratio) <= RATIO_EPS);

/**
 * The ratio for an added level: the first conventional ratio the ladder does
 * not have, else one past its largest, so "add" always adds something new.
 */
export function nextRatio(levels: readonly FibLevel[]): number {
  for (const r of FIB_SEQUENCE) if (!has(levels, r)) return r;
  let max = 0;
  for (const l of levels) if (Number.isFinite(l.ratio)) max = Math.max(max, l.ratio);
  return max + 1;
}

/** What the tool prints beside an unlabelled level, for the label box's placeholder. */
function levelLabeller(toolId: string): (ratio: number) => string {
  if (toolId === 'gann-fan') return gannLabel;
  if (toolId === 'fib-time-zone') return (r) => String(r);
  return formatRatio;
}

/** The drawings among `ids` the user may edit whose tool declares a levels field, with the first one's schema. */
function ladderDrawings(ctx: WidgetContext, ids: readonly string[]): { drawings: Drawing[]; schema: SettingsSchema | null } {
  const drawings: Drawing[] = [];
  for (const id of ids) {
    const d = ctx.draw.get(id);
    if (d !== undefined && d.policy?.editable !== false && drawingSettingsSchema(d.tool).fields.some((f) => f.kind === 'levels')) drawings.push(d);
  }
  return { drawings, schema: drawings.length === 0 ? null : drawingSettingsSchema(drawings[0]!.tool) }; // length checked first
}

/**
 * Open the editor for the selected ladder drawings, below `anchor` when there
 * is one (the properties dialog's button), else beside the selection.
 */
export function mountLevelEditor(ctx: WidgetContext, anchor?: HTMLElement, opts: LevelEditorOptions = {}): PanelHandle {
  const doc = ctx.document;
  const ids = opts.ids ?? ctx.draw.selection();
  const { drawings, schema } = ladderDrawings(ctx, ids);
  if (schema === null) return declinedPanel(ctx, widgetText(ctx, 'Select a drawing with levels first'));
  const primary = drawings[0]!; // the schema is null exactly when there are no drawings
  const tool = drawingToolOf(primary.tool);
  const levelsField = schema.fields.find((f) => f.kind === 'levels');
  const labelsField = schema.fields.find((f) => f.path === 'style.showLabels');
  const levelsPath = levelsField?.path ?? 'style.levels';
  const defaults: readonly FibLevel[] = tool?.defaultStyle?.levels ?? DEFAULT_FIB;
  const fmt = levelLabeller(primary.tool);

  const readList = (): FibLevel[] => {
    const v = readDrawingSetting(primary, levelsPath);
    return Array.isArray(v) ? cloneLevels(v as FibLevel[]) : cloneLevels(defaults);
  };
  const readLabels = (): boolean => {
    const v = readDrawingSetting(primary, 'style.showLabels');
    return v === undefined ? tool?.defaultStyle?.showLabels === true : v === true;
  };
  let list = readList();

  /** Write `{ path: value }` to every selected ladder as one undo entry. */
  function apply(patch: Record<string, unknown>): void {
    const patches: Array<{ id: string; patch: Partial<Drawing> }> = [];
    for (const d of drawings) {
      const live = ctx.draw.get(d.id);
      if (live === undefined) continue;
      const p = applyDrawingSettings(live, patch, schema as SettingsSchema);
      if (Object.keys(p).length > 0) patches.push({ id: d.id, patch: p });
    }
    if (patches.length > 0) ctx.draw.updateMany(patches);
  }
  const emit = (): void => apply({ [levelsPath]: cloneLevels(list) });

  const root = el(doc, 'div', 'oac-panel oac-levels');
  root.setAttribute('role', 'dialog');
  root.setAttribute('aria-label', widgetText(ctx, 'Levels'));
  root.tabIndex = -1;
  stopOwnKeys(root);

  const head = el(doc, 'div', 'oac-levels__head');
  head.appendChild(el(doc, 'b', 'oac-levels__title', widgetText(ctx, 'Levels')));
  let labelsBox: HTMLInputElement | null = null;
  if (labelsField !== undefined) {
    const lab = el(doc, 'label', 'oac-levels__labels');
    labelsBox = el(doc, 'input');
    labelsBox.type = 'checkbox';
    labelsBox.checked = readLabels();
    labelsBox.dataset.path = labelsField.path;
    const box = labelsBox;
    box.addEventListener('change', () => apply({ [labelsField.path]: box.checked }));
    lab.appendChild(box);
    lab.appendChild(el(doc, 'span', undefined, widgetText(ctx, 'Show labels')));
    head.appendChild(lab);
  }
  head.appendChild(button(doc, { label: widgetText(ctx, 'Close'), icon: 'close', iconOnly: true, onClick: () => handle.close() }));
  root.appendChild(head);

  const rows = el(doc, 'div', 'oac-levels__rows');
  root.appendChild(rows);
  let pickers: ColorPickerHandle[] = [];

  // A row's handlers read list[i] with `!`: whatever changes the list's length
  // repaints, and a repaint builds every row again with its own index.
  function row(lv: FibLevel, i: number): HTMLElement {
    const r = el(doc, 'div', 'oac-levels__row' + (lv.enabled === false ? ' is-off' : ''));

    const on = el(doc, 'input');
    on.type = 'checkbox';
    on.checked = lv.enabled !== false;
    on.addEventListener('change', () => {
      // `true` is the default, so an enabled level carries no flag at all.
      if (on.checked) delete list[i]!.enabled; else list[i]!.enabled = false;
      r.classList.toggle('is-off', !on.checked);
      emit();
    });
    r.appendChild(on);

    const ratio = el(doc, 'input');
    ratio.type = 'number';
    ratio.step = '0.001';
    ratio.value = String(lv.ratio);
    ratio.addEventListener('change', () => {
      const n = Number(ratio.value);
      // A blank or unparseable ratio would drop the level on coercion; keep
      // the last good value on screen instead.
      if (ratio.value.trim() === '' || !Number.isFinite(n)) { ratio.value = String(list[i]!.ratio); return; }
      list[i]!.ratio = n;
      if (list[i]!.label === undefined) label.placeholder = fmt(n);
      name();
      emit();
    });
    r.appendChild(ratio);

    const color = createColorPicker(doc, {
      id: `oac-level-${primary.id}-${i}`,
      label: widgetText(ctx, 'Level {level} color', { level: fmt(lv.ratio) }),
      value: lv.color ?? primary.style.color ?? levelColor(lv.ratio) ?? LEVEL_NEUTRAL,
      translate: ctx.translate, openOverlay: ctx.openOverlay,
      onChange: value => { list[i]!.color = value; emit(); },
    });
    pickers.push(color);
    r.appendChild(color.el);

    const label = el(doc, 'input');
    label.type = 'text';
    label.value = lv.label ?? '';
    label.placeholder = fmt(lv.ratio);
    label.setAttribute('spellcheck', 'false');
    label.addEventListener('change', () => {
      const v = label.value.trim();
      if (v === '') delete list[i]!.label; else list[i]!.label = v;
      emit();
    });
    r.appendChild(label);

    const x = el(doc, 'button', 'oac-levels__x');
    x.type = 'button';
    x.appendChild(chromeGlyph(doc, 'close'));
    x.addEventListener('click', (e) => { e.stopPropagation(); list.splice(i, 1); paint(); emit(); });
    r.appendChild(x);
    // Every control names its level, or seven rows would read the same.
    function name(): void {
      const level = fmt(list[i]!.ratio);
      on.setAttribute('aria-label', widgetText(ctx, 'Level {level} enabled', { level }));
      ratio.setAttribute('aria-label', widgetText(ctx, 'Level {level} ratio', { level }));
      color.trigger.setAttribute('aria-label', widgetText(ctx, 'Level {level} color', { level }));
      label.setAttribute('aria-label', widgetText(ctx, 'Level {level} label', { level }));
      x.setAttribute('aria-label', widgetText(ctx, 'Remove level {level}', { level }));
    }
    name();
    return r;
  }

  function paint(): void {
    pickers.forEach(picker => picker.destroy());
    pickers = [];
    rows.innerHTML = '';
    if (list.length === 0) {
      rows.appendChild(el(doc, 'div', 'oac-empty', widgetText(ctx, 'No levels. Add one, or reset to the defaults.')));
      return;
    }
    list.forEach((lv, i) => rows.appendChild(row(lv, i)));
  }
  paint();

  const foot = el(doc, 'div', 'oac-levels__foot');
  foot.appendChild(button(doc, {
    label: widgetText(ctx, 'Add level'), icon: 'plus',
    onClick: () => {
      const r = nextRatio(list);
      const lv: FibLevel = { ratio: r };
      const c = levelColor(r);
      if (c !== LEVEL_NEUTRAL) lv.color = c;
      list.push(lv);
      paint();
      emit();
    },
  }));
  foot.appendChild(el(doc, 'span', 'oac-spacer'));
  foot.appendChild(button(doc, { label: widgetText(ctx, 'Reset'), onClick: () => { list = cloneLevels(defaults); paint(); emit(); } }));
  root.appendChild(foot);

  // An edit from elsewhere (an undo, the properties dialog) repaints the rows,
  // unless the user is typing in one, in which case their box wins.
  const offUpdate = ctx.chart.on('draw:update', () => {
    if (!handle.isOpen()) return;
    if (ctx.draw.get(primary.id) === undefined) { handle.close(); return; }
    const fresh = readList();
    if (JSON.stringify(fresh) !== JSON.stringify(list) && !root.contains(doc.activeElement)) { list = fresh; paint(); }
    if (labelsBox !== null && labelsBox !== doc.activeElement) labelsBox.checked = readLabels();
  });
  const offRemove = ctx.chart.on('draw:remove', () => {
    if (handle.isOpen() && ctx.draw.get(primary.id) === undefined) handle.close();
  });

  const cleanup = (): void => { pickers.forEach(picker => picker.destroy()); offUpdate(); offRemove(); };
  const handle = openPanel(
    ctx, root,
    anchor === undefined ? { placement: 'below', dismissOnOutside: true } : { anchor, placement: 'below' },
    cleanup,
  );
  if (anchor === undefined) placePanel(ctx.root, root, { point: selectionPoint(ctx.root, ctx.chart, drawings) });
  const close = handle.close;
  return {
    el: root,
    isOpen: handle.isOpen,
    close: () => { cleanup(); close(); },
  };
}
