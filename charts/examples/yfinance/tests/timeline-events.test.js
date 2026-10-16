import { describe, expect, it, vi } from 'vitest';
import { sampleTimelineEvents, timelineActions } from '../src/timeline.js';

// A short daily walk: enough bars for the sample events to land on.
const bars = [2841.5, 2856.2, 2838.9, 2861.4, 2874.05, 2869.3, 2880.75, 2866.1, 2891.6, 2903.25]
  .map((close, i) => ({ time: 1758758400 + i * 86400, open: close - 6.4, high: close + 9.1, low: close - 12.3, close }));

describe('reference host timeline events', () => {
  it('shows rich sample content with a vetted link and markup kept as text', () => {
    const results = sampleTimelineEvents(bars).find(event => event.id === 'sample-results');
    const blocks = results.details.blocks;
    expect(blocks.map(block => block.type)).toEqual(['heading', 'paragraph', 'list']);
    expect(blocks[1].text.find(span => span.href).href).toMatch(/^https:\/\//);
    expect(blocks[2].items).toContain('Markup such as <b>this</b> stays text');
  });

  it('marks the event on the chart it was clicked on, and only there', () => {
    const add = vi.fn();
    let current = true;
    const chart = { primaryPaneIndex: () => 0 };
    const [action] = timelineActions({ current: () => current, chart, draw: { add } }, { bars })();
    expect(action.label).toBe('Mark on chart');
    action.run({ id: 'sample-call', time: bars[6].time + 1, type: 'news', label: 'N' });
    expect(add).toHaveBeenCalledWith({ tool: 'vertical-line', paneIndex: 0, points: [{ time: bars[6].time + 1, price: bars[6].close }] });
    current = false;
    action.run({ id: 'sample-call', time: bars[6].time + 1, type: 'news', label: 'N' });
    expect(add).toHaveBeenCalledTimes(1);
  });

  it('marks the pane the candles are on after the price pane has moved below a study', () => {
    const add = vi.fn();
    const chart = { primaryPaneIndex: () => 1 };
    const [action] = timelineActions({ current: () => true, chart, draw: { add } }, { bars })();
    action.run({ id: 'sample-dividend', time: bars[8].time, type: 'dividend', label: 'D' });
    expect(add).toHaveBeenCalledWith({ tool: 'vertical-line', paneIndex: 1, points: [{ time: bars[8].time, price: bars[8].close }] });
  });
});
