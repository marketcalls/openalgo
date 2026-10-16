/**
 * The helpers that used to be private copies in several modules: warmup-gap
 * alignment and the Smoothing block in the indicator tier, and the luminance
 * arithmetic shared by the canvas helpers and the widget's tokens.
 *
 * Merging copies is only safe if no output moves, so every comparison between
 * the helpers and their oracles is bitwise (`Object.is`, which also tells 0
 * from -0 and NaN from NaN), and the oracles are the copies as they were
 * written before the merge. Constants recorded on one machine are the one
 * exception; see the luminance block.
 */
import ts from 'typescript';
import { describe, it, expect } from 'vitest';
import { fromFirstValue, emaOfGapped, smoothingMa } from '../src/indicators/smoothing';
import { sma, wma, rma, vwma, smaSeededEma } from '../src/indicators/calc';
import { windowMean } from '../src/indicators/window-mean';
import {
  srgbLuminance, luminance as canvasLuminance, contrastText, withAlpha as canvasWithAlpha,
  parseColor as canvasParse,
} from '../src/render/pill';
import {
  luminance as tokenLuminance, withAlpha as tokenWithAlpha, parseColor as tokenParse, themeMode,
} from '../src/widget/tokens';

function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * A series shaped like a chained indicator: a leading warmup gap, an interior
 * hole or two, and now and then an infinity or an exact zero, since those are
 * the values the alignment and the kernels treat specially.
 */
function series(seed: number, n: number): number[] {
  const r = mulberry32(seed);
  const lead = Math.floor(r() * Math.min(n, 40));
  const out: number[] = [];
  let v = (r() - 0.5) * 200;
  for (let i = 0; i < n; i++) {
    v += (r() - 0.5) * 10;
    const roll = r();
    if (i < lead) out.push(roll < 0.9 ? NaN : roll < 0.95 ? Infinity : -Infinity);
    else if (roll < 0.03) out.push(NaN);
    else if (roll < 0.035) out.push(Infinity);
    else if (roll < 0.045) out.push(0);
    else out.push(v);
  }
  return out;
}

function volumes(seed: number, n: number): number[] {
  const r = mulberry32(seed ^ 0x5bd1e995);
  return Array.from({ length: n }, () => (r() < 0.05 ? 0 : Math.round(r() * 1e5)));
}

function expectBitwise(actual: readonly number[], expected: readonly number[], label: string): void {
  expect(actual.length, label).toBe(expected.length);
  for (let i = 0; i < expected.length; i++) {
    if (!Object.is(actual[i], expected[i])) {
      throw new Error(`${label}: index ${i} is ${actual[i]}, expected ${expected[i]}`);
    }
  }
}

// The copies this module replaced, verbatim apart from their names. None of
// them calls into the module under test, so a regression in a shared helper
// cannot carry an oracle along with it.

/** The momentum and ranges copy, whose smoother is told where the tail starts. */
function fromFirstValueCopy(
  values: readonly number[],
  smooth: (tail: readonly number[], start: number) => number[],
): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  let start = 0;
  while (start < n && !Number.isFinite(values[start])) start += 1;
  if (start >= n) return out;
  const tail = smooth(values.slice(start), start);
  for (let i = 0; i < tail.length && start + i < n; i++) out[start + i] = tail[i];
  return out;
}
/** The wavetrend copy: the same alignment for a smoother that needs no offset. */
function fromFirstValueWavetrend(
  values: readonly number[],
  smooth: (tail: readonly number[]) => number[],
): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  let start = 0;
  while (start < n && !Number.isFinite(values[start])) start += 1;
  if (start >= n) return out;
  const tail = smooth(values.slice(start));
  for (let i = 0; i < tail.length && start + i < n; i++) out[start + i] = tail[i];
  return out;
}
function emaOfGappedCopy(values: readonly number[], period: number): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  let start = 0;
  while (start < n && !Number.isFinite(values[start])) start += 1;
  if (start >= n) return out;
  const tail = smaSeededEma(values.slice(start), period);
  for (let i = 0; i < tail.length; i++) out[start + i] = tail[i];
  return out;
}
/** The momentum copy: every kernel starts at the first real value. */
function smoothingAligned(kind: string, values: readonly number[], vols: readonly number[], length: number): number[] {
  switch (kind) {
    case 'EMA': return fromFirstValueCopy(values, (t) => smaSeededEma(t, length));
    case 'SMMA (RMA)': return fromFirstValueCopy(values, (t) => rma(t, length));
    case 'WMA': return fromFirstValueCopy(values, (t) => wma(t, length));
    case 'VWMA': return fromFirstValueCopy(values, (t, start) => vwma(t, vols.slice(start), length));
    default: return fromFirstValueCopy(values, (t) => sma(t, length));
  }
}
/** The ranges copy: the EMA finds its own seed and is not sliced. */
function smoothingEmaUnsliced(kind: string, values: readonly number[], vols: readonly number[], length: number): number[] {
  return kind === 'EMA' ? smaSeededEma(values, length) : smoothingAligned(kind, values, vols, length);
}
/**
 * The volume copy, for a running total that prints from bar 0, and the
 * moving-average ribbon's, for a price source: no alignment at all.
 */
