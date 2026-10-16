import { describe, expect, it } from 'vitest';
import { footprintTextColor, readableTextColor, type FootprintTextColorMode } from '../src/profile/footprint-colors';

const base = {
  mode: 'contrast' as FootprintTextColorMode, side: 'ask' as const,
  bidVol: 1, askVol: 3, peak: 4, hot: false,
  neutral: '#ffffff', buy: '#80ff80', sell: '#ffaaaa', background: '#000000',
};

// Independent WCAG sRGB reference; deliberately does not reuse production helpers.
function channels(color: string): number[] {
  if (color.startsWith('#')) {
    const hex = color.length === 4 ? [...color.slice(1)].map((c) => c + c).join('') : color.slice(1);
    return [0, 2, 4].map((at) => Number.parseInt(hex.slice(at, at + 2), 16));
  }
  return color.match(/[\d.]+/g)!.slice(0, 3).map(Number);
}
function contrast(a: string, b: string): number {
  const luminance = (color: string): number => channels(color).reduce((sum, channel, i) => {
    const c = channel / 255;
    return sum + [0.2126, 0.7152, 0.0722][i] * (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  }, 0);
  const left = luminance(a), right = luminance(b);
  return (Math.max(left, right) + 0.05) / (Math.min(left, right) + 0.05);
}

describe('footprint text coloring methods', () => {
  it('keeps contrast mode neutral even for a hot row', () => {
    expect(footprintTextColor({ ...base, hot: true })).toBe('#ffffff');
  });

  it('assigns directional palettes by the displayed side', () => {
    expect(footprintTextColor({ ...base, mode: 'side' })).toBe('#80ff80');
    expect(footprintTextColor({ ...base, mode: 'side', side: 'bid' })).toBe('#ffaaaa');
    expect(footprintTextColor({ ...base, mode: 'side', side: 'single' })).toBe('#80ff80');
  });

  it('colors both numbers by row delta and treats exact ties as neutral', () => {
    expect(footprintTextColor({ ...base, mode: 'delta', side: 'bid' })).toBe('#80ff80');
    expect(footprintTextColor({ ...base, mode: 'delta', bidVol: 4 })).toBe('#ffaaaa');
    expect(footprintTextColor({ ...base, mode: 'delta', bidVol: 3 })).toBe('#ffffff');
  });

  it('colors only the larger same-row side in dominant mode', () => {
    expect(footprintTextColor({ ...base, mode: 'dominant' })).toBe('#80ff80');
    expect(footprintTextColor({ ...base, mode: 'dominant', side: 'bid' })).toBe('#ffffff');
    expect(footprintTextColor({ ...base, mode: 'dominant', side: 'bid', bidVol: 4 })).toBe('#ffaaaa');
    expect(footprintTextColor({ ...base, mode: 'dominant', bidVol: 3 })).toBe('#ffffff');
    expect(footprintTextColor({ ...base, mode: 'dominant', side: 'single', bidVol: 4 })).toBe('#ffaaaa');
  });

  it('uses supplied diagonal flags independently of same-row dominance', () => {
    expect(footprintTextColor({ ...base, mode: 'imbalance', side: 'bid', hot: true })).toBe('#ffaaaa');
    expect(footprintTextColor({ ...base, mode: 'imbalance', hot: true })).toBe('#80ff80');
    expect(footprintTextColor({ ...base, mode: 'imbalance', hot: false })).toBe('#ffffff');
  });

  it('blends volume text continuously by the displayed side quantity', () => {
    expect(channels(footprintTextColor({ ...base, mode: 'volume', askVol: 2 }))).toEqual([192, 255, 192]);
    expect(channels(footprintTextColor({ ...base, mode: 'volume', side: 'bid' }))).toEqual([255, 234, 234]);
    expect(footprintTextColor({ ...base, mode: 'volume', askVol: 8 })).toBe('#80ff80');
    expect(footprintTextColor({ ...base, mode: 'volume', askVol: 0 })).toBe('#ffffff');
    expect(footprintTextColor({ ...base, mode: 'volume', peak: 0 })).toBe('#ffffff');
  });

  it('uses total quantity for single volume labels, with delta determining direction', () => {
    expect(footprintTextColor({ ...base, mode: 'volume', side: 'single' })).toBe('#80ff80');
    expect(footprintTextColor({ ...base, mode: 'volume', side: 'single', bidVol: 3 })).toBe('#ffffff');
  });

  it('falls back to the neutral palette when a directional color cannot be parsed', () => {
    expect(footprintTextColor({ ...base, mode: 'side', buy: 'var(--buy)' })).toBe('#ffffff');
  });

  it.each<FootprintTextColorMode>(['contrast', 'side', 'delta', 'dominant', 'imbalance', 'volume'])(
    'enforces readable text after selecting %s mode', (mode) => {
      const output = footprintTextColor({ ...base, mode, hot: true, background: '#ffffff' });
      expect(contrast(output, '#ffffff')).toBeGreaterThanOrEqual(4.5);
    },
  );
});

describe('readable footprint text colors', () => {
  it.each([
    ['#ffffff', '#000000'], ['#000', '#fff'], ['rgb(0, 128, 0)', '#ffffff'],
  ])('preserves an already readable palette %s on %s', (preferred, background) => {
    expect(readableTextColor(preferred, background)).toBe(preferred);
  });

  it.each([
    ['#ffffff', '#ffffff'], ['#000000', '#000000'],
    ['#777777', '#808080'], ['#661111', '#101010'],
    ['#80ff80', '#ffffff'], ['#ffaaaa', '#ffffff'],
    ['#ff6600', '#00ff00'], ['#00eeff', '#ffff00'], ['#00ffff', '#00ffff'],
  ])('reaches WCAG AA contrast for %s on %s', (preferred, background) => {
    expect(contrast(readableTextColor(preferred, background), background)).toBeGreaterThanOrEqual(4.5);
  });

  it('retains directional hue while lightening a dark red for a dark background', () => {
    const [r, g, b] = channels(readableTextColor('#661111', '#101010'));
    expect(r).toBeGreaterThan(g);
    expect(g).toBe(b);
  });

  it('accounts for text alpha before correcting its displayed contrast', () => {
    const output = readableTextColor('rgba(255,255,255,0.1)', '#000000');
    expect(output).not.toBe('rgba(255,255,255,0.1)');
    expect(contrast(output, '#000000')).toBeGreaterThanOrEqual(4.5);
  });

  it('chooses legible monochrome for an unknown preference on a known background', () => {
    const output = readableTextColor('var(--text)', '#ffffff');
    expect(output).toMatch(/^(#|rgb)/);
    expect(contrast(output, '#ffffff')).toBeGreaterThanOrEqual(4.5);
  });

  // rgb() accepts any channel, and a canvas paints one above 255 as 255.
  it.each(['#555555', '#80ff80', '#ffffff', 'rgb(0,300,0)'])('reads a channel above 255 as the 255 it paints, for %s', preferred => {
    expect(readableTextColor(preferred, 'rgb(300,0,0)')).toBe(readableTextColor(preferred, 'rgb(255,0,0)'));
    expect(readableTextColor(preferred, 'rgb(0,0,999)')).toBe(readableTextColor(preferred, 'rgb(0,0,255)'));
  });

  it('preserves caller preference when the background cannot be resolved', () => {
    expect(readableTextColor('#ffffff', 'var(--background)')).toBe('#ffffff');
  });
});
