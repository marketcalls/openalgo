/**
 * The indicator templates list, from the indicator picker's footer: each
 * saved template applies in place of the chart's studies or beside them, and
 * the chart's studies save as a new one.
 *
 * It loads on first use (lazy.ts): a widget whose user never opens it never
 * fetches it. Applying and saving are layouts-templates.ts's, which a host
 * can call without it.
 */
import { isReplaying } from 'openalgo-charts';
import type { IndicatorTemplateDocument, IndicatorTemplateInput, WorkspaceCatalog, WorkspaceStore } from 'openalgo-charts/workspace';
import type { WidgetContext } from './context';
import { openTemplateNamePrompt } from './drawing-templates';
import { button, el, stopOwnKeys, type PanelHandle } from './form';
import { applyIndicatorTemplate, hostKept, saveIndicatorTemplate, type IndicatorTemplateApplyMode } from './layouts-templates';
import { errorText, widgetText } from './localization';
import { addWidgetStyles } from './styles';

/** Studies a template would hold: the user's, none of the host's. */
const userStudies = (ctx: Pick<WidgetContext, 'chart'>): number =>
  ctx.chart.indicators().filter(study => !hostKept((study as Partial<typeof study>).policy?.())).length;

/**
 * The saved templates, from the indicator picker's footer: each applies in
 * place of the chart's studies or beside them, and the chart's studies save
 * as a new one. Closes once a template is applied.
 */