function smoothingRaw(kind: string, values: readonly number[], vols: readonly number[], length: number): number[] {
  switch (kind) {
    case 'EMA': return smaSeededEma(values, length);
    case 'SMMA (RMA)': return rma(values, length);
    case 'WMA': return wma(values, length);
    case 'VWMA': return vwma(values, vols, length);
    default: return sma(values, length);
  }
}

const KINDS = ['SMA', 'SMA + Bollinger Bands', 'EMA', 'SMMA (RMA)', 'WMA', 'VWMA', 'not a kind'];

describe('fromFirstValue', () => {
  it('smooths from the first finite value, hands the smoother its offset, and pads back', () => {
    const seen: number[] = [];
    const out = fromFirstValue([NaN, Infinity, 1, 2, NaN, 4], (tail, start) => {
      seen.push(start, tail.length);
      return tail.map((v) => v * 10);
    });
    expect(seen).toEqual([2, 4]);
    expectBitwise(out, [NaN, NaN, 10, 20, NaN, 40], 'padded');
    expectBitwise(fromFirstValue([NaN, NaN], () => [1, 2]), [NaN, NaN], 'all missing');
    expectBitwise(fromFirstValue([], () => []), [], 'empty');
  });

  it('never writes past the input, whatever length the smoother returns', () => {
    expectBitwise(fromFirstValue([NaN, 1, 2], () => [7, 8, 9, 10]), [NaN, 7, 8], 'long tail');
  });

  it('matches the three copies it replaced, bit for bit, whatever the smoother', () => {
    const smoothers: [string, (t: readonly number[]) => number[]][] = [
      ['ema 9', (t) => smaSeededEma(t, 9)],
      ['window mean 3', (t) => windowMean(t, 3)],
      ['sma 14', (t) => sma(t, 14)],
      ['short', (t) => t.slice(0, 2).map((v) => v * 2)],
      ['long', (t) => [...t, 1, 2, 3]],
    ];
    for (let seed = 1; seed <= 40; seed++) {
      const v = series(seed, 1 + (seed * 29) % 200);
      for (const [name, smooth] of smoothers) {
        const merged = fromFirstValue(v, smooth);
        expectBitwise(merged, fromFirstValueCopy(v, smooth), `seed ${seed} ${name} (momentum and ranges copies)`);
        expectBitwise(merged, fromFirstValueWavetrend(v, smooth), `seed ${seed} ${name} (wavetrend copy)`);
      }
    }
  });
});

describe('emaOfGapped', () => {
  it('matches the four copies it replaced, bit for bit, for every period', () => {
    for (let seed = 1; seed <= 60; seed++) {
      const n = 1 + (seed * 37) % 260;
      const v = series(seed, n);
      for (const period of [1, 2, 3, 5, 9, 14, 25, 50, n - 1, n, n + 1, 2.5, 0, -2]) {
        expectBitwise(emaOfGapped(v, period), emaOfGappedCopy(v, period), `seed ${seed} period ${period}`);
      }
    }
  });
});

