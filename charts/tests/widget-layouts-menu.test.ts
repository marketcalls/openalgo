/**
 * The Layouts menu on a widget given a `workspaces` store: the top bar button
 * naming the held layout, save, save as, rename, delete with a confirm, the
 * recent list, autosave with its status, the question before unsaved work is
 * dropped, the three ways out of a conflict with another window, the layout
 * reopened on the next page load, autosave held during a replay, the phone
 * layout's More sheet, and a chart grid's charts.
 */
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { ReplayController, applyChartSettings, type Bar } from '../src/index';
import '../src/indicators/index';
import {
  WorkspaceRepository, createMemoryWorkspaceStorage, type WorkspacePayload, type WorkspaceStorage, type WorkspaceStore,
} from '../src/workspace/index';
import {
  createChartGrid, createLayoutsController, createWidget, widgetLayoutTarget,
  type ChartGrid, type LayoutsController, type Widget, type WidgetOptions,
} from '../src/widget/index';
import { ensureWindowGlobal, fakeContainer, fakeWidgetDocument, fire, fireKey, type FakeDocument, type FakeElement } from './helpers/fake-dom-widget';

beforeAll(ensureWindowGlobal);

/** A seeded random walk of five-minute bars, so the chart reads like a traded stock. */
function walk(count: number, start: number, seed: number): Bar[] {
  let s = seed;
  let close = start;
  return Array.from({ length: count }, (_, i) => {
    s = (s * 16807) % 2147483647;
    const open = close;
    close = Math.round((open + (s / 2147483647 - 0.5) * start * 0.004) * 20) / 20;
    return { time: 1_700_000_000 + i * 300, open, high: Math.max(open, close) + 0.35, low: Math.min(open, close) - 0.35, close, volume: 1000 + (s % 500) };
  });
}

const settle = async (): Promise<void> => {
  for (let i = 0; i < 12; i++) await Promise.resolve();
  if (vi.isFakeTimers()) await vi.advanceTimersByTimeAsync(0);
  else await new Promise(r => setTimeout(r, 0));
};

const live: Array<{ destroy(): void }> = [];
afterEach(() => {
  for (const item of live.splice(0)) item.destroy();
  vi.useRealTimers();
});

/** One account's layouts: a storage every repository here shares, as tabs share IndexedDB. */
function account(storage: WorkspaceStorage = createMemoryWorkspaceStorage()) {
  let n = 0;
  const repo = (): WorkspaceRepository => new WorkspaceRepository(storage, 'desk', { id: () => `layout-${++n}`, now: () => 1000 + n });
  return { storage, repo };
}

async function make(options: WidgetOptions = {}, repo: WorkspaceRepository | null = account().repo(), doc: FakeDocument = fakeWidgetDocument()) {
  const widget = createWidget(fakeContainer(doc, 1100, 700) as unknown as HTMLElement, {
    document: doc as unknown as Document, pixelRatio: () => 1, mobile: 'never', panels: false,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    symbol: 'INFY', exchange: 'NSE', interval: '5m',
    ...(repo === null ? {} : { workspaces: repo }), ...options,
  });
  widget.chart.applySize(1000, 600);
  widget.series.setData(walk(240, 1510, 7));
  live.push(widget);
  await settle();
  await widget.layouts?.flush();
  return { widget, doc, repo, root: widget.root as unknown as FakeElement };
}

const q = (root: FakeElement, selector: string): FakeElement | null => root.querySelector(selector) as FakeElement | null;
const must = (root: FakeElement, selector: string): FakeElement => {
  const found = q(root, selector);
  if (found === null) throw new Error(`nothing matches ${selector}`);
  return found;
};

/** Open the menu from the top bar and let its first read land. */
async function openMenu(widget: Widget, root: FakeElement): Promise<FakeElement> {
  must(root, '.oac-topbar__layouts').click();
  await widget.layouts!.flush();
  await settle();
  return must(root, '.oac-layouts');
}

/** Press a control in the menu and wait for what it started. */
async function press(widget: Widget, menu: FakeElement, selector: string): Promise<void> {
  must(menu, selector).click();
  await settle();
  await widget.layouts!.flush();
  await settle();
}

/** Save as, through the name form. */
async function saveAs(widget: Widget, menu: FakeElement, name: string, trigger = '[data-action="save-as"]'): Promise<void> {
  must(menu, trigger).click();
  const input = must(menu, '.oac-layouts__input');
  input.value = name;
  await press(widget, menu, '[data-action="submit-name"]');
}

const rows = (menu: FakeElement, list?: string): string[] =>
  (menu.querySelectorAll(`${list === undefined ? '' : `[data-list="${list}"] `}.oac-layouts__row`) as unknown as FakeElement[])
    .map(row => must(row, '.oac-layouts__row-name').textContent);

