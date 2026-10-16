/**
 * README and ARCHITECTURE.md describe how the engine paints and how fast it
 * is, and hosts size dashboards on what they say. Several of those statements
 * had stopped being true, or had never been measured: a single canvas where
 * every pane has two, a time-scale operation queue nothing ever filled, one
 * study repainting only its own pane while every pane repainted, and "50k+
 * bars stay 60 fps". A review
 * found more of the same kind: order lines placed on the overlay canvas, a
 * GPU speed-up nobody had measured, SVG credited to one tier of three, and a
 * right-edge append said to leave the shared index alone.
 *
 * These checks tie each such statement to the code or to a measurement
 * record. Where the engine could reasonably change (how far a recompute or a
 * tick repaints, whether a glide runs on the render loop's frame), the check
 * is symmetric: the document must say what the chart does today, so changing
 * the engine without updating the document fails here just as surely as the
 * reverse.
 */
/// <reference types="vite/client" />
import { afterEach, describe, expect, it, vi } from 'vitest';
import readme from '../README.md?raw';
import architecture from '../ARCHITECTURE.md?raw';
import compatibility from '../COMPATIBILITY.md?raw';
import maskSource from '../src/core/invalidate-mask.ts?raw';
import enduranceFixture from '../scripts/fixtures/browser-endurance.html?raw';
import { Chart } from '../src/core/chart';
import { Pane } from '../src/core/pane';
import type { Bar } from '../src/model/bar';
import { DataLayer } from '../src/model/data-layer';
import { PriceLine } from '../src/primitives/price-line';
import { registerIndicator, type IndicatorAttachContext } from '../src/model/indicator-registry';
import { fakeDocument } from './helpers/fake-dom';

type Sources = Record<string, string>;
/** `import.meta.glob`, typed; the suite carries no Vite client globals beyond the raw imports. */
type Glob = { glob(pattern: string, options: { query: string; import: string; eager: true }): Sources };
// Vite expands each glob at transform time, so every pattern is a literal call.
const SOURCES = (import.meta as unknown as Glob).glob('../src/**/*.ts', { query: '?raw', import: 'default', eager: true });
/** The skills references, the docs folder and the website docs: prose a host reads. */
const GUIDES: Sources = {
  ...(import.meta as unknown as Glob).glob('../.github/skills/**/*.md', { query: '?raw', import: 'default', eager: true }),
  ...(import.meta as unknown as Glob).glob('../docs/*.md', { query: '?raw', import: 'default', eager: true }),
  ...(import.meta as unknown as Glob).glob('../website/pages/docs/*.mdx', { query: '?raw', import: 'default', eager: true }),
};

const DOCS: Readonly<Record<string, string>> = { 'README.md': readme, 'ARCHITECTURE.md': architecture };

/**
 * The units a reader takes one claim from: a table row, a list item, or a
 * paragraph. Splitting a table into rows matters: a measurement cited in one
 * row must not vouch for a figure in another.
 */
function statements(markdown: string): string[] {
  const out: string[] = [];
  for (const block of markdown.split(/\n\s*\n/)) {
    let current: string | null = null;
    for (const line of block.split('\n')) {
      if (current === null || /^\s*(?:\||[-*] |\d+\. |>)/.test(line)) {
        if (current !== null) out.push(current);
        current = line;
      } else {
        current += `\n${line}`;
      }
    }
    if (current !== null) out.push(current);
  }
  return out;
}

/** A frame rate, a percentile, a duration, or a bar count quoted as a workload. */
const PERFORMANCE_FIGURE = /\b\d+(?:\.\d+)?\s*fps\b|\bframes? per second\b|\b\d+(?:\.\d+)?k\+?[-\s]bars?\b|\b\d{1,3}(?:,\d{3})+\s+bars?\b|\b\d+(?:\.\d+)?\s?ms\b|\bp9[59]\b/i;

/** A record someone can rerun: the harness, its documentation or a bench script. */
const MEASUREMENT = /scripts\/browser-endurance\.mjs|docs\/browser-endurance\.md|scripts\/(?:bench-indicators|soak)\.mjs|npm run (?:bench|soak|endurance:browser)\b/;

