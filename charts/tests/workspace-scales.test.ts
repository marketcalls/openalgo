import { describe, expect, it } from 'vitest';
import { parseWorkspaceDocument, WorkspaceDocumentError } from '../src/workspace/index';
import { workspaceFixture } from './helpers/workspace-fixture';

const scale = () => ({ marginTop: 0.1, marginBottom: 0.2, minMove: 0.05, minPrecision: 4,
  mode: 'logarithmic' as const, inverted: true, autoScale: false, range: { min: 10, max: 100 },
  fixedRange: null, ratioLock: { barSpacing: 10, height: 578 } });

function documentWithScales() {
  const document = workspaceFixture();
  return { ...document, panes: [{ ...document.panes[0], chart: {
    ...document.panes[0].chart, panes: [{ weight: 1, priceScale: scale(),
      scales: { left: scale(), '': scale(), 'overlay:spread': scale() } }],
  } }, document.panes[1]] as const };
}

describe('workspace scale state', () => {
  it('retains every scale setting and lock through its portable document boundary', () => {
    const input = documentWithScales();
    const restored = parseWorkspaceDocument(JSON.stringify(input));
    expect(restored).toEqual(input);
    input.panes[0].chart.panes![0].scales.left.range.min = 25;
    expect(restored.panes[0].chart.panes?.[0].scales?.left?.range?.min).toBe(10);
  });

  it.each([
    { minPrecision: 1.5 }, { fixedRange: { min: 10, max: 1 } },
    { ratioLock: { barSpacing: -1, height: 200 } },
    { autoScale: true, ratioLock: { barSpacing: 8, height: 200 } },
  ])('rejects malformed optional scale fields: %j', patch => {
    const input = documentWithScales();
    Object.assign(input.panes[0].chart.panes![0].scales.left, patch);
    expect(() => parseWorkspaceDocument(input)).toThrow(WorkspaceDocumentError);
  });
});
