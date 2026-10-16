import { afterEach, describe, expect, it } from 'vitest';
import type { ChartObjects, ChartObjectSnapshot } from 'openalgo-charts';
import { createOverlayStack, type WidgetContext } from '../src/widget/context';
import { mountObjectsPanel } from '../src/widget/objects-panel';
import {
  fakeContainer, fakeWidgetDocument, fire, fireKey, type FakeElement,
} from './helpers/fake-dom-widget';

const ALL = { select: true, visibility: true, lock: true, remove: true, settings: true, focus: true };
const source: ChartObjectSnapshot = {
  id: 'source:price', sourceId: 'price', kind: 'source', name: 'Primary price', paneIndex: 0,
  visible: true, selected: false,
  capabilities: { ...ALL, lock: false, remove: false },
};
const drawing: ChartObjectSnapshot = {
  id: 'drawing:line', sourceId: 'line', kind: 'drawing', name: 'Trend line', paneIndex: 0,
  visible: true, locked: false, selected: false, capabilities: ALL,
};
const indicator: ChartObjectSnapshot = {
  id: 'indicator:oi', sourceId: 'oi', kind: 'indicator', name: 'Open interest', paneIndex: 1,
  visible: false, selected: false, dataStatus: { state: 'loading' },
  capabilities: { ...ALL, lock: false },
};
const profile: ChartObjectSnapshot = {
  id: 'profile:session', sourceId: 'session', kind: 'profile', name: 'Session profile', paneIndex: 0,
  visible: true, selected: false,
  capabilities: { select: false, visibility: false, lock: false, remove: false, settings: false, focus: false },
};

// The model is being implemented independently. This double keeps its public
// state transition contract while the tests exercise the actual panel and stack.
class ObjectModel {
  public rows: readonly ChartObjectSnapshot[];
  /** Where the price pane sits; a host can move it below its studies. */
  public pricePane = 0;
  public panes = 2;
  public readonly listeners = new Set<(rows: readonly ChartObjectSnapshot[]) => void>();
  public readonly calls: unknown[][] = [];
  public fail: 'false' | 'throw' | null = null;

  public constructor(rows: readonly ChartObjectSnapshot[]) { this.rows = rows; }
  public list(): readonly ChartObjectSnapshot[] { return this.rows; }
  public get(id: string): ChartObjectSnapshot | undefined { return this.rows.find(row => row.id === id); }
  public publish(rows: readonly ChartObjectSnapshot[]): void {
    this.rows = rows;
    for (const listener of this.listeners) listener(rows);
  }
  public subscribe(listener: (rows: readonly ChartObjectSnapshot[]) => void): () => void {
    this.listeners.add(listener);
    listener(this.rows);
    return () => { this.listeners.delete(listener); };
  }
  public patch(id: string, patch: Partial<ChartObjectSnapshot>): void {
    this.publish(this.rows.map(row => row.id === id ? { ...row, ...patch } : row));
  }
  private accept(action: string, id: string | null, value?: boolean): boolean {
    this.calls.push([action, id, value]);
    if (this.fail === 'throw') throw new Error('Provider unavailable');
    return this.fail !== 'false';
  }
  public select(id: string | null, additive = false): boolean {
    if (!this.accept('select', id, additive)) return false;
    this.publish(this.rows.map(row => ({ ...row, selected: row.id === id || (additive && row.selected) })));
    return true;
  }
  public setVisible(id: string, on: boolean): boolean {
    if (!this.accept('visibility', id, on)) return false;
    this.patch(id, { visible: on });
    return true;
  }
  public setLocked(id: string, on: boolean): boolean {
    if (!this.accept('lock', id, on)) return false;
    this.patch(id, { locked: on });
    return true;
  }
  public remove(id: string): boolean {
    if (!this.accept('remove', id)) return false;
    this.publish(this.rows.filter(row => row.id !== id));
    return true;
  }
  public openSettings(id: string): boolean { return this.accept('settings', id); }
  public primaryPaneIndex(): number { return this.pricePane; }
  public paneCount(): number { return this.panes; }
  public move(id: string, paneIndex: number): boolean {
    if (!this.accept('move', id, undefined)) return false;
    this.patch(id, { paneIndex });
    return true;
  }
  public focus(id: string): boolean { return this.accept('focus', id); }
  // The stack members every inventory has: this one keeps no paint order, so
  // rows keep their list order and nothing is placed, grouped or refused a move.
  public stack(): readonly ChartObjectSnapshot[] { return []; }
  public canPlace(): boolean { return false; }
  public canGroup(): boolean { return false; }
  public canReorder(): boolean { return true; }
  public destroy(): void { this.calls.push(['destroy']); }
}