/**
 * A figure about frames or pointer latency. Only the browser harness measures
 * those, so a bench or soak script in the same paragraph does not vouch for one.
 */
const FRAME_FIGURE = /\bfps\b|\bframes? per second\b|\bframe[- ](?:interval|time|rate)s?\b|\bp9[59]\b|\bpointer (?:latency|p9[59])\b/i;
const FRAME_RECORD = /scripts\/browser-endurance\.mjs|docs\/browser-endurance\.md/;

/** The statements in `markdown` that quote a performance figure no fitting record backs. */
function unmeasuredFigures(markdown: string): string[] {
  return statements(markdown).filter(s => PERFORMANCE_FIGURE.test(s) && !(FRAME_FIGURE.test(s) ? FRAME_RECORD : MEASUREMENT).test(s));
}

describe('performance figures', () => {
  it.each(Object.keys(DOCS))('%s quotes none without the record it was measured in', (name) => {
    expect(unmeasuredFigures(DOCS[name])).toEqual([]);
  });

  it('counts durations and written-out bar counts, and holds a frame figure to the harness that measures frames', () => {
    expect(unmeasuredFigures('The series pass holds 60 fps at 50k bars; see `npm run bench`.')).toHaveLength(1);
    expect(unmeasuredFigures('A frame-interval p95 of 17 ms (`npm run soak`).')).toHaveLength(1);
    expect(unmeasuredFigures('A recompute takes 12 ms at 10,000 bars.')).toHaveLength(1);
    expect(unmeasuredFigures('Frame p95 is 17 ms at 2,000 bars (docs/browser-endurance.md).')).toEqual([]);
    expect(unmeasuredFigures('RSI over 10,000 bars takes 3 ms (`npm run bench`).')).toEqual([]);
  });
});

/** Wording that claims a speed, which only a measurement can back. */
const SPEED_WORDING = /\b(?:fast(?:er|est)?|slow(?:er|est)?|speed(?:s|-?ups?)?|accelerat\w*|quick(?:er|ly)?|hot path|throughput)\b/i;

/** A statement about the GPU backend. */
const GPU_BACKEND = /webgl|\bgpu\b|renderer: 'auto'/i;

describe('the GPU backend', () => {
  it('is called faster than the 2D path nowhere, because no record measures it', () => {
    // The browser harness pins its charts to Canvas2D. Once it can run the GPU
    // backend, a speed statement that cites it is allowed again.
    const measured = /renderer:\s*'(?:webgl2|auto)'/.test(enduranceFixture);
    const docs: Sources = { 'README.md': readme, 'ARCHITECTURE.md': architecture, 'COMPATIBILITY.md': compatibility, ...GUIDES };
    expect(Object.keys(GUIDES).length).toBeGreaterThan(50);
    const claims = Object.entries(docs)
      .filter(([name]) => !name.endsWith('/release-notes.mdx'))
      .flatMap(([name, text]) => statements(text)
        .filter(s => GPU_BACKEND.test(s) && SPEED_WORDING.test(s) && !(measured && FRAME_RECORD.test(s)))
        .map(s => `${name}: ${s}`));
    expect(claims).toEqual([]);
  });
});

