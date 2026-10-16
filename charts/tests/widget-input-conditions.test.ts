/**
 * Conditional study inputs and inline rows in the widget's generated forms.
 *
 * A descriptor says when an input can be edited (`activeWhen`) and when it is
 * shown at all (`visibleWhen`), and which neighbours share a row (`inline`).
 * The form reads those against the values it holds after every edit and every
 * sync, keeps a hidden input's draft for when it returns, and never lets a
 * hidden or inactive control block a save it cannot show.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart, darkTheme, registerIndicator, type ChartSettingsInput, type IndicatorInput } from 'openalgo-charts';
import { DrawingController } from 'openalgo-charts/draw';
import { inputConditionMet, inputStates } from 'openalgo-charts/widget';
import { controlsFromInputs, renderForm, type FormOptions } from '../src/widget/form';
import { mountIndicatorSettings } from '../src/widget/dialogs/indicator-settings';
import { createOverlayStack, WidgetBus, WidgetStorage, type WidgetContext } from '../src/widget/context';
import { installDom, asDoc, asEl, type FakeElement } from './widget-form.test';

const MODES = [{ label: 'Simple', value: 'simple' }, { label: 'Bands', value: 'bands' }];
const SMOOTHING = [{ label: 'None', value: 'none' }, { label: 'Moving average', value: 'sma' }];

/** A study's inputs with every rule in play: a shown-when row, an active-when row, a cascade and one inline row. */
const inputs: IndicatorInput[] = [
  { key: 'length', type: 'number', label: 'Length', default: 14, min: 1, max: 500, inline: 'len' },
  { key: 'source', type: 'source', label: 'Source', default: 'close', inline: 'len' },
  { key: 'mode', type: 'select', label: 'Mode', default: 'simple', options: MODES },
  { key: 'width', type: 'number', label: 'Band width', default: 2, min: 0.5, max: 5, step: 0.5,
    visibleWhen: { key: 'mode', is: 'bands' } },
  { key: 'bandColor', type: 'color', label: 'Band colour', default: '#2962ff',
    visibleWhen: { key: 'mode', is: 'bands' }, activeWhen: { key: 'width', isNot: 0.5 } },
  { key: 'smoothing', type: 'select', label: 'Smoothing', default: 'none', options: SMOOTHING, group: 'Smoothing' },
  { key: 'smoothLength', type: 'number', label: 'Smoothing length', default: 5, min: 1, max: 50,
    group: 'Smoothing', activeWhen: { key: 'smoothing', isNot: 'none' } },
  { key: 'showSignal', type: 'boolean', label: 'Signal', default: false, group: 'Signal', inline: 'signal' },
  { key: 'signalLength', type: 'number', label: 'Length', default: 9, min: 1, max: 50, group: 'Signal', inline: 'signal',
    activeWhen: { key: 'showSignal', is: true } },
  { key: 'signalColor', type: 'color', label: 'Colour', default: '#f59e0b', group: 'Signal', inline: 'signal',
    activeWhen: { key: 'showSignal', is: true } },
  { key: 'level', type: 'price', label: 'Anchor price', default: 10, min: 0, max: 100, group: 'Anchor',
    visibleWhen: { key: 'mode', is: 'bands' } },
];
const defaults = Object.fromEntries(inputs.map(input => [input.key, input.default]));

/** False when `node` or any ancestor up to `host` is hidden: out of view and out of the tab order. */
function shown(node: FakeElement, host: FakeElement): boolean {
  for (let n: FakeElement | null = node; n !== null && n !== host; n = n.parentElement) if (n.hidden) return false;
  return true;
}

function form(extra: Partial<FormOptions> = {}, list: readonly ChartSettingsInput[] = inputs, values: Record<string, unknown> = defaults) {
  const dom = installDom(), doc = asDoc(dom.doc);
  const host = dom.doc.createElement('div');
  dom.root.appendChild(host);
  const changes: Array<[string, unknown]> = [];
  const handle = renderForm(asEl(host), controlsFromInputs(list), {
    values, idPrefix: 't', onChange: (key, value) => changes.push([key, value]), ...extra,
  });
  const field = (key: string): FakeElement => {
    const found = host.querySelector(`#t-${key}`);
    expect(found, `field ${key}`).not.toBeNull();
    return found!;
  };
  const visible = (key: string): boolean => shown(field(key), host);
  const choose = (key: string, value: string): void => { field(key).value = value; field(key).fire('change'); };
  const live = (): FakeElement => host.querySelector('[role="status"][aria-live="polite"]')!;
  return { dom, doc, host, handle, changes, field, visible, choose, live };
}