describe('smoothingMa', () => {
  // Every caller passes a length through its `int` setting reader, a whole
  // number of at least 1, so these are the lengths the kernel switch can meet.
  // 2 ** 53 + 2 is what that reader returns for an absurd setting.
  const lengths = (n: number): number[] => [1, 2, 3, 4, 7, 14, 20, 50, n - 1, n, n + 1, 1e6, 2 ** 53 + 2]
    .filter((l) => l >= 1);

  it('matches the four copies it replaced, bit for bit, on gapped series', () => {
    for (let seed = 1; seed <= 40; seed++) {
      const n = 1 + (seed * 53) % 300;
      const v = series(seed, n);
      const vol = volumes(seed, n);
      for (const kind of KINDS) {
        for (const length of lengths(n)) {
          const merged = smoothingMa(kind, v, vol, length);
          const label = `seed ${seed} ${kind} length ${length}`;
          expectBitwise(merged, smoothingAligned(kind, v, vol, length), label + ' (aligned copy)');
          expectBitwise(merged, smoothingEmaUnsliced(kind, v, vol, length), label + ' (unsliced EMA copy)');
          expectBitwise(merged, smoothingRaw(kind, v, vol, length), label + ' (unaligned volume and ribbon copies)');
        }
      }
    }
  });

  it('passes a series with no leading gap through untouched, the running-total case', () => {
    const v = [0, 3, -1, 4, 4, 9, NaN, 2, 6, 5, 3, 5];
    const vol = [1, 2, 3, 0, 5, 6, 7, 8, 9, 10, 11, 12];
    for (const kind of KINDS) {
      for (const length of [1, 3, 5, 12, 13]) {
        expectBitwise(smoothingMa(kind, v, vol, length), smoothingRaw(kind, v, vol, length), `${kind} ${length}`);
      }
    }
  });

  it('pairs VWMA volumes with the aligned tail, not with bar 0', () => {
    const v = [NaN, NaN, 10, 20, 30];
    const vol = [1000, 1000, 1, 1, 2];
    // (20 * 1 + 30 * 2) / 3 over the last two bars.
    expect(smoothingMa('VWMA', v, vol, 2)[4]).toBeCloseTo(80 / 3, 12);
    expect(smoothingMa('VWMA', v, vol, 2)[3]).toBe(15);
  });
});

describe('one copy of each shared indicator helper', () => {
  // The merge only pays if no study module keeps a private copy that can be
  // corrected apart from its siblings, which is how the copies drifted in the
  // first place. So the modules are read as text, resolved at transform time
  // like the tier-boundary suite's sources: every definition of a shared piece
  // has to be the one in smoothing.ts.
  const SOURCES = (import.meta as unknown as {
    glob(pattern: string, options: { query: string; import: string; eager: true }): Record<string, string>;
  }).glob('../src/indicators/*.ts', { query: '?raw', import: 'default', eager: true });
  const definedIn = (pattern: RegExp): string[] => Object.keys(SOURCES)
    .filter((path) => pattern.test(SOURCES[path]))
    .map((path) => path.slice(path.lastIndexOf('/') + 1));

  it.each([
    ['the first-value alignment', /function fromFirstValue\b/],
    ['the gapped EMA', /function emaOfGapped\b/],
    ['the Smoothing kernel switch', /case 'SMMA \(RMA\)'/],
    ['the Smoothing option list and its Bollinger choice', /'SMA \+ Bollinger Bands'/],
    // The alignment itself, whatever a copy is called: writing a smoothed tail
    // back from its first finite bar. A renamed private copy would pass the
    // name checks above and drift from the shared one just the same.
    ['the tail written back from the first value', /\[\w+ \+ i\] = \w+\[i\]/],
  ])('%s lives only in smoothing.ts', (_name, pattern) => {
    expect(definedIn(pattern)).toEqual(['smoothing.ts']);
  });
});