describe('the canvas layout', () => {
  const words = ['no', 'one', 'two', 'three', 'four'];

  it('the README counts the canvases each pane really creates', () => {
    const chart = new Chart(fakeDocument().createElement('div'), {
      document: fakeDocument(), pixelRatio: () => 1, shortcuts: false,
    });
    chart.addSeries('line', { paneIndex: 1 });
    expect(chart.panes()).toHaveLength(2);
    const counts = chart.panes().map(pane =>
      (pane.element as unknown as { children: { tagName?: string }[] }).children.filter(c => c.tagName === 'CANVAS').length);
    chart.destroy();
    expect(new Set(counts).size).toBe(1);
    expect(readme).not.toMatch(/single[- ]canvas/i);
    expect(readme).toContain(`${words[counts[0]]} canvases per pane`);
  });

  it('ARCHITECTURE.md draws no separate axis canvases, because the axes paint on the pane canvas', () => {
    expect(architecture).not.toMatch(/\b(?:left|right|time)-axis canvas\b/i);
    expect(architecture).not.toMatch(/axes as separate widgets/i);
    expect(architecture).not.toMatch(/\baxis widgets?\b/i);
  });

  it('the README names every tier that builds SVG markup', () => {
    const tiers = new Set(Object.entries(SOURCES)
      .filter(([, text]) => /<svg[\s>]|http:\/\/www\.w3\.org\/2000\/svg/.test(text))
      .map(([path]) => path.split('/')[2]));
    expect(tiers.size).toBeGreaterThan(1);
    const where = statements(readme).find(s => /\bSVG appears\b/.test(s)) ?? '';
    expect(where).not.toBe('');
    // The render directory's SVG is the vector export.
    const unnamed = [...tiers].filter(tier => tier === 'render' ? !where.includes('exportSVG') : !new RegExp(`\\b${tier}\\b`).test(where));
    expect(unnamed).toEqual([]);
  });
});

describe('what the overlay canvas carries', () => {
  afterEach(() => { vi.restoreAllMocks(); });

  it('ARCHITECTURE.md and README put order lines on the overlay exactly when dragging one leaves the base canvas alone', () => {
    const document = fakeDocument();
    const chart = new Chart(document.createElement('div'), {
      document, pixelRatio: () => 1, shortcuts: false,
      raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    });
    chart.applySize(800, 600);
    chart.addSeries('candlestick').setData(Array.from({ length: 50 }, (_, i) => ({
      time: 1_700_000_000 + i * 60, open: 100 + i, high: 101 + i, low: 99 + i, close: 100 + i,
    })));
    // The trading layer's own drag path: the chart hands it the callbacks.
    let onDrag: ((id: string, price: number, time: number) => void) | undefined;
    vi.spyOn(chart, 'subscribeDrag').mockImplementation((drag) => { onDrag = drag; return () => {}; });
    chart.trading.setOrders([{ id: 'o1', type: 'limit', side: 'buy', price: 120, size: 1 }]);
    expect(onDrag).toBeDefined();
    const moved = vi.spyOn(PriceLine.prototype, 'setPrice');
    const spy = vi.spyOn(Pane.prototype, 'paintBase');
    onDrag?.('ord:o1', 121, 1_700_000_000);
    const baseRepainted = spy.mock.calls.length > 0;
    spy.mockRestore();
    chart.destroy();
    expect(moved).toHaveBeenCalledWith(121);

    const topBullet = /^- \*\*top canvas\*\*.*$/m.exec(architecture)?.[0] ?? '';
    expect(topBullet).not.toBe('');
    expect(/order lines/i.test(topBullet)).toBe(!baseRepainted);
    expect(/overlay canvas for[^.]*\bdragged\b/i.test(readme)).toBe(!baseRepainted);
  });
});

describe('the shared index', () => {
  it('ARCHITECTURE.md says what a right-edge append does to it, and the DataLayer agrees', () => {
    const layer = new DataLayer();
    const id = layer.createSeries();
    const bars: Bar[] = Array.from({ length: 3 }, (_, i) => ({ time: 1_700_000_000 + i * 60, open: 1, high: 2, low: 0, close: 1 }));
    layer.setSeriesData(id, bars);
    const rebuild = vi.spyOn(layer as unknown as { _rebuild(): void }, '_rebuild');
    layer.update(id, { ...bars[2], close: 1.5 });
    const afterReplace = layer.length;
    layer.update(id, { ...bars[2], time: bars[2].time + 60 });
    const grew = layer.length === afterReplace + 1;
    const rebuilt = rebuild.mock.calls.length > 0;
    rebuild.mockRestore();

    const asShipped = /\*\*As shipped\*\*[^\n]*/.exec(architecture)?.[0] ?? '';
    expect(asShipped).not.toBe('');
    expect(/appending past the right edge leaves it/i.test(asShipped)).toBe(!grew);
    expect(/appending past the right edge adds one time/i.test(asShipped)).toBe(grew);
    expect(/without a rebuild/i.test(asShipped)).toBe(!rebuilt);
  });
});