describe('inputConditionMet', () => {
  const values = { mode: 'bands', on: true, n: 5, zero: 0, own: 'x' };

  it('compares strictly with one value or a list, and negates with isNot', () => {
    expect(inputConditionMet({ key: 'mode', is: 'bands' }, values)).toBe(true);
    expect(inputConditionMet({ key: 'mode', is: ['simple', 'bands'] }, values)).toBe(true);
    expect(inputConditionMet({ key: 'mode', is: 'simple' }, values)).toBe(false);
    expect(inputConditionMet({ key: 'mode', isNot: 'simple' }, values)).toBe(true);
    expect(inputConditionMet({ key: 'mode', isNot: ['simple', 'bands'] }, values)).toBe(false);
    expect(inputConditionMet({ key: 'on', is: true }, values)).toBe(true);
    // A number is not its text, and a missing key is not false.
    expect(inputConditionMet({ key: 'n', is: '5' }, values)).toBe(false);
    expect(inputConditionMet({ key: 'missing', is: false }, values)).toBe(false);
    expect(inputConditionMet({ key: 'missing', isNot: false }, values)).toBe(true);
  });

  it('combines with all and any, where all of nothing holds and any of nothing does not', () => {
    expect(inputConditionMet({ all: [{ key: 'mode', is: 'bands' }, { key: 'on', is: true }] }, values)).toBe(true);
    expect(inputConditionMet({ all: [{ key: 'mode', is: 'bands' }, { key: 'on', is: false }] }, values)).toBe(false);
    expect(inputConditionMet({ any: [{ key: 'mode', is: 'simple' }, { key: 'n', is: 5 }] }, values)).toBe(true);
    expect(inputConditionMet({ all: [] }, values)).toBe(true);
    expect(inputConditionMet({ any: [] }, values)).toBe(false);
    expect(inputConditionMet(undefined, values)).toBe(true);
  });

  it('reads only own settings, so an inherited name never satisfies a condition', () => {
    expect(inputConditionMet({ key: 'toString', isNot: 'x' }, values)).toBe(true);
    expect(inputConditionMet({ key: 'constructor', is: 'x' }, {})).toBe(false);
  });

  it('treats a shape it cannot read as met, so a malformed descriptor never locks an input away', () => {
    expect(inputConditionMet({ key: 'mode' } as never, values)).toBe(true);
    expect(inputConditionMet(null as never, values)).toBe(true);
  });
});

describe('inputStates', () => {
  it('cascades: a hidden controller hides what it shows, and a hidden or inactive one deactivates what it enables', () => {
    const states = inputStates([
      { key: 'mode' },
      { key: 'width', visibleWhen: { key: 'mode', is: 'bands' } },
      { key: 'fill', visibleWhen: { key: 'width', isNot: 0 } },
      { key: 'color', activeWhen: { key: 'width', isNot: 0 } },
      { key: 'shade', activeWhen: { key: 'color', isNot: '' } },
    ], { mode: 'simple', width: 2, color: '#fff' });
    expect(states.get('width')).toMatchObject({ visible: false, active: true });
    // Its own test passes (2 is not 0), but the input it reads is hidden.
    expect(states.get('fill')).toMatchObject({ visible: false });
    expect(states.get('color')).toMatchObject({ visible: true, active: false, dependsOn: ['width'] });
    expect(states.get('shade')).toMatchObject({ visible: true, active: false, dependsOn: ['color'] });
  });

  it('decides by value alone for a key outside the list and for a cycle', () => {
    const states = inputStates([
      { key: 'a', visibleWhen: { key: 'b', is: 1 } },
      { key: 'b', visibleWhen: { key: 'a', is: 1 } },
      { key: 'c', activeWhen: { key: 'elsewhere', is: true } },
    ], { a: 1, b: 1, elsewhere: true });
    expect(states.get('a')!.visible).toBe(true);
    expect(states.get('b')!.visible).toBe(true);
    expect(states.get('c')!.active).toBe(true);
  });

  it('cascades through the switch and swatches of a colour pair, which belong to the pair', () => {
    const values = { on: false, pe: true, pu: '#00ff00' };
    const rules = [
      { key: 'w', visibleWhen: { key: 'pe', is: true } },
      { key: 'shade', activeWhen: { key: 'pu', isNot: '' } },
    ];
    // A chart settings pair carries its keys on the input itself.
    const flat = inputStates([{ key: 'on' }, { key: 'p', visibleWhen: { key: 'on', is: true },
      enabled: { key: 'pe' }, up: { key: 'pu' }, down: { key: 'pd' } }, ...rules], values);
    expect(flat.get('p')!.visible).toBe(false);
    expect(flat.get('w')!.visible).toBe(false);
    expect(flat.get('shade')).toMatchObject({ visible: true, active: false, dependsOn: ['pu'] });
    // The widget's own controls carry the same keys under `pair`.
    const nested = inputStates([{ key: 'on' }, { key: 'p', visibleWhen: { key: 'on', is: true },
      pair: { enabled: { key: 'pe' }, up: { key: 'pu' }, down: { key: 'pd' } } }, ...rules], values);
    expect(nested.get('w')!.visible).toBe(false);
    expect(nested.get('shade')!.active).toBe(false);
    // Once the pair is shown, its switch decides by value again.
    expect(inputStates([{ key: 'on' }, { key: 'p', visibleWhen: { key: 'on', is: true },
      enabled: { key: 'pe' }, up: { key: 'pu' }, down: { key: 'pd' } }, ...rules], { ...values, on: true }).get('w')!.visible).toBe(true);
  });
});

