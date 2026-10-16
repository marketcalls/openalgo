/**
 * Status-line switches on the pane legend: the Status line settings tab (logo,
 * title, market state, chart values, bar change, volume, last day change,
 * background) plus the last-value label control that lives on the Scales and
 * lines tab but is drawn by this row.
 *
 * Each test drives the primitive through the repo's recording canvas. The
 * shared recorder logs fillText coordinates but not the string, and every one
 * of these switches is about which strings survive, so the string is captured
 * alongside.
 */
import { describe, it, expect } from 'vitest';
import { PaneLegend, type LegendValue, type LegendStatusData, type PaneLegendOptions } from '../src/primitives/pane-legend';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';
import { PriceScale } from '../src/scale/price-scale';
import { TimeScale } from '../src/scale/time-scale';
import { DataLayer } from '../src/model/data-layer';
import { withAlpha } from '../src/render/pill';
import { darkTheme } from '../src/theme';
import { makeCtx, type RecordingContext } from './helpers/fake-ctx';

function rc(hoverId?: string): PrimitiveRenderContext {
  const priceScale = new PriceScale();
  priceScale.setHeight(300);
  const timeScale = new TimeScale();
  timeScale.setWidth(800);
  return {
    timeScale, priceScale, dataLayer: new DataLayer(),
    plotWidth: 800, plotHeight: 300, priceAxisWidth: 56, dpr: 1,
    theme: darkTheme, hoverId,
  };
}

interface Drawn {
  ctx: CanvasRenderingContext2D;
  rec: RecordingContext;
  texts: string[];
  legend: PaneLegend;
}

function paint(opts: PaneLegendOptions, values: readonly LegendValue[] = [], hoverId?: string): Drawn {
  const { ctx, rec } = makeCtx();
  const texts: string[] = [];
  const base = rec.fillText.bind(rec);
  rec.fillText = (t: string, x: number, y: number): void => { texts.push(t); base(t, x, y); };
  const legend = new PaneLegend(opts);
  legend.setValues(values);
  legend.draw(ctx, rc(hoverId));
  return { ctx, rec, texts, legend };
}

/** fillText x coordinates, in draw order. */
function textXs(rec: RecordingContext): number[] {
  return rec.ops.filter((o) => o.type === 'fillText').map((o) => o.args[0]);
}

/** Drop one occurrence of each listed string, so "removed too much" also fails. */
function without(base: readonly string[], ...gone: readonly string[]): string[] {
  const rest = [...gone];
  return base.filter((t) => {
    const i = rest.indexOf(t);
    if (i < 0) return true;
    rest.splice(i, 1);
    return false;
  });
}

/** The fake measureText: 6 px a character, so layout is arithmetic. */
const W = (t: string): number => t.length * 6;

const LOGO_IMAGE = {} as unknown as CanvasImageSource;

const STATUS: LegendStatusData = {
  logo: LOGO_IMAGE,
  description: 'Apple Inc.',
  ticker: 'NASDAQ:AAPL',
  marketStatus: { text: 'Market open', color: '#26a69a' },
  lastDayChange: { text: '+2.10 (+2.11%)', color: '#26a69a' },
};

/** A full symbol status line: OHLC, bar change, volume, own last value. */
const VALUES: readonly LegendValue[] = [
  { label: 'O', text: '101.00', field: 'ohlc' },
  { label: 'H', text: '102.00', field: 'ohlc' },
  { label: 'L', text: '100.00', field: 'ohlc' },
  { label: 'C', text: '101.50', field: 'ohlc' },
  { text: '+0.50 (+0.49%)', field: 'change' },
  { label: 'Vol', text: '1.2M', field: 'volume' },
  { text: '101.42' },
];

const BASE_TEXTS = [
  'AAPL', 'Market open',
  'O', '101.00', 'H', '102.00', 'L', '100.00', 'C', '101.50',
  '+0.50 (+0.49%)', 'Vol', '1.2M', '101.42',
  '+2.10 (+2.11%)',
];

const symbol = (statusLine?: PaneLegendOptions['statusLine']): PaneLegendOptions =>
  ({ id: 'sym', title: 'AAPL', status: STATUS, actions: ['hide', 'settings', 'close'], statusLine });