/** Source files outside the mask that read its time-scale queue. */
const queueReaders = (): string[] => Object.entries(SOURCES)
  .filter(([path, text]) => !path.endsWith('/invalidate-mask.ts') && /\.timeScaleOps\(\)/.test(text))
  .map(([path]) => path);

describe('the invalidation mask', () => {
  it('ARCHITECTURE.md puts a time-scale queue in the mask it sketches exactly when the frame reads one', () => {
    const read = queueReaders().length > 0;
    const sketch = /class InvalidateMask \{[\s\S]*?\n\}/.exec(architecture)?.[0] ?? '';
    expect(sketch).not.toBe('');
    expect(/timeScaleOps/.test(sketch)).toBe(read);
    expect(/mask is a[^.]*queue of time-scale operations/i.test(architecture)).toBe(read);
    // An operation the document names is one the mask declares.
    const declared = new Set([...maskSource.matchAll(/type: '(\w+)'/g)].map(m => m[1]));
    expect(declared.size).toBeGreaterThan(0);
    const named = /type TimeScaleOp =[\s\S]*?\n\n/.exec(architecture)?.[0] ?? '';
    expect([...named.matchAll(/type: '(\w+)'/g)].map(m => m[1]).filter(op => !declared.has(op))).toEqual([]);
  });

  it('ARCHITECTURE.md says whether anything queues a time-scale operation, and the code agrees', () => {
    const callers = Object.entries(SOURCES)
      .filter(([path, text]) => !path.endsWith('/invalidate-mask.ts') && /\.addTimeScaleOp\(/.test(text));
    expect(Object.keys(SOURCES).length).toBeGreaterThan(100);
    const saysUnused = /`addTimeScaleOp` has no caller/.test(architecture);
    expect(saysUnused).toBe(callers.length === 0);
  });

  it('the TimeScaleOp declaration says the queue is applied only when something reads it', () => {
    const readers = queueReaders();
    const doc = /\/\*\*((?:(?!\*\/)[\s\S])*)\*\/\s*export type TimeScaleOp\b/.exec(maskSource)?.[1] ?? '';
    expect(doc).not.toBe('');
    expect(/applied to the shared time scale/i.test(doc)).toBe(readers.length > 0);
    // A queue nothing reads is a control with nothing behind it: it is
    // deprecated for the next major, and the tag says so where editors show it.
    expect(/@deprecated Removed in \d+\.0\.0/.test(doc)).toBe(readers.length === 0);
  });
});

/**
 * Wording that confines a recompute or a tick to some of the panes. The
 * shapes include the ones ARCHITECTURE.md used while the claim was false, so
 * while the chart repaints every pane, bringing one back fails here even
 * beside a sentence that says the opposite.
 */
const LOCAL_REPAINT = /(?:recomput\w*|finishing a calc|live tick)[^.|]*?(?:must not repaint|(?:is|are) not repainted|aren't repainted|\bentry only\b|\bis local\b|repaints only|only (?:its|the study's) own pane)/i;

const localRepaintClaims = (markdown: string): string[] => statements(markdown).filter(s => LOCAL_REPAINT.test(s));

/** What each document says when a study recompute or a replacing tick leaves an unrelated pane alone. */
const RECOMPUTE_LOCAL = /a study recompute repaints only the panes its output lands on/i;
const TICK_LOCAL: Readonly<Record<string, RegExp>> = {
  'ARCHITECTURE.md': /a live tick that replaces the forming bar[^.]*repaints only its own series' pane/i,
  'README.md': /a live tick repaints the price pane and the panes of the studies computed from it/i,
};
/**
 * What each document says about the wall-clock readings keeping a pane
 * repainting on a pane-scoped write: the corner clock on the bottom pane, and
 * the bar countdown in the last-price tag of each pane with a price series.
 */