const rigs: { stack: ReturnType<typeof createOverlayStack> }[] = [];
function rig(rows: readonly ChartObjectSnapshot[] = [source, drawing, indicator, profile]) {
  const doc = fakeWidgetDocument();
  const root = fakeContainer(doc);
  const opener = doc.createElement('button');
  opener.textContent = 'Objects';
  root.appendChild(opener);
  opener.focus();
  const stack = createOverlayStack(root as unknown as HTMLElement, doc as unknown as Document);
  const model = new ObjectModel(rows);
  const toasts: string[] = [];
  const ctx = {
    document: doc,
    root,
    objects: model,
    openOverlay: stack.open,
    toast: (message: string, kind: string) => { toasts.push(`${kind}:${message}`); },
  } as unknown as WidgetContext;
  const value = { doc, root, opener, stack, model, ctx, toasts };
  rigs.push(value);
  return value;
}
const node = (element: HTMLElement): FakeElement => element as unknown as FakeElement;
function find(root: HTMLElement, selector: string): FakeElement {
  const match = node(root).querySelector(selector);
  expect(match, selector).not.toBeNull();
  return match!;
}
function row(root: HTMLElement, id: string): FakeElement {
  return find(root, `[data-object-id="${id}"]`);
}
function control(root: FakeElement, label: string): FakeElement {
  const match = root.querySelectorAll('button').find(button => button.getAttribute('aria-label') === label);
  expect(match, label).toBeDefined();
  return match!;
}
function names(root: HTMLElement): string[] {
  return node(root).querySelectorAll('.oac-objects__name').map(name => name.textContent);
}

afterEach(() => { for (const value of rigs.splice(0)) value.stack.destroy(); });