export function openTemplatesMenu(ctx: WidgetContext, anchor: HTMLElement, store: WorkspaceStore): PanelHandle {
  const doc = ctx.document;
  addWidgetStyles(doc, INDICATOR_TEMPLATES_CSS);
  const text = (key: string, fallback: string, values: Record<string, string | number> = {}): string =>
    widgetText(ctx, `schema.ui.templates.${key}`, values, fallback);
  const card = el(doc, 'div', 'oac-templates');
  card.setAttribute('role', 'dialog');
  card.setAttribute('aria-label', text('title', 'Indicator templates'));
  const head = el(doc, 'div', 'oac-head', widgetText(ctx, 'Templates'));
  const list = el(doc, 'div', 'oac-templates__list');
  list.setAttribute('role', 'list');
  list.setAttribute('aria-label', widgetText(ctx, 'Templates'));
  const message = el(doc, 'p', 'oac-templates__message');
  message.setAttribute('role', 'status');
  message.setAttribute('aria-live', 'polite');
  const foot = el(doc, 'div', 'oac-templates__foot');
  const save = button(doc, { label: text('save', 'Save studies as template...'), icon: 'save', onClick: () => askName() });
  save.dataset.action = 'save-template';
  foot.appendChild(save);
  card.append(head, list, message, foot);
  stopOwnKeys(card);

  let catalog: WorkspaceCatalog | null = null;
  let failed = false;
  let asking: string | null = null;
  let prompt: PanelHandle | null = null;
  let closed = false;
  const say = (words: string, error = false): void => {
    message.textContent = words;
    message.classList.toggle('is-error', error);
    message.setAttribute('role', error ? 'alert' : 'status');
  };
  const reason = (error: unknown): string => errorText(ctx, error);
  const disable = (b: HTMLButtonElement, why: string | null): void => {
    b.setAttribute('aria-disabled', String(why !== null));
    if (why === null) b.removeAttribute('title'); else b.title = why;
  };

  function paint(): void {
    const focused = doc.activeElement as HTMLElement | null;
    const keep = focused !== null && list.contains(focused)
      ? { id: (focused.closest('[data-template-id]') as HTMLElement | null)?.dataset.templateId, action: focused.dataset.action } : null;
    list.textContent = '';
    const replaying = isReplaying(ctx.chart);
    const templates = catalog?.templates ?? [];
    if (catalog === null) list.appendChild(el(doc, 'div', 'oac-empty', failed ? text('loadFailed', 'Templates could not be loaded') : text('loading', 'Loading templates')));
    else if (templates.length === 0) list.appendChild(el(doc, 'div', 'oac-empty', text('empty', 'No saved templates yet')));
    for (const template of templates) {
      const row = el(doc, 'div', 'oac-templates__row');
      row.setAttribute('role', 'listitem');
      row.dataset.templateId = template.id;
      const name = el(doc, 'span', 'oac-templates__name', template.name);
      const count = template.indicators.length;
      const meta = el(doc, 'span', 'oac-templates__meta', count === 1 ? text('one', '1 study') : text('count', '{count} studies', { count }));
      if (asking === template.id) {
        row.classList.add('is-confirm');
        const keepButton = button(doc, { label: text('keep', 'Keep'), onClick: () => { asking = null; paint(); } });
        keepButton.dataset.action = 'keep';
        const drop = button(doc, { label: text('delete', 'Delete'), variant: 'danger', onClick: () => { void remove(template); } });
        drop.dataset.action = 'confirm-delete';
        row.append(el(doc, 'span', 'oac-templates__name', text('confirm', 'Delete {name}?', { name: template.name })), keepButton, drop);
        list.appendChild(row);
        continue;
      }
      const why = replaying ? text('replay', 'Stop the replay to apply a template') : null;
      const replace = button(doc, { label: text('replace', 'Replace'), onClick: () => apply(template, 'replace') });
      replace.dataset.action = 'replace';
      replace.setAttribute('aria-label', text('replaceNamed', 'Replace the studies with {name}', { name: template.name }));
      const append = button(doc, { label: text('append', 'Append'), onClick: () => apply(template, 'append') });
      append.dataset.action = 'append';
      append.setAttribute('aria-label', text('appendNamed', 'Add {name} to the studies', { name: template.name }));
      disable(replace, why);
      disable(append, why);
      const trash = button(doc, { label: text('deleteNamed', 'Delete {name}', { name: template.name }), icon: 'trash', iconOnly: true,
        onClick: () => { asking = template.id; paint(); list.querySelector<HTMLElement>(`[data-action="keep"]`)?.focus(); } });
      trash.dataset.action = 'delete';
      row.append(name, meta, replace, append, trash);
      list.appendChild(row);
    }
    disable(save, userStudies(ctx) === 0 ? text('nothing', 'Add a study to save a template') : null);
    if (keep !== null) {
      const row = Array.from(list.querySelectorAll<HTMLElement>('[data-template-id]')).find(item => item.dataset.templateId === keep.id) ?? null;
      // Keep goes back to the delete button it came from; a row that went, to
      // the next one, or to Save when the list is empty, never to the page.
      const action = keep.action === 'keep' ? 'delete' : keep.action;
      (row?.querySelector<HTMLElement>(`[data-action="${action}"]`) ?? row?.querySelector<HTMLElement>('button')
        ?? list.querySelector<HTMLElement>('button') ?? save).focus();
    }
  }

  function apply(template: IndicatorTemplateDocument, mode: IndicatorTemplateApplyMode): void {
    if (isReplaying(ctx.chart)) return;
    try {
      const input: IndicatorTemplateInput = template.layout === undefined ? template.indicators : { indicators: template.indicators, layout: template.layout };
      const changed = applyIndicatorTemplate(ctx, store, input, mode, widgetText(ctx, 'Apply {name}', { name: template.name }));
      ctx.toast(changed ? text('applied', 'Applied {name}', { name: template.name }) : text('nothingNew', '{name} added nothing new', { name: template.name }),
        changed ? 'success' : 'info');
      handle.close();
    } catch (error) {
      say(text('applyFailed', '{name} could not be applied: {error}', { name: template.name, error: reason(error) }), true);
    }
  }

  async function remove(template: IndicatorTemplateDocument): Promise<void> {
    asking = null;
    try {
      await store.remove('indicator-template', template.id);
      say(text('removed', 'Deleted {name}', { name: template.name }));
      await reload();
    } catch (error) {
      say(text('removeFailed', '{name} could not be deleted: {error}', { name: template.name, error: reason(error) }), true);
      paint();
    }
  }

  function askName(): void {
    if (save.getAttribute('aria-disabled') === 'true') return;
    prompt?.close();
    prompt = openTemplateNamePrompt(ctx, save, async name => {
      const doc = await saveIndicatorTemplate(ctx, store, name);
      say(widgetText(ctx, 'Saved the template {name}', { name: doc.name }));
      // The prompt closes once the store has it; a store that tells no one is read again meanwhile.
      void reload();
    });
  }

  async function reload(): Promise<void> {
    try {
      const next = await store.load();
      // A load that lands after a newer commit must not put the older catalog back.
      if (catalog === null || next.revision >= catalog.revision) catalog = next;
      failed = false;
    } catch (error) {
      failed = true;
      if (catalog === null) say(text('loadFailedWith', 'Templates could not be loaded: {error}', { error: reason(error) }), true);
    }
    if (!closed) paint();
  }

  const offStore = store.subscribe(next => {
    if (catalog !== null && next.revision <= catalog.revision) return;
    catalog = next;
    if (!closed) paint();
  });
  const offReplay = (['replay:start', 'replay:stop', 'objects:change'] as const).map(event => ctx.chart.on(event, () => { if (!closed) paint(); }));
  paint();
  void reload();

  const close = ctx.openOverlay(card, {
    anchor, placement: 'below', initialFocus: null,
    onClose: () => {
      closed = true;
      offStore();
      for (const offOne of offReplay) offOne();
      prompt?.close();
    },
  });
  // The first control once painted: the list may still be loading.
  (list.querySelector<HTMLElement>('button') ?? save).focus();
  const handle: PanelHandle = { el: card, isOpen: () => !closed, close: () => { if (!closed) close(); } };
  return handle;
}

