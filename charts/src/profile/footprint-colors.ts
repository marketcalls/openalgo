import { parseColor, srgbLuminance, type Rgba } from '../render/pill';
import { clamp } from '../helpers/math';

/** Text coloring is independent of the footprint's background display mode. */
export type FootprintTextColorMode = 'contrast' | 'side' | 'delta' | 'dominant' | 'imbalance' | 'volume';

interface FootprintTextColorInput {
  mode: FootprintTextColorMode;
  side: 'bid' | 'ask' | 'single';
  bidVol: number;
  askVol: number;
  peak: number;
  /** Diagonal flag for this displayed side; supplied by the footprint analytics. */
  hot: boolean;
  neutral: string;
  buy: string;
  sell: string;
  /** Resolved opaque background immediately behind the number. */
  background: string;
}

function rgb(color: Rgba): string {
  return `rgb(${Math.round(color.r)},${Math.round(color.g)},${Math.round(color.b)})`;
}

function mix(a: Rgba, b: Rgba, t: number): Rgba {
  return { r: a.r + (b.r - a.r) * t, g: a.g + (b.g - a.g) * t, b: a.b + (b.b - a.b) * t, a: 1 };
}

/** Luminance of the colour a canvas paints: `parseColor` keeps an `rgb()` channel past 255, the canvas does not. */
function luminance(c: Rgba): number {
  return srgbLuminance({ r: clamp(c.r, 0, 255), g: clamp(c.g, 0, 255), b: clamp(c.b, 0, 255), a: c.a });
}

/**
 * Keep readable preferences; otherwise mix toward black or white until WCAG
 * normal-text contrast reaches 4.5:1. Ten bounded bisection steps retain as much
 * of the selected hue as the chosen direction allows. Text alpha is composited
 * first; corrections are opaque. Callers must resolve translucent backgrounds
 * against their backplate. Unknown backgrounds preserve the caller preference;
 * an unknown preference on a known background falls back to black/white.
 */
export function readableTextColor(preferred: string, background: string): string {
  const bg = parseColor(background);
  if (!bg) return preferred;
  const bgLum = luminance(bg);
  const contrast = (color: Rgba): number => {
    const lum = luminance(color);
    return (Math.max(lum, bgLum) + 0.05) / (Math.min(lum, bgLum) + 0.05);
  };
  const endpoint = (bgLum + 0.05) / 0.05 >= 1.05 / (bgLum + 0.05) ? 0 : 255;
  const target = { r: endpoint, g: endpoint, b: endpoint, a: 1 };
  const parsed = parseColor(preferred);
  if (!parsed) return rgb(target);
  const displayed = mix(bg, parsed, Math.max(0, Math.min(1, parsed.a)));
  if (contrast(displayed) >= 4.5) return preferred;
  let low = 0, high = 1;
  let best = target;
  for (let i = 0; i < 10; i++) {
    const amount = (low + high) / 2;
    const blended = mix(displayed, target, amount);
    // Test the actual quantized output, so rounding cannot drop it below 4.5.
    const candidate = { r: Math.round(blended.r), g: Math.round(blended.g), b: Math.round(blended.b), a: 1 };
    if (contrast(candidate) >= 4.5) { high = amount; best = candidate; }
    else low = amount;
  }
  return rgb(best);
}

/**
 * Select a text palette, then enforce contrast against the displayed fill.
 * Volume uses a continuous neutral-to-directional blend of quantity / peak,
 * clamped to [0, 1]. Single labels use total volume and row-delta direction;
 * bid/ask labels use their own quantity. Tied single labels remain neutral.
 */
export function footprintTextColor(input: FootprintTextColorInput): string {
  const { mode, side, bidVol, askVol, neutral, buy, sell } = input;
  const deltaColor = askVol > bidVol ? buy : bidVol > askVol ? sell : neutral;
  const sideColor = side === 'ask' ? buy : side === 'bid' ? sell : deltaColor;
  let selected = neutral;
  switch (mode) {
    case 'contrast': break;
    case 'side': selected = sideColor; break;
    case 'delta': selected = deltaColor; break;
    case 'dominant':
      if (side === 'single' || (side === 'ask' && askVol > bidVol) || (side === 'bid' && bidVol > askVol)) selected = deltaColor;
      break;
    case 'imbalance': if (input.hot) selected = sideColor; break;
    case 'volume': {
      const qty = side === 'ask' ? askVol : side === 'bid' ? bidVol : askVol + bidVol;
      const strength = input.peak > 0 ? Math.max(0, Math.min(1, qty / input.peak)) : 0;
      if (strength >= 1) selected = sideColor;
      else if (strength > 0 && sideColor !== neutral) {
        const from = parseColor(neutral), to = parseColor(sideColor);
        if (from && to) selected = rgb(mix(from, to, strength));
      }
      break;
    }
  }
  return readableTextColor(parseColor(selected) ? selected : neutral, input.background);
}
