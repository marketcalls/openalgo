/**
 * Every chart a reader sees on the website looks like a traded instrument: a
 * seeded random walk with wicks and volume, never a sine wave, a straight
 * ramp or a sawtooth. Smooth synthetic curves made the examples look like
 * test fixtures, and a study drawn from `sin(i)` shows nothing about how the
 * study reads real prices. The generator is `stockBars` in
 * website/components/synthetic-market.ts; a demo drawing or study output is
 * computed from the bars it sits on.
 */
import { describe, expect, it } from 'vitest';
import { STOCK_BARS_SOURCE, stockBars } from '../website/components/synthetic-market';

type Sources = Record<string, string>;
/** `import.meta.glob`, typed; the suite carries no Vite client globals. */
type Glob = { glob(pattern: string, options: { query: string; import: string; eager: true }): Sources };
// Vite expands each glob at transform time, so every pattern is a literal call.
// The synced library bundles in website/lib are not the site's own source.
const SOURCES: Sources = {
  ...(import.meta as unknown as Glob).glob('../website/pages/**/*.{mdx,md,tsx,ts}', { query: '?raw', import: 'default', eager: true }),
  ...(import.meta as unknown as Glob).glob('../website/components/**/*.{tsx,ts}', { query: '?raw', import: 'default', eager: true }),
};

/** Shapes a price or study series takes when it is written as a formula of the bar index. */
const SYNTHETIC: Array<[string, RegExp]> = [
  ['a sine or cosine of the index', /Math\.(?:sin|cos)\(/],
  ['a straight ramp in the bar index', /\b(?:open|high|low|close|value)\s*:\s*[\d.]+\s*[+-]\s*(?:i|index)\s*[*/]/],
  ['a sawtooth in the bar index', /\+\s*\(?\s*(?:i|index)\s*%\s*\d+(?!\d)\s*\)?(?!\s*[=!<>])/],
];

describe('website example data', () => {
  it('draws no price or study series from a formula of the bar index', () => {
    expect(Object.keys(SOURCES).length).toBeGreaterThan(50);
    const found: string[] = [];
    for (const [file, text] of Object.entries(SOURCES)) {
      text.split(/\r?\n/).forEach((line: string, i: number) => {
        for (const [what, pattern] of SYNTHETIC) {
          if (pattern.test(line)) found.push(`${file.slice('../website/'.length)}:${i + 1} ${what}: ${line.trim()}`);
        }
      });
    }
    expect(found).toEqual([]);
  });

  it('gives components the same generator the runnable examples print', () => {
    const fromSource = new Function(`${STOCK_BARS_SOURCE}\nreturn stockBars;`)() as typeof stockBars;
    const bars = stockBars(1_789_776_000, 120, 60, 100, 33, 0.0022, 900);
    expect(bars).toEqual(fromSource(1_789_776_000, 120, 60, 100, 33, 0.0022, 900));
    // A walk, not a curve: up and down bars both common, and wicks on both sides.
    expect(bars.filter(bar => bar.close > bar.open).length).toBeGreaterThan(30);
    expect(bars.filter(bar => bar.close < bar.open).length).toBeGreaterThan(30);
    expect(bars.every(bar => bar.high > Math.max(bar.open, bar.close) && bar.low < Math.min(bar.open, bar.close))).toBe(true);
  });
});
