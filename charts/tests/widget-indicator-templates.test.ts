/**
 * Indicator templates in the widget's picker: offered only with a store that
 * can plan them, the studies on the chart saved with their panes, a template
 * applied in place of the studies or beside them, one undo step that takes
 * the apply back and one redo that puts it on again, drawings and alerts kept
 * across both, a template that cannot apply leaving the chart and its undo
 * timeline alone, a replay holding every apply back, and a delete that asks.
 */
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { ReplayController, registerIndicator, type Bar, type IndicatorPolicy } from '../src/index';
import '../src/indicators/index';
import {
  WorkspaceRepository, captureIndicatorTemplate, createMemoryWorkspaceStorage, planIndicatorTemplateState,
  type WorkspaceStore,
} from '../src/workspace/index';
import {
  applyIndicatorTemplate, createWidget, mountIndicatorPicker, saveIndicatorTemplate, type Widget, type WidgetOptions,
} from '../src/widget/index';
import { hostKept } from '../src/widget/layouts-templates';
import { hostOwnedStudy } from '../src/model/indicator-policy';
import { hostOwnedStudy as workspaceRule } from '../src/workspace/documents';
import { ensureWindowGlobal, fakeContainer, fakeWidgetDocument, type FakeElement } from './helpers/fake-dom-widget';

beforeAll(ensureWindowGlobal);
// A study whose saved settings the chart checks before a restore begins.
beforeAll(() => registerIndicator({
  id: 'template-session-probe', name: 'Session probe', placement: 'onchart',
  inputs: [{ key: 'session', type: 'session', label: 'Session', default: '0915-1530' }],
  plots: [{ key: 'line', title: 'Value', type: 'line' }],
  calc: rows => ({ line: rows.map(row => row.close) }),
}));

const bars: Bar[] = (() => {
  let s = 29;
  let close = 1486.4;
  return Array.from({ length: 240 }, (_, i) => {
    s = (s * 16807) % 2147483647;
    const open = close;
    close = Math.round((open + (s / 2147483647 - 0.5) * 6) * 20) / 20;
    return { time: 1_700_000_000 + i * 300, open, high: Math.max(open, close) + 0.6, low: Math.min(open, close) - 0.6, close, volume: 40_000 + (s % 9000) };
  });
})();

const settle = async (): Promise<void> => { for (let i = 0; i < 12; i++) await Promise.resolve(); await new Promise(r => setTimeout(r, 0)); };

const live: Widget[] = [];
afterEach(() => { for (const w of live.splice(0)) if (!w.isDestroyed) w.destroy(); });

function repository(): WorkspaceRepository {
  let n = 0;
  return new WorkspaceRepository(createMemoryWorkspaceStorage(), 'desk', { id: () => `template-${++n}`, now: () => 1000 + n });
}

async function make(options: WidgetOptions = {}) {
  const doc = fakeWidgetDocument();
  const widget = createWidget(fakeContainer(doc, 1100, 700) as unknown as HTMLElement, {
    document: doc as unknown as Document, pixelRatio: () => 1, mobile: 'never', panels: false,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    symbol: 'INFY', exchange: 'NSE', interval: '5m', ...options,
  });
  widget.chart.applySize(1000, 600);
  widget.series.setData(bars);
  live.push(widget);
  await settle();
  return { widget, root: widget.root as unknown as FakeElement };
}

const q = (root: FakeElement, selector: string): FakeElement | null => root.querySelector(selector) as FakeElement | null;
const must = (root: FakeElement, selector: string): FakeElement => {
  const found = q(root, selector);
  if (found === null) throw new Error(`nothing matches ${selector}`);
  return found;
};
const studies = (widget: Widget): string[] => widget.chart.indicators().map(study => study.indicatorId);

/** Open the picker and its templates list, and let the list load. */
async function openTemplates(widget: Widget, root: FakeElement): Promise<FakeElement> {
  expect(widget.openIndicatorPicker()).toBe(true);
  must(root, '.oac-pick [data-action="templates"]').click();
  await settle();
  return must(root, '.oac-templates');
}

const templateRow = (menu: FakeElement, name: string): FakeElement =>
  (menu.querySelectorAll('.oac-templates__row') as unknown as FakeElement[]).find(row => must(row, '.oac-templates__name').textContent === name)!;