describe('defaults reproduce the row as it drew before the switches existed', () => {
  it('keeps OI off by default and renders an explicitly enabled zero reading', () => {
    const values: LegendValue[] = [{ label: 'OI', text: '0', field: 'openInterest' }];
    expect(paint(symbol(), values).texts).not.toContain('OI');
    expect(paint(symbol({ openInterest: true }), values).texts).toContain('0');
    expect(paint(symbol({ openInterest: false }), values).texts).not.toContain('OI');
    expect(paint({ ...symbol({ openInterest: true }), hasOpenInterest: false }, values).texts).not.toContain('OI');
    expect(paint({ ...symbol({ openInterest: true }), hasOpenInterest: true }, values).texts).toContain('0');
  });

  it('lays out swatch, title, params and a labelled reading unchanged', () => {
    const { rec, texts } = paint(
      { id: 'ind', title: 'EMA', params: '20 close', color: '#f5a623' },
      [{ label: 'C', text: '101.50' }],
    );
    expect(rec.ops.map((o) => o.type)).toEqual([
      'save', 'beginPath', 'rect', 'clip', 'beginPath', 'arc', 'fill', 'fillText', 'fillText', 'fillText', 'fillText', 'restore',
    ]);
    expect(texts).toEqual(['EMA', '20 close', 'C', '101.50']);
    // left 8, swatch centre 8+3, advance 11; then width + 6 (3 before a value).
    expect(rec.ops.find(op => op.type === 'arc')?.args).toEqual([11, 15, 3]);
    expect(textXs(rec)).toEqual([19, 43, 97, 106]);
    expect(rec.ops.every((o) => o.type !== 'fillText' || o.args[1] === 15)).toBe(true);
  });

  it('draws no background, no logo and no plate when nothing asks for them', () => {
    const { rec } = paint({ id: 'ind', title: 'EMA' }, [{ text: '1.00' }]);
    expect(rec.count('roundRect')).toBe(0);
    expect(rec.count('drawImage')).toBe(0);
  });

  it('draws every status-line field the host supplied, in reference order', () => {
    const { texts, rec } = paint(symbol(), VALUES);
    expect(texts).toEqual(BASE_TEXTS);
    expect(rec.count('drawImage')).toBe(1);
  });

  it('draws nothing for market state and day change when no source supplies them', () => {
    const { texts, rec } = paint({ id: 'sym', title: 'AAPL' }, VALUES);
    expect(texts).toEqual(without(BASE_TEXTS, 'Market open', '+2.10 (+2.11%)'));
    expect(rec.count('drawImage')).toBe(0);
  });

  it('draws nothing for a status source that returns null', () => {
    const { texts, rec } = paint({ id: 'sym', title: 'AAPL', status: () => null }, VALUES);
    expect(texts).toEqual(without(BASE_TEXTS, 'Market open', '+2.10 (+2.11%)'));
    expect(rec.count('drawImage')).toBe(0);
  });
});