describe('mountObjectsPanel', () => {
  it('shows object state and exposes only supported actions, protecting the primary source', () => {
    const r = rig();
    const panel = mountObjectsPanel(r.ctx);
    expect(names(panel.el)).toEqual(['Primary price', 'Trend line', 'Session profile', 'Open interest']);
    expect(row(panel.el, indicator.id).textContent).toContain('Pane 2');
    expect(row(panel.el, indicator.id).textContent).toContain('Hidden');
    expect(row(panel.el, indicator.id).textContent).toContain('Loading');
    expect(row(panel.el, source.id).querySelector('[data-action="remove"]')).toBeNull();
    expect(row(panel.el, indicator.id).querySelector('[data-action="lock"]')).toBeNull();
    expect(row(panel.el, profile.id).querySelectorAll('button')).toHaveLength(0);
    expect(node(panel.el).querySelectorAll('.oac-glyph')).toHaveLength(0);
    expect(find(panel.el, 'input[type="search"]').getAttribute('aria-label')).toBe('Search objects');
  });

  it('names the price pane wherever it sits, in the pane headings and the move targets', () => {
    const movable = { ...drawing, capabilities: { ...ALL, move: true } };
    const r = rig([source, movable, indicator]);
    const panel = mountObjectsPanel(r.ctx);
    const headings = (): string[] => node(panel.el).querySelectorAll('.oac-objects__pane-title').map(title => title.textContent);
    const targets = (): string[] => row(panel.el, movable.id).querySelector('select')!.querySelectorAll('option').map(option => option.textContent);
    expect(headings()).toEqual(['Price pane', 'Pane 2']);
    expect(targets()).toEqual(['Price pane', 'Pane 2', 'New pane']);
    // The price pane moved below the study pane: the names follow it, not the slot.
    r.model.pricePane = 1;
    r.model.panes = 2;
    r.model.publish([{ ...source, paneIndex: 1 }, { ...movable, paneIndex: 1 }, { ...indicator, paneIndex: 0 }]);
    expect(headings()).toEqual(['Pane 1', 'Price pane']);
    expect(targets()).toEqual(['Pane 1', 'Price pane', 'New pane']);
    const search = find(panel.el, 'input');
    search.value = 'price pane';
    fire(search, 'input');
    expect(names(panel.el)).toEqual(['Primary price', 'Trend line']);
  });

  it('filters by name, kind and pane and explains an empty result', () => {
    const r = rig();
    const panel = mountObjectsPanel(r.ctx);
    const search = find(panel.el, 'input');
    for (const [query, expected] of [
      ['TREND', ['Trend line']], ['indicator', ['Open interest']],
      ['pane 2', ['Open interest']], ['session profile', ['Session profile']],
      ['absent', []], ['  ', ['Primary price', 'Trend line', 'Session profile', 'Open interest']],
    ] as const) {
      search.value = query;
      fire(search, 'input');
      expect(names(panel.el)).toEqual(expected);
      if (query === 'absent') expect(find(panel.el, '.oac-empty').textContent).toContain('match');
    }
    r.model.publish([]);
    expect(find(panel.el, '.oac-empty').textContent).toContain('No objects');
  });

  it('describes selectable rows with their pane, visibility and external-data state', () => {
    const r = rig([indicator]);
    const panel = mountObjectsPanel(r.ctx);
    const select = find(panel.el, '[data-action="select"]');
    const describedBy = select.getAttribute('aria-describedby');
    expect(describedBy).not.toBeNull();
    const description = describedBy!.split(' ').map(id => r.doc.getElementById(id)?.textContent).join(' ');
    expect(description).toContain('Pane 2');
    expect(description).toContain('Hidden');
    expect(description).toContain('Loading');
  });

  it('reads canvas selection and updated state without replacing focused controls', () => {
    const r = rig();
    const panel = mountObjectsPanel(r.ctx);
    const search = find(panel.el, 'input');
    search.value = 'trend';
    fire(search, 'input');
    expect(r.doc.activeElement).toBe(search);
    r.model.patch(drawing.id, { selected: true, locked: true });
    expect(find(panel.el, 'input')).toBe(search);
    expect(search.value).toBe('trend');
    expect(r.doc.activeElement).toBe(search);
    const select = find(panel.el, '[data-action="select"]');
    expect(select.getAttribute('aria-pressed')).toBe('true');
    const visibility = control(row(panel.el, drawing.id), 'Hide Trend line');
    visibility.focus();
    r.model.patch(drawing.id, { visible: false });
    expect(control(row(panel.el, drawing.id), 'Show Trend line')).toBe(visibility);
    expect(r.doc.activeElement).toBe(visibility);
    r.model.publish([]);
    expect(r.doc.activeElement).toBe(search);
  });

  it('selects from the row and forwards additive selection to the model', () => {
    const r = rig();
    const panel = mountObjectsPanel(r.ctx);
    const selected = find(panel.el, '[data-object-id="drawing:line"] [data-action="select"]');
    selected.click();
    expect(selected.getAttribute('aria-pressed')).toBe('true');
    expect(r.model.calls[0]).toEqual(['select', drawing.id, false]);
    fire(find(panel.el, '[data-object-id="indicator:oi"] [data-action="select"]'), 'click', { ctrlKey: true });
    expect(r.model.calls[1]).toEqual(['select', indicator.id, true]);
    expect(selected.getAttribute('aria-pressed')).toBe('true');
  });

  it('updates visibility and lock labels and sends settings, focus and removal to the exact object', () => {
    const r = rig();
    const panel = mountObjectsPanel(r.ctx);
    const line = row(panel.el, drawing.id);
    control(line, 'Hide Trend line').click();
    control(line, 'Show Trend line').click();
    control(line, 'Lock Trend line').click();
    control(line, 'Unlock Trend line').click();
    control(line, 'Settings for Trend line').click();
    control(line, 'Focus Trend line').click();
    control(line, 'Delete Trend line').click();
    expect(r.model.calls).toEqual([
      ['visibility', drawing.id, false], ['visibility', drawing.id, true],
      ['lock', drawing.id, true], ['lock', drawing.id, false],
      ['settings', drawing.id, undefined], ['focus', drawing.id, undefined], ['remove', drawing.id, undefined],
    ]);
    expect(names(panel.el)).toEqual(['Primary price', 'Session profile', 'Open interest']);
  });

  it.each(['false', 'throw'] as const)('reports a refused action (%s) without optimistic changes', failure => {
    const r = rig();
    const panel = mountObjectsPanel(r.ctx);
    r.model.fail = failure;
    const line = row(panel.el, drawing.id);
    control(line, 'Hide Trend line').click();
    expect(control(line, 'Hide Trend line')).toBeDefined();
    expect(r.toasts).toHaveLength(1);
    expect(r.toasts[0]).toMatch(/^error:.*Trend line/);
  });

  it('refreshes external-data state and removes capabilities that are no longer available', () => {
    const r = rig([indicator]);
    const panel = mountObjectsPanel(r.ctx);
    r.model.patch(indicator.id, { dataStatus: { state: 'error', error: new Error('offline') } });
    expect(row(panel.el, indicator.id).textContent).toContain('Could not load');
    r.model.patch(indicator.id, { dataStatus: { state: 'ready' }, capabilities: profile.capabilities });
    expect(row(panel.el, indicator.id).textContent).toContain('Ready');
    expect(row(panel.el, indicator.id).querySelectorAll('button')).toHaveLength(0);
  });

  it.each(['close', 'escape', 'outside'] as const)('disposes its subscription on %s and cannot act after dismissal', dismissal => {
    const r = rig();
    let closes = 0;
    const panel = mountObjectsPanel(r.ctx, r.opener as unknown as HTMLElement, { onClose: () => { closes++; } });
    const hide = control(row(panel.el, drawing.id), 'Hide Trend line');
    const lateUpdate = [...r.model.listeners][0];
    if (dismissal === 'close') panel.close();
    else if (dismissal === 'escape') fireKey(r.doc.activeElement, 'Escape');
    else fire(r.root, 'pointerdown');
    panel.close();
    expect(panel.isOpen()).toBe(false);
    expect(closes).toBe(1);
    expect(r.model.listeners.size).toBe(0);
    expect(r.doc.activeElement).toBe(r.opener);
    hide.click();
    lateUpdate([]);
    expect(r.model.calls).toEqual([]);
  });

  it('uses an explicit model in a custom context and isolates it from the widget inventory', () => {
    const r = rig();
    const own = new ObjectModel([{ ...profile, name: '<script>Profile</script>' }]);
    const panel = mountObjectsPanel(r.ctx, undefined, { objects: own as unknown as ChartObjects });
    expect(names(panel.el)).toEqual(['<script>Profile</script>']);
    expect(node(panel.el).querySelector('script')).toBeNull();
    expect(r.model.listeners.size).toBe(0);
    panel.close();
    expect(own.listeners.size).toBe(0);
  });
});