describe('the Layouts button', () => {
  it('is there only with a store, names the held layout and marks unsaved changes', async () => {
    const bare = await make({}, null);
    expect(q(bare.root, '.oac-topbar__layouts')).toBeNull();
    expect(bare.widget.layouts).toBeNull();
    expect(bare.widget.openLayouts()).toBe(false);

    const { widget, root } = await make();
    const button = must(root, '.oac-topbar__layouts');
    expect(button.getAttribute('aria-haspopup')).toBe('dialog');
    expect(must(button, '.oac-topbar__layouts-name').textContent).toBe('Layouts');
    const menu = await openMenu(widget, root);
    await saveAs(widget, menu, 'Morning');
    expect(must(button, '.oac-topbar__layouts-name').textContent).toBe('Morning');
    expect(button.dataset.attention).toBe('false');
    expect(button.getAttribute('aria-label')).toBe('Layouts: Morning');
    widget.setInterval('15m');
    await widget.layouts!.flush();
    await settle();
    expect(button.dataset.attention).toBe('true');
    // The mark is a dot; the name says it too.
    expect(button.getAttribute('aria-label')).toBe('Layouts: Morning, Unsaved changes');
    // Reaching it by keyboard or pointer re-reads the tip, and keeps the status in the name.
    fire(button, 'focus');
    expect(button.getAttribute('aria-label')).toBe('Layouts: Morning, Unsaved changes');
    fire(button, 'pointerenter');
    expect(button.getAttribute('aria-label')).toBe('Layouts: Morning, Unsaved changes');
    expect(widget.openLayouts()).toBe(true);
  });
});

