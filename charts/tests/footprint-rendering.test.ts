import { describe, expect, it } from 'vitest';
import { Footprint, compactVol } from '../src/profile/footprint-primitive';
import type { FootprintBar } from '../src/profile/profile-model';
import { DataLayer } from '../src/model/data-layer';
import { PriceScale } from '../src/scale/price-scale';
import { TimeScale } from '../src/scale/time-scale';
import { darkTheme, lightTheme } from '../src/theme';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';
import { makeCtx } from './helpers/fake-ctx';

const sample = (): FootprintBar => ({
  time: 1, delta: 110, rowSize: 1, tradeCount: 17,
  open: 101, high: 102, low: 98, close: 99,
  cells: [
    { price: 101, bidVol: 10, askVol: 20 },
    { price: 100, bidVol: 100, askVol: 200 },
  ],
});

function context(spacing = 140, dpr = 1): PrimitiveRenderContext {
  const dataLayer = new DataLayer();
  const id = dataLayer.createSeries();
  dataLayer.setSeriesData(id, [1, 2].map(time => ({ time, open: 101, high: 102, low: 98, close: 99 })));
  const timeScale = new TimeScale({ barSpacing: spacing, maxBarSpacing: 250, rightOffset: 1 });
  timeScale.setWidth(560);
  timeScale.setBaseIndex(1);
  const priceScale = new PriceScale();
  priceScale.setHeight(400);
  priceScale.setPriceRange({ min: 95, max: 105 });
  return { dataLayer, timeScale, priceScale, dpr, plotWidth: 560, plotHeight: 400, priceAxisWidth: 60, theme: darkTheme };
}