describe('controlsFromInputs', () => {
  it('threads the conditions and the inline id onto every control, a colour pair included', () => {
    const pair: ChartSettingsInput = { key: 'p', type: 'colorPair', label: 'P', visibleWhen: { key: 'mode', is: 'bands' },
      up: { key: 'p.up', label: 'Up', default: '#0f0' }, down: { key: 'p.down', label: 'Down', default: '#f00' } };
    const controls = controlsFromInputs([...inputs, pair], { translate: () => null, scope: 'indicator.test' });
    const byKey = new Map(controls.map(control => [control.key, control]));
    expect(byKey.get('length')!.inline).toBe('len');
    expect(byKey.get('width')!.visibleWhen).toEqual({ key: 'mode', is: 'bands' });
    expect(byKey.get('bandColor')!.activeWhen).toEqual({ key: 'width', isNot: 0.5 });
    expect(byKey.get('p')!.visibleWhen).toEqual({ key: 'mode', is: 'bands' });
  });

  it('takes no inline id on a colour pair, which is always a row of its own', () => {
    const pair: ChartSettingsInput = {
      key: 'p', type: 'colorPair', label: 'P',
      // @ts-expect-error a colour pair already holds a switch and two swatches on one row
      inline: 'x',
      up: { key: 'p.up', label: 'Up', default: '#0f0' }, down: { key: 'p.down', label: 'Down', default: '#f00' },
    };
    expect(controlsFromInputs([pair])[0].inline).toBeUndefined();
    const list: ChartSettingsInput[] = [
      { key: 'a', type: 'number', label: 'A', default: 1, inline: 'x' },
      pair,
      { key: 'b', type: 'number', label: 'B', default: 1, inline: 'x' },
    ];
    const h = form({}, list, { a: 1, 'p.up': '#0f0', 'p.down': '#f00', b: 1 });
    expect(h.host.querySelectorAll('.oac-row').map(row => [row.dataset.key, row.dataset.inline])).toEqual([['a', 'x'], ['p', undefined], ['b', 'x']]);
  });
});

