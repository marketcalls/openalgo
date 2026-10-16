import { describe, it, expect } from 'vitest';
import { MarketProfile } from '../src/profile/market-profile-primitive';
import { computeMarketProfile } from '../src/profile/market-profile';
import { istStringToUtcSeconds } from '../src/feed/time';
import type { Bar } from '../src/model/bar';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';

const bar = (time: number, low: number, high: number, volume = 100): Bar => ({
  time, open: low, high, low, close: high, volume,
});

function makeResult() {
  const t0 = istStringToUtcSeconds('2024-01-15 09:15:00');
  const bars = [bar(t0, 100, 110), bar(t0 + 1800, 105, 110)];
  return { result: computeMarketProfile(bars, { tickSize: 1, session: 'day', blockMinutes: 30 }), t0, bars };
}

function recorder() {
  const calls = { fillText: 0, fillRect: 0, stroke: 0, drawImage: 0 };
  const ctx = {
    canvas: {},
    globalAlpha: 1, fillStyle: '', strokeStyle: '', lineWidth: 1, font: '', textAlign: '', textBaseline: '',
    save() {}, restore() {},
    beginPath() {}, moveTo() {}, lineTo() {},
    stroke() { calls.stroke++; },
    fillRect() { calls.fillRect++; },
    fillText() { calls.fillText++; },
  } as unknown as CanvasRenderingContext2D;
  return { ctx, calls };
}

function makeRc(startTime: number, endTime: number): PrimitiveRenderContext {
  return {
    dpr: 2,
    plotWidth: 600, plotHeight: 300, priceAxisWidth: 60,
    timeScale: { indexToX: (i: number) => 100 + i * 40 },
    priceScale: { priceToY: (p: number) => 400 - p, format: (p: number) => p.toFixed(2) },
    dataLayer: { timeToIndex: (t: number) => (t === startTime ? 0 : t === endTime ? 5 : 5) },
    theme: {},
  } as unknown as PrimitiveRenderContext;
}

describe('MarketProfile primitive', () => {
  it('renders letters and POC/VA lines without throwing', () => {
    const { result, t0 } = makeResult();
    const mp = new MarketProfile(result);
    const { ctx, calls } = recorder();
    mp.draw(ctx, makeRc(t0, t0 + 1800));
    expect(calls.fillText).toBeGreaterThan(0); // TPO letters + labels
    expect(calls.stroke).toBeGreaterThan(0);   // POC / VA / IB lines
  });

  it('draws solid blocks when letters are disabled', () => {
    const { result, t0 } = makeResult();
    const mp = new MarketProfile(result, { blockDisplay: 'blocks', showValueAreaLabels: false, showPocLabel: false });
    const { ctx, calls } = recorder();
    mp.draw(ctx, makeRc(t0, t0 + 1800));
    expect(calls.fillRect).toBeGreaterThan(0);
  });

  it('paints period blocks in the base colour when the period palette is empty', () => {
    // A palette with no colours used to hand the canvas `undefined`, which a
    // real canvas ignores, so the blocks took whatever fill came before them.
    const { result, t0 } = makeResult();
    const blocksOnly = {
      blockDisplay: 'blocks', showValueAreaLabels: false, showPocLabel: false, showSessionLabel: false,
      showPoc: false, showValueArea: false, fillValueArea: false, showInitialBalance: false,
      showSinglePrints: false, showTails: false, colorMode: 'period', color: '#3a6ea5',
    } as const;
    const fills = (periodColors: readonly string[]): unknown[] => {
      const { ctx } = recorder();
      const seen: unknown[] = [];
      ctx.fillRect = () => { seen.push(ctx.fillStyle); };
      new MarketProfile(result, { ...blocksOnly, periodColors }).draw(ctx, makeRc(t0, t0 + 1800));
      return [...new Set(seen)];
    };
    expect(fills(['#aa3322', '#22aa33'])).toEqual(['#aa3322', '#22aa33']);
    expect(fills([])).toEqual(['#3a6ea5']);
  });

  it('reports its price extent via autoscaleInfo', () => {
    const { result } = makeResult();
    const mp = new MarketProfile(result);
    expect(mp.autoscaleInfo()).toEqual({ min: 100, max: 110 });
  });

  it('is a no-op with no data', () => {
    const mp = new MarketProfile(null);
    const { ctx, calls } = recorder();
    mp.draw(ctx, makeRc(0, 1));
    expect(calls.fillText + calls.fillRect + calls.stroke).toBe(0);
    expect(mp.autoscaleInfo()).toBeNull();
  });
});