describe('footprint display geometry', () => {
  it('scales profile widths by actual volume while keeping numbers aligned at the center', () => {
    const fp = new Footprint({ cellStyle: 'profile', showCandle: false, showPoc: false, stackedImbalances: 0, statsRows: [], imbalanceRatio: 1000 });
    fp.setBars([sample()]);
    const { ctx, rec } = makeCtx();
    fp.draw(ctx, context());
    const cells = rec.ops.filter(op => op.type === 'roundRect');
    expect(cells).toHaveLength(4);
    expect(cells[0].args[2] / cells[2].args[2]).toBeCloseTo(0.1);
    expect(cells[1].args[2] / cells[3].args[2]).toBeCloseTo(0.1);
    const label = (text: string) => rec.ops.find(op => op.type === 'fillText' && op.text === text)!;
    expect(label('10').args[0]).toBe(label('100').args[0]);
    expect(label('20').args[0]).toBe(label('200').args[0]);
  });

  it('uses combined row volume as the peak in volume display mode', () => {
    const fp = new Footprint({ cellStyle: 'profile', displayMode: 'volume', statsRows: [], showCandle: false, showPoc: false, stackedImbalances: 0 });
    fp.setBars([sample()]);
    const { ctx, rec } = makeCtx();
    fp.draw(ctx, context());
    const rows = rec.ops.filter(op => op.type === 'roundRect');
    expect(rows).toHaveLength(2);
    expect(rows[0].args[2] / rows[1].args[2]).toBeCloseTo(0.1);
  });

  it('draws ladder cells at equal widths with square corners', () => {
    const fp = new Footprint({ cellStyle: 'ladder', radius: 9, statsRows: [], showCandle: false, showPoc: false, stackedImbalances: 0 });
    fp.setBars([sample()]);
    const { ctx, rec } = makeCtx();
    fp.draw(ctx, context());
    const rows = rec.ops.filter(op => op.type === 'roundRect');
    expect(rows).toHaveLength(4);
    expect(new Set(rows.map(op => op.args[2])).size).toBe(1);
    expect(rows.every(op => op.args[4] === 0)).toBe(true);
  });

  it('uses actual OHLC direction and body even when delta has the opposite sign', () => {
    const fp = new Footprint({ statsRows: [], sellColor: '#ff0000', buyColor: '#00ff00', showPoc: false, stackedImbalances: 0 });
    fp.setBars([sample()]);
    const { ctx, rec } = makeCtx();
    const rc = context();
    fp.draw(ctx, rc);
    const body = rec.ops.find(op => op.type === 'fillRect' && op.fillStyle === '#ff0000' && op.args[2] > 1);
    expect(body).toBeDefined();
    expect(body!.args[1]).toBeCloseTo(rc.priceScale.priceToY(101));
    expect(body!.args[3]).toBeCloseTo(rc.priceScale.priceToY(99) - rc.priceScale.priceToY(101));
  });

  it('puts labeled stats under each footprint and outlines the POC row', () => {
    const fp = new Footprint({ cellStyle: 'profile', statsPosition: 'bar', pocStyle: 'outline', statsRows: ['volume', 'delta', 'deltaPct'], stackedImbalances: 0 });
    fp.setBars([sample()]);
    const { ctx, rec } = makeCtx();
    const rc = context();
    fp.draw(ctx, rc);
    const volume = rec.ops.find(op => op.type === 'fillText' && op.text === 'Volume');
    expect(volume).toBeDefined();
    expect(volume!.args[1]).toBeGreaterThan(rc.priceScale.priceToY(98));
    expect(rec.count('strokeRect')).toBe(1);
  });

  it('derives POC and contiguous 70 percent value area from classified volume', () => {
    const fp = new Footprint({ showValueArea: true });
    fp.setBars([{ time: 1, delta: 100, rowSize: 1, cells: [
      { price: 103, bidVol: 0, askVol: 10 },
      { price: 102, bidVol: 0, askVol: 40 },
      { price: 101, bidVol: 0, askVol: 30 },
      { price: 100, bidVol: 0, askVol: 20 },
    ] }]);
    expect(fp.stats()[0]).toMatchObject({ poc: 102, vah: 102, val: 101 });
    fp.setOptions({ valueAreaPercent: 1 });
    expect(fp.stats()[0]).toMatchObject({ vah: 103, val: 100 });
  });

  it('fits rows and columns into their actual slots when zoomed out', () => {
    const fp = new Footprint({ statsRows: [], tickSize: 0.001, minTextHeight: 10, showCandle: false, showPoc: false, stackedImbalances: 0 });
    fp.setBars([sample()]);
    const { ctx, rec } = makeCtx();
    fp.draw(ctx, context(8));
    const rows = rec.ops.filter(op => op.type === 'roundRect');
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.every(op => op.args[2] <= 4 && op.args[3] <= 1)).toBe(true);
    expect(rec.count('fillText')).toBe(0);
  });

  it('keeps the OHLC candle inside its shrinking column gutter', () => {
    const fp = new Footprint({ statsRows: [], showPoc: false, stackedImbalances: 0 });
    fp.setBars([sample()]);
    const rc = context(24), { ctx, rec } = makeCtx(); fp.draw(ctx, rc);
    const left = rc.timeScale.indexToX(0) - 24 * 0.9 / 2;
    const candle = rec.ops.filter(op => op.type === 'fillRect');
    expect(candle.length).toBeGreaterThan(0);
    expect(candle.every(op => op.args[0] >= left)).toBe(true);
  });

  it('clips rendering to the plot and excludes invisible rows from hover', () => {
    const fp = new Footprint({ statsRows: [] });
    const b = sample(); b.cells.push({ price: 80, bidVol: 1, askVol: 2 });
    fp.setBars([b]);
    const rc = context();
    const { ctx, rec } = makeCtx();
    fp.draw(ctx, rc);
    expect(rec.count('clip')).toBeGreaterThan(0);
    expect(fp.hoverAt(rc.timeScale.indexToX(0), -1)).toBeNull();
    expect(fp.hoverAt(rc.timeScale.indexToX(0), 500)).toBeNull();
  });

  it('uses each column row bounds for hover and clears stale hit geometry', () => {
    const fp = new Footprint({ statsRows: [] });
    fp.setBars([sample(), { time: 2, rowSize: 0.1, delta: 2, cells: [{ price: 100, bidVol: 1, askVol: 3 }] }]);
    const rc = context();
    fp.draw(makeCtx().ctx, rc);
    const x = rc.timeScale.indexToX(1);
    expect(fp.hoverAt(x, rc.priceScale.priceToY(100.3))?.cell ?? null).toBeNull();
    expect(fp.hoverAt(x, rc.priceScale.priceToY(100))?.cell?.price).toBe(100);
    fp.setBars([]);
    fp.draw(makeCtx().ctx, rc);
    expect(fp.hitTest(x, 200)).toBeNull();
  });

  it('keeps row geometry aligned at fractional display scaling', () => {
    const fp = new Footprint({ statsRows: [] });
    fp.setBars([sample()]);
    const rc = context(140, 1.25);
    fp.draw(makeCtx().ctx, rc);
    expect(fp.hoverAt(rc.timeScale.indexToX(0), rc.priceScale.priceToY(100))?.cell?.price).toBe(100);
  });

  it('includes half of each row in autoscale so boundary rows fit', () => {
    const fp = new Footprint({ showCandle: false });
    fp.setBars([sample()]);
    expect(fp.autoscaleInfo()).toEqual({ min: 99.5, max: 101.5 });
  });

  it('keeps default cell numbers legible on light theme backgrounds', () => {
    const fp = new Footprint({ statsRows: [], cellStyle: 'profile' });
    fp.setBars([sample()]);
    const rc = context(); rc.theme = lightTheme;
    const { ctx, rec } = makeCtx();
    fp.draw(ctx, rc);
    const labels = rec.ops.filter(op => op.type === 'fillText');
    expect(labels.length).toBeGreaterThan(0);
    expect(labels.every(op => !op.fillStyle?.startsWith('rgba(255,255,255'))).toBe(true);
  });

  it('colors a sell-imbalanced total-volume label by the sell side', () => {
    const fp = new Footprint({ displayMode: 'volume', textColorMode: 'imbalance', statsRows: [],
      textColor: '#ffffff', buyTextColor: '#aaffaa', sellTextColor: '#ffaaaa', buyColor: '#001200', sellColor: '#120000' });
    fp.setBars([{ time: 1, delta: -90, rowSize: 1, cells: [
      { price: 101, bidVol: 1, askVol: 1 }, { price: 100, bidVol: 100, askVol: 10 },
    ] }]);
    const { ctx, rec } = makeCtx(); fp.draw(ctx, context());
    expect(rec.ops.find(op => op.type === 'fillText' && op.text === '110')?.fillStyle).toBe('rgba(255,170,170,1)');
  });

  it('grades volume text independently of equal row deltas', () => {
    const fp = new Footprint({ displayMode: 'delta', textColorMode: 'volume', statsRows: [], textColor: '#ffffff', buyTextColor: '#aaffaa' });
    fp.setBars([{ time: 1, delta: 4, rowSize: 1, cells: [
      { price: 101, bidVol: 9, askVol: 11 }, { price: 100, bidVol: 99, askVol: 101 },
    ] }]);
    const { ctx, rec } = makeCtx(); fp.draw(ctx, context());
    const labels = rec.ops.filter(op => op.type === 'fillText' && op.text === '2');
    expect(labels).toHaveLength(2);
    expect(labels[0].fillStyle).not.toBe(labels[1].fillStyle);
  });

  it('uses the plot background behind centered text outside a short profile fill', () => {
    const fp = new Footprint({ cellStyle: 'profile', displayMode: 'volume', statsRows: [],
      showCandle: false, textColor: '#ffffff', buyColor: '#00ff00', imbalanceRatio: 1000 });
    fp.setBars([{ time: 1, delta: 104, rowSize: 1, cells: [
      { price: 101, bidVol: 9, askVol: 11 }, { price: 100, bidVol: 0, askVol: 100 },
    ] }]);
    const { ctx, rec } = makeCtx(); fp.draw(ctx, context());
    expect(rec.ops.find(op => op.type === 'fillText' && op.text === '20')?.fillStyle).toBe('rgba(255,255,255,1)');
  });

  it('gives text crossing a profile edge one consistent contrast background', () => {
    const fp = new Footprint({ cellStyle: 'profile', statsRows: [], showCandle: false, showPoc: false, stackedImbalances: 0 });
    fp.setBars([sample()]);
    const { ctx, rec } = makeCtx(); fp.draw(ctx, context());
    expect(rec.ops.some(op => op.type === 'fillRect' && op.fillStyle === darkTheme.background)).toBe(true);
  });
});

