/**
 * Drawing style templates in the widget: the look of a drawing saved by name
 * or as its tool's default, from a `DrawingTemplateStore` the host hands over
 * (`openalgo-charts/workspace` ships `DrawingTemplateRepository`).
 *
 * The store is asynchronous and the chart is not, so the catalog is held here
 * as last loaded or committed, and every decision a placement needs is made
 * from that copy in the same turn. A template holds settings by schema path,
 * and is applied through the drawing's own schema, so a path its tool no
 * longer declares is dropped and a value is coerced to its field's kind.
 *
 * A tool's default reaches only drawings the user places with that tool
 * after it was saved: a drawing already on the chart keeps its look, and a
 * pasted or duplicated one keeps the look it was copied with. It is folded
 * into the placement's own undo step (the controller's `untracked`), so
 * placing a drawing stays one step and its redo brings the default back too.
 */
import { applyDrawingSettings, drawingSettingsSchema, readDrawingSettings } from 'openalgo-charts/draw';
import type { Drawing, DrawingChangeEvent } from 'openalgo-charts/draw';
import type { DrawingTemplate, DrawingTemplateCatalog, DrawingTemplateStore, DrawingTemplateValues } from 'openalgo-charts/workspace';
import { drawingToolOf, editableIds, historyStep, type WidgetContext } from './context';
import { button, dialogFrame, el, openPanel, type PanelHandle } from './form';
import { errorText, widgetText } from './localization';

/** What the widget holds for a template store; see `createDrawingTemplates`. */
export interface DrawingTemplates {
  readonly store: DrawingTemplateStore;
  /** The catalog as last loaded or committed; null until the first load lands, or when it failed. */
  catalog(): DrawingTemplateCatalog | null;
  /** The saved templates of one tool, in the order they were saved. */
  templatesFor(tool: string): DrawingTemplate[];
  /** The look new drawings of `tool` start with, if one was saved. */
  defaultFor(tool: string): DrawingTemplateValues | undefined;
  /** The look of a drawing: every setting its schema declares, except the words it says and where it is. */
  capture(drawing: Drawing): DrawingTemplateValues;
  /** Apply a look to the editable drawings among `ids` as one undo step. Returns how many changed. */
  apply(ids: readonly string[], values: DrawingTemplateValues): number;
  /** Save the look of drawing `id` as its tool's default. */
  saveDefault(id: string): Promise<void>;
  /** Forget a tool's default. */
  clearDefault(tool: string): Promise<void>;
  /** Save the look of drawing `id` under `name`. */
  saveTemplate(id: string, name: string): Promise<DrawingTemplate>;
  removeTemplate(templateId: string): Promise<void>;
  /** Called after the held catalog changes. Returns the unsubscribe. */
  subscribe(listener: () => void): () => void;
  destroy(): void;
}

/** The paths a template holds: the look, never the words or the anchoring. */
const LOOK = /^(style|text|props)\./;

function isTemplateValue(value: unknown): value is DrawingTemplateValues[string] {
  return typeof value === 'string' || typeof value === 'boolean' || (typeof value === 'number' && Number.isFinite(value)) || Array.isArray(value);
}

/**
 * Hold `store`'s catalog for the widget in `ctx` and give each drawing the
 * user places the default saved for its tool. `destroy` stops both.
 */
