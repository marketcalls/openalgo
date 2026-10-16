import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import type { Bar } from '../src/index';
import { createWidget, type Widget, type WidgetOptions } from '../src/widget/index';
import {
  MOBILE_MAX_WIDTH, PHONE_LANDSCAPE_MAX_WIDTH, TABLET_MIN_HEIGHT, resolveMobileMode,
} from '../src/widget/mobile';
import {
  ensureWindowGlobal, fakeContainer, fakeWidgetDocument, fire, fireKey,
  type FakeDocument, type FakeElement,
} from './helpers/fake-dom-widget';

beforeAll(ensureWindowGlobal);

const DAY = 86400;
const T0 = 1700000000;
const bars: Bar[] = Array.from({ length: 20 }, (_, i) => ({
  time: T0 + i * DAY, open: 99, high: 102, low: 98, close: 100, volume: 1000,
}));

class ResizeObserverDouble {
  public static instances: ResizeObserverDouble[] = [];
  public readonly disconnect = vi.fn();
  private readonly _callback: ResizeObserverCallback;

  public constructor(callback: ResizeObserverCallback) {
    this._callback = callback;
    ResizeObserverDouble.instances.push(this);
  }

  public observe(): void {}
  public fire(): void { this._callback([], this as unknown as ResizeObserver); }
}

class MediaQueryListDouble {
  public static instances: MediaQueryListDouble[] = [];
  public matches: boolean;
  public readonly media: string;
  public readonly addEventListener = vi.fn((_type: string, listener: () => void) => { this._listener = listener; });
  public readonly removeEventListener = vi.fn((_type: string, listener: () => void) => {
    if (this._listener === listener) this._listener = null;
  });
  private _listener: (() => void) | null = null;

  public constructor(media: string, matches: boolean) {
    this.media = media;
    this.matches = matches;
    MediaQueryListDouble.instances.push(this);
  }

  public fire(matches: boolean): void {
    this.matches = matches;
    this._listener?.();
  }
}

interface Made {
  w: Widget;
  doc: FakeDocument;
  container: FakeElement;
  root: FakeElement;
}

const live: Widget[] = [];
afterEach(() => {
  for (const w of live.splice(0)) if (!w.isDestroyed) w.destroy();
  ResizeObserverDouble.instances = [];
  MediaQueryListDouble.instances = [];
  vi.useRealTimers();
});

function make(opts: WidgetOptions = {}, width = 390, coarsePointer = false, height = 700): Made {
  const doc = fakeWidgetDocument();
  Object.assign(doc, { defaultView: {
    ResizeObserver: ResizeObserverDouble,
    matchMedia: (query: string) => new MediaQueryListDouble(query, query === '(pointer: coarse)' && coarsePointer),
  } });
  const container = fakeContainer(doc, width, height);
  const w = createWidget(container as unknown as HTMLElement, {
    document: doc as unknown as Document,
    pixelRatio: () => 1,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    ...opts,
  });
  w.chart.applySize(width, height);
  w.series.setData(bars);
  live.push(w);
  return { w, doc, container, root: w.root as unknown as FakeElement };
}

const action = (root: FakeElement, name: string): FakeElement =>
  root.querySelector(`[data-mobile-action="${name}"]`) as FakeElement;

const settle = async (): Promise<void> => {
  await Promise.resolve();
  await Promise.resolve();
};