/** Render context whose price scale can be zoomed, so row height is testable. */
function makeScaledRc(startTime: number, endTime: number, pxPerPrice: number): PrimitiveRenderContext {
  return {
    dpr: 2,
    plotWidth: 600, plotHeight: 300, priceAxisWidth: 60,
    timeScale: { indexToX: (i: number) => 100 + i * 40 },
    priceScale: { priceToY: (p: number) => 400 - p * pxPerPrice, format: (p: number) => p.toFixed(2) },
    dataLayer: { timeToIndex: (t: number) => (t === startTime ? 0 : t === endTime ? 5 : 5) },
    theme: {},
  } as unknown as PrimitiveRenderContext;
}

/** Records the alpha each glyph was painted at, so a fade is observable. */
function alphaRecorder() {
  const letterAlphas: number[] = [];
  const rectAlphas: number[] = [];
  const ctx: Record<string, unknown> = {
    canvas: {},
    globalAlpha: 1, fillStyle: '', strokeStyle: '', lineWidth: 1, font: '', textAlign: '', textBaseline: '',
    save() {}, restore() {},
    beginPath() {}, rect() {}, clip() {}, moveTo() {}, lineTo() {}, stroke() {}, setLineDash() {},
    fillRect() { rectAlphas.push(ctx.globalAlpha as number); },
    fillText() { letterAlphas.push(ctx.globalAlpha as number); },
  };
  return { ctx: ctx as unknown as CanvasRenderingContext2D, letterAlphas, rectAlphas };
}
describe('TPO letter / brick auto transition', () => {
  // Letters and labels both call fillText, so compare against a labels-off run.
  const quiet = { showValueAreaLabels: false, showPocLabel: false, showSessionLabel: false } as const;

  it('draws letters when rows are tall enough', () => {
    const { result, t0 } = makeResult();
    const mp = new MarketProfile(result, quiet);
    const { ctx, letterAlphas } = alphaRecorder();
    mp.draw(ctx, makeScaledRc(t0, t0 + 1800, 20)); // 20px per price unit -> tall rows
    expect(letterAlphas.length).toBeGreaterThan(0);
    expect(Math.max(...letterAlphas)).toBeGreaterThan(0.9);
  });

  it('drops to bricks when rows get too short for a glyph', () => {
    const { result, t0 } = makeResult();
    const mp = new MarketProfile(result, quiet);
    const { ctx, letterAlphas, rectAlphas } = alphaRecorder();
    mp.draw(ctx, makeScaledRc(t0, t0 + 1800, 1)); // 1px per price unit -> tiny rows
    expect(letterAlphas).toHaveLength(0);   // no glyphs at all
    expect(rectAlphas.length).toBeGreaterThan(0); // but the blocks still render
  });

  it('crossfades through the threshold instead of snapping', () => {
    const { result, t0 } = makeResult();
    const mp = new MarketProfile(result, { ...quiet, minLetterHeight: 7, letterFade: 4 });
    const { ctx, letterAlphas } = alphaRecorder();
    // Row height ~9px sits inside the 7..11px fade band.
    mp.draw(ctx, makeScaledRc(t0, t0 + 1800, 9));
    expect(letterAlphas.length).toBeGreaterThan(0);
    const a = Math.max(...letterAlphas);
    expect(a).toBeGreaterThan(0);
    expect(a).toBeLessThan(1);   // partially faded, not fully on
  });

  it('explicit blockDisplay overrides the auto behaviour', () => {
    const { result, t0 } = makeResult();
    // 'letters' forces glyphs even at a row height auto would call too short.
    const forced = new MarketProfile(result, { ...quiet, blockDisplay: 'letters' });
    const r1 = alphaRecorder();
    forced.draw(r1.ctx, makeScaledRc(t0, t0 + 1800, 1));
    expect(r1.letterAlphas.length).toBeGreaterThan(0);

    // 'blocks' suppresses them even when there is plenty of room.
    const blocks = new MarketProfile(result, { ...quiet, blockDisplay: 'blocks' });
    const r2 = alphaRecorder();
    blocks.draw(r2.ctx, makeScaledRc(t0, t0 + 1800, 20));
    expect(r2.letterAlphas).toHaveLength(0);
    expect(r2.rectAlphas.length).toBeGreaterThan(0);
  });
});