describe('renderForm with conditions', () => {
  it('hides a row until its condition holds, re-reading after every edit', () => {
    const h = form();
    expect(h.visible('width')).toBe(false);
    expect(h.visible('bandColor-trigger')).toBe(false);
    expect(h.visible('level')).toBe(false);
    // The Anchor head has nothing left under it, so it goes too.
    const head = h.host.querySelectorAll('.oac-head').find(node => node.textContent === 'Anchor')!;
    expect(head.hidden).toBe(true);
    h.choose('mode', 'bands');
    expect(h.changes).toEqual([['mode', 'bands']]);
    expect(h.visible('width')).toBe(true);
    expect(h.visible('bandColor-trigger')).toBe(true);
    expect(head.hidden).toBe(false);
    h.choose('mode', 'simple');
    expect(h.visible('width')).toBe(false);
    expect(head.hidden).toBe(true);
  });

  it('keeps a hidden draft and reports it, without writing anything for the hidden input', () => {
    const h = form();
    h.choose('mode', 'bands');
    h.field('width').value = '3.5'; h.field('width').fire('change');
    h.choose('mode', 'simple');
    expect(h.visible('width')).toBe(false);
    expect(h.field('width').value).toBe('3.5');
    expect(h.handle.values().width).toBe(3.5);
    h.choose('mode', 'bands');
    expect(h.field('width').value).toBe('3.5');
    expect(h.changes).toEqual([['mode', 'bands'], ['width', 3.5], ['mode', 'simple'], ['mode', 'bands']]);
  });

  it('disables an inactive control with a reason naming what it depends on, and enables it again', () => {
    const h = form();
    const length = h.field('smoothLength'), row = h.host.querySelector('[data-key="smoothLength"]')!;
    expect(length.disabled).toBe(true);
    expect(length.title).toBe('Depends on Smoothing');
    expect(row.classList.contains('oac-row--off')).toBe(true);
    expect(h.visible('smoothLength')).toBe(true);
    h.choose('smoothing', 'sma');
    expect(length.disabled).toBe(false);
    expect(length.title).toBe('');
    expect(row.classList.contains('oac-row--off')).toBe(false);
    h.choose('smoothing', 'none');
    expect(length.disabled).toBe(true);
  });

  it('disables both halves of a colour picker and restores its own title', () => {
    const h = form();
    h.choose('mode', 'bands');
    const trigger = h.field('bandColor-trigger');
    expect(trigger.disabled).toBe(false);
    h.field('width').value = '0.5'; h.field('width').fire('change');
    expect(trigger.disabled).toBe(true);
    expect(h.field('bandColor').disabled).toBe(true);
    expect(trigger.title).toBe('Depends on Band width');
    h.field('width').value = '1'; h.field('width').fire('change');
    expect(trigger.disabled).toBe(false);
    expect(trigger.title).toBe('Band colour');
  });

  it('re-reads the host unavailable callback on every change and names its reason first', () => {
    let locked = true;
    const h = form({ unavailable: key => key === 'smoothLength' && locked ? 'Locked by the host' : null });
    h.choose('smoothing', 'sma');
    expect(h.field('smoothLength').title).toBe('Locked by the host');
    locked = false;
    h.handle.sync({ smoothing: 'sma' });
    expect(h.field('smoothLength').disabled).toBe(false);
  });

  it('announces what appeared and what became editable in a polite live region, and nothing at first paint', () => {
    const h = form();
    const live = h.live();
    expect(live).not.toBeNull();
    expect(live.textContent).toBe('');
    h.choose('mode', 'bands');
    expect(live.textContent).toBe('Shown: Band width, Band colour, Anchor price');
    h.choose('smoothing', 'sma');
    expect(live.textContent).toBe('Available: Smoothing length');
    h.choose('smoothing', 'none');
    expect(live.textContent).toBe('Unavailable: Smoothing length');
    h.choose('mode', 'simple');
    expect(live.textContent).toBe('Hidden: Band width, Band colour, Anchor price');
  });

  it('still reads out the same words twice in a row', () => {
    const list: IndicatorInput[] = [
      { key: 'fast', type: 'boolean', label: 'Fast line', default: false },
      { key: 'fastLength', type: 'number', label: 'Length', default: 5, visibleWhen: { key: 'fast', is: true } },
      { key: 'slow', type: 'boolean', label: 'Slow line', default: false },
      { key: 'slowLength', type: 'number', label: 'Length', default: 20, visibleWhen: { key: 'slow', is: true } },
    ];
    const h = form({}, list, { fast: false, fastLength: 5, slow: false, slowLength: 20 });
    h.field('fast').checked = true; h.field('fast').fire('change');
    expect(h.live().textContent).toBe('Shown: Length');
    h.field('slow').checked = true; h.field('slow').fire('change');
    // A live region is read when its text changes, so identical words need a difference no one hears.
    expect(h.live().textContent).not.toBe('Shown: Length');
    expect(h.live().textContent.trim()).toBe('Shown: Length');
  });

  it('adds no live region to a form without conditions', () => {
    const h = form({}, [{ key: 'n', type: 'number', label: 'N', default: 1 }], { n: 1 });
    expect(h.live()).toBeNull();
  });

  it('moves focus off a control that a sync hides, instead of dropping it on the page', () => {
    const h = form();
    h.choose('mode', 'bands');
    h.field('width').focus();
    h.handle.sync({ mode: 'simple' });
    expect(h.visible('width')).toBe(false);
    expect(h.doc.activeElement).toBe(h.field('length'));
  });

  it('returns focus to the edited control when its own edit disables the focused one', () => {
    const h = form();
    h.choose('smoothing', 'sma');
    h.field('smoothLength').focus();
    h.field('smoothing').value = 'none';
    h.field('smoothing').fire('change');
    expect(h.doc.activeElement).toBe(h.field('smoothing'));
  });

  it('never lets a hidden invalid draft block validation, and brings it back with its error', () => {
    const h = form();
    h.choose('mode', 'bands');
    h.field('level').value = '-4'; h.field('level').fire('change');
    expect(h.field('level').getAttribute('aria-invalid')).toBe('true');
    expect(h.handle.validate()).toBe(false);
    h.choose('mode', 'simple');
    expect(h.handle.validate()).toBe(true);
    // The message goes with its field instead of floating under the row above.
    const error = h.host.querySelector('#t-level-error')!;
    expect(error.hidden).toBe(true);
    h.choose('mode', 'bands');
    expect(h.field('level').value).toBe('-4');
    expect(error.hidden).toBe(false);
    expect(h.handle.validate()).toBe(false);
    expect(h.changes.filter(([key]) => key === 'level')).toEqual([]);
  });

  it('never lets an inactive invalid draft block validation', () => {
    const list: IndicatorInput[] = [
      { key: 'on', type: 'boolean', label: 'Use anchor', default: true },
      { key: 'level', type: 'price', label: 'Anchor', default: 1, min: 0, activeWhen: { key: 'on', is: true } },
    ];
    const h = form({}, list, { on: true, level: 1 });
    h.field('level').value = 'x'; h.field('level').fire('change');
    expect(h.handle.validate()).toBe(false);
    h.field('on').checked = false; h.field('on').fire('change');
    expect(h.handle.validate()).toBe(true);
  });

  it('updates a hidden control on sync, so it is not stale when it returns', () => {
    const h = form();
    expect(h.visible('width')).toBe(false);
    h.handle.sync({ width: 4 });
    expect(h.visible('width')).toBe(false);
    expect(h.field('width').value).toBe('4');
    h.handle.sync({ mode: 'bands' });
    expect(h.visible('width')).toBe(true);
    expect(h.field('width').value).toBe('4');
  });

  it('focuses the first control that is shown and enabled', () => {
    const list: IndicatorInput[] = [
      { key: 'hidden', type: 'number', label: 'Hidden', default: 1, visibleWhen: { key: 'on', is: true } },
      { key: 'idle', type: 'number', label: 'Idle', default: 1, activeWhen: { key: 'on', is: true } },
      { key: 'on', type: 'boolean', label: 'On', default: false },
    ];
    const h = form({}, list, { hidden: 1, idle: 1, on: false });
    expect(h.handle.focusFirst()).toBe(true);
    expect(h.doc.activeElement).toBe(h.field('on'));
  });

  it('honours a condition on a colour pair and a custom row', () => {
    const list: ChartSettingsInput[] = [
      { key: 'on', type: 'boolean', label: 'On', default: false },
      { key: 'body', type: 'colorPair', label: 'Body', visibleWhen: { key: 'on', is: true },
        up: { key: 'bodyUp', label: 'Up', default: '#00ff00' }, down: { key: 'bodyDown', label: 'Down', default: '#ff0000' } },
      { key: 'wick', type: 'colorPair', label: 'Wick', activeWhen: { key: 'on', is: true },
        up: { key: 'wickUp', label: 'Up', default: '#00ff00' }, down: { key: 'wickDown', label: 'Down', default: '#ff0000' } },
    ];
    const h = form({}, list, { on: false });
    expect(h.visible('bodyUp-trigger')).toBe(false);
    expect(h.field('wickUp-trigger').disabled).toBe(true);
    expect(h.field('wickUp-trigger').title).toBe('Up: Depends on On');
    expect(h.host.querySelector('[data-key="wick"]')!.classList.contains('oac-row--off')).toBe(true);
    h.field('on').checked = true; h.field('on').fire('change');
    expect(h.visible('bodyUp-trigger')).toBe(true);
    expect(h.field('wickDown-trigger').disabled).toBe(false);
    expect(h.field('wickDown-trigger').title).toBe('Down');
    expect(h.host.querySelector('[data-key="wick"]')!.classList.contains('oac-row--off')).toBe(false);
  });

  it('hides a row that reads the switch of a hidden colour pair, and names the pair for one that reads its swatch', () => {
    const list: ChartSettingsInput[] = [
      { key: 'on', type: 'boolean', label: 'On', default: false },
      { key: 'borders', type: 'colorPair', label: 'Borders', visibleWhen: { key: 'on', is: true },
        enabled: { key: 'pe', default: true },
        up: { key: 'pu', label: 'Up', default: '#00ff00' }, down: { key: 'pd', label: 'Down', default: '#ff0000' } },
      { key: 'w', type: 'number', label: 'Border width', default: 1, visibleWhen: { key: 'pe', is: true } },
      { key: 'shade', type: 'number', label: 'Shade', default: 1, activeWhen: { key: 'pu', isNot: '' } },
    ];
    const h = form({}, list, { on: false, pe: true, pu: '#00ff00', pd: '#ff0000', w: 1, shade: 1 });
    expect(h.visible('pe')).toBe(false);
    expect(h.visible('w')).toBe(false);
    expect(h.field('shade').disabled).toBe(true);
    expect(h.field('shade').title).toBe('Depends on Borders');
    h.field('on').checked = true; h.field('on').fire('change');
    expect(h.visible('w')).toBe(true);
    expect(h.field('shade').disabled).toBe(false);
    h.field('pe').checked = false; h.field('pe').fire('change');
    expect(h.visible('w')).toBe(false);
  });
});