describe('each switch removes exactly its own field', () => {
  const cases: readonly [string, PaneLegendOptions['statusLine'], readonly string[]][] = [
    ['title', { title: false }, ['AAPL']],
    ['marketStatus', { marketStatus: false }, ['Market open']],
    ['chartValues', { chartValues: false }, ['O', '101.00', 'H', '102.00', 'L', '100.00', 'C', '101.50']],
    ['barChange', { barChange: false }, ['+0.50 (+0.49%)']],
    ['volume', { volume: false }, ['Vol', '1.2M']],
    ['lastValueLabel', { lastValueLabel: false }, ['101.42']],
    ['lastDayChange', { lastDayChange: false }, ['+2.10 (+2.11%)']],
  ];

  for (const [name, statusLine, gone] of cases) {
    it(`${name}: false drops ${gone.join(' ')} and keeps the rest`, () => {
      const { texts, rec } = paint(symbol(statusLine), VALUES);
      expect(texts).toEqual(without(BASE_TEXTS, ...gone));
      expect(rec.count('drawImage')).toBe(1); // the logo is nobody else's business
    });
  }

  it('logo: false drops the logo and no text', () => {
    const { texts, rec } = paint(symbol({ logo: false }), VALUES);
    expect(texts).toEqual(BASE_TEXTS);
    expect(rec.count('drawImage')).toBe(0);
  });

  it('closes the gap a hidden field leaves, rather than drawing into a hole', () => {
    const on = paint(symbol(), VALUES);
    const off = paint(symbol({ marketStatus: false }), VALUES);
    const shift = W('Market open') + 6;
    // The title sits before the market state, so it does not move; everything
    // after it shifts left by exactly the missing text plus its gap.
    expect(textXs(off.rec)[0]).toBe(textXs(on.rec)[0]);
    expect(textXs(off.rec).slice(1)).toEqual(textXs(on.rec).slice(2).map((x) => x - shift));
  });

  it('places the logo before the title and moves the row over by its width', () => {
    const withLogo = paint(symbol(), VALUES);
    const noLogo = paint(symbol({ logo: false }), VALUES);
    const img = withLogo.rec.ops.find((o) => o.type === 'drawImage');
    expect(img?.args).toEqual([8, 9]); // left inset, 12 px square centred on the row
    expect(textXs(withLogo.rec)[0] - textXs(noLogo.rec)[0]).toBe(17); // 12 wide + 5 gap
  });
});

describe('title mode', () => {
  it('shows the symbol by default', () => {
    expect(paint(symbol(), []).texts[0]).toBe('AAPL');
  });

  it('shows the description or the ticker when asked', () => {
    expect(paint(symbol({ titleMode: 'description' }), []).texts[0]).toBe('Apple Inc.');
    expect(paint(symbol({ titleMode: 'ticker' }), []).texts[0]).toBe('NASDAQ:AAPL');
  });

  it('falls back to the title when the host supplies no alternative name', () => {
    const opts: PaneLegendOptions = { id: 'sym', title: 'AAPL', statusLine: { titleMode: 'ticker' } };
    expect(paint(opts, []).texts).toEqual(['AAPL']);
  });
});

describe('background plate', () => {
  const plate = (rec: RecordingContext): number => rec.ops.findIndex((o) => o.type === 'roundRect');

  it('is off by default and on demand fills before any text is drawn', () => {
    const off = paint(symbol(), VALUES);
    expect(off.rec.count('roundRect')).toBe(0);

    const on = paint(symbol({ background: true }), VALUES);
    const i = plate(on.rec);
    expect(i).toBeGreaterThanOrEqual(0);
    const firstInk = on.rec.ops.findIndex((o) => o.type === 'fillText' || o.type === 'drawImage' || o.type === 'arc');
    expect(i).toBeLessThan(firstInk);
    expect(on.rec.ops[i + 1].type).toBe('fill');
  });

  it('spans the row it sits behind, from the left inset past the last reading', () => {
    const { rec } = paint(symbol({ background: true }), VALUES);
    const box = rec.ops[plate(rec)].args;
    const xs = textXs(rec);
    const end = xs[xs.length - 1] + W(BASE_TEXTS[BASE_TEXTS.length - 1]);
    expect(box[0]).toBe(4);              // 8 left inset less 4 px padding
    expect(box[1]).toBe(6);              // top of an 18 px row at top 6
    expect(box[0] + box[2]).toBe(end + 4); // 4 px past the last glyph, no trailing gap
    expect(box[3]).toBe(18);
  });

  it('uses the theme background at 0.8, and the caller colour and opacity when given', () => {
    const { rec } = paint(symbol({ background: true }), VALUES);
    expect(rec.ops[plate(rec) + 1].fillStyle).toBe(withAlpha(darkTheme.background, 0.8));

    const tinted = paint(symbol({ background: true, backgroundColor: '#123456', backgroundOpacity: 0.5 }), VALUES);
    expect(tinted.rec.ops[plate(tinted.rec) + 1].fillStyle).toBe('rgba(18,52,86,0.5)');
  });

  it('leaves the text exactly where it was', () => {
    const off = paint(symbol(), VALUES);
    const on = paint(symbol({ background: true }), VALUES);
    expect(on.texts).toEqual(off.texts);
    expect(textXs(on.rec)).toEqual(textXs(off.rec));
  });

  it('draws no plate behind a row that has nothing on it', () => {
    const { rec } = paint({ id: 'sym', title: 'AAPL', statusLine: { title: false, background: true } }, []);
    expect(rec.count('roundRect')).toBe(0);
  });
});

