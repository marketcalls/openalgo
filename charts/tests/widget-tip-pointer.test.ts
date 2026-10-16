/**
 * A tooltip never takes the pointer.
 *
 * The overlay layer turns pointer events back on for everything mounted in
 * it, and that rule came after the tooltip's own `pointer-events: none` at
 * the same specificity, so it won. A tooltip shown over a control swallowed
 * the click meant for that control: in a browser, the bottom bar's range tip
 * sat over the folded rail's tab and the tab could not be pressed.
 *
 * Asserted against the stylesheet by resolving the cascade the way a browser
 * does for a tooltip mounted in the overlay layer: among the rules that reach
 * it, an important declaration beats a normal one, then the more specific
 * selector wins, then the later rule.
 */
import { describe, expect, it } from 'vitest';
import { WIDGET_CSS } from '../src/widget/styles';

/** Whether a compound or complex selector reaches a tooltip mounted in the overlay layer. */
function reachesTip(selector: string): boolean {
  const not = /\.oac-layer > :not\(([^)]*)\)$/.exec(selector);
  if (not !== null) return !not[1]!.split(',').some((s) => s.trim() === '.oac-tip');
  if (/\.oac-layer > \*$/.test(selector)) return true;
  return /\.oac-tip(?![-_a-z])/.test(selector);
}

/** Specificity as [ids, classes and attributes and pseudo-classes, elements]; `:not()` counts its most specific argument. */
function specificity(selector: string): [number, number, number] {
  let s = selector;
  const out: [number, number, number] = [0, 0, 0];
  for (const m of s.matchAll(/:not\(([^)]*)\)/g)) {
    const best = m[1]!.split(',').map((x) => specificity(x.trim()))
      .sort((p, q) => q[0] - p[0] || q[1] - p[1] || q[2] - p[2])[0]!;
    out[0] += best[0]; out[1] += best[1]; out[2] += best[2];
  }
  s = s.replace(/:not\([^)]*\)/g, ' ');
  out[0] += (s.match(/#[\w-]+/g) ?? []).length;
  out[1] += (s.match(/\.[\w-]+|\[[^\]]*\]|:(?!:)[\w-]+/g) ?? []).length;
  out[2] += (s.replace(/\[[^\]]*\]/g, '').match(/(^|[\s>+~])[a-z][\w-]*/gi) ?? []).length;
  return out;
}

/** The pointer-events a tooltip in the overlay layer ends up with, resolved as the cascade resolves it. */
function tipPointerEvents(css: string): string | null {
  const stripped = css.replace(/\/\*[\s\S]*?\*\//g, '');
  let best: { value: string; important: boolean; spec: [number, number, number] } | null = null;
  for (const m of stripped.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const pe = /pointer-events:\s*([a-z]+)\s*(!important)?/.exec(m[2]!);
    if (pe === null) continue;
    for (const selector of m[1]!.split(/,(?![^(]*\))/).map((x) => x.trim()).filter(reachesTip)) {
      const cand = { value: pe[1]!, important: pe[2] !== undefined, spec: specificity(selector) };
      // Positive when the candidate outranks the standing winner; a tie goes to the later rule.
      const rank = best === null ? 1 : (Number(cand.important) - Number(best.important))
        || cand.spec[0] - best.spec[0] || cand.spec[1] - best.spec[1] || cand.spec[2] - best.spec[2];
      if (rank >= 0) best = cand;
    }
  }
  return best === null ? null : best.value;
}

describe('tooltips in the overlay layer', () => {
  it('leave the press to the control under them', () => {
    expect(tipPointerEvents(WIDGET_CSS)).toBe('none');
  });

  it('resolve the cascade by importance, then specificity, then order', () => {
    // The resolver itself, on rules written to disagree with source order.
    expect(specificity('.oac-widget .oac-layer > :not(.oac-tip, .oac-tip-spot)')).toEqual([0, 3, 0]);
    expect(tipPointerEvents('.a .oac-tip { pointer-events: none; } .oac-layer > * { pointer-events: auto; }')).toBe('none');
    expect(tipPointerEvents('.oac-tip { pointer-events: none; } .a .oac-layer > * { pointer-events: auto; }')).toBe('auto');
    expect(tipPointerEvents('.oac-layer > * { pointer-events: auto !important; } .a .b .oac-tip { pointer-events: none; }')).toBe('auto');
    expect(tipPointerEvents('.a .oac-tip { pointer-events: auto; } .b .oac-tip { pointer-events: none; }')).toBe('none');
  });
});