export function createDrawingTemplates(ctx: WidgetContext, store: DrawingTemplateStore): DrawingTemplates {
  const { draw, chart } = ctx;
  let held: DrawingTemplateCatalog | null = null;
  let destroyed = false;
  const listeners = new Set<() => void>();
  const notify = (): void => { for (const listener of Array.from(listeners)) listener(); };
  const take = (catalog: DrawingTemplateCatalog): void => {
    // A load that lands after a newer commit must not put the older catalog back.
    if (destroyed || (held !== null && catalog.revision < held.revision)) return;
    held = catalog;
    notify();
  };
  const unsubscribe = store.subscribe(take);
  store.load().then(take, () => {
    if (!destroyed) ctx.status(widgetText(ctx, 'Drawing templates could not be loaded'), 'error');
  });

  const templatesFor = (tool: string): DrawingTemplate[] => held?.templates.filter((item) => item.tool === tool) ?? [];
  const defaultFor = (tool: string): DrawingTemplateValues | undefined => held?.defaults.find((item) => item.tool === tool)?.values;

  function capture(drawing: Drawing): DrawingTemplateValues {
    const out: DrawingTemplateValues = {};
    for (const [path, value] of Object.entries(readDrawingSettings(drawing, drawingSettingsSchema(drawing.tool)))) {
      if (LOOK.test(path) && path !== 'text.value' && isTemplateValue(value)) out[path] = value;
    }
    return out;
  }

  function patchesFor(ids: readonly string[], values: DrawingTemplateValues): Array<{ id: string; patch: Partial<Drawing> }> {
    const out: Array<{ id: string; patch: Partial<Drawing> }> = [];
    for (const id of editableIds(draw, ids)) {
      const d = draw.get(id);
      if (d === undefined) continue;
      const patch = applyDrawingSettings(d, values, drawingSettingsSchema(d.tool));
      if (Object.keys(patch).length > 0) out.push({ id, patch });
    }
    return out;
  }

  function apply(ids: readonly string[], values: DrawingTemplateValues): number {
    const patches = patchesFor(ids, values);
    if (patches.length > 0) draw.updateMany(patches);
    return patches.length;
  }

  /**
   * A placement is an `add` step of one drawing of the tool in use, which
   * the controller closes, in the same turn, by announcing the tool again
   * (`draw:tool`: the same one while drawing stays on, else none). A paste,
   * a duplicate and a host's `add` are never followed by one, so they keep
   * the look they came with even while a tool of their kind is in use.
   */
  let placed: string | null = null;
  const onChange = (payload: unknown): void => {
    placed = null;
    const change = payload as DrawingChangeEvent;
    if (destroyed || change.kind !== 'add' || change.step === undefined || change.linked === true || change.ids.length !== 1) return;
    const d = draw.get(change.ids[0]!); // exactly one id, checked above
    if (d === undefined || draw.activeTool() !== d.tool || defaultFor(d.tool) === undefined) return;
    const candidate = d.id;
    placed = candidate;
    // Only the turn that added it can confirm it.
    queueMicrotask(() => { if (placed === candidate) placed = null; });
  };
  const onTool = (): void => {
    const id = placed;
    placed = null;
    const d = id === null || destroyed ? undefined : draw.get(id);
    const values = d === undefined ? undefined : defaultFor(d.tool);
    if (d === undefined || values === undefined) return;
    const patches = patchesFor([d.id], values);
    if (patches.length === 0) return;
    const run = (): void => { draw.updateMany(patches); };
    // The host's own act: every recorded step, the placement included, takes it in.
    if (ctx.history !== undefined && !ctx.history.isDestroyed) ctx.history.ignore(run);
    else draw.untracked(run);
  };
  const offs = [chart.on('drawing:change', onChange), chart.on('draw:tool', onTool)];

  const commit = async <T>(work: () => Promise<T>, done: string): Promise<T> => {
    try {
      const result = await work();
      if (!destroyed) ctx.toast(done, 'success');
      return result;
    } catch (error) {
      if (!destroyed) ctx.toast(widgetText(ctx, 'The drawing template could not be saved: {error}', { error: errorText(ctx, error) }), 'error');
      throw error;
    }
  };
  const drawingOf = (id: string): Drawing => {
    const d = draw.get(id);
    if (d === undefined) throw new Error(widgetText(ctx, 'Select a drawing first'));
    return d;
  };
  const toolLabel = (tool: string): string => widgetText(ctx, `schema.drawing.${tool}.name`, {}, drawingToolOf(tool)?.name ?? tool);

  return {
    store,
    catalog: () => held,
    templatesFor,
    defaultFor,
    capture,
    apply,
    saveDefault: async (id) => {
      const d = drawingOf(id);
      await commit(() => store.setDefault(d.tool, capture(d)), widgetText(ctx, 'New {tool} drawings start with this look', { tool: toolLabel(d.tool) }));
    },
    clearDefault: async (tool) => {
      await commit(() => store.setDefault(tool, null), widgetText(ctx, 'New {tool} drawings start with the standard look', { tool: toolLabel(tool) }));
    },
    saveTemplate: async (id, name) => {
      const d = drawingOf(id);
      return commit(() => store.saveTemplate(name, d.tool, capture(d)), widgetText(ctx, 'Saved the template {name}', { name: name.trim() }));
    },
    removeTemplate: async (templateId) => {
      await commit(() => store.removeTemplate(templateId), widgetText(ctx, 'Removed the template'));
    },
    subscribe: (listener) => {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
    destroy: () => {
      if (destroyed) return;
      destroyed = true;
      for (const off of offs) off();
      unsubscribe();
      listeners.clear();
    },
  };
}

/** One row of a template menu, in the shape `openMenu` takes. */
export interface TemplateMenuRow {
  label: string;
  sub?: string | undefined;
  on?: boolean;
  disabled?: boolean;
  danger?: boolean;
  onSelect: () => void;
}

/**
 * The template rows for a selection: save as default, save by name, and
 * each saved template of the selection's tool to apply. A selection of
 * several tools has no one tool to save for or to offer templates of, and a
 * read-only one nothing to apply them to, so those rows are greyed.
 */
export function templateMenuRows(
  ctx: WidgetContext, templates: DrawingTemplates, ids: readonly string[], anchor: HTMLElement | undefined,
): Array<TemplateMenuRow | string> {
  const drawings = ids.map((id) => ctx.draw.get(id)).filter((d): d is Drawing => d !== undefined);
  const tools = new Set(drawings.map((d) => d.tool));
  const tool = tools.size === 1 ? drawings[0]!.tool : null; // one tool means at least one drawing
  const primary = drawings[0];
  const editable = editableIds(ctx.draw, ids).length > 0;
  const rows: Array<TemplateMenuRow | string> = [widgetText(ctx, 'Templates')];
  const quiet = (work: () => Promise<unknown>): void => { void work().catch(() => { /* reported by a toast */ }); };
  rows.push({
    label: widgetText(ctx, 'Save as default for this tool'),
    sub: tool === null ? widgetText(ctx, 'one tool at a time') : undefined,
    disabled: tool === null,
    onSelect: () => { if (primary !== undefined) quiet(() => templates.saveDefault(primary.id)); },
  });
  if (tool !== null && templates.defaultFor(tool) !== undefined) {
    rows.push({ label: widgetText(ctx, 'Forget the default for this tool'), onSelect: () => quiet(() => templates.clearDefault(tool)) });
  }
  rows.push({
    label: widgetText(ctx, 'Save as template...'),
    disabled: tool === null,
    onSelect: () => {
      if (primary === undefined) return;
      openTemplateNamePrompt(ctx, anchor, (name) => templates.saveTemplate(primary.id, name));
    },
  });
  const saved = tool === null ? [] : templates.templatesFor(tool);
  for (const item of saved) {
    rows.push({
      label: widgetText(ctx, 'Apply {name}', { name: item.name }),
      disabled: !editable,
      sub: editable ? undefined : widgetText(ctx, 'read-only'),
      onSelect: () => { historyStep(ctx, 'template', () => templates.apply(ids, item.values)); },
    });
  }
  return rows;
}

let promptSequence = 0;

/**
 * Ask for a template name, then run `save` with it. The prompt stays open
 * with the reason when the save fails, so a name the store refused can be
 * changed rather than typed again.
 */
export function openTemplateNamePrompt(
  ctx: WidgetContext, anchor: HTMLElement | undefined, save: (name: string) => Promise<unknown>,
): PanelHandle {
  const doc = ctx.document;
  const frame = dialogFrame(doc, { translate: ctx.translate, title: widgetText(ctx, 'Save as template'), className: 'oac-template-name', onClose: () => handle.close() });
  const label = el(doc, 'label', 'oac-template-name__label', widgetText(ctx, 'Template name'));
  const input = el(doc, 'input', 'oac-template-name__input');
  input.type = 'text';
  input.maxLength = 120;
  input.id = `oac-template-name-${++promptSequence}`;
  label.htmlFor = input.id;
  const error = el(doc, 'p', 'oac-input-error');
  error.setAttribute('role', 'alert');
  error.hidden = true;
  frame.body.append(label, input, error);
  let busy = false;
  const submit = async (): Promise<void> => {
    const name = input.value.trim();
    if (busy) return;
    if (name === '') {
      error.textContent = widgetText(ctx, 'Enter a name');
      error.hidden = false;
      input.setAttribute('aria-invalid', 'true');
      input.focus();
      return;
    }
    busy = true;
    try {
      await save(name);
      handle.close();
    } catch (reason) {
      error.textContent = errorText(ctx, reason);
      error.hidden = false;
      input.setAttribute('aria-invalid', 'true');
    } finally { busy = false; }
  };
  input.addEventListener('keydown', (event) => {
    if ((event as KeyboardEvent).key !== 'Enter') return;
    event.preventDefault();
    void submit();
  });
  input.addEventListener('input', () => { error.hidden = true; input.removeAttribute('aria-invalid'); });
  frame.actions.appendChild(button(doc, { label: widgetText(ctx, 'Cancel'), onClick: () => handle.close() }));
  const confirm = frame.actions.appendChild(button(doc, { label: widgetText(ctx, 'Save'), variant: 'primary', onClick: () => { void submit(); } }));
  confirm.dataset.action = 'save-template';
  const handle = openPanel(ctx, frame.el, anchor === undefined
    ? { placement: 'center', modal: true, initialFocus: input }
    : { anchor, placement: 'below', initialFocus: input }, () => {});
  return handle;
}

export const DRAWING_TEMPLATES_CSS = `
.oac-widget .oac-template-name { width: 300px; }
.oac-widget .oac-template-name .oac-dialog__body { display: flex; flex-direction: column; gap: 6px; padding-top: 8px; }
.oac-widget .oac-template-name__label { color: var(--oac-mut); font-size: 11px; }
.oac-widget .oac-template-name__input { width: 100%; }
`;
