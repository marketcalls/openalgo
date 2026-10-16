/**
 * The indicator picker: everything the indicator registry holds, grouped by
 * category, with a search box that filters as you type. Built from
 * `registeredIndicators()` rather than a list of names, so a descriptor a host
 * registers itself appears beside the built-ins, and a widget loaded without
 * the indicators tier says so instead of showing an empty box.
 *
 * Picking a row adds an instance and leaves the picker up: a trader building
 * a layout adds three studies in a row, and closing after each would make
 * that three round trips through the menu.
 *
 * With a template store (the widget's `workspaces`), the footer's Templates
 * button opens the saved study sets, bottom left where a dialog keeps its
 * secondary control.
 */
import { widgetText } from '../localization';
import { registeredIndicators } from 'openalgo-charts';
import type { IndicatorApi, IndicatorDescriptor } from 'openalgo-charts';
import type { WorkspaceStore } from 'openalgo-charts/workspace';
import type { WidgetContext } from '../context';
import { button, dialogFrame, el, openPanel, type PanelHandle } from '../form';
import { templateStoreOf } from '../layouts-templates';
import { lazyPart, partFailed, usePart, type PartSlot } from '../lazy';

/** The templates list, fetched when it first opens. Internal. */
export const templatesPart = lazyPart(() => import('../layouts-templates-menu'));

export interface IndicatorPickerOptions {
  /** Runs after each instance is added, with its handle. */
  onAdd?(inst: IndicatorApi): void;
  /** Close the picker after the first add. Default false. */
  closeOnAdd?: boolean;
  /**
   * Where saved indicator templates live. Default: the store the widget was
   * given (`WidgetOptions.workspaces`); null offers none. A store without
   * `planIndicatorTemplateState` offers none either. Since 2.5.10.
   */
  templates?: WorkspaceStore | null;
}

/** Descriptors matching `query` (name, id or category, case-insensitive), sorted by name. */
export function filterIndicators(all: readonly IndicatorDescriptor[], query: string): IndicatorDescriptor[] {
  const q = query.trim().toLowerCase();
  const hit = (d: IndicatorDescriptor): boolean => q === ''
    || d.name.toLowerCase().includes(q)
    || d.id.toLowerCase().includes(q)
    || (d.category ?? '').toLowerCase().includes(q);
  return all.filter(hit).sort((a, b) => a.name.localeCompare(b.name));
}

/** Descriptors grouped by category, categories in alphabetical order, `Other` for the unfiled. */
export function groupIndicators(list: readonly IndicatorDescriptor[]): Array<[string, IndicatorDescriptor[]]> {
  const byCat = new Map<string, IndicatorDescriptor[]>();
  for (const d of list) {
    const cat = d.category ?? 'Other';
    const bucket = byCat.get(cat);
    if (bucket === undefined) byCat.set(cat, [d]); else bucket.push(d);
  }
  return Array.from(byCat.entries()).sort((a, b) => a[0].localeCompare(b[0]));
}

/**
 * Open the picker below `anchor` (the toolbar's Indicators button), or centred
 * when there is none.
 */
