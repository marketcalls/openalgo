import { afterEach, describe, expect, it } from 'vitest';
import '../src/indicators/index';
import { Chart } from '../src/core/chart';
import type { Bar } from '../src/model/bar';
import { getIndicator, hasIndicator, indicatorStyleInputs, plotStyleKeys } from '../src/model/indicator-registry';
import { fakeDocument } from './helpers/fake-dom';

const charts: Chart[] = [];
afterEach(() => { for (const chart of charts.splice(0)) chart.destroy(); });

function rows(readings: readonly (number | undefined)[], closes: readonly number[] = []): Bar[] {
  return readings.map((oi, i) => ({
    time: 1735689600 + i * 60, open: 100, high: 120, low: 80,
    close: closes[i] ?? 100 + i, ...(oi === undefined ? {} : { oi }),
  }));
}

function mount(id: string, bars: Bar[], settings: Record<string, unknown> = {}) {
  expect(hasIndicator(id), `${id} must be selectable from the built-in registry`).toBe(true);
  const doc = fakeDocument();
  const chart = new Chart(doc.createElement('div'), {
    document: doc, pixelRatio: () => 1, shortcuts: false,
    raf: { schedule: cb => { cb(); return 1; }, cancel() {} },
  });
  charts.push(chart);
  chart.applySize(800, 600);
  const price = chart.addSeries('candlestick');
  price.setData(bars);
  return { chart, price, study: chart.addIndicator(id, settings) };
}

describe('open-interest studies', () => {
  it('plots zero as a reading, preserves gaps and formats the axis as a position size', () => {
    const { study } = mount('open-interest', rows([100, undefined, 0, 1_500_000]));
    expect(study.values().oi).toEqual([100, null, 0, 1_500_000]);
    const plot = study.series('oi')!;
    expect(plot.getData().map(b => b.close)).toEqual([100, NaN, 0, 1_500_000]);
    expect(plot.priceScale().format(1_500_000)).toMatch(/1\.5\d*M/);
    expect(study.paneIndex).toBeGreaterThan(0);
  });

  it('replaces the forming reading with a gap and follows replacement history', () => {
    const bars = rows([100, 120]);
    const { price, study } = mount('open-interest', bars);
    price.update({ ...bars[1], oi: undefined });
    expect(study.values().oi).toEqual([100, null]);
    price.update({ ...bars[1], oi: 0 });
    price.update({ ...bars[1], time: bars[1].time + 60, oi: 40 });
    expect(study.values().oi).toEqual([100, 0, 40]);
    price.setData(rows([undefined, 500]));
    expect(study.values().oi).toEqual([null, 500]);
  });

  it('computes adjacent changes without bridging gaps or fabricating warmup', () => {
    const { study } = mount('open-interest-change', rows([100, 140, 110, undefined, 0, 20, 20]), {
      upColor: '#11bb11', downColor: '#bb1111',
    });
    expect(study.values().change).toEqual([null, 40, -30, null, null, 20, 0]);
    expect(study.series('change')!.getData().map(b => b.color)).toEqual([
      undefined, '#11bb11', '#bb1111', undefined, undefined, '#11bb11', '#11bb11',
    ]);
    study.setSettings({ downColor: '#aa0011' });
    expect(study.series('change')!.getData()[2].color).toBe('#aa0011');
    const style = plotStyleKeys(getIndicator('open-interest-change').plots[0]);
    study.setSettings({ [style.color]: '#112233', [style.opacity]: 50 });
    expect(study.series('change')!.getData()[1].color).toBe('rgba(17,34,51,0.5)');
    expect(study.series('change')!.getData()[2].color).toBe('rgba(170,0,17,0.5)');
  });

  it('recomputes a live change and a replay prefix from only the supplied rows', () => {
    const bars = rows([100, 140, 110]);
    const { price, study } = mount('open-interest-change', bars);
    price.update({ ...bars[2], oi: 0 });
    expect(study.values().change).toEqual([null, 40, -140]);
    price.setData(bars.slice(0, 1));
    expect(study.values().change).toEqual([null]);
    price.update(bars[1]);
    expect(study.values().change).toEqual([null, 40]);
  });

  it.each(['open-interest', 'open-interest-change'])('%s exposes working generated plot styles', id => {
    const { chart, study } = mount(id, rows([100, 120]));
    const descriptor = getIndicator(id);
    const key = descriptor.plots[0].key;
    expect(indicatorStyleInputs(descriptor).map(input => input.key)).toEqual(
      expect.arrayContaining([`${key}:opacity`, `${key}:width`, `${key}:lineStyle`, `${key}:type`]),
    );
    const oldSeries = study.series(key);
    study.setSettings({ [`${key}:type`]: 'area', [`${key}:width`]: 3 });
    expect(study.series(key)).toBe(oldSeries);
    expect(chart.seriesType(study.series(key)!)).toBe('area');
    expect(study.series(key)!.getData().map(b => b.close)).toEqual(id === 'open-interest' ? [100, 120] : [NaN, 20]);
    expect(chart.getState().indicators?.[0].settings[`${key}:width`]).toBe(3);
  });

  const colors = {
    longBuildupColor: '#11aa11', shortBuildupColor: '#aa1111',
    shortCoveringColor: '#1111aa', longUnwindingColor: '#aaaa11',
  };

  it('paints all four buildup states from close-to-close signs and restores source colors', () => {
    const bars = rows([100, 110, 120, 110, 100], [100, 101, 99, 101, 99]);
    bars[0].color = '#ffffff';
    const { price, study } = mount('open-interest-buildup', bars, colors);
    expect(study.paneIndex).toBe(0);
    expect(price.getData().map(b => b.color)).toEqual(['#ffffff', '#11aa11', '#aa1111', '#1111aa', '#aaaa11']);
    expect(bars.map(b => b.color)).toEqual(['#ffffff', undefined, undefined, undefined, undefined]);
    study.setSettings({ longBuildupColor: '#22bb22' });
    expect(price.getData()[1].color).toBe('#22bb22');
    study.setVisible(false);
    expect(price.getData().map(b => b.color)).toEqual(['#ffffff', undefined, undefined, undefined, undefined]);
    study.setVisible(true);
    expect(price.getData()[1].color).toBe('#22bb22');
    study.remove();
    expect(price.getData().map(b => b.color)).toEqual(['#ffffff', undefined, undefined, undefined, undefined]);
  });

  it('keeps unchanged readings neutral by default and optionally treats zero change as up', () => {
    const { price, study } = mount('open-interest-buildup', rows([100, 100, 110, 110, 100], [100, 101, 101, 100, 100]), colors);
    expect(price.getData().map(b => b.color)).toEqual([undefined, undefined, undefined, undefined, undefined]);
    study.setSettings({ unchanged: 'up' });
    expect(price.getData().map(b => b.color)).toEqual([undefined, '#11aa11', '#11aa11', '#aa1111', '#1111aa']);
  });

  it('never classifies missing readings as zero and clears a live color when OI disappears', () => {
    const bars = rows([10, 0, undefined, 20, 30], [100, 101, 99, 101, 102]);
    const { price, study } = mount('open-interest-buildup', bars, { ...colors, unchanged: 'up' });
    expect(price.getData().map(b => b.color)).toEqual([undefined, '#1111aa', undefined, undefined, '#11aa11']);
    price.update({ ...bars[4], oi: undefined });
    expect(price.getData()[4].color).toBeUndefined();
    price.setData(rows([100, 80], [100, 99]));
    expect(price.getData().map(b => b.color)).toEqual([undefined, '#aaaa11']);
    expect(study.values().state).toHaveLength(2);
  });
});
