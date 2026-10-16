import { describe, expect, it, vi } from 'vitest';
import { afterChartSettingsWrite, chartDecorationsForRebuild, chartSettingUnavailable, initChartSettings } from '../src/chart-settings.js';
import { fakeDom } from './helpers.js';

describe('chart rebuild settings', () => {
  it('carries each chart own legend button size through a rebuild', () => {
    expect(chartDecorationsForRebuild({ legendIconSize: () => 24 })).toEqual({ legendIconSize: 24 });
    expect(chartDecorationsForRebuild({ legendIconSize: () => 12 })).toEqual({ legendIconSize: 12 });
    expect(chartDecorationsForRebuild({ legendIconSize: () => undefined })).toEqual({});
  });
  it('carries disabled branding and customized watermark options to the replacement chart', () => {
    const watermark = {
      visible: true,
      text: 'Desk view',
      color: '#aabbcc',
      opacity: 0.42,
      fontSize: 37,
    };
    const chart = {
      brandingOptions: vi.fn(() => false),
      watermarkOptions: vi.fn(() => ({ ...watermark })),
    };

    expect(chartDecorationsForRebuild(chart)).toEqual({ branding: false, watermark });
    expect(chart.brandingOptions).toHaveBeenCalledOnce();
    expect(chart.watermarkOptions).toHaveBeenCalledOnce();
  });

  it('carries custom branding and omits APIs an older build does not expose', () => {
    const branding = { href: 'https://charts.example.test', label: 'Charts provider' };
    expect(chartDecorationsForRebuild({ brandingOptions: () => ({ ...branding }) }))
      .toEqual({ branding });
    expect(chartDecorationsForRebuild(null)).toEqual({});
    expect(chartDecorationsForRebuild({})).toEqual({});
  });
});

describe('chart settings availability', () => {
  it('names the chart that trades as Chart 1, the way the rest of the page names it', () => {
    expect(chartSettingUnavailable('trading.longColor', undefined, { pane: 2, request: { symbol: 'AAPL' }, chart: {} }))
      .toBe('Trading is available on Chart 1');
  });
});

describe('transform options edited from the chart settings', () => {
  it('follow the chart into the copy the demo rebuilds and saves with', () => {
    fakeDom();
    const pf = { mode: 'fixed', boxSize: 1, reversal: 3, method: 'hl' };
    const renko = { mode: 'percent', percent: 2, method: 'close' };
    const app = { p2: { transforms: { 'point-figure': pf } } };
    initChartSettings(app);
    let spec = { type: 'renko', options: renko };
    const chart = { primarySeries: () => ({}), seriesTransform: () => spec, timezone: () => 'Asia/Kolkata', legendIconSize: () => 16 };
    const target = { pane: 2, chart, request: {}, current: () => true };
    afterChartSettingsWrite(target);
    expect(app.p2.transforms).toEqual({ 'point-figure': pf, renko });
    expect(app.p2.transforms.renko).not.toBe(renko);
    // A transform without a dialog here, or none at all, leaves the copy alone.
    for (spec of [{ type: 'kagi', options: { reversal: 2 } }, null]) {
      afterChartSettingsWrite(target);
      expect(app.p2.transforms).toEqual({ 'point-figure': pf, renko });
    }
  });
});