/** The templates popover's rules, added to the widget sheet when it first opens. */
const INDICATOR_TEMPLATES_CSS = `
.oac-widget .oac-templates { width: 360px; max-width: calc(100% - 16px); max-height: min(420px, calc(100% - 16px)); display: flex; flex-direction: column;
  padding: 4px 6px 6px; background: var(--oac-panel); border: 1px solid var(--oac-bd); border-radius: 10px; box-shadow: var(--oac-shadow); outline: none; }
.oac-widget .oac-templates__list { flex: 1 1 auto; min-height: 0; overflow-y: auto; overscroll-behavior: contain; display: grid; gap: 1px; align-content: start; }
.oac-widget .oac-templates__row { display: flex; align-items: center; gap: 4px; min-height: 32px; padding: 2px 2px 2px 8px; border-radius: 6px; }
.oac-widget .oac-templates__row:hover, .oac-widget .oac-templates__row:focus-within { background: var(--oac-elev); }
.oac-widget .oac-templates__name { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.oac-widget .oac-templates__meta { flex: none; color: var(--oac-mut); font-size: 11px; margin-right: 4px; }
.oac-widget .oac-templates__row .oac-btn { height: 24px; padding: 0 7px; font-size: 11.5px; border-color: var(--oac-bd-soft); }
.oac-widget .oac-templates__row .oac-btn--icon { width: 24px; padding: 0; border-color: transparent; color: var(--oac-mut); }
.oac-widget .oac-templates__row .oac-btn--icon:hover { color: var(--oac-danger); }
.oac-widget .oac-templates__row.is-confirm { background: var(--oac-elev); }
.oac-widget .oac-templates__message { margin: 4px 8px 0; font-size: 11px; color: var(--oac-mut); overflow-wrap: anywhere; }
.oac-widget .oac-templates__message:empty { display: none; }
.oac-widget .oac-templates__message.is-error { color: var(--oac-danger); }
.oac-widget .oac-templates__foot { display: flex; padding: 6px 2px 0; margin-top: 4px; border-top: 1px solid var(--oac-bd-soft); }
.oac-widget.is-mobile .oac-templates__row { min-height: 44px; }
.oac-widget.is-mobile .oac-templates__row .oac-btn { height: 36px; }
.oac-widget.is-mobile .oac-templates__row .oac-btn--icon { width: 36px; }
`;