describe('relative luminance', () => {
  it('is one kernel, read through each module\'s own parser', () => {
    for (const c of ['#26a69a', '#131722', '#abc', '#ffffff', '#000', 'rgba(300, 1, 2.5, 2)', 'rgb(10.1,0,0)']) {
      const canvas = canvasParse(c);
      const token = tokenParse(c);
      expect(canvas, c).not.toBeNull();
      expect(token, c).not.toBeNull();
      expect(canvasLuminance(c), c).toBe(srgbLuminance(canvas!));
      expect(tokenLuminance(c), c).toBe(srgbLuminance(token!));
    }
    // Neither parser reads a named colour; both fall back to mid-grey.
    expect(canvasLuminance('red')).toBe(0.5);
    expect(tokenLuminance('red')).toBe(0.5);
    expect(contrastText('red')).toBe('#10131a');
  });

  it('keeps the values recorded before the merge', () => {
    // Recorded on Windows. The sRGB curve goes through Math.pow, whose last bit
    // differs between platforms (Linux CI reads 0.30017599301394504 for the
    // first one), so a recorded constant is held to a few units in the last
    // place. The test above still holds both modules to one kernel bitwise.
    const recorded = (actual: number, expected: number): void => {
      expect(Math.abs(actual - expected)).toBeLessThanOrEqual(4 * Number.EPSILON * Math.abs(expected));
    };
    recorded(canvasLuminance('#26a69a'), 0.3001759930139451);
    recorded(tokenLuminance('#26a69a'), 0.3001759930139451);
    recorded(canvasLuminance('#131722'), 0.008667326325538549);
    recorded(canvasLuminance('#abc'), 0.4844632879252147);
    // A fractional channel between the two published sRGB thresholds: the
    // curve branch taken here is the one this arithmetic has always used.
    recorded(canvasLuminance('rgb(10.1,0,0)'), 0.0006516021323610484);
    recorded(tokenLuminance('rgb(10.1,0,0)'), 0.0006516021323610484);
    recorded(canvasLuminance('rgba(300, 1, 2.5, 2)'), 0.3084310154143921);
  });

  it('still answers from each parser where the two parsers disagree', () => {
    // Space-separated rgb() parses only in the widget.
    expect(canvasLuminance('rgb(1 2 3)')).toBe(0.5);
    expect(tokenLuminance('rgb(1 2 3)')).toBe(0.0005644387786074181);
    expect(tokenLuminance('rgb(1 2 3 / 50%)')).toBe(0.0005644387786074181);
    // A stray letter in a six-digit hex is read up to that letter on canvas.
    expect(canvasLuminance('#12345g')).toBe(0.01638187637053478);
    expect(tokenLuminance('#12345g')).toBe(0.5);
    expect(contrastText('rgb(1 2 3)')).toBe('#10131a');
    expect(themeMode({ background: 'rgb(1 2 3)' })).toBe('dark');
    expect(contrastText('#12345g')).toBe('#ffffff');
    expect(themeMode({ background: '#12345g' })).toBe('light');
  });
});

describe("the widget's Rgba", () => {
  // The kernel takes the canvas module's `Rgba`, but the widget publishes its
  // own. Re-exporting the canvas one moved the widget's declaration and its API
  // page to render/pill.ts, and the pill module's file header rode along as the
  // type's doc comment in dist/widget/index.d.ts. The compiler's view of the
  // widget entry is what both the declaration bundle and the API reference read.
  it('is still declared by the widget, with no doc comment borrowed from another module', () => {
    const root = decodeURIComponent(new URL('..', import.meta.url).pathname).replace(/^\/([A-Za-z]:)/, '$1');
    const files = ['src/widget/index.ts', 'src/widget/tokens.ts', 'src/render/pill.ts'].map((f) => root + f);
    // noResolve keeps the program to these three files; the exports between
    // them still resolve, and nothing else is parsed.
    const program = ts.createProgram(files, {
      noResolve: true, noEmit: true, target: ts.ScriptTarget.ES2020,
      module: ts.ModuleKind.ESNext, moduleResolution: ts.ModuleResolutionKind.Bundler,
    });
    const checker = program.getTypeChecker();
    const entry = checker.getSymbolAtLocation(program.getSourceFile(files[0])!)!;
    const exported = checker.getExportsOfModule(entry).find((sym) => sym.name === 'Rgba')!;
    const rgba = exported.flags & ts.SymbolFlags.Alias ? checker.getAliasedSymbol(exported) : exported;
    expect(rgba.declarations?.map((d) => d.getSourceFile().fileName)).toEqual([files[1]]);
    expect(ts.displayPartsToString(rgba.getDocumentationComment(checker))).toBe('');
  });
});

describe('the two withAlpha contracts', () => {
  it('canvas writes rgba() with the alpha as given; tokens write #rrggbb when opaque and round', () => {
    expect(canvasWithAlpha('#26a69a', 1)).toBe('rgba(38,166,154,1)');
    expect(tokenWithAlpha('#26a69a', 1)).toBe('#26a69a');
    expect(canvasWithAlpha('#26a69a', 0.12345678)).toBe('rgba(38,166,154,0.12345678)');
    expect(tokenWithAlpha('#26a69a', 0.12345678)).toBe('rgba(38,166,154,0.123)');
    expect(canvasWithAlpha('#26a69a', 1.5)).toBe('rgba(38,166,154,1.5)');
    expect(tokenWithAlpha('#26a69a', 1.5)).toBe('#26a69a');
    expect(canvasWithAlpha('rgb(1 2 3)', 0.5)).toBe('rgb(1 2 3)');
    expect(tokenWithAlpha('rgb(1 2 3)', 0.5)).toBe('rgba(1,2,3,0.5)');
    expect(canvasWithAlpha('#12345g', 0.5)).toBe('rgba(1,35,69,0.5)');
    expect(tokenWithAlpha('#12345g', 0.5)).toBe('#12345g');
  });
});