describe('renderForm inline rows', () => {
  it('puts consecutive inputs with one inline id on one row, each with its own label', () => {
    const h = form();
    const row = h.host.querySelector('[data-inline="len"]')!;
    expect(row.classList.contains('oac-row')).toBe(true);
    expect(row.classList.contains('oac-row--inline')).toBe(true);
    expect(row.querySelector('#t-length')).not.toBeNull();
    expect(row.querySelector('#t-source')).not.toBeNull();
    const labels = row.querySelectorAll('label');
    expect(labels.map(label => [label.textContent, label.htmlFor])).toEqual([['Length', 't-length'], ['Source', 't-source']]);
    // Two inline rows and the plain rows between them, not one row per input.
    expect(h.host.querySelectorAll('[data-inline="signal"]').length).toBe(1);
    const signal = h.host.querySelector('[data-inline="signal"]')!;
    expect(signal.querySelector('input[type="checkbox"]')).toBe(h.field('showSignal'));
    expect(signal.querySelector('#t-signalLength')).not.toBeNull();
    expect(signal.querySelector('#t-signalColor-trigger')).not.toBeNull();
  });

  it('dims and disables one member of an inline row without touching its neighbours', () => {
    const h = form();
    const item = h.host.querySelectorAll('.oac-inline__item').find(node => node.dataset.key === 'signalLength')!;
    expect(h.field('showSignal').disabled).toBe(false);
    expect(h.field('signalLength').disabled).toBe(true);
    expect(h.field('signalColor-trigger').disabled).toBe(true);
    expect(item.classList.contains('oac-inline__item--off')).toBe(true);
    h.field('showSignal').checked = true; h.field('showSignal').fire('change');
    expect(h.field('signalLength').disabled).toBe(false);
    expect(item.classList.contains('oac-inline__item--off')).toBe(false);
  });

  it('hides one member of an inline row, and the row itself once every member is hidden', () => {
    const list: IndicatorInput[] = [
      { key: 'mode', type: 'select', label: 'Mode', default: 'simple', options: MODES },
      { key: 'lo', type: 'number', label: 'Low', default: 1, inline: 'range', visibleWhen: { key: 'mode', isNot: 'off' } },
      { key: 'hi', type: 'number', label: 'High', default: 2, inline: 'range', visibleWhen: { key: 'mode', is: 'bands' } },
    ];
    const h = form({}, list, { mode: 'simple', lo: 1, hi: 2 });
    const row = h.host.querySelector('[data-inline="range"]')!;
    expect(h.visible('lo')).toBe(true);
    expect(h.visible('hi')).toBe(false);
    expect(row.hidden).toBe(false);
    h.handle.sync({ mode: 'off' });
    expect(row.hidden).toBe(true);
  });

  it('starts a new row for a multi-line input and at a new group, even with the same inline id', () => {
    const list: IndicatorInput[] = [
      { key: 'a', type: 'number', label: 'A', default: 1, inline: 'x', group: 'One' },
      { key: 'note', type: 'multiline', label: 'Note', default: '', inline: 'x', group: 'One' },
      { key: 'b', type: 'number', label: 'B', default: 1, inline: 'x', group: 'One' },
      { key: 'c', type: 'number', label: 'C', default: 1, inline: 'x', group: 'Two' },
    ];
    const h = form({}, list, { a: 1, note: '', b: 1, c: 1 });
    const rows = h.host.querySelectorAll('.oac-row');
    expect(rows.map(row => row.dataset.key)).toEqual(['a', 'note', 'b', 'c']);
  });
});

