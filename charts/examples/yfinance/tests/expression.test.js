import { describe, expect, it, vi } from 'vitest';
vi.mock('../src/feed.js', () => ({ fetchBars: vi.fn() }));
import { fetchBars } from '../src/feed.js';
import { fetchExpressionBars } from '../src/expression.js';

describe('combined leg activity', () => {
  it('passes caller-owned cancellation to every leg without using another chart slot', async () => {
    fetchBars.mockClear();
    fetchBars.mockResolvedValue([{ time: 6000, open: 10, high: 12, low: 9, close: 11 }]);
    const controller = new AbortController();
    await fetchExpressionBars('A+B', '1d', '1y', { signal: controller.signal });
    expect(fetchBars).toHaveBeenCalledTimes(2);
    for (const call of fetchBars.mock.calls) {
      expect(call[3].signal).toBe(controller.signal);
      expect(call[3].slot).toBeUndefined();
    }
  });

  it('reports each distinct leg volume once, including spread and weighted expressions', async () => {
    fetchBars.mockImplementation(async symbol => [{
      time: 6000, open: 10, high: 12, low: 9, close: 11, volume: symbol === 'A' ? 20 : 30,
    }]);
    for (const expression of ['A+B', '2*A-B', 'A+A+B']) {
      const { bars } = await fetchExpressionBars(expression, '1d', '1y');
      expect(bars[0].volume).toBe(50);
    }
  });
});