describe('MarketProfile hit-testing', () => {
  it('maps a pointer back to the session row under it', () => {
    const { result, t0 } = makeResult();
    const mp = new MarketProfile(result);
    const { ctx } = alphaRecorder();
    const rc = makeScaledRc(t0, t0 + 1800, 20);
    mp.draw(ctx, rc);                       // hit-testing needs drawn geometry
    const x = 150;                          // inside the session box (102..298)
    const hit = mp.hitTest(x, 50);
    expect(hit?.externalId).toBe('mp:0');
    const hover = mp.hoverAt(x, rc.priceScale.priceToY(110));
    expect(hover?.price).toBe(110);
    expect(hover?.level.letters).toBe('AB');
    expect(mp.hitTest(-500, 50)).toBeNull();
  });
});

describe('compact TPO text', () => {
  const quiet = {
    blockDisplay: 'compact',
    showValueAreaLabels: false, showPocLabel: false, showSessionLabel: false,
    showPoc: false, showValueArea: false, fillValueArea: false,
    showInitialBalance: false, showSinglePrints: false, showTails: false,
    opacity: 1,
  } as const;

  function pixels() {
    const rects: { x: number; y: number; w: number; h: number; alpha: number }[] = [];
    const { ctx, letterAlphas } = alphaRecorder();
    ctx.fillRect = (x, y, w, h) => rects.push({ x, y, w, h, alpha: ctx.globalAlpha });
    return { ctx, rects, letterAlphas };
  }

  it.each([1, 1.25, 2])('retains opaque, pixel-aligned glyphs in 5px rows at DPR %s', (dpr) => {
    const { result, t0 } = makeResult();
    const mp = new MarketProfile(result, quiet);
    const rc = makeScaledRc(t0, t0 + 1800, 5);
    Object.assign(rc, { dpr, priceScale: { priceToY: (p: number) => 60.3 + (110 - p) * 5 } });
    const { ctx, rects, letterAlphas } = pixels();
    mp.draw(ctx, rc);
    expect(letterAlphas).toHaveLength(0); // Compact glyphs do not depend on browser font rasterization.
    expect(rects.length).toBeGreaterThan(result.sessions[0].levels.reduce((n, l) => n + l.count, 0));
    for (const r of rects) {
      expect([r.x, r.y, r.w, r.h].every(Number.isInteger)).toBe(true);
      expect(r.alpha).toBe(1); // Includes levels outside the value area.
    }
    expect(mp.hoverAt(150, rc.priceScale.priceToY(110))?.level.letters).toBe('AB');
    expect(mp.autoscaleInfo()).toEqual({ min: 100, max: 110 });
  });

  it('keeps volume numbers below the legacy 7 CSS pixel cutoff', () => {
    const { result, t0 } = makeResult();
    const rc = makeScaledRc(t0, t0 + 1800, 5);
    Object.assign(rc, { priceScale: { priceToY: (p: number) => 60 + (110 - p) * 5 } });
    const mp = new MarketProfile(result, { ...quiet, showVolumeProfile: true });
    const before = pixels();
    mp.draw(before.ctx, rc);
    mp.setOptions({ showVolumeValues: true });
    const after = pixels();
    mp.draw(after.ctx, rc);
    expect(after.rects.length).toBeGreaterThan(before.rects.length);
  });

  it('preserves heat variation when the host explicitly selects count colouring', () => {
    const { result, t0 } = makeResult();
    const rc = makeScaledRc(t0, t0 + 1800, 5);
    Object.assign(rc, { priceScale: { priceToY: (p: number) => 60 + (110 - p) * 5 } });
    const mp = new MarketProfile(result, { ...quiet, colorMode: 'count' });
    const { ctx, rects } = pixels();
    mp.draw(ctx, rc);
    expect(new Set(rects.map((r) => r.alpha)).size).toBeGreaterThan(1);
  });

  it('does not paint rows outside the viewport in compact mode', () => {
    const { result, t0 } = makeResult();
    const mp = new MarketProfile(result, quiet);
    const rc = makeScaledRc(t0, t0 + 1800, 5);
    Object.assign(rc, { priceScale: { priceToY: (p: number) => -100 + (110 - p) * 5 } });
    const { ctx, rects } = pixels();
    mp.draw(ctx, rc);
    expect(rects).toHaveLength(0);
  });
});