describe('mobile mode', () => {
  it('switches at 640 CSS pixels without recreating chart state', () => {
    const { w, container, root } = make({ feed: { getBars: async () => [] } }, 641);
    const chart = w.chart;
    const draw = w.draw;
    const series = w.series;
    const dataController = w.dataController;
    expect(root.classList.contains('is-mobile')).toBe(false);

    container.clientWidth = 640;
    container.rect = { left: 0, top: 0, width: 640, height: 700 };
    for (const observer of ResizeObserverDouble.instances) observer.fire();

    expect(root.classList.contains('is-mobile')).toBe(true);
    expect(w.chart).toBe(chart);
    expect(w.draw).toBe(draw);
    expect(w.series).toBe(series);
    expect(w.dataController).toBe(dataController);
    expect(w.series.getData()).toHaveLength(20);

    const forcedOff = make({ mobile: 'never' }, 390, true);
    expect(forcedOff.root.classList.contains('is-mobile')).toBe(false);
    expect(forcedOff.root.querySelector('.oac-mobile')?.hidden).toBe(true);
  });

  it('keeps auto mode active in a landscape phone container with a coarse pointer', () => {
    const { w, root } = make({}, 740, true, 390);
    const pointer = MediaQueryListDouble.instances.find((query) => query.media === '(pointer: coarse)')!;
    expect(root.classList.contains('is-mobile')).toBe(true);

    pointer.fire(false);
    expect(root.classList.contains('is-mobile')).toBe(false);
    pointer.fire(true);
    expect(root.classList.contains('is-mobile')).toBe(true);
    w.destroy();
    expect(pointer.removeEventListener).toHaveBeenCalledWith('change', expect.any(Function));
  });

  it('lets the compact header change the symbol and interval', () => {
    const { w, doc, root } = make({ mobile: 'always', symbol: 'INFY', interval: '5m', intervals: ['5m', '1d'] }, 900);
    const symbol = root.querySelector('.oac-mobile__symbol') as FakeElement;
    symbol.value = 'reliance';
    fireKey(symbol, 'Enter');
    expect(w.symbol()).toBe('RELIANCE');

    action(root, 'interval').click();
    expect((doc.activeElement as FakeElement).dataset.interval).toBe('5m');
    (root.querySelector('[data-interval="1d"]') as FakeElement).click();
    expect(w.interval()).toBe('1d');
    expect(action(root, 'interval').textContent).toBe('D');
  });

  it('offers only permitted registered drawing tools and uses controller state', () => {
    const { w, root } = make({ mobile: 'always', rail: { tools: ['trend-line', 'rectangle', 'missing-tool'] } });
    action(root, 'draw').click();
    const tools = root.querySelectorAll('.oac-mobile__tool').map((el) => el.dataset.tool);
    expect(tools).toEqual(['trend-line', 'rectangle']);

    (root.querySelector('[data-tool="rectangle"]') as FakeElement).click();
    expect(w.draw.activeTool()).toBe('rectangle');
    expect(action(root, 'draw').getAttribute('aria-pressed')).toBe('true');

    action(root, 'draw').click();
    action(root, 'cancel').click();
    expect(w.draw.activeTool()).toBeNull();
    expect(action(root, 'draw').getAttribute('aria-pressed')).toBe('false');
  });

  it('keeps drawing preferences and undo on the existing rail controller path', () => {
    const { w, root } = make({ mobile: 'always' });
    w.draw.add({ tool: 'horizontal-line', points: [{ time: T0, price: 100 }], style: {}, paneIndex: 0 });
    w.draw.setTool('trend-line');
    action(root, 'draw').click();
    action(root, 'magnet').click();
    action(root, 'stay').click();
    action(root, 'undo').click();

    expect(w.draw.magnetMode()).toBe('weak');
    expect(w.getState().rail?.stay).toBe(true);
    expect(w.draw.drawings()).toHaveLength(0);
  });

  it('keeps keyboard focus and scroll position through drawing action refreshes', () => {
    const { w, doc, root } = make({ mobile: 'always' });
    w.draw.add({ tool: 'horizontal-line', points: [{ time: T0, price: 100 }], style: {}, paneIndex: 0 });
    w.draw.setTool('trend-line');
    action(root, 'draw').click();
    const body = root.querySelector('.oac-mobile-sheet__body') as FakeElement;
    Object.assign(body, { scrollTop: 120 });

    let magnet = action(root, 'magnet');
    magnet.focus();
    magnet.click();
    magnet = action(root, 'magnet');
    expect(doc.activeElement).toBe(magnet);
    expect((body as unknown as { scrollTop: number }).scrollTop).toBe(120);
    magnet.click();
    expect(w.draw.magnetMode()).toBe('strong');
    expect(doc.activeElement).toBe(action(root, 'magnet'));

    let stay = action(root, 'stay');
    stay.focus();
    stay.click();
    stay = action(root, 'stay');
    expect(doc.activeElement).toBe(stay);
    stay.click();
    expect(w.getState().rail?.stay).toBe(false);

    const undo = action(root, 'undo');
    undo.focus();
    undo.click();
    expect(w.draw.drawings()).toHaveLength(0);
    expect(doc.activeElement).toBe(action(root, 'undo'));

    const cancel = action(root, 'cancel');
    cancel.focus();
    cancel.click();
    expect(w.draw.activeTool()).toBeNull();
    expect((doc.activeElement as FakeElement).classList.contains('oac-mobile__tool')).toBe(true);
  });

  it('keeps the focused tool through controller-driven sheet refresh', () => {
    const { w, doc, root } = make({ mobile: 'always' });
    w.draw.setTool('trend-line');
    action(root, 'draw').click();
    const rectangle = root.querySelector('[data-tool="rectangle"]') as FakeElement;
    rectangle.focus();
    w.draw.add({ tool: 'horizontal-line', points: [{ time: T0, price: 101 }], style: {}, paneIndex: 0 });
    expect(doc.activeElement).toBe(root.querySelector('[data-tool="rectangle"]'));
  });

  it('shows live selection actions that lock, open properties and delete', () => {
    const { w, root } = make({ mobile: 'always' });
    const drawing = w.draw.add({
      tool: 'horizontal-line', points: [{ time: T0, price: 100 }], style: {}, paneIndex: 0,
    });
    w.draw.select(drawing.id);
    const selected = root.querySelector('.oac-mobile__selection') as FakeElement;
    expect(selected.hidden).toBe(false);

    action(root, 'lock').click();
    expect(w.draw.get(drawing.id)?.locked).toBe(true);
    expect(action(root, 'lock').textContent).toBe('Lock');
    expect(action(root, 'lock').getAttribute('aria-pressed')).toBe('true');
    action(root, 'properties').click();
    expect(root.querySelector('.oac-props')).not.toBeNull();
    w.context.overlays.closeAll();
    // A locked drawing stays, as on the desktop; unlocked, it goes.
    expect(action(root, 'delete').getAttribute('aria-disabled')).toBe('true');
    action(root, 'lock').click();
    action(root, 'delete').click();
    expect(w.draw.get(drawing.id)).toBeUndefined();
    expect(selected.hidden).toBe(true);
  });

  it('omits controls disabled by host options', () => {
    const enabled = make({ mobile: 'always' });
    expect(enabled.root.querySelector('.oac-mobile__header')).not.toBeNull();
    for (const name of ['draw', 'studies', 'objects', 'more']) expect(action(enabled.root, name)).not.toBeNull();

    const { root } = make({ mobile: 'always', topbar: false, rail: false, indicators: false });
    expect(root.querySelector('.oac-mobile__header')).toBeNull();
    expect(action(root, 'draw')).toBeNull();
    expect(action(root, 'studies')).toBeNull();
    expect(action(root, 'objects')).toBeNull();
    expect(action(root, 'more')).toBeNull();
  });

  it('uses the words the rest of the widget uses for studies, the theme and the stay toggle', () => {
    const { w, root } = make({ mobile: 'always' });
    expect(action(root, 'studies').textContent).toBe('Indicators');
    action(root, 'more').click();
    expect(action(root, 'theme').textContent).toMatch(/^Switch to the (light|dark) theme$/);
    w.context.overlays.closeAll();
    w.draw.setTool('trend-line');
    action(root, 'draw').click();
    expect(action(root, 'stay').textContent).toBe('Keep tool active: off');
  });

  it('keeps an accessible branding link current in the More sheet', () => {
    const { w, doc, root } = make({ mobile: 'always' });
    action(root, 'more').click();
    let link = action(root, 'branding');
    expect(link.tagName).toBe('A');
    expect(link.classList.contains('oac-mobile__action')).toBe(true);
    expect(doc.head.textContent).toContain('.oac-mobile__branding { display: flex;');
    expect(link.getAttribute('href')).toBe('https://openalgo.in');
    expect(link.getAttribute('target')).toBe('_blank');
    expect(link.getAttribute('rel')).toContain('noopener');
    expect(link.getAttribute('aria-label')).toBe('Chart by OpenAlgo');

    w.chart.setBranding(false);
    expect(action(root, 'branding')).toBeNull();

    w.chart.setBranding({ href: 'https://charts.example.test', label: 'Charts provider' });
    link = action(root, 'branding');
    expect(link.getAttribute('href')).toBe('https://charts.example.test');
    expect(link.textContent).toBe('Charts provider');
    expect(link.getAttribute('aria-label')).toBe('Charts provider');
  });

  it('uses symbol search only when the host supplies it', async () => {
    vi.useFakeTimers();
    const search = vi.fn(() => [{ symbol: 'INFY', exchange: 'NSE', name: 'Infosys' }]);
    const withSearch = make({ mobile: 'always', symbolSearch: search });
    const input = withSearch.root.querySelector('.oac-mobile__symbol') as FakeElement;
    input.focus();
    input.value = 'inf';
    fire(input, 'input');
    await vi.advanceTimersByTimeAsync(150);
    expect(search).toHaveBeenCalledWith('inf', { signal: expect.any(AbortSignal) });
    (withSearch.root.querySelector('[data-mobile-action="pick-symbol"]') as FakeElement).click();
    expect(withSearch.w.symbol()).toBe('INFY');

    const withoutSearch = make({ mobile: 'always' });
    const plain = withoutSearch.root.querySelector('.oac-mobile__symbol') as FakeElement;
    plain.value = 'rel';
    fire(plain, 'input');
    await vi.advanceTimersByTimeAsync(150);
    expect(withoutSearch.root.querySelector('[data-mobile-action="pick-symbol"]')).toBeNull();
  });

  it('waits for a pending symbol search on Enter, and drops a lookup the input left by blur', async () => {
    vi.useFakeTimers();
    let resolveFirst!: (matches: Array<{ symbol: string }>) => void;
    let resolveSecond!: (matches: Array<{ symbol: string }>) => void;
    const search = vi.fn()
      .mockImplementationOnce(() => new Promise<Array<{ symbol: string }>>((resolve) => { resolveFirst = resolve; }))
      .mockImplementationOnce(() => new Promise<Array<{ symbol: string }>>((resolve) => { resolveSecond = resolve; }));
    const { w, root } = make({ mobile: 'always', symbolSearch: search });
    const input = root.querySelector('.oac-mobile__symbol') as FakeElement;
    const before = w.symbol();

    input.focus();
    input.value = 'aaa';
    fire(input, 'input');
    // In the debounce, and with the lookup out, Enter waits for what the search finds.
    fireKey(input, 'Enter');
    await vi.advanceTimersByTimeAsync(150);
    expect(search).toHaveBeenCalledTimes(1);
    fireKey(input, 'Enter');
    expect(w.symbol()).toBe(before);
    // A search that finds nothing leaves the typed text to commit.
    resolveFirst([]);
    await settle();
    fireKey(input, 'Enter');
    expect(w.symbol()).toBe('AAA');
    expect(root.querySelector('[data-mobile-action="pick-symbol"]')).toBeNull();

    input.focus();
    input.value = 'ccc';
    fire(input, 'input');
    await vi.advanceTimersByTimeAsync(150);
    input.blur();
    resolveSecond([{ symbol: 'CCC-OLD' }]);
    await settle();
    expect(root.querySelector('[data-mobile-action="pick-symbol"]')).toBeNull();
  });

  it('cancels a pending search when its results surface closes', async () => {
    vi.useFakeTimers();
    let resolveSearch!: (matches: Array<{ symbol: string }>) => void;
    const search = vi.fn(() => new Promise<Array<{ symbol: string }>>((resolve) => { resolveSearch = resolve; }));
    const { doc, root } = make({ mobile: 'always', symbolSearch: search });
    const input = root.querySelector('.oac-mobile__symbol') as FakeElement;
    input.focus();
    input.value = 'bbb';
    fire(input, 'input');
    await vi.advanceTimersByTimeAsync(150);

    const results = root.querySelector('.oac-mobile-results') as FakeElement;
    expect(results).not.toBeNull();
    expect(results.classList.contains('oac-dialog')).toBe(false);
    expect(results.getAttribute('aria-modal')).toBeNull();
    expect(doc.activeElement).toBe(input);
    expect(input.getAttribute('aria-expanded')).toBe('true');
    const controlled = input.getAttribute('aria-controls');
    expect(controlled).not.toBeNull();
    expect(results.querySelector(`#${controlled}`)?.getAttribute('role')).toBe('listbox');

    action(root, 'close-search').click();
    expect(input.getAttribute('aria-expanded')).toBe('false');
    expect(input.getAttribute('aria-controls')).toBeNull();
    resolveSearch([{ symbol: 'BBB-OLD' }]);
    await settle();
    expect(root.querySelector('.oac-mobile-results')).toBeNull();
    expect(root.querySelector('[data-mobile-action="pick-symbol"]')).toBeNull();
  });

  it('clears previous symbol results when the latest response is empty', async () => {
    vi.useFakeTimers();
    const search = vi.fn((query: string) => query === 'bbb' ? [{ symbol: 'BBB' }] : []);
    const { root } = make({ mobile: 'always', symbolSearch: search });
    const input = root.querySelector('.oac-mobile__symbol') as FakeElement;
    input.focus();
    input.value = 'bbb';
    fire(input, 'input');
    await vi.advanceTimersByTimeAsync(150);
    expect(root.querySelector('[data-mobile-action="pick-symbol"]')?.textContent).toContain('BBB');

    input.value = 'zzz';
    fire(input, 'input');
    await vi.advanceTimersByTimeAsync(150);
    expect(root.querySelector('.oac-mobile-results')).toBeNull();
    expect(root.querySelector('[data-mobile-action="pick-symbol"]')).toBeNull();
  });

  it('stops control presses before chart capture and tears down resize observation', () => {
    const { w, doc, root } = make({ mobile: 'auto' });
    const reachedDocument = vi.fn();
    doc.addEventListener('pointerdown', reachedDocument);
    fire(action(root, 'draw'), 'pointerdown', { pointerType: 'touch' });
    expect(reachedDocument).not.toHaveBeenCalled();

    const observer = ResizeObserverDouble.instances[0];
    w.destroy();
    expect(observer.disconnect).toHaveBeenCalledOnce();
    expect(root.parentNode).toBeNull();
  });

  it('dismisses mobile sheets through the shared overlay stack', () => {
    const { doc, root } = make({ mobile: 'always' });
    action(root, 'draw').click();
    expect(root.querySelector('.oac-mobile-sheet')).not.toBeNull();
    fireKey(doc, 'Escape');
    expect(root.querySelector('.oac-mobile-sheet')).toBeNull();

    action(root, 'draw').click();
    fire(doc.body, 'pointerdown');
    expect(root.querySelector('.oac-mobile-sheet')).toBeNull();
  });
});