const CLOCK_REPAINT: Readonly<Record<'sessionClock' | 'barCountdown', Readonly<Record<string, RegExp>>>> = {
  sessionClock: {
    'ARCHITECTURE.md': /except while the corner clock is on \(`axisChrome\.sessionClock`\)[^.]*each such write also repaints that pane/i,
    'README.md': /the bottom pane repaints with them while the corner clock is on/i,
  },
  barCountdown: {
    'ARCHITECTURE.md': /the bar countdown \(`axisChrome\.barCountdown`\)[^.]*each such write also repaints every pane with a price series/i,
    'README.md': /every pane with a price series while the bar countdown is on/i,
  },
};

describe('how far a repaint reaches', () => {
  afterEach(() => { vi.restoreAllMocks(); });
  let sequence = 0;

  /**
   * A price series, a study computed from it in a pane of its own, and a
   * line series of the host's in a third pane that nothing here writes to,
   * painting synchronously.
   */
  function mount(): { chart: Chart; tick: () => void; recompute: () => void } {
    const document = fakeDocument();
    const chart = new Chart(document.createElement('div'), {
      document, pixelRatio: () => 1, shortcuts: false,
      raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    });
    chart.applySize(800, 600);
    const bars: Bar[] = Array.from({ length: 50 }, (_, i) => ({
      time: 1_700_000_000 + i * 60, open: 100 + i, high: 101 + i, low: 99 + i, close: 100 + i,
    }));
    const source = chart.addSeries('candlestick');
    source.setData(bars);
    let attachment!: IndicatorAttachContext;
    const id = `docs-claims-probe-${sequence++}`;
    registerIndicator({
      id, name: 'Probe', placement: 'pane', inputs: [],
      plots: [{ key: 'v', type: 'line', title: 'Value' }],
      calc: input => ({ v: input.map(bar => bar.close) }),
      attach: context => { attachment = context; },
    });
    chart.addIndicator(id);
    chart.addSeries('line', { paneIndex: 2 }).setData(bars.map(bar => ({ time: bar.time, value: bar.close })));
    expect(chart.panes()).toHaveLength(3);
    const last = bars[bars.length - 1];
    return {
      chart,
      tick: () => source.update({ ...last, close: last.close + 0.5 }),
      recompute: () => attachment.requestRecompute(),
    };
  }

  /** Which panes repainted their base canvas while `act` ran. */
  function repainted(chart: Chart, act: () => void): boolean[] {
    const spy = vi.spyOn(Pane.prototype, 'paintBase');
    act();
    const painted = new Set(spy.mock.contexts);
    spy.mockRestore();
    return chart.panes().map(pane => painted.has(pane));
  }

  it('an indicator recompute: the documents confine it to the study panes exactly when the unrelated pane is left alone', () => {
    const { chart, recompute } = mount();
    const [pricePane, studyPane, otherPane] = repainted(chart, recompute);
    chart.destroy();
    expect(studyPane).toBe(true);
    // The study sends nothing to the candles, so the price pane has nothing new either.
    expect(pricePane).toBe(otherPane);
    expect(/an indicator recompute repaints every pane/i.test(architecture)).toBe(otherPane);
    for (const [name, text] of Object.entries(DOCS)) {
      expect(RECOMPUTE_LOCAL.test(text), name).toBe(!otherPane);
      if (otherPane) expect(localRepaintClaims(text), name).toEqual([]);
    }
  });

  it('a live tick: the documents confine it to the panes it changes exactly when the unrelated pane is left alone', () => {
    const { chart, tick } = mount();
    const [pricePane, studyPane, otherPane] = repainted(chart, tick);
    chart.destroy();
    expect(pricePane).toBe(true);
    // The study is computed from the ticking series, so it has a new value to show.
    expect(studyPane).toBe(true);
    expect(/a live tick repaints every pane/i.test(architecture)).toBe(otherPane);
    for (const [name, text] of Object.entries(DOCS)) {
      expect(TICK_LOCAL[name].test(text), name).toBe(!otherPane);
      if (otherPane) expect(localRepaintClaims(text), name).toEqual([]);
    }
  });

  for (const reading of ['sessionClock', 'barCountdown'] as const) {
    it(`${reading}: the documents say it keeps an unrelated pane repainting exactly when it does`, () => {
      const plain = mount();
      const without = repainted(plain.chart, plain.tick)[2];
      plain.chart.destroy();
      const on = mount();
      on.chart.setAxisChromeOptions({ [reading]: true });
      const withReading = repainted(on.chart, on.tick)[2];
      on.chart.destroy();
      // The unrelated pane is the bottom one, where the clock is drawn, and it
      // holds a line, a price series whose last-price tag carries the countdown.
      const readingOnly = withReading && !without;
      for (const [name, text] of Object.entries(DOCS)) expect(CLOCK_REPAINT[reading][name].test(text), name).toBe(readingOnly);
    });
  }

  it('recognises the pane-local wording the document used while it was false', () => {
    for (const old of [
      '| **Per-pane invalidation mask** | one indicator pane recomputing must not repaint the others. |',
      '- **Per-pane invalidation**: recomputing the RSI pane raises *its* entry only; the price pane is not repainted.',
      'An indicator finishing a calc, or one pane\'s autoscale changing, is local.',
    ]) expect(localRepaintClaims(old), old).toHaveLength(1);
    expect(localRepaintClaims('A study recompute and a live tick still repaint every pane, not only the study\'s own.')).toEqual([]);
  });
});