describe('per-session split overrides', () => {
  function twoDays() {
    const t0 = istStringToUtcSeconds('2024-01-15 09:15:00');
    // Each session has a row visited only by B, making split vs packed visible.
    const bars = [bar(t0, 100, 100), bar(t0 + 1800, 101, 101),
      bar(t0 + 86400, 100, 100), bar(t0 + 88200, 101, 101)];
    const options = { tickSize: 1, session: 'day', blockMinutes: 30 } as const;
    return { t0, bars, options, result: computeMarketProfile(bars, options) };
  }

  it('splits and unsplits one day without moving the neighbouring profile', () => {
    const { t0, result } = twoDays();
    const original = JSON.stringify(result);
    const mp = new MarketProfile(result, {
      blockDisplay: 'letters', profileSpacing: 0, letterWidth: 8,
      showValueAreaLabels: false, showPocLabel: false, showSessionLabel: false,
    });
    const rc = makeScaledRc(t0, t0 + 1800, 10);
    Object.assign(rc, {
      dpr: 1,
      timeScale: { indexToX: (i: number) => 50 + i * 50 },
      dataLayer: { timeToIndex: (t: number) => [t0, t0 + 1800, t0 + 86400, t0 + 88200].indexOf(t) },
    });
    const { ctx } = alphaRecorder();
    let xs: number[] = [];
    ctx.fillText = (text, x) => { if (text === 'B') xs.push(x); };
    mp.draw(ctx, rc);
    expect(xs).toEqual([54, 154]);
    expect(mp.setSessionSplit(0, true)).toBe(true);
    xs = [];
    mp.draw(ctx, rc);
    expect(xs).toEqual([62, 154]);
    expect(mp.isSessionSplit(1)).toBe(false);
    mp.setSessionSplit(0, false);
    xs = [];
    mp.draw(ctx, rc);
    expect(xs).toEqual([54, 154]);
    expect(JSON.stringify(result)).toBe(original);
  });

  it('keeps a day override when earlier history shifts its index and first bar', () => {
    const { t0, bars, options, result } = twoDays();
    const mp = new MarketProfile(result);
    mp.setSessionSplit(0, true);
    mp.setOptions({ colorMode: 'valueArea', blockDisplay: 'compact' });
    mp.setData(computeMarketProfile([
      bar(t0 - 86400, 100, 101), bar(t0 - 300, 99, 101), ...bars,
    ], { ...options, rowTicks: 2 }));
    expect([0, 1, 2].map((i) => mp.isSessionSplit(i))).toEqual([false, true, false]);
  });

  it('allows unsplitting one day under a split-all default and resetting it', () => {
    const { result } = twoDays();
    const mp = new MarketProfile(result, { split: true });
    mp.setSessionSplit(1, false);
    expect([0, 1].map((i) => mp.isSessionSplit(i))).toEqual([true, false]);
    mp.setSessionSplit(1, null);
    expect(mp.isSessionSplit(1)).toBe(true);
    mp.setSessionSplit(1, false);
    mp.setOptions({ split: true }); // Explicit global choice resets per-day overrides.
    expect([0, 1].map((i) => mp.isSessionSplit(i))).toEqual([true, true]);
  });

  it('rejects missing sessions without changing the display', () => {
    const { result } = twoDays();
    const mp = new MarketProfile(result);
    for (const index of [-1, 2, 0.5, NaN]) {
      expect(mp.setSessionSplit(index, true)).toBe(false);
      expect(mp.isSessionSplit(index)).toBe(false);
    }
    expect(mp.isSessionSplit(0)).toBe(false);
  });
});