describe('templates in the indicator picker', () => {
  it('are offered only with a store that can plan them', async () => {
    const bare = await make();
    bare.widget.openIndicatorPicker();
    expect(q(bare.root, '.oac-pick')).not.toBeNull();
    expect(q(bare.root, '.oac-pick [data-action="templates"]')).toBeNull();

    const repo = repository();
    const { widget, root } = await make({ workspaces: repo });
    widget.openIndicatorPicker();
    const open = must(root, '.oac-pick [data-action="templates"]');
    expect(open.getAttribute('aria-haspopup')).toBe('dialog');
    expect(open.closest('.oac-dialog__lead')).not.toBeNull();

    // A host store that implements the contract without the planner.
    const plain: WorkspaceStore = {
      load: () => repo.load(), subscribe: listener => repo.subscribe(listener),
      createWorkspace: (...args) => repo.createWorkspace(...args), saveWorkspace: (...args) => repo.saveWorkspace(...args),
      openWorkspace: (...args) => repo.openWorkspace(...args), createTemplate: (...args) => repo.createTemplate(...args),
      saveTemplate: (...args) => repo.saveTemplate(...args), rename: (...args) => repo.rename(...args),
      duplicate: (...args) => repo.duplicate(...args), remove: (...args) => repo.remove(...args), setAutosave: (...args) => repo.setAutosave(...args),
    };
    const hosted = await make({ workspaces: plain });
    hosted.widget.openIndicatorPicker();
    expect(q(hosted.root, '.oac-pick [data-action="templates"]')).toBeNull();
    // And an explicit null offers none even with a store.
    const quiet = await make({ workspaces: repo });
    mountIndicatorPicker(quiet.widget.context, undefined, { templates: null });
    expect(q(quiet.root, '.oac-pick [data-action="templates"]')).toBeNull();
  });

  it('saves the studies on the chart with their panes, and refuses to save none', async () => {
    const repo = repository();
    const { widget, root } = await make({ workspaces: repo });
    let menu = await openTemplates(widget, root);
    expect(must(menu, '.oac-empty').textContent).toBe('No saved templates yet');
    const save = must(menu, '[data-action="save-template"]');
    expect(save.getAttribute('aria-disabled')).toBe('true');
    expect(save.title).toBe('Add a study to save a template');
    widget.chart.addIndicator('rsi');
    widget.chart.addIndicator('sma');
    menu = must(root, '.oac-templates');
    expect(must(menu, '[data-action="save-template"]').getAttribute('aria-disabled')).toBe('false');
    must(menu, '[data-action="save-template"]').click();
    const prompt = must(root, '.oac-template-name');
    must(prompt, '.oac-template-name__input').value = 'Momentum';
    must(prompt, '[data-action="save-template"]').click();
    await settle();
    const [template] = (await repo.load()).templates;
    expect(template.name).toBe('Momentum');
    expect(template.indicators.map(study => study.indicatorId)).toEqual(['rsi', 'sma']);
    expect(template.layout?.panes).toHaveLength(2);
    expect(must(templateRow(menu, 'Momentum'), '.oac-templates__meta').textContent).toBe('2 studies');
  });

  it('saves none of the studies the host keeps, and no empty template', async () => {
    const repo = repository();
    const { widget, root } = await make({ workspaces: repo });
    // Kept by the host: listed, but the user may not remove it.
    widget.chart.addIndicator('rsi', {}, { policy: { removable: false } });
    const menu = await openTemplates(widget, root);
    const save = must(menu, '[data-action="save-template"]');
    expect(save.getAttribute('aria-disabled')).toBe('true');
    expect(save.title).toBe('Add a study to save a template');
    await expect(saveIndicatorTemplate(widget.context, repo, 'Host only')).rejects.toThrow('The chart has no studies of yours to save');
    expect((await repo.load()).templates).toHaveLength(0);
    widget.chart.addIndicator('sma');
    expect(must(menu, '[data-action="save-template"]').getAttribute('aria-disabled')).toBe('false');
    const saved = await saveIndicatorTemplate(widget.context, repo, 'Mine');
    expect(saved.indicators.map(study => study.indicatorId)).toEqual(['sma']);
    // A store that cannot capture gets the plain list, without the host's study either.
    const plain = { createTemplate: (name: string, input: unknown) => repo.createTemplate(name, input as never) } as unknown as WorkspaceStore;
    expect((await saveIndicatorTemplate(widget.context, plain, 'Plain')).indicators.map(study => study.indicatorId)).toEqual(['sma']);
  });

  it('puts a template in place of the studies in one undo step, and redoes it, keeping drawings and alerts', async () => {
    const repo = repository();
    const { widget, root } = await make({ workspaces: repo });
    widget.chart.addIndicator('rsi');
    widget.chart.addIndicator('macd');
    await saveIndicatorTemplate(widget.context, repo, 'Oscillators');
    for (const study of widget.chart.indicators().slice()) widget.chart.removeIndicator(study.id);
    expect(studies(widget)).toEqual([]);
    widget.chart.addIndicator('sma');
    widget.draw.add({ tool: 'trend-line', paneIndex: 0, style: { color: '#2a9df4' }, points: [{ time: bars[20].time, price: bars[20].low }, { time: bars[80].time, price: bars[80].high }] });
    widget.alerts.add({ source: { kind: 'price', price: bars[200].close + 40 } });
    await settle();
    const panesBefore = widget.chart.panes().length;
    const menu = await openTemplates(widget, root);
    must(templateRow(menu, 'Oscillators'), '[data-action="replace"]').click();
    await settle();
    expect(studies(widget)).toEqual(['rsi', 'macd']);
    expect(widget.chart.panes()).toHaveLength(3);
    expect(widget.draw.drawings()).toHaveLength(1);
    expect(widget.alerts.list()).toHaveLength(1);
    expect(q(root, '.oac-templates')).toBeNull();
    expect(widget.history.canUndo()).toBe(true);
    expect(widget.history.peekUndo()?.label).toBe('Apply Oscillators');

    expect(widget.history.undo()).toBe(true);
    expect(studies(widget)).toEqual(['sma']);
    expect(widget.chart.panes()).toHaveLength(panesBefore);
    expect(widget.draw.drawings()).toHaveLength(1);
    expect(widget.alerts.list()).toHaveLength(1);
    expect(widget.history.canRedo()).toBe(true);
    expect(widget.history.redo()).toBe(true);
    expect(studies(widget)).toEqual(['rsi', 'macd']);
    expect(widget.history.canUndo()).toBe(true);
  });

  it('appends a template beside the studies, in panes of its own', async () => {
    const repo = repository();
    const { widget, root } = await make({ workspaces: repo });
    widget.chart.addIndicator('rsi');
    await saveIndicatorTemplate(widget.context, repo, 'Strength');
    widget.chart.removeIndicator(widget.chart.indicators()[0].id);
    widget.chart.addIndicator('macd');
    const menu = await openTemplates(widget, root);
    must(templateRow(menu, 'Strength'), '[data-action="append"]').click();
    await settle();
    expect(studies(widget)).toEqual(['macd', 'rsi']);
    expect(widget.chart.panes()).toHaveLength(3);
    expect(widget.history.undo()).toBe(true);
    expect(studies(widget)).toEqual(['macd']);
  });

  it('keeps the price source over the study it was moved above when a template is appended', async () => {
    const repo = repository();
    const { widget } = await make({ workspaces: repo });
    widget.chart.addIndicator('rsi');
    const template = await saveIndicatorTemplate(widget.context, repo, 'Strength');
    widget.chart.removeIndicator(widget.chart.indicators()[0].id);
    const sma = widget.chart.addIndicator('sma');
    expect(widget.chart.moveInSeriesStack('source:primary', `indicator:${sma.id}`, 'above')).toBe(true);
    await settle();
    expect(applyIndicatorTemplate(widget.context, repo, { indicators: template.indicators, layout: template.layout }, 'append')).toBe(true);
    expect(studies(widget)).toEqual(['sma', 'rsi']);
    expect(widget.chart.getState().sourceAbove).toBe(sma.id);
    expect(widget.history.undo()).toBe(true);
    expect(widget.chart.getState().sourceAbove).toBe(sma.id);
    expect(widget.history.redo()).toBe(true);
    expect(widget.chart.getState().sourceAbove).toBe(sma.id);
  });

  it('takes a template back after later steps, keeping an alert set after it', async () => {
    const repo = repository();
    const { widget } = await make({ workspaces: repo });
    widget.chart.addIndicator('rsi');
    const template = await saveIndicatorTemplate(widget.context, repo, 'Strength');
    widget.chart.removeIndicator(widget.chart.indicators()[0].id);
    await settle();
    expect(applyIndicatorTemplate(widget.context, repo, { indicators: template.indicators, layout: template.layout }, 'replace', 'Strength')).toBe(true);
    widget.draw.add({ tool: 'trend-line', paneIndex: 0, style: { color: '#2a9df4' }, points: [{ time: bars[30].time, price: bars[30].low }, { time: bars[90].time, price: bars[90].high }] });
    widget.alerts.add({ source: { kind: 'price', price: bars[200].close - 30 } });
    await settle();
    // The drawing first, then the template: the alert is never a step.
    expect(widget.history.undo()).toBe(true);
    expect(widget.draw.drawings()).toHaveLength(0);
    expect(studies(widget)).toEqual(['rsi']);
    expect(widget.history.undo()).toBe(true);
    expect(studies(widget)).toEqual([]);
    expect(widget.alerts.list()).toHaveLength(1);
    expect(widget.history.canUndo()).toBe(false);
  });

  it('leaves the chart and its undo steps alone when a template cannot apply', async () => {
    const repo = repository();
    const { widget, root } = await make({ workspaces: repo });
    await repo.createTemplate('Lost', [{ indicatorId: 'no-such-study', settings: {}, paneIndex: 1 }]);
    widget.chart.addIndicator('sma');
    await settle();
    expect(widget.history.canUndo()).toBe(true);
    const menu = await openTemplates(widget, root);
    must(templateRow(menu, 'Lost'), '[data-action="replace"]').click();
    await settle();
    expect(studies(widget)).toEqual(['sma']);
    expect(widget.history.canUndo()).toBe(true);
    const message = must(menu, '.oac-templates__message');
    expect(message.getAttribute('role')).toBe('alert');
    expect(message.textContent).toMatch(/^Lost could not be applied: Missing indicators: no-such-study$/);
  });

  it('puts the chart back when a template fails part way through its restore', async () => {
    const repo = repository();
    const { widget } = await make({ workspaces: repo });
    const sma = widget.chart.addIndicator('sma');
    // The source moved over the study goes back over it, too.
    expect(widget.chart.moveInSeriesStack('source:primary', `indicator:${sma.id}`, 'above')).toBe(true);
    await settle();
    const before = widget.chart.getState();
    // A host store whose plan names a study this page cannot build: the restore
    // starts, builds the rest, and reports one study short.
    const store = {
      planIndicatorTemplateState: (...args: Parameters<NonNullable<WorkspaceStore['planIndicatorTemplateState']>>) => {
        const plan = repo.planIndicatorTemplateState(...args);
        return { ...plan, indicators: [...plan.indicators, { ...plan.indicators[plan.indicators.length - 1], indicatorId: 'gone-since', instanceId: 'gone-since-1' }] };
      },
    } as unknown as WorkspaceStore;
    let started = 0;
    const off = widget.chart.on('state:restore:start', () => { started++; });
    expect(() => applyIndicatorTemplate(widget.context, store, [{ indicatorId: 'rsi', settings: {}, paneIndex: 1 }], 'replace'))
      .toThrow('The chart did not restore every study');
    off();
    // The template's restore began, and a second put the chart back as it was.
    expect(started).toBe(2);
    expect(studies(widget)).toEqual(['sma']);
    expect(widget.chart.panes().length).toBe(before.panes!.length);
    expect(widget.chart.getState().indicators).toEqual(before.indicators);
    expect(widget.chart.getState().sourceAbove).toBe(sma.id);
  });

  it('leaves the undo steps alone when the chart refuses a planned template before restoring', async () => {
    const repo = repository();
    const { widget, root } = await make({ workspaces: repo });
    await repo.createTemplate('Broken', [{ indicatorId: 'template-session-probe', settings: { session: 'not a session' }, paneIndex: 0 }]);
    widget.chart.addIndicator('sma');
    await settle();
    const menu = await openTemplates(widget, root);
    must(templateRow(menu, 'Broken'), '[data-action="append"]').click();
    await settle();
    expect(studies(widget)).toEqual(['sma']);
    expect(widget.history.canUndo()).toBe(true);
    expect(must(menu, '.oac-templates__message').textContent).toMatch(/^Broken could not be applied: .*session/);
  });

  it('holds every apply back while a replay runs', async () => {
    const repo = repository();
    const { widget, root } = await make({ workspaces: repo });
    widget.chart.addIndicator('rsi');
    await saveIndicatorTemplate(widget.context, repo, 'Strength');
    const replay = new ReplayController(widget.chart, { startIndex: 120 });
    const menu = await openTemplates(widget, root);
    const replace = must(templateRow(menu, 'Strength'), '[data-action="replace"]');
    expect(replace.getAttribute('aria-disabled')).toBe('true');
    expect(replace.title).toBe('Stop the replay to apply a template');
    replace.click();
    await settle();
    expect(widget.history.canUndo()).toBe(true);
    expect(() => applyIndicatorTemplate(widget.context, repo, [], 'append')).toThrow(/replay/);
    replay.stop();
    await settle();
    expect(must(templateRow(must(root, '.oac-templates'), 'Strength'), '[data-action="replace"]').getAttribute('aria-disabled')).toBe('false');
  });

  it('deletes a template only after asking', async () => {
    const repo = repository();
    const { widget, root } = await make({ workspaces: repo });
    await repo.createTemplate('Old set', []);
    const menu = await openTemplates(widget, root);
    must(templateRow(menu, 'Old set'), '[data-action="delete"]').click();
    const row = templateRow(menu, 'Delete Old set?');
    expect(row.classList.contains('is-confirm')).toBe(true);
    must(row, '[data-action="keep"]').click();
    expect((await repo.load()).templates).toHaveLength(1);
    must(templateRow(menu, 'Old set'), '[data-action="delete"]').click();
    must(templateRow(menu, 'Delete Old set?'), '[data-action="confirm-delete"]').click();
    await settle();
    expect((await repo.load()).templates).toHaveLength(0);
    expect(must(menu, '.oac-templates__message').textContent).toBe('Deleted Old set');
  });

  it('keeps the focus in the list through a delete, by keyboard', async () => {
    const repo = repository();
    const { widget, root } = await make({ workspaces: repo });
    await repo.createTemplate('Only set', []);
    const menu = await openTemplates(widget, root);
    const active = (): FakeElement => widget.context.document.activeElement as unknown as FakeElement;
    const press = (el: FakeElement): void => { el.focus(); el.click(); };
    press(must(templateRow(menu, 'Only set'), '[data-action="delete"]'));
    expect(active().dataset.action).toBe('keep');
    // Keep: back to the delete button it came from.
    press(active());
    expect(active()).toBe(must(templateRow(menu, 'Only set'), '[data-action="delete"]'));
    press(active());
    press(must(templateRow(menu, 'Delete Only set?'), '[data-action="confirm-delete"]'));
    await settle();
    expect((await repo.load()).templates).toHaveLength(0);
    // The list is empty: the focus is on the one control left, not on the row that went.
    expect(active()).toBe(must(menu, '[data-action="save-template"]'));
  });
});