// ── the widget's study settings dialog ────────────────────────────────────

let serial = 0;
const cleanups: (() => void)[] = [];
afterEach(() => { for (const dispose of cleanups.splice(0).reverse()) dispose(); });

function dialog(list: IndicatorInput[] = inputs, settings: Record<string, unknown> = {}, extra: Partial<WidgetContext> = {}) {
  const dom = installDom(), doc = asDoc(dom.doc);
  const chart = new Chart(asEl(dom.chartEl), { document: doc, pixelRatio: () => 1, shortcuts: false,
    branding: false, timeNavigator: false, raf: { schedule: callback => { callback(); return 1; }, cancel() {} } });
  chart.applySize(900, 600);
  chart.addSeries('line').setData([1, 2, 3].map((close, index) => ({
    time: 1700000000 + index * 60, open: close, high: close, low: close, close,
  })));
  const id = `conditional-host-${++serial}`;
  registerIndicator({ id, name: 'Conditional inputs', placement: 'onchart', inputs: list,
    plots: [{ key: 'value', title: 'Value', type: 'line' }],
    calc: (bars, values) => ({ value: bars.map(() => values.width as number) }) });
  const inst = chart.addIndicator(id, settings), draw = new DrawingController(chart);
  const overlays = createOverlayStack(asEl(dom.root), doc);
  const ctx: WidgetContext = { chart, draw, root: asEl(dom.root), document: doc, theme: 'dark', chartTheme: darkTheme,
    keymap: {} as WidgetContext['keymap'], bus: new WidgetBus(), storage: new WidgetStorage('conditional', null), locale: undefined,
    toast: vi.fn(() => ({ node: doc.createElement('div'), dismiss() {} })), status() {},
    openOverlay: (node, options) => overlays.open(node, options), overlays,
    tips: { attach() {}, refreshLabel() {}, show() {}, hide() {}, target: () => null, destroy() {} },
    symbol: () => ({ symbol: 'PRIMARY', exchange: 'HOST' }), interval: () => '1m', ...extra };
  cleanups.push(() => { overlays.destroy(); draw.destroy(); chart.destroy(); });
  const open = () => mountIndicatorSettings(ctx, undefined, { instanceId: inst.id });
  let panel = open();
  const root = dom.root;
  const field = (key: string): FakeElement => {
    const result = root.querySelector(`#oac-ind-${inst.id}-${key}`);
    expect(result, `field ${key}`).not.toBeNull();
    return result!;
  };
  const visible = (key: string): boolean => shown(field(key), root);
  const button = (label: string): FakeElement => {
    const result = root.querySelectorAll('button').find(node => node.textContent === label);
    expect(result, `button ${label}`).toBeDefined();
    return result!;
  };
  const choose = (key: string, value: string): void => { field(key).value = value; field(key).fire('change'); };
  return { dom, ctx, chart, inst, root, field, visible, button, choose,
    get panel() { return panel; }, reopen() { panel = open(); } };
}

