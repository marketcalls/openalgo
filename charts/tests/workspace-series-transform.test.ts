import { describe, expect, it } from 'vitest';
import { parseIndicatorTemplate, parseWorkspaceDocument, WorkspaceDocumentError } from '../src/workspace/index';
import { workspaceFixture } from './helpers/workspace-fixture';

/** A workspace whose first chart is a Renko chart with one study on the underlying bars. */
function renkoDesk() {
  const fixture = workspaceFixture();
  const [first, second] = fixture.panes;
  return { ...fixture, panes: [{ ...first, chartType: 'renko', chart: { ...first.chart,
    series: [{ type: 'candlestick', style: {}, paneIndex: 0, priceScaleId: 'right', transform: { type: 'renko', options: { boxSize: 2.5 } } }],
    indicators: [{ ...first.chart.indicators[0], barSource: 'underlying' }, first.chart.indicators[1]],
  } }, second] };
}

describe('workspace documents with in-chart transforms', () => {
  it('keeps a series transform and a study bar source through a round trip', () => {
    const desk = renkoDesk();
    const parsed = parseWorkspaceDocument(desk);
    expect(parsed.panes[0].chartType).toBe('renko');
    expect(parsed.panes[0].chart.series?.[0].transform).toEqual({ type: 'renko', options: { boxSize: 2.5 } });
    expect(parsed.panes[0].chart.indicators?.[0].barSource).toBe('underlying');
    expect(parsed.panes[0].chart.indicators?.[1]).not.toHaveProperty('barSource');
    expect(parseWorkspaceDocument(JSON.parse(JSON.stringify(parsed)))).toEqual(parsed);
  });

  it('reads a document written before either existed exactly as before', () => {
    const fixture = workspaceFixture();
    const parsed = parseWorkspaceDocument(fixture);
    expect(parsed.panes[0].chart.indicators?.every(study => !('barSource' in study))).toBe(true);
    expect(parsed.panes[0].chart).not.toHaveProperty('series');
  });

  it('refuses a malformed transform or bar source rather than guessing', () => {
    const desk = renkoDesk();
    const withTransform = (transform: unknown) => {
      const copy = JSON.parse(JSON.stringify(desk));
      copy.panes[0].chart.series[0].transform = transform;
      return copy;
    };
    expect(() => parseWorkspaceDocument(withTransform('renko'))).toThrow(WorkspaceDocumentError);
    expect(() => parseWorkspaceDocument(withTransform({ type: 'renko', options: { boxSize: 'big', x: null } }))).toThrow(/transform options/);
    const study = JSON.parse(JSON.stringify(desk));
    study.panes[0].chart.indicators[0].barSource = 'raw';
    expect(() => parseWorkspaceDocument(study)).toThrow(/bar source/);
  });

  it('keeps the bar source in an indicator template', () => {
    const indicators = renkoDesk().panes[0].chart.indicators;
    const template = parseIndicatorTemplate({ kind: 'indicator-template', version: 1, id: 't', name: 'Renko studies', createdAt: 1, updatedAt: 2, indicators });
    expect(template.indicators.map(study => study.barSource)).toEqual(['underlying', undefined]);
  });
});