describe('the animation loop', () => {
  afterEach(() => { vi.restoreAllMocks(); });

  /**
   * Run a kinetic glide frame by frame. It is on the render loop's frame when
   * no frame asks for more than one callback and every frame that moved the
   * view painted the offset it moved to.
   */
  function glideOnTheFrame(): boolean {
    let now = 0;
    let id = 0;
    let requests = 0;
    const queue = new Map<number, () => void>();
    const document = fakeDocument();
    const chart = new Chart(document.createElement('div'), {
      document, pixelRatio: () => 1, shortcuts: false, now: () => now,
      raf: { schedule: cb => { requests++; queue.set(++id, cb); return id; }, cancel: key => { queue.delete(key); } },
    });
    chart.applySize(800, 600);
    chart.addSeries('candlestick').setData(Array.from({ length: 300 }, (_, i) => ({
      time: 1_700_000_000 + i * 60, open: 100, high: 101, low: 99, close: 100,
    })));
    const frame = (): number => {
      now += 16;
      const before = requests;
      for (const [key, cb] of [...queue.entries()]) if (queue.delete(key)) cb();
      return requests - before;
    };
    for (let i = 0; i < 50 && queue.size > 0; i++) frame();
    const pricePane = chart.panes()[0];
    let painted: number | null = null;
    vi.spyOn(Pane.prototype, 'paintBase').mockImplementation(function (this: Pane) {
      if (this === pricePane) painted = chart.timeScale.rightOffset;
    });
    (chart as unknown as { _startKinetic(v: number): void })._startKinetic(1.5);
    let one = true;
    let frames = 0;
    for (let last = chart.timeScale.rightOffset; frames < 200 && queue.size > 0; frames++) {
      painted = null;
      if (frame() > 1) one = false;
      const offset = chart.timeScale.rightOffset;
      if (offset !== last && painted !== offset) one = false;
      last = offset;
    }
    chart.destroy();
    expect(frames).toBeGreaterThan(10);
    return one;
  }

  it('ARCHITECTURE.md and README say a glide steps inside the frame exactly when it does', () => {
    const one = glideOnTheFrame();
    expect(/\*\*Glides step inside the frame\.\*\*/.test(architecture)).toBe(one);
    expect(/each frame paints the step it made/i.test(architecture)).toBe(one);
    expect(/each frame paints the step it made/i.test(readme)).toBe(one);
    // The wording the document used while each glide ran its own frames.
    expect(/schedule their own animation frames|run their own animation-frame loop|paint follows one frame behind/i.test(architecture)).toBe(!one);
  });
});