/** Give the fake container a new size and deliver it the way a browser does, through the observer. */
function resize(container: FakeElement, width: number, height: number): void {
  container.clientWidth = width;
  container.clientHeight = height;
  container.rect = { left: 0, top: 0, width, height };
  for (const observer of ResizeObserverDouble.instances) observer.fire();
}

describe('auto mobile mode decision', () => {
  // Width and height of the widget container, whether the primary pointer is
  // coarse, and whether the compact controls should show.
  const table: Array<[number, number, boolean, boolean]> = [
    [390, 740, false, true],
    [640, 700, false, true],
    [641, 700, false, false],
    [932, 430, false, false],
    [820, 1180, false, false],
    [390, 740, true, true],
    [640, 1000, true, true],
    [740, 390, true, true],
    [932, 430, true, true],
    [960, 599, true, true],
    [961, 430, true, false],
    [960, 600, true, false],
    [744, 1133, true, false],
    [820, 1180, true, false],
    [1180, 820, true, false],
    [1024, 768, true, false],
    [1366, 768, true, false],
    [0, 700, false, false],
    [0, 700, true, false],
    [820, 0, true, false],
  ];

  it.each(table)('a %i by %i container with coarse pointer %s shows compact controls: %s', (width, height, coarse, expected) => {
    const { root } = make({}, width, coarse, height);
    expect(root.classList.contains('is-mobile')).toBe(expected);
    expect(root.dataset.mobile).toBe(String(expected));
    expect(root.querySelector('.oac-mobile')?.hidden).toBe(!expected);
  });

  it('resolves the same table as a pure function, and explicit modes ignore it', () => {
    expect([MOBILE_MAX_WIDTH, PHONE_LANDSCAPE_MAX_WIDTH, TABLET_MIN_HEIGHT]).toEqual([640, 960, 600]);
    for (const [width, height, coarse, expected] of table) {
      expect(resolveMobileMode('auto', width, height, coarse)).toBe(expected);
      expect(resolveMobileMode('always', width, height, coarse)).toBe(true);
      expect(resolveMobileMode('never', width, height, coarse)).toBe(false);
    }
  });

  it('keeps explicit modes whatever the container and pointer', () => {
    expect(make({ mobile: 'always' }, 1180, false, 820).root.classList.contains('is-mobile')).toBe(true);
    expect(make({ mobile: 'never' }, 390, true, 740).root.classList.contains('is-mobile')).toBe(false);
    expect(MediaQueryListDouble.instances.some((query) => query.media === '(pointer: coarse)')).toBe(false);
  });

  it('re-evaluates when the container changes size, with the window left alone', () => {
    const { container, root } = make({}, 820, true, 1180);
    expect(root.classList.contains('is-mobile')).toBe(false);

    resize(container, 1180, 820);
    expect(root.classList.contains('is-mobile')).toBe(false);
    resize(container, 820, 500);
    expect(root.classList.contains('is-mobile')).toBe(true);
    resize(container, 1180, 500);
    expect(root.classList.contains('is-mobile')).toBe(false);
    resize(container, 600, 1180);
    expect(root.classList.contains('is-mobile')).toBe(true);
    // Hiding the container (a background tab) leaves the open sheet alone.
    action(root, 'draw').click();
    resize(container, 0, 0);
    expect(root.classList.contains('is-mobile')).toBe(true);
    expect(root.querySelector('.oac-mobile-sheet')).not.toBeNull();
    resize(container, 820, 1180);
    expect(root.classList.contains('is-mobile')).toBe(false);
    expect(root.querySelector('.oac-mobile-sheet')).toBeNull();
    resize(container, 0, 0);
    expect(root.classList.contains('is-mobile')).toBe(false);
  });

  it('keeps the layout of a container collapsed to no height, and decides again once it has one', () => {
    const { container, root } = make({}, 820, true, 450);
    expect(root.classList.contains('is-mobile')).toBe(true);
    action(root, 'draw').click();
    // A closed accordion or a zero-height transition: the width is still there,
    // but a height of 0 must not read as a tablet and close the open sheet.
    resize(container, 820, 0);
    expect(root.classList.contains('is-mobile')).toBe(true);
    expect(root.querySelector('.oac-mobile-sheet')).not.toBeNull();
    resize(container, 820, 1180);
    expect(root.classList.contains('is-mobile')).toBe(false);
  });

  it('starts an unmeasured container on the desktop controls and decides once it has a size', () => {
    const { container, root } = make({}, 0, true, 0);
    expect(root.classList.contains('is-mobile')).toBe(false);
    resize(container, 390, 740);
    expect(root.classList.contains('is-mobile')).toBe(true);
  });

  it('holds the layout while a text field in the widget has focus', () => {
    const { container, doc, root } = make({}, 820, true, 1180);
    const field = root.querySelector('.oac-sym__input') as FakeElement;
    field.focus();
    // An on-screen keyboard shortens the container: switching now would hide the field being typed in.
    resize(container, 820, 520);
    expect(root.classList.contains('is-mobile')).toBe(false);

    field.blur();
    expect(doc.activeElement).toBe(doc.body);
    expect(root.classList.contains('is-mobile')).toBe(true);

    resize(container, 820, 1180);
    expect(root.classList.contains('is-mobile')).toBe(false);
    const button = root.querySelector('.oac-rail__btn') as FakeElement;
    button.focus();
    resize(container, 820, 520);
    expect(root.classList.contains('is-mobile')).toBe(true);
  });

  it('keeps holding while focus moves on to another text field in the widget', () => {
    const { container, doc, root } = make({}, 820, true, 1180);
    const field = root.querySelector('.oac-sym__input') as FakeElement;
    const next = doc.createElement('input');
    root.appendChild(next);
    field.focus();
    resize(container, 820, 520);
    // Tabbing from one field to the next keeps the keyboard up, so the switch still waits.
    next.focus();
    expect(root.classList.contains('is-mobile')).toBe(false);
    next.blur();
    expect(root.classList.contains('is-mobile')).toBe(true);
  });
});