describe('footprint reporting', () => {
  it('divides displayed quantities by lot size without changing raw stats or trade counts', () => {
    const fp = new Footprint({ volumeDivisor: 65, tableRows: ['volume', 'askVolume', 'bidVolume', 'delta', 'minDelta', 'maxDelta', 'cvd', 'deltaPct', 'trades'] });
    fp.setBars([{ ...sample(), minDelta: -65, maxDelta: 130 }]);
    const raw = fp.stats().map(s => ({ ...s }));
    const rc = context(140), { ctx, rec } = makeCtx(); fp.draw(ctx, rc);
    const values = rec.ops.filter(op => op.type === 'fillText' && op.args[1] > rc.plotHeight - 135).map(op => op.text);
    expect(values).toEqual(expect.arrayContaining(['5.08', '3.38', '1.69', '+1.69', '-1', '+2', '+33.3%', '17']));
    fp.setOptions({ volumeDivisor: 1 });
    expect(fp.stats()).toEqual(raw);
    const quantities = makeCtx(); fp.draw(quantities.ctx, rc);
    expect(quantities.rec.ops.some(op => op.type === 'fillText' && op.text === '330')).toBe(true);
  });

  it('applies the lot divisor to each bid/ask number', () => {
    const fp = new Footprint({ volumeDivisor: 65, showCandle: false, showPoc: false, stackedImbalances: 0 });
    fp.setBars([{ time: 1, delta: 65, rowSize: 1, cells: [{ price: 100, bidVol: 130, askVol: 195 }] }]);
    const { ctx, rec } = makeCtx(); fp.draw(ctx, context());
    expect(rec.ops.filter(op => op.type === 'fillText').map(op => op.text)).toEqual(['2', '3']);
  });

  it.each([0, -65, Infinity, NaN])('rejects an invalid lot divisor %s without changing options', (volumeDivisor) => {
    expect(() => new Footprint({ volumeDivisor })).toThrow(RangeError);
    const fp = new Footprint({ volumeDivisor: 65 });
    expect(() => fp.setOptions({ volumeDivisor })).toThrow(RangeError);
    expect(fp.options().volumeDivisor).toBe(65);
  });

  it('keeps the optional table disabled until rows are supplied', () => {
    const fp = new Footprint();
    expect(fp.options().statsRows).toEqual([]);
    expect(fp.options().tableRows).toEqual([]);
  });

  it('reports side totals and actual intrabar delta extremes, leaving legacy extremes unknown', () => {
    const fp = new Footprint();
    fp.setBars([{ ...sample(), minDelta: -50, maxDelta: 160 }, { ...sample(), time: 2 }]);
    expect(fp.stats()[0]).toMatchObject({ bidVolume: 110, askVolume: 220, volume: 330, minDelta: -50, maxDelta: 160 });
    expect(fp.stats()[1]).toMatchObject({ minDelta: null, maxDelta: null });
  });

  it('draws selected table rows in caller order with fixed labels and aligned columns', () => {
    const fp = new Footprint({ tableRows: ['delta', 'minDelta', 'maxDelta', 'cvd', 'askVolume', 'bidVolume', 'volume'], statsRowHeight: 19 });
    fp.setBars([{ ...sample(), minDelta: -50, maxDelta: 160 }]);
    const rc = context(140, 1.25), { ctx, rec } = makeCtx(); fp.draw(ctx, rc);
    const labels = ['Delta', 'Min Delta', 'Max Delta', 'Cumulative Delta', 'Total Ask Volume', 'Total Bid Volume', 'Total Volume'];
    const drawn = rec.ops.filter(op => op.type === 'fillText' && labels.includes(op.text ?? ''));
    expect(drawn.map(op => op.text)).toEqual(labels);
    expect(new Set(drawn.map(op => op.args[0])).size).toBe(1);
    const value = rec.ops.find(op => op.type === 'fillText' && op.text === '-50')!;
    expect(value.args[0]).toBeCloseTo(rc.timeScale.indexToX(0) * rc.dpr);
    expect(fp.hoverAt(rc.timeScale.indexToX(0), rc.plotHeight - 5)?.stats.minDelta).toBe(-50);
    expect(fp.hoverAt(5, rc.plotHeight - 5)).toBeNull();
    fp.setOptions({ tableRows: ['bidVolume'] });
    const next = makeCtx(); fp.draw(next.ctx, rc);
    expect(next.rec.ops.filter(op => op.type === 'fillText' && labels.includes(op.text ?? '')).map(op => op.text)).toEqual(['Total Bid Volume']);
    fp.setOptions({ tableRows: [] }); fp.draw(makeCtx().ctx, rc);
    expect(fp.hoverAt(rc.timeScale.indexToX(0), rc.plotHeight - 5)).toBeNull();
  });

  it('keeps per-bar cards interactive when a separate table is shown', () => {
    const fp = new Footprint({ statsPosition: 'bar', statsRows: ['volume'], tableRows: ['delta'] });
    fp.setBars([sample()]);
    const rc = context(), { ctx, rec } = makeCtx(); fp.draw(ctx, rc);
    const card = rec.ops.find(op => op.type === 'fillText' && op.text === 'Volume')!;
    expect(fp.hoverAt(rc.timeScale.indexToX(0), card.args[1])?.price).toBeNull();
    expect(fp.hoverAt(rc.timeScale.indexToX(0), rc.plotHeight - 5)?.price).toBeNull();
  });

  it('does not show a plus sign on ask/bid volume table values', () => {
    const fp = new Footprint({ tableRows: ['askVolume', 'bidVolume'], showCandle: false });
    fp.setBars([sample()]);
    const rc = context(), { ctx, rec } = makeCtx(); fp.draw(ctx, rc);
    const values = rec.ops.filter(op => op.type === 'fillText' && op.args[1] > rc.plotHeight - 30).map(op => op.text);
    expect(values).toContain('220'); expect(values).toContain('110');
    expect(values).not.toContain('+220'); expect(values).not.toContain('+110');
  });

  it('reports actual trade counts and distinguishes missing counts from zero', () => {
    const fp = new Footprint();
    const legacy = { ...sample(), time: 2, tradeCount: undefined };
    fp.setBars([sample(), legacy]);
    expect(fp.stats().map(s => s.trades)).toEqual([17, null]);
  });

  it('preserves session CVD when a caller drops old bars and supplies the offset', () => {
    const fp = new Footprint({ cvdOffset: 10 });
    fp.setBars([sample()]);
    expect(fp.stats()[0].cvd).toBe(120);
    fp.setOptions({ cvdOffset: -10 });
    expect(fp.stats()[0].cvd).toBe(100);
  });

  it.each([[0.125, '0.125'], [0.001, '0.001'], [23.4, '23.4'], [999999, '1M']])('formats fractional volumes and suffix rollover: %s', (value, expected) => {
    expect(compactVol(value as number)).toBe(expected);
  });
});