describe('the Layouts menu', () => {
  it('saves the chart under a name, prefilled with its symbol and interval, and refuses an empty one', async () => {
    const { widget, root, repo } = await make();
    const menu = await openMenu(widget, root);
    expect(must(menu, '.oac-layouts__name').textContent).toBe('No layout open');
    expect(must(menu, '.oac-layouts__line').textContent).toBe('This chart is not saved as a layout');
    // With nothing held, Save names the chart first.
    must(menu, '[data-action="save"]').click();
    const form = must(menu, '.oac-layouts__form');
    expect(form.hidden).toBe(false);
    const input = must(menu, '.oac-layouts__input');
    expect(input.value).toBe('INFY 5m');
    input.value = '   ';
    await press(widget, menu, '[data-action="submit-name"]');
    expect(must(menu, '.oac-input-error').textContent).toBe('Enter a name');
    expect(input.getAttribute('aria-invalid')).toBe('true');
    expect((await repo!.load()).workspaces).toHaveLength(0);
    input.value = 'Morning';
    await press(widget, menu, '[data-action="submit-name"]');
    expect(form.hidden).toBe(true);
    const catalog = await repo!.load();
    expect(catalog.workspaces.map(doc => doc.name)).toEqual(['Morning']);
    expect(catalog.activeWorkspaceId).toBe(catalog.workspaces[0].id);
    expect(catalog.workspaces[0].panes[0]).toMatchObject({ symbol: 'INFY', interval: '5m', chartType: 'candlestick' });
    expect(must(menu, '.oac-layouts__name').textContent).toBe('Morning');
    expect(must(menu, '.oac-layouts__line').textContent).toMatch(/^Saved \S/);
    // Nothing unsaved: Save has nothing to do.
    expect(must(menu, '[data-action="save"]').getAttribute('aria-disabled')).toBe('true');
    widget.setChartType('line');
    await widget.layouts!.flush();
    await settle();
    expect(must(menu, '.oac-layouts__line').textContent).toBe('Unsaved changes');
    await press(widget, menu, '[data-action="save"]');
    expect((await repo!.load()).workspaces[0].panes[0].chartType).toBe('line');
    expect(must(menu, '.oac-layouts__line').textContent).toMatch(/^Saved \S/);
  });

  it('compares the chart as it opens, so Save is ready for a change made a moment before', async () => {
    const { widget, root } = await make();
    const menu = await openMenu(widget, root);
    await saveAs(widget, menu, 'Morning');
    must(menu, '.oac-dialog__head .oac-btn--icon').click();
    expect(q(root, '.oac-layouts')).toBeNull();
    // The controller's quiet period is still running: it has not judged the change.
    widget.setChartType('line');
    expect(widget.layouts!.state().dirty).toBe(false);
    must(root, '.oac-topbar__layouts').click();
    await settle();
    const again = must(root, '.oac-layouts');
    expect(must(again, '.oac-layouts__line').textContent).toBe('Unsaved changes');
    expect(must(again, '[data-action="save"]').getAttribute('aria-disabled')).toBe('false');
  });

  it('renames the held layout, and deletes it only after asking, leaving the chart as it is', async () => {
    const { widget, root, repo } = await make();
    const menu = await openMenu(widget, root);
    await saveAs(widget, menu, 'Morning');
    must(menu, '[data-action="rename"]').click();
    expect(must(menu, '.oac-layouts__input').value).toBe('Morning');
    must(menu, '.oac-layouts__input').value = 'Opening range';
    await press(widget, menu, '[data-action="submit-name"]');
    expect((await repo!.load()).workspaces.map(doc => doc.name)).toEqual(['Opening range']);
    expect(must(root, '.oac-topbar__layouts-name').textContent).toBe('Opening range');

    await press(widget, menu, '[data-action="delete"]');
    const confirm = must(menu, '.oac-layouts__confirm');
    expect(confirm.hidden).toBe(false);
    expect(must(confirm, '.oac-layouts__confirm-text').textContent).toBe('Delete Opening range? The chart stays as it is.');
    await press(widget, menu, '[data-action="keep"]');
    expect(confirm.hidden).toBe(true);
    expect((await repo!.load()).workspaces).toHaveLength(1);
    await press(widget, menu, '[data-action="delete"]');
    await press(widget, menu, '[data-action="confirm-delete"]');
    expect((await repo!.load()).workspaces).toHaveLength(0);
    expect(widget.layouts!.state().layoutId).toBeNull();
    expect([widget.symbol(), widget.interval()]).toEqual(['INFY', '5m']);
    expect(must(menu, '.oac-layouts__name').textContent).toBe('No layout open');
  });

  it('lists up to ten recent layouts, most recent first, and the others by name', async () => {
    const { widget, root, repo } = await make();
    // Twelve layouts saved elsewhere on the account, eleven of them opened there in turn.
    const made: string[] = [];
    for (let i = 0; i < 12; i++) made.push((await repo!.createWorkspace(`Desk ${String.fromCharCode(76 - i)}`, widgetLayoutTarget(widget).capture())).id);
    for (const id of made.slice(0, 11)) await repo!.openWorkspace(id);
    const menu = await openMenu(widget, root);
    const recent = rows(menu, 'recent');
    expect(recent).toHaveLength(10);
    expect(recent[0]).toBe('Desk B');
    expect(recent[9]).toBe('Desk K');
    // The one opened longest ago and the one never opened, in name order.
    expect(rows(menu, 'others')).toEqual(['Desk A', 'Desk L']);
    // Arrow keys walk the rows.
    const first = must(menu, '.oac-layouts__row');
    first.focus();
    fireKey(first, 'ArrowDown');
    expect((widget.context.document.activeElement as unknown as FakeElement).dataset.layoutId).toBe(made[9]);
    fireKey(widget.context.document.activeElement as unknown as FakeElement, 'ArrowUp');
    expect((widget.context.document.activeElement as unknown as FakeElement).dataset.layoutId).toBe(made[10]);
  });

  it('lists ten recent layouts from a host store that keeps more', async () => {
    const repo = account().repo();
    const ids: string[] = [];
    // A host's own store: the same catalog, with a longer recent list than the repository keeps.
    const store: WorkspaceStore = {
      load: async () => ({ ...(await repo.load()), recentWorkspaceIds: [...ids].reverse() }),
      subscribe: listener => repo.subscribe(listener),
      createWorkspace: (...args) => repo.createWorkspace(...args), saveWorkspace: (...args) => repo.saveWorkspace(...args),
      openWorkspace: (...args) => repo.openWorkspace(...args), createTemplate: (...args) => repo.createTemplate(...args),
      saveTemplate: (...args) => repo.saveTemplate(...args), rename: (...args) => repo.rename(...args),
      duplicate: (...args) => repo.duplicate(...args), remove: (...args) => repo.remove(...args), setAutosave: (...args) => repo.setAutosave(...args),
    };
    const { widget, root } = await make({ workspaces: store }, null);
    for (let i = 0; i < 12; i++) ids.push((await repo.createWorkspace(`Desk ${String.fromCharCode(65 + i)}`, widgetLayoutTarget(widget).capture())).id);
    const menu = await openMenu(widget, root);
    expect(rows(menu, 'recent')).toEqual(['L', 'K', 'J', 'I', 'H', 'G', 'F', 'E', 'D', 'C'].map(letter => `Desk ${letter}`));
    expect(rows(menu, 'others')).toEqual(['Desk A', 'Desk B']);
  });

  it('turns autosave on and off and says what it is doing', async () => {
    vi.useFakeTimers();
    const { widget, root, repo } = await make();
    const menu = await openMenu(widget, root);
    await saveAs(widget, menu, 'Morning');
    const toggle = must(menu, '[data-action="autosave"]');
    expect(toggle.getAttribute('role')).toBe('switch');
    expect(toggle.getAttribute('aria-checked')).toBe('false');
    expect(must(toggle, '.oac-layouts__switch-value').textContent).toBe('Off');
    await press(widget, menu, '[data-action="autosave"]');
    expect((await repo!.load()).autosave).toBe(true);
    expect(toggle.getAttribute('aria-checked')).toBe('true');
    expect(must(toggle, '.oac-layouts__switch-value').textContent).toBe('On');
    expect(must(menu, '.oac-layouts__autosave-state').textContent).toBe('Saved');
    widget.setInterval('15m');
    expect(must(menu, '.oac-layouts__autosave-state').textContent).toBe('Waiting to save');
    await vi.advanceTimersByTimeAsync(1000);
    await widget.layouts!.flush();
    await vi.advanceTimersByTimeAsync(0);
    expect((await repo!.load()).workspaces[0].panes[0].interval).toBe('15m');
    expect(must(menu, '.oac-layouts__autosave-state').textContent).toBe('Saved');
    await press(widget, menu, '[data-action="autosave"]');
    expect((await repo!.load()).autosave).toBe(false);
    expect(must(menu, '.oac-layouts__autosave-state').textContent).toBe('');
  });

  it('says so on the status line and in the menu when autosave cannot write', async () => {
    const storage = createMemoryWorkspaceStorage();
    let fail = false;
    const flaky: WorkspaceStorage = {
      read: key => storage.read(key),
      write: (key, catalog, expected, options) => fail ? Promise.reject(new Error('quota exceeded')) : storage.write(key, catalog, expected, options),
    };
    const { widget, root } = await make({}, account(flaky).repo());
    const menu = await openMenu(widget, root);
    await saveAs(widget, menu, 'Morning');
    await press(widget, menu, '[data-action="autosave"]');
    fail = true;
    widget.setInterval('15m');
    await widget.layouts!.flush();
    await settle();
    expect(widget.layouts!.state().autosave).toBe('failed');
    expect(must(menu, '.oac-layouts__autosave-state').textContent).toBe('Could not save');
    expect(must(menu, '.oac-layouts__error').textContent).toBe('Autosave could not save the layout: quota exceeded');
    expect(must(root, '.oac-topbar__layouts').dataset.attention).toBe('true');
    expect(must(root, '.oac-statusline__msg').textContent).toBe('Autosave stopped: the layout could not be saved');
  });

  it('compares the chart first, and asks before opening another layout over unsaved changes', async () => {
    const { widget, root, repo } = await make();
    const menu = await openMenu(widget, root);
    await saveAs(widget, menu, 'Evening');
    widget.setSymbol('TCS', 'NSE');
    await saveAs(widget, menu, 'Morning');
    const evening = (await repo!.load()).workspaces.find(doc => doc.name === 'Evening')!;
    // A change the controller has not judged yet: its quiet period is still running.
    widget.setInterval('15m');
    expect(widget.layouts!.state().dirty).toBe(false);
    const row = (): FakeElement => (menu.querySelectorAll('.oac-layouts__row') as unknown as FakeElement[]).find(item => item.dataset.layoutId === evening.id)!;
    row().click();
    await settle();
    const confirm = must(menu, '.oac-layouts__confirm');
    expect(confirm.hidden).toBe(false);
    expect(must(confirm, '.oac-layouts__confirm-text').textContent).toBe('Morning has unsaved changes. Save them before opening Evening?');
    await press(widget, menu, '[data-action="stay"]');
    expect(widget.symbol()).toBe('TCS');
    // Save and open keeps the change in Morning, then shows Evening.
    row().click();
    await settle();
    await press(widget, menu, '[data-action="save-and-open"]');
    await settle();
    expect(widget.symbol()).toBe('INFY');
    expect((await repo!.load()).workspaces.find(doc => doc.name === 'Morning')!.panes[0].interval).toBe('15m');
    expect(q(root, '.oac-layouts')).toBeNull();

    // Open without saving drops the change.
    const again = await openMenu(widget, root);
    widget.setInterval('1h');
    const morning = (await repo!.load()).workspaces.find(doc => doc.name === 'Morning')!;
    (again.querySelectorAll('.oac-layouts__row') as unknown as FakeElement[]).find(item => item.dataset.layoutId === morning.id)!.click();
    await settle();
    await press(widget, again, '[data-action="discard"]');
    await settle();
    expect([widget.symbol(), widget.interval()]).toEqual(['TCS', '15m']);
    expect((await repo!.load()).workspaces.find(doc => doc.name === 'Evening')!.panes[0].interval).toBe('5m');
  });

  it('gives the focus back to where a form or a question came from as it closes', async () => {
    const { widget, root } = await make();
    const menu = await openMenu(widget, root);
    const active = (): FakeElement => widget.context.document.activeElement as unknown as FakeElement;
    // A press focuses its button first, as a browser does.
    const tap = async (selector: string): Promise<void> => { must(menu, selector).focus(); await press(widget, menu, selector); };
    await tap('[data-action="save-as"]');
    expect(active()).toBe(must(menu, '.oac-layouts__input'));
    await tap('[data-action="cancel-name"]');
    expect(active()).toBe(must(menu, '[data-action="save-as"]'));
    await tap('[data-action="save-as"]');
    must(menu, '.oac-layouts__input').value = 'Evening';
    await tap('[data-action="submit-name"]');
    expect(active()).toBe(must(menu, '[data-action="save"]'));
    widget.setSymbol('TCS', 'NSE');
    await saveAs(widget, menu, 'Morning');
    const evening = widget.layouts!.state().catalog!.workspaces.find(doc => doc.name === 'Evening')!;
    widget.setInterval('15m');
    const row = (): FakeElement => (menu.querySelectorAll('.oac-layouts__row') as unknown as FakeElement[]).find(item => item.dataset.layoutId === evening.id)!;
    row().focus();
    row().click();
    await settle();
    expect(active().dataset.action).toBe('stay');
    await tap('[data-action="stay"]');
    // The rows were painted afresh meanwhile: the focus is on the one asked about.
    expect(active()).toBe(row());
    await tap('[data-action="delete"]');
    expect(active().dataset.action).toBe('keep');
    await tap('[data-action="keep"]');
    expect(active()).toBe(must(menu, '[data-action="delete"]'));
  });

  it('keeps the focus in the menu when a conflict is settled from its own buttons', async () => {
    const shared = account();
    const { widget, root } = await make({}, shared.repo());
    const elsewhere = shared.repo();
    const menu = await openMenu(widget, root);
    await saveAs(widget, menu, 'Morning');
    const id = widget.layouts!.state().layoutId!;
    const theirs = (await elsewhere.load()).workspaces[0];
    await elsewhere.saveWorkspace(id, { layout: theirs.layout, panes: [{ ...theirs.panes[0], interval: '1h' }], activePaneId: theirs.activePaneId, sync: theirs.sync });
    widget.setChartType('line');
    await widget.layouts!.flush();
    await press(widget, menu, '[data-action="save"]');
    expect(must(menu, '.oac-layouts__conflict').hidden).toBe(false);
    must(menu, '[data-action="overwrite"]').focus();
    await press(widget, menu, '[data-action="overwrite"]');
    expect(must(menu, '.oac-layouts__conflict').hidden).toBe(true);
    expect(widget.context.document.activeElement).toBe(must(menu, '[data-action="save"]'));
  });

  it('says why the list could not be read in words, even when the store rejects with a plain object', async () => {
    const repo = account().repo();
    repo.load = () => Promise.reject({ code: 1 });
    const { widget, root } = await make({}, repo);
    const menu = await openMenu(widget, root);
    expect(must(menu, '.oac-layouts__error').textContent).toBe('The saved layouts could not be read: unknown error');
  });

  it('says the list could not be read, and does not go on saying it is loading', async () => {
    const repo = account().repo();
    let fail = false;
    const load = repo.load.bind(repo);
    repo.load = () => fail ? Promise.reject(new Error('storage is locked')) : load();
    fail = true;
    const { widget, root } = await make({}, repo);
    const menu = await openMenu(widget, root);
    expect(widget.layouts!.state().catalog).toBeNull();
    expect(must(menu, '.oac-layouts__error').textContent).toBe('The saved layouts could not be read: storage is locked');
    expect(q(menu, '.oac-layouts__lists .oac-empty')).toBeNull();
    fail = false;
    await press(widget, menu, '[data-action="save"]');
    must(menu, '.oac-layouts__input').value = 'Morning';
    await press(widget, menu, '[data-action="submit-name"]');
    expect(rows(menu)).toEqual(['Morning']);
  });

  it('offers the three ways out when another window changed the held layout', async () => {
    const shared = account();
    const { widget, root } = await make({}, shared.repo());
    const elsewhere = shared.repo();
    const menu = await openMenu(widget, root);
    await saveAs(widget, menu, 'Morning');
    const id = widget.layouts!.state().layoutId!;
    // Another window saves Morning on 1h.
    const theirs = (await elsewhere.load()).workspaces[0];
    const payload: WorkspacePayload = { layout: theirs.layout, panes: [{ ...theirs.panes[0], interval: '1h' }], activePaneId: theirs.activePaneId, sync: theirs.sync };
    await elsewhere.saveWorkspace(id, payload);
    widget.setChartType('line');
    await widget.layouts!.flush();
    await press(widget, menu, '[data-action="save"]');
    const conflict = must(menu, '.oac-layouts__conflict');
    expect(conflict.hidden).toBe(false);
    expect(conflict.getAttribute('role')).toBe('alert');
    expect(must(conflict, '.oac-layouts__conflict-text').textContent).toBe('Morning was changed in another window. This chart is not saved over it.');
    expect(must(menu, '.oac-layouts__line').textContent).toBe('Changed in another window');
    expect(must(menu, '[data-action="save"]').getAttribute('aria-disabled')).toBe('true');
    // Reading the list again keeps the choice open: the layout is still not as this chart left it.
    await press(widget, menu, '[data-action="reload"]');
    expect(conflict.hidden).toBe(false);
    // A copy keeps both versions, and the copy is held from then on.
    must(menu, '[data-action="copy"]').click();
    expect(must(menu, '.oac-layouts__input').value).toBe('Morning copy');
    await press(widget, menu, '[data-action="submit-name"]');
    const after = await elsewhere.load();
    expect(after.workspaces.map(doc => [doc.name, doc.panes[0].interval, doc.panes[0].chartType])).toEqual([
      ['Morning', '1h', 'candlestick'], ['Morning copy', '5m', 'line'],
    ]);
    expect(conflict.hidden).toBe(true);
    expect(must(menu, '.oac-layouts__name').textContent).toBe('Morning copy');
  });

  it('overwrites the other window\'s version when the user chooses it', async () => {
    const shared = account();
    const { widget, root } = await make({}, shared.repo());
    const elsewhere = shared.repo();
    const menu = await openMenu(widget, root);
    await saveAs(widget, menu, 'Morning');
    const id = widget.layouts!.state().layoutId!;
    await elsewhere.rename('workspace', id, 'Morning');
    const theirs = (await elsewhere.load()).workspaces[0];
    await elsewhere.saveWorkspace(id, { layout: theirs.layout, panes: [{ ...theirs.panes[0], interval: '1h' }], activePaneId: theirs.activePaneId, sync: theirs.sync });
    widget.setChartType('line');
    await widget.layouts!.flush();
    await press(widget, menu, '[data-action="save"]');
    expect(must(menu, '.oac-layouts__conflict').hidden).toBe(false);
    await press(widget, menu, '[data-action="overwrite"]');
    expect((await elsewhere.load()).workspaces[0].panes[0]).toMatchObject({ interval: '5m', chartType: 'line' });
    expect(must(menu, '.oac-layouts__conflict').hidden).toBe(true);
    expect(must(menu, '.oac-layouts__line').textContent).toMatch(/^Saved \S/);
  });

  it('writes a change still in its quiet period when the page is hidden or goes away, and stops listening once destroyed', async () => {
    vi.useFakeTimers();
    // The fake document has no window, and the page going away is heard on the window.
    const doc = fakeWidgetDocument();
    const listeners = new Map<string, Set<() => void>>();
    (doc as unknown as { defaultView: unknown }).defaultView = {
      addEventListener: (type: string, fn: () => void) => { listeners.set(type, (listeners.get(type) ?? new Set()).add(fn)); },
      removeEventListener: (type: string, fn: () => void) => { listeners.get(type)?.delete(fn); },
    };
    const { widget, root, repo } = await make({}, account().repo(), doc);
    const menu = await openMenu(widget, root);
    await saveAs(widget, menu, 'Morning');
    await press(widget, menu, '[data-action="autosave"]');
    const stored = async (): Promise<string> => (await repo!.load()).workspaces[0].panes[0].interval;
    widget.setInterval('15m');
    await vi.advanceTimersByTimeAsync(0);
    // Inside the quiet period nothing is written yet; a tab switched away from may never come back.
    expect(await stored()).toBe('5m');
    (doc as unknown as { visibilityState: string }).visibilityState = 'hidden';
    fire(doc as unknown as FakeElement, 'visibilitychange');
    await vi.advanceTimersByTimeAsync(0);
    expect(await stored()).toBe('15m');
    (doc as unknown as { visibilityState: string }).visibilityState = 'visible';
    widget.setInterval('1h');
    for (const fn of [...(listeners.get('pagehide') ?? [])]) fn();
    await vi.advanceTimersByTimeAsync(0);
    expect(await stored()).toBe('1h');
    widget.destroy();
    expect(listeners.get('pagehide')?.size ?? 0).toBe(0);
  });

  it('reopens the layout that was active when the page last closed, and writes nothing to do it', async () => {
    const shared = account();
    const first = await make({}, shared.repo());
    const menu = await openMenu(first.widget, first.root);
    first.widget.setSymbol('TCS', 'NSE');
    first.widget.setInterval('15m');
    await saveAs(first.widget, menu, 'Morning');
    const revision = (await shared.repo().load()).revision;
    first.widget.destroy();
    const repo = shared.repo();
    const writes = vi.spyOn(repo, 'openWorkspace');
    const second = await make({}, repo);
    await second.widget.layouts!.flush();
    await settle();
    expect([second.widget.symbol(), second.widget.interval()]).toEqual(['TCS', '15m']);
    expect(second.widget.layouts!.state()).toMatchObject({ dirty: false });
    expect(must(second.root, '.oac-topbar__layouts-name').textContent).toBe('Morning');
    expect(writes).not.toHaveBeenCalled();
    expect((await repo.load()).revision).toBe(revision);
  });

  // Each is heard by itself, with no flush. The widget raises its own event for
  // most; an alert and an undo it does not, so the target listens to the chart's
  // alert events and to the undo timeline as well.
  const line = (w: Widget, at: number, lift = 0): { time: number; price: number } => {
    const bar = w.chart.primaryBars()[at];
    return { time: bar.time, price: bar.close + lift };
  };
  for (const [kind, change, prepare] of [
    ['a chart type', w => { w.setChartType('line'); }],
    ['a study added', w => { w.chart.addIndicator('sma'); }],
    ['a study removed', w => { w.chart.indicators()[0].remove(); }],
    ['study settings', w => { w.chart.indicators()[0].setSettings({ length: 21 }); }],
    ['a drawing', w => { w.draw.add({ tool: 'trend-line', paneIndex: 0, style: {}, points: [line(w, 40), line(w, 200)] }); }],
    ['the theme', w => { w.setTheme('light'); }],
    // The settings dialog's write, as one step on the timeline.
    ['a chart setting', w => { w.history.transact(() => applyChartSettings(w.chart, { 'symbol.upColor': '#1e8a5a' }), 'Settings'); }],
    // A host's own step whose undo sets a pane height: the chart tells no one the
    // widget listens to, and only the timeline hears the press.
    ['an undo', w => { expect(w.history.undo()).toBe(true); }, w => {
      w.history.push({ label: 'Pane height', undo: () => { w.chart.setPaneWeight(1, 3); }, redo: () => { w.chart.setPaneWeight(1, 1); } });
    }],
    // A host's own drawing is no step on the timeline: the widget's layout event carries it.
    ['a drawing the host adds outside the undo timeline', w => {
      w.history.ignore(() => { w.draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [line(w, 120)] }); });
    }],
    ['an alert set', w => { w.alerts.add({ source: { kind: 'price', price: line(w, 239, 40).price }, condition: 'crossingUp' }); }],
    // A spent alert is part of the layout: reopened as set, it would fire again.
    ['an alert that fires', w => {
      const last = w.chart.primaryBars()[239];
      w.series.update({ time: last.time + 300, open: last.close, high: last.close + 60, low: last.close - 1, close: last.close + 55, volume: 1200 });
      w.series.update({ time: last.time + 600, open: last.close + 55, high: last.close + 57, low: last.close + 53, close: last.close + 56, volume: 1100 });
      expect(w.alerts.list()[0].state).toBe('triggered');
    }, w => { w.alerts.add({ source: { kind: 'price', price: line(w, 239, 30).price }, condition: 'crossingUp' }); }],
  ] as Array<[string, (w: Widget) => void, ((w: Widget) => void)?]>) {
    it(`autosaves ${kind} once its quiet period ends`, async () => {
      vi.useFakeTimers();
      const { widget, repo } = await make();
      widget.chart.addIndicator('rsi');
      prepare?.(widget);
      await widget.layouts!.saveAs('Morning');
      await widget.layouts!.setAutosave(true);
      await vi.advanceTimersByTimeAsync(0);
      const stored = async (): Promise<string> => JSON.stringify((await repo!.load()).workspaces[0].panes[0]);
      const before = await stored();
      change(widget);
      await vi.advanceTimersByTimeAsync(999);
      expect(await stored()).toBe(before);
      await vi.advanceTimersByTimeAsync(1);
      await vi.advanceTimersByTimeAsync(0);
      expect(await stored()).not.toBe(before);
      expect(widget.layouts!.state()).toMatchObject({ dirty: false, autosave: 'saved' });
    });
  }

  it('leaves alert bookkeeping out of a layout: a bar closing under an alert marks nothing unsaved', async () => {
    const { widget } = await make();
    const last = widget.chart.primaryBars()[239];
    widget.alerts.add({ source: { kind: 'price', price: last.close + 40 }, condition: 'crossingUp' });
    await widget.layouts!.saveAs('Morning');
    await widget.layouts!.flush();
    // Two bars close far from the alert's price: it judged them, and nothing the user set moved.
    widget.series.update({ time: last.time + 300, open: last.close, high: last.close + 1, low: last.close - 1, close: last.close + 0.5, volume: 900 });
    widget.series.update({ time: last.time + 600, open: last.close + 0.5, high: last.close + 1, low: last.close - 1, close: last.close, volume: 950 });
    expect(widget.getState().chart.alerts?.alerts[0].lastClosedTime).toBe(last.time + 300);
    await widget.layouts!.flush();
    expect(widget.layouts!.state().dirty).toBe(false);
    const saved = widget.layouts!.state().catalog!.workspaces[0].panes[0].chart.alerts?.alerts[0] as unknown as Record<string, unknown>;
    expect(saved.state).toBe('armed');
    for (const key of ['lastClosedTime', 'lastTouchedTime', 'lastTriggeredAt', 'lastTriggeredTime']) expect(saved).not.toHaveProperty(key);
  });

  it('leaves a view out of a layout: panning marks nothing unsaved', async () => {
    const { widget, root } = await make();
    const menu = await openMenu(widget, root);
    await saveAs(widget, menu, 'Morning');
    widget.chart.setVisibleLogicalRange({ from: 40, to: 120 });
    widget.chart.emit('zoom', {});
    await widget.layouts!.flush();
    expect(widget.layouts!.state().dirty).toBe(false);
    expect(widget.layouts!.state().catalog!.workspaces[0].panes[0].chart.viewport).toBeUndefined();
  });

  it('holds autosave while a replay runs, and does not open a layout under it', async () => {
    vi.useFakeTimers();
    const { widget, root, repo } = await make();
    const menu = await openMenu(widget, root);
    await saveAs(widget, menu, 'Morning');
    await press(widget, menu, '[data-action="autosave"]');
    const replay = new ReplayController(widget.chart, { startIndex: 120 });
    await vi.advanceTimersByTimeAsync(0);
    expect(widget.layouts!.state().suspended).toBe(true);
    const row = must(menu, '.oac-layouts__row');
    expect(row.getAttribute('aria-disabled')).toBe('true');
    expect(row.title).toBe('Stop the replay to open a layout');
    const writes = vi.spyOn(repo!, 'saveWorkspace');
    widget.setChartType('line');
    await vi.advanceTimersByTimeAsync(3000);
    await widget.layouts!.flush();
    await vi.advanceTimersByTimeAsync(0);
    expect(writes).not.toHaveBeenCalled();
    expect(must(menu, '.oac-layouts__autosave-state').textContent).toBe('Autosave waits for the replay to end');
    replay.stop();
    await vi.advanceTimersByTimeAsync(1000);
    await widget.layouts!.flush();
    await vi.advanceTimersByTimeAsync(0);
    expect(writes).toHaveBeenCalledTimes(1);
    expect((await repo!.load()).workspaces[0].panes[0].chartType).toBe('line');
    // Rows are painted afresh on every change.
    expect(must(menu, '.oac-layouts__row').getAttribute('aria-disabled')).toBe('false');
  });
});