describe('hit-test ids survive every switch', () => {
  const buttonIds = (legend: PaneLegend): string[] =>
    (legend as unknown as { _buttons: { id: string; x: number }[] })._buttons.map((b) => b.id);
  const buttons = (legend: PaneLegend): { id: string; x: number }[] =>
    (legend as unknown as { _buttons: { id: string; x: number }[] })._buttons;

  const variants: readonly [string, PaneLegendOptions['statusLine']][] = [
    ['defaults', undefined],
    ['logo', { logo: false }],
    ['title', { title: false }],
    ['titleMode', { titleMode: 'ticker' }],
    ['marketStatus', { marketStatus: false }],
    ['chartValues', { chartValues: false }],
    ['barChange', { barChange: false }],
    ['volume', { volume: false }],
    ['lastValueLabel', { lastValueLabel: false }],
    ['lastDayChange', { lastDayChange: false }],
    ['background', { background: true }],
    ['everything off', {
      logo: false, title: false, marketStatus: false, chartValues: false,
      barChange: false, volume: false, lastValueLabel: false, lastDayChange: false,
    }],
  ];

  for (const [name, statusLine] of variants) {
    it(`${name}: same button ids, each still under its own glyph`, () => {
      const { legend } = paint(symbol(statusLine), VALUES, 'sym::row');
      expect(buttonIds(legend)).toEqual(['sym::hide', 'sym::settings', 'sym::close']);
      for (const b of buttons(legend)) {
        expect(legend.hitTest(b.x + 8, 12)?.externalId).toBe(b.id);
      }
      expect(legend.hitTest(8, 12)?.externalId).toBe('sym::row');
      expect(legend.hitTest(8, 2)).toBeNull();
    });
  }

  it('still swallows the row click when every field is switched off', () => {
    const { legend } = paint(symbol({ title: false, chartValues: false, volume: false }), []);
    expect(legend.hitTest(10, 12)?.externalId).toBe('sym::row');
  });
});

describe('option plumbing', () => {
  it('merges a status-line patch field by field', () => {
    const legend = new PaneLegend(symbol({ volume: false }));
    legend.setOptions({ statusLine: { title: false } });
    expect(legend.options().statusLine).toEqual({ volume: false, title: false });

    const { ctx, rec } = makeCtx();
    const texts: string[] = [];
    const base = rec.fillText.bind(rec);
    rec.fillText = (t: string, x: number, y: number): void => { texts.push(t); base(t, x, y); };
    legend.setValues(VALUES);
    legend.draw(ctx, rc());
    expect(texts).toEqual(without(BASE_TEXTS, 'AAPL', 'Vol', '1.2M'));
  });

  it('reads a status callback on every frame', () => {
    let open = true;
    const legend = new PaneLegend({
      id: 'sym', title: 'AAPL',
      status: (): LegendStatusData => ({ marketStatus: { text: open ? 'Market open' : 'Market closed' } }),
    });
    const first = makeCtx();
    const seen: string[] = [];
    for (const { ctx, rec } of [first, makeCtx()]) {
      const base = rec.fillText.bind(rec);
      rec.fillText = (t: string, x: number, y: number): void => { seen.push(t); base(t, x, y); };
      legend.draw(ctx, rc());
      open = false;
    }
    expect(seen).toEqual(['AAPL', 'Market open', 'AAPL', 'Market closed']);
  });

  it('repaints when a reading changes only its field tag', () => {
    const legend = new PaneLegend({ id: 'sym', title: 'AAPL' });
    let updates = 0;
    legend.attached({ requestUpdate: (): void => { updates += 1; } });
    legend.setValues([{ text: '1.2M' }]);
    legend.setValues([{ text: '1.2M' }]);
    expect(updates).toBe(1);
    legend.setValues([{ text: '1.2M', field: 'volume' }]);
    expect(updates).toBe(2);
  });
});