export function mountIndicatorPicker(
  ctx: WidgetContext, anchor?: HTMLElement, opts: IndicatorPickerOptions = {},
): PanelHandle {
  const { chart } = ctx;
  const doc = ctx.document;
  const all = registeredIndicators();

  const frame = dialogFrame(doc, { translate: ctx.translate, title: widgetText(ctx, 'Indicators'), className: 'oac-pick', onClose: () => handle.close() });
  const find = el(doc, 'input', 'oac-pick__find');
  find.type = 'search';
  find.placeholder = widgetText(ctx, 'Search indicators');
  find.setAttribute('aria-label', widgetText(ctx, 'Search indicators'));
  find.setAttribute('spellcheck', 'false');
  const findWrap = el(doc, 'div', 'oac-pick__findwrap');
  findWrap.appendChild(find);
  const list = el(doc, 'div', 'oac-pick__list');
  list.setAttribute('role', 'listbox');
  list.setAttribute('aria-label', widgetText(ctx, 'Indicators'));
  frame.body.appendChild(findWrap);
  frame.body.appendChild(list);
  const runningHead = el(doc, 'div', 'oac-head oac-pick__running-head', widgetText(ctx, 'schema.ui.indicatorPicker.running', {}, 'Running studies'));
  const running = el(doc, 'div', 'oac-pick__running');
  running.setAttribute('aria-label', widgetText(ctx, 'schema.ui.indicatorPicker.running', {}, 'Running studies'));
  frame.body.appendChild(runningHead);
  frame.body.appendChild(running);
  frame.actions.appendChild(button(doc, { label: widgetText(ctx, 'Done'), variant: 'primary', onClick: () => handle.close() }));
  const templates = opts.templates === undefined ? templateStoreOf(ctx) : opts.templates ?? undefined;
  let templatesMenu: PanelHandle | null = null;
  if (templates?.planIndicatorTemplateState !== undefined) {
    // The list loads on first use; a press while it loads opens it once, and none opens after the picker closed.
    const slot: PartSlot = { waiting: null };
    const open = button(doc, { label: widgetText(ctx, 'Templates'), icon: 'template', onClick: () => {
      usePart(templatesPart, module => {
        templatesMenu?.close();
        templatesMenu = module.openTemplatesMenu(ctx, open, templates);
      }, error => ctx.toast(partFailed(ctx, widgetText(ctx, 'Templates'), error), 'error'), () => handle.isOpen(), { slot, doc, from: open });
    } });
    open.dataset.action = 'templates';
    open.setAttribute('aria-haspopup', 'dialog');
    frame.lead.appendChild(open);
  }

  let rows: HTMLButtonElement[] = [];
  let active = -1;

  const onChart = (id: string): number => chart.indicators().filter((i) => i.indicatorId === id).length;

  const setActive = (i: number): void => {
    if (rows.length === 0) { active = -1; return; }
    active = Math.max(0, Math.min(rows.length - 1, i));
    rows.forEach((r, k) => {
      r.classList.toggle('is-active', k === active);
      r.setAttribute('aria-selected', k === active ? 'true' : 'false');
    });
  };

  const add = (d: IndicatorDescriptor): void => {
    const inst = chart.addIndicator(d.id);
    ctx.toast(widgetText(ctx, 'Added {name}', { name: inst.name }), 'success');
    opts.onAdd?.(inst);
    if (opts.closeOnAdd === true) { handle.close(); return; }
    paint();
    find.focus();
  };

  function paintRunning(): void {
    running.innerHTML = '';
    // A study its host keeps out of the inventory stays out of this list too.
    const instances = chart.indicators().filter(inst => inst.policy().listed !== false);
    if (instances.length === 0) {
      running.appendChild(el(doc, 'div', 'oac-empty oac-pick__running-empty', widgetText(ctx, 'schema.ui.indicatorPicker.empty', {}, 'No running studies')));
      return;
    }
    const ordinal = new Map<string, number>();
    for (const inst of instances) {
      const n = (ordinal.get(inst.indicatorId) ?? 0) + 1;
      ordinal.set(inst.indicatorId, n);
      const row = el(doc, 'div', 'oac-pick__running-row');
      row.dataset.instanceId = inst.id;
      row.appendChild(el(doc, 'span', 'oac-pick__running-name', inst.name));
      row.appendChild(el(doc, 'span', 'oac-pick__running-number', String(n)));
      const removeLabel = widgetText(ctx, 'schema.ui.indicatorPicker.remove', {}, 'Remove');
      const remove = button(doc, {
        label: removeLabel,
        onClick: () => { chart.removeIndicator(inst.id); paint(); find.focus(); },
      });
      remove.classList.add('oac-pick__remove');
      remove.setAttribute('aria-label', `${removeLabel} ${inst.name} ${n}`);
      // Shown greyed with its reason: the host keeps this study on the chart.
      if (inst.policy().removable === false) {
        remove.disabled = true;
        remove.title = widgetText(ctx, 'protected');
        remove.setAttribute('aria-label', `${removeLabel} ${inst.name} ${n}, ${widgetText(ctx, 'protected')}`);
      }
      row.appendChild(remove);
      running.appendChild(row);
    }
  }

  function paint(): void {
    paintRunning();
    const query = find.value;
    list.innerHTML = '';
    rows = [];
    if (all.length === 0) {
      list.appendChild(el(doc, 'div', 'oac-empty',
        widgetText(ctx, 'No indicators are registered. Import the indicators tier to fill this list.')));
      return;
    }
    const localized = all.map(descriptor => ({ ...descriptor, name: widgetText(ctx, `schema.indicator.${descriptor.id}.name`, {}, descriptor.name), category: descriptor.category === undefined ? undefined : widgetText(ctx, `schema.indicator.category.${descriptor.category}`, {}, descriptor.category) }));
    const shown = filterIndicators(localized, query);
    if (shown.length === 0) {
      list.appendChild(el(doc, 'div', 'oac-empty', widgetText(ctx, 'No match')));
      return;
    }
    for (const [cat, items] of groupIndicators(shown)) {
      list.appendChild(el(doc, 'div', 'oac-head', cat === 'Other' ? widgetText(ctx, 'Other') : cat));
      for (const d of items) {
        const row = el(doc, 'button', 'oac-pick__row');
        row.type = 'button';
        row.setAttribute('role', 'option');
        row.dataset.id = d.id;
        row.appendChild(el(doc, 'span', 'oac-pick__name', d.name));
        const n = onChart(d.id);
        if (n > 0) {
          const badge = el(doc, 'span', 'oac-pick__count', n === 1 ? widgetText(ctx, 'on chart') : widgetText(ctx, 'on chart x{count}', { count: n }));
          badge.setAttribute('aria-label', n === 1 ? widgetText(ctx, 'one instance on the chart') : widgetText(ctx, '{count} instances on the chart', { count: n }));
          row.appendChild(badge);
        }
        row.addEventListener('click', (e) => { e.stopPropagation(); add(d); });
        list.appendChild(row);
        rows.push(row);
      }
    }
    setActive(active < 0 ? 0 : active);
  }

  find.addEventListener('input', () => { active = 0; paint(); });
  find.addEventListener('keydown', (e) => {
    const k = (e as KeyboardEvent).key;
    if (k === 'ArrowDown') { e.preventDefault(); setActive(active + 1); }
    else if (k === 'ArrowUp') { e.preventDefault(); setActive(active - 1); }
    else if (k === 'Enter') {
      e.preventDefault();
      const row = rows[active];
      const id = row?.dataset.id;
      const d = all.find((x) => x.id === id);
      if (d !== undefined) add(d);
    }
  });
  paint();

  const offObjects = chart.on('objects:change', paint);
  const offRemove = chart.on('indicatorRemoved', paint);
  const offRestore = chart.on('state:restore:end', paint);
  const cleanup = (): void => { offObjects(); offRemove(); offRestore(); templatesMenu?.close(); };

  const panel = openPanel(
    ctx, frame.el,
    anchor === undefined ? { placement: 'center', modal: true, initialFocus: find } : { anchor, placement: 'below', initialFocus: find },
    cleanup,
  );
  const handle: PanelHandle = {
    el: panel.el, isOpen: panel.isOpen,
    close: () => { if (!panel.isOpen()) return; cleanup(); panel.close(); },
  };
  return handle;
}

/** Include beside the dialog stylesheet in the widget's static CSP stylesheet. */
export const INDICATOR_PICKER_CSS = `
.oac-widget .oac-pick__running-head { margin-top: 10px; border-top: 1px solid var(--oac-bd); padding-top: 9px; }
.oac-widget .oac-pick__running { display: grid; gap: 1px; max-height: 132px; overflow-y: auto; scrollbar-width: thin; scrollbar-color: var(--oac-sb-thumb) transparent; }
.oac-widget .oac-pick__running::-webkit-scrollbar { width: 6px; }
.oac-widget .oac-pick__running::-webkit-scrollbar-thumb { background: var(--oac-sb-thumb); border-radius: 3px; }
.oac-widget .oac-pick__running-row { display: flex; align-items: center; gap: 7px; min-height: 29px; padding: 2px 6px; }
.oac-widget .oac-pick__running-name { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.oac-widget .oac-pick__running-number { min-width: 16px; color: var(--oac-mut); font-size: 11px; text-align: right; }
.oac-widget .oac-pick__running-row .oac-pick__remove { height: 23px; min-height: 23px; padding: 2px 6px; }
`;
