import { describe, it, expect } from 'vitest';
import { Chart } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';

describe('Chart time-scale configuration', () => {
  it('lets wide footprint columns fit the viewport and preserves default spacing limits', () => {
    const doc = fakeDocument();
    const create = (wide: boolean) => new Chart(doc.createElement('div'), {
      document: doc, pixelRatio: () => 1, raf: { schedule: () => 0, cancel: () => {} },
      ...(wide ? { timeScale: { maxBarSpacing: 260, barSpacing: 120, rightOffset: 0 } } : {}),
    });
    const wide = create(true);
    expect(wide.timeScale.barSpacing).toBe(120);
    wide.timeScale.setWidth(1200);
    wide.timeScale.fitContent(7);
    expect(wide.timeScale.barSpacing).toBeGreaterThan(80);
    wide.timeScale.setBarSpacing(300);
    expect(wide.timeScale.barSpacing).toBe(260);
    const standard = create(false);
    standard.timeScale.setBarSpacing(300);
    expect(standard.timeScale.barSpacing).toBe(80);
    wide.destroy();
    standard.destroy();
  });
});