describe('the Layouts menu on a phone and in a chart grid', () => {
  it('opens from the More sheet on a phone layout, centred as a dialog', async () => {
    const { widget, root } = await make({ mobile: 'always' });
    must(root, '.oac-mobile__action[data-mobile-action="more"]').click();
    const row = must(root, '.oac-mobile-sheet [data-mobile-action="layouts"]');
    expect(row.textContent).toBe('Layouts');
    row.click();
    await widget.layouts!.flush();
    await settle();
    const menu = must(root, '.oac-layouts');
    expect(menu.classList.contains('oac-dialog')).toBe(true);
    expect(menu.getAttribute('aria-modal')).toBe('true');
    expect(q(root, '.oac-mobile-sheet')).toBeNull();
  });

  it('has no row in the More sheet without a store', async () => {
    const { root } = await make({ mobile: 'always' }, null);
    must(root, '.oac-mobile__action[data-mobile-action="more"]').click();
    expect(q(root, '.oac-mobile-sheet [data-mobile-action="layouts"]')).toBeNull();
  });

  function grid(options: Parameters<typeof createChartGrid>[1]): { grid: ChartGrid; doc: FakeDocument } {
    const doc = fakeWidgetDocument();
    const made = createChartGrid(fakeContainer(doc, 1200, 800) as unknown as HTMLElement, {
      document: doc as unknown as Document, pixelRatio: () => 1, rail: false, preset: '1x2',
      raf: { schedule: cb => { cb(); return 1; }, cancel: () => {} }, symbol: 'INFY', exchange: 'NSE', interval: '5m', ...options,
    });
    live.push(made);
    return { grid: made, doc };
  }

  it('gives each chart of a grid no layouts of its own, and every chart the controller the grid host passes', async () => {
    const repo = account().repo();
    const plain = grid({ workspaces: repo });
    for (const cell of plain.grid.cells()) {
      expect(cell.widget.layouts).toBeNull();
      expect(q(cell.widget.root as unknown as FakeElement, '.oac-topbar__layouts')).toBeNull();
    }
    let held: ChartGrid | null = null;
    const controller: LayoutsController = createLayoutsController(repo, {
      capture: () => held!.getWorkspace(), apply: payload => held!.applyWorkspace(payload),
    });
    live.push(controller);
    const handed = grid({ workspaces: repo, layouts: controller });
    held = handed.grid;
    for (const cell of handed.grid.cells()) {
      expect(cell.widget.layouts).toBe(controller);
      expect(q(cell.widget.root as unknown as FakeElement, '.oac-topbar__layouts')).not.toBeNull();
    }
    const root = handed.grid.cells()[1].widget.root as unknown as FakeElement;
    must(root, '.oac-topbar__layouts').click();
    await controller.flush();
    await settle();
    const menu = must(root, '.oac-layouts');
    await saveAs(handed.grid.cells()[1].widget, menu, 'Two charts');
    expect((await repo.load()).workspaces[0].panes).toHaveLength(2);
  });
});