describe('session open marker', () => {
  it.each([false, true])('keeps # in a narrow newest session (split=%s)', (split) => {
    const { result, t0 } = makeResult();
    const mp = new MarketProfile(result, {
      blockDisplay: 'letters', showSessionOpen: true, showLastPrice: true, split, profileSpacing: 0,
    });
    const rc = makeScaledRc(t0, t0 + 1800, 20);
    Object.assign(rc, {
      timeScale: { indexToX: (i: number) => 100 + i * 20 },
      dataLayer: { timeToIndex: (t: number) => t === t0 ? 0 : 1 },
    });
    const { ctx } = alphaRecorder();
    const marks: { text: string; x: number }[] = [];
    ctx.fillText = (text, x) => { if (text === 'o' || text === '#') marks.push({ text, x }); };
    mp.draw(ctx, rc);
    expect(marks.map((m) => m.text)).toEqual(['o', '#']);
    expect(Math.abs(marks[1].x - marks[0].x)).toBeGreaterThanOrEqual(6 * rc.dpr);
  });

  it('keeps # inside the plot for a one-bar newest session at the right edge', () => {
    const { bars, t0 } = makeResult();
    const mp = new MarketProfile(computeMarketProfile(bars.slice(0, 1), { tickSize: 1 }), {
      blockDisplay: 'letters', showLastPrice: true, profileSpacing: 0,
    });
    const rc = makeScaledRc(t0, t0, 20);
    Object.assign(rc, { timeScale: { indexToX: () => rc.plotWidth - 2 } });
    const { ctx } = alphaRecorder();
    const xs: number[] = [];
    ctx.fillText = (text, x) => { if (text === '#') xs.push(x); };
    mp.draw(ctx, rc);
    expect(xs).toHaveLength(1);
    expect(xs[0]).toBeLessThanOrEqual((rc.plotWidth - 3) * rc.dpr);
  });

  it('reserves space for o inside the first profile at the left plot edge', () => {
    const { result, t0 } = makeResult();
    const mp = new MarketProfile(result, {
      blockDisplay: 'letters', showSessionOpen: true, profileSpacing: 0,
    });
    const rc = makeScaledRc(t0, t0 + 1800, 20);
    Object.assign(rc, { timeScale: { indexToX: (i: number) => i * 200 } });
    const { ctx } = alphaRecorder();
    const xs: number[] = [];
    ctx.fillText = (text, x) => { if (text === 'o') xs.push(x); };
    mp.draw(ctx, rc);
    expect(xs).toHaveLength(1);
    expect(xs[0]).toBeGreaterThanOrEqual(3 * rc.dpr);
  });

  it('keeps the LTP marker clear of the optional TPO count column', () => {
    const { result, t0 } = makeResult();
    const mp = new MarketProfile(result, {
      blockDisplay: 'letters', showLastPrice: true, showTpoCounts: true,
    });
    const rc = makeScaledRc(t0, t0 + 1800, 20);
    const { ctx } = alphaRecorder();
    let markX = 0, countX = 0;
    ctx.fillText = (text, x) => {
      if (text === '#') markX = x;
      if (text === '2') countX = x;
    };
    mp.draw(ctx, rc);
    expect(markX).toBeGreaterThan(0);
    expect(countX - markX).toBeGreaterThanOrEqual(4 * rc.dpr);
  });

  it('places lowercase o at the opening price row in packed and split views', () => {
    const { t0, bars } = makeResult();
    bars[0].open = 103.4;
    const result = computeMarketProfile(bars, { tickSize: 1, rowTicks: 2 });
    const mp = new MarketProfile(result, {
      blockDisplay: 'letters', showSessionOpen: true, sessionOpenColor: '#ff0000',
    });
    const rc = makeScaledRc(t0, t0 + 1800, 20);
    const { ctx } = alphaRecorder();
    const marks: { x: number; y: number; color: string | CanvasGradient | CanvasPattern }[] = [];
    ctx.fillText = (text, x, y) => { if (text === 'o') marks.push({ x, y, color: ctx.fillStyle }); };
    mp.draw(ctx, rc);
    expect(marks).toHaveLength(1);
    expect(marks[0].y).toBe(rc.priceScale.priceToY(104) * rc.dpr); // The model buckets to the nearest row.
    expect(marks[0].color).toBe('#ff0000');
    mp.setSessionSplit(0, true);
    mp.draw(ctx, rc);
    expect(marks[1]).toEqual(marks[0]);
    mp.setOptions({ showSessionOpen: false });
    mp.draw(ctx, rc);
    expect(marks).toHaveLength(2);
  });

  it('shows # on the newest session only and moves it when that session updates', () => {
    const { t0, bars } = makeResult();
    const allBars = [...bars, bar(t0 + 86400, 100, 110), bar(t0 + 88200, 105, 109)];
    const mp = new MarketProfile(computeMarketProfile(allBars, { tickSize: 1 }), {
      blockDisplay: 'letters', showLastPrice: true,
    });
    const rc = makeScaledRc(t0, t0 + 88200, 20);
    Object.assign(rc, { dataLayer: { timeToIndex: (t: number) => allBars.findIndex((b) => b.time === t) } });
    const { ctx } = alphaRecorder();
    const marks: number[] = [];
    ctx.fillText = (text, _x, y) => { if (text === '#') marks.push(y); };
    mp.draw(ctx, rc);
    expect(marks).toEqual([rc.priceScale.priceToY(109) * rc.dpr]);
    allBars[3].close = 106;
    mp.setData(computeMarketProfile(allBars, { tickSize: 1 }));
    marks.length = 0;
    mp.draw(ctx, rc);
    expect(marks).toEqual([rc.priceScale.priceToY(106) * rc.dpr]);
  });
});