describe('the workspace store as the widget reaches it', () => {
  it('captures and plans a template exactly as the workspace tier functions do', async () => {
    const repo = repository();
    const { widget } = await make();
    widget.chart.addIndicator('rsi');
    widget.chart.addIndicator('sma');
    expect(repo.captureIndicatorTemplate(widget.chart)).toEqual(captureIndicatorTemplate(widget.chart));
    const input = captureIndicatorTemplate(widget.chart);
    const strip = (plan: ReturnType<typeof planIndicatorTemplateState>) => JSON.parse(JSON.stringify(plan).replace(/template-study-[0-9a-f]+-/g, 'id-'));
    expect(strip(repo.planIndicatorTemplateState(widget.chart, input, 'append'))).toEqual(strip(planIndicatorTemplateState(widget.chart, input, 'append')));
    const store: WorkspaceStore = repo;
    expect(typeof store.planIndicatorTemplateState).toBe('function');
  });
});

describe('the host-kept study rule', () => {
  // One rule, declared in the base: the widget and the workspace tier each take
  // that function by path, so they cannot disagree.
  it('is one function, declared in the base policy module, in the widget and the workspace tier', () => {
    expect(hostKept).toBe(hostOwnedStudy);
    expect(workspaceRule).toBe(hostOwnedStudy);
  });

  it('keeps a study the user may not remove or cannot see, and no other', () => {
    const flag = [true, false, undefined] as const;
    const policies: Array<IndicatorPolicy | undefined> = [undefined];
    for (const removable of flag) for (const configurable of flag) for (const movable of flag) for (const listed of flag) {
      policies.push({ ...(removable === undefined ? {} : { removable }), ...(configurable === undefined ? {} : { configurable }),
        ...(movable === undefined ? {} : { movable }), ...(listed === undefined ? {} : { listed }) });
    }
    expect(policies).toHaveLength(82);
    for (const policy of policies) {
      expect(hostOwnedStudy(policy), JSON.stringify(policy)).toBe(policy?.removable === false || policy?.listed === false);
    }
    expect(policies.filter(policy => hostOwnedStudy(policy))).toHaveLength(45);
  });
});