describe('the widget study settings dialog', () => {
  it('applies each edit live and keeps a hidden input value untouched', () => {
    const h = dialog();
    const writes = vi.spyOn(h.inst, 'setSettings');
    h.choose('mode', 'bands');
    h.field('width').value = '3'; h.field('width').fire('change');
    h.choose('mode', 'simple');
    expect(writes.mock.calls.map(([patch]) => patch)).toEqual([{ mode: 'bands' }, { width: 3 }, { mode: 'simple' }]);
    expect(h.inst.settings().width).toBe(3);
    expect(h.visible('width')).toBe(false);
    h.choose('mode', 'bands');
    expect(h.field('width').value).toBe('3');
  });

  it('restores every default, hidden inputs included, and redraws what the defaults show', () => {
    const h = dialog();
    h.choose('mode', 'bands');
    h.field('width').value = '4'; h.field('width').fire('change');
    h.choose('smoothing', 'sma');
    h.choose('mode', 'simple');
    h.button('Defaults').click();
    expect(h.inst.settings()).toMatchObject({ mode: 'simple', width: 2, smoothing: 'none' });
    expect(h.visible('width')).toBe(false);
    expect(h.field('width').value).toBe('2');
    expect(h.field('smoothLength').disabled).toBe(true);
  });

  it('cancels back to the settings from before the dialog, and reopens with their visibility', () => {
    const h = dialog(inputs, { mode: 'bands', width: 1.5 });
    expect(h.visible('width')).toBe(true);
    h.choose('mode', 'simple');
    h.choose('smoothing', 'sma');
    h.button('Cancel').click();
    expect(h.panel.isOpen()).toBe(false);
    expect(h.inst.settings()).toMatchObject({ mode: 'bands', width: 1.5, smoothing: 'none' });
    h.reopen();
    expect(h.visible('width')).toBe(true);
    expect(h.field('width').value).toBe('1.5');
    expect(h.field('smoothLength').disabled).toBe(true);
  });

  it('commits with OK while a hidden price holds an invalid draft, and keeps the accepted value', () => {
    const h = dialog();
    h.choose('mode', 'bands');
    h.field('level').value = '-1'; h.field('level').fire('change');
    h.button('OK').click();
    expect(h.panel.isOpen()).toBe(true);
    h.choose('mode', 'simple');
    h.button('OK').click();
    expect(h.panel.isOpen()).toBe(false);
    expect(h.inst.settings()).toMatchObject({ mode: 'simple', level: 10 });
  });

  it('switches tabs past a hidden invalid draft instead of trapping the user on a tab', () => {
    const h = dialog();
    h.choose('mode', 'bands');
    h.field('level').value = '-1'; h.field('level').fire('change');
    h.choose('mode', 'simple');
    h.button('Style').click();
    expect(h.root.querySelector(`#oac-ind-${h.inst.id}-mode`)).toBeNull();
  });

  it('turns off the chart pick of a price input that is inactive', () => {
    const list: IndicatorInput[] = [
      { key: 'anchored', type: 'boolean', label: 'Anchor', default: false },
      { key: 'level', type: 'price', label: 'Anchor price', default: 2, pick: true, activeWhen: { key: 'anchored', is: true } },
      { key: 'width', type: 'number', label: 'Width', default: 1 },
    ];
    const h = dialog(list);
    const pick = h.root.querySelector('[data-input-action="level"]')!;
    expect(pick.disabled).toBe(true);
    expect(pick.title).toBe('Depends on Anchor');
    h.field('anchored').checked = true; h.field('anchored').fire('change');
    expect(pick.disabled).toBe(false);
  });

  it('turns off the symbol search of a symbol input that is inactive, and names the host reason once it is not', () => {
    const list: IndicatorInput[] = [
      { key: 'useOther', type: 'boolean', label: 'Use other', default: false },
      { key: 'other', type: 'symbol', label: 'Other symbol', default: 'AAA', activeWhen: { key: 'useOther', is: true } },
    ];
    const searched = dialog(list, {}, { symbolSearch: () => [] });
    const search = searched.root.querySelector('[data-input-action="other"]')!;
    expect(search.disabled).toBe(true);
    expect(search.title).toBe('Depends on Use other');
    searched.field('useOther').checked = true; searched.field('useOther').fire('change');
    expect(search.disabled).toBe(false);
    expect(search.title).toBe('');
    searched.field('useOther').checked = false; searched.field('useOther').fire('change');
    expect(search.disabled).toBe(true);
    // With no search configured, the field's own reason still comes first.
    const plain = dialog(list);
    const idle = plain.root.querySelector('[data-input-action="other"]')!;
    expect(idle.title).toBe('Depends on Use other');
    plain.field('useOther').checked = true; plain.field('useOther').fire('change');
    expect(idle.disabled).toBe(true);
    expect(idle.title).toBe('Symbol search is not configured; enter an instrument manually');
  });
});
