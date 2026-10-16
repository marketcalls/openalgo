import { describe, it, expect, vi } from 'vitest';
import { fmt, fmtVol, esc, round2, pnlText, onEscape, inTextField, UP, DOWN, plural } from '../src/ui.js';

describe('formatting helpers', () => {
  it('fmt writes two decimals with thousands separators', () => {
    expect(fmt(1234.5)).toBe('1,234.50');
    expect(fmt('7')).toBe('7.00');
  });

  it('fmtVol abbreviates by magnitude and leaves small counts alone', () => {
    expect(fmtVol(1.5e9)).toBe('1.50B');
    expect(fmtVol(2.5e6)).toBe('2.50M');
    expect(fmtVol(1200)).toBe('1.20K');
    expect(fmtVol(999)).toBe('999');
    expect(fmtVol(null)).toBe('');
  });

  it('esc neutralises markup', () => {
    expect(esc('<a href="x">&</a>')).toBe('&lt;a href=&quot;x&quot;&gt;&amp;&lt;/a&gt;');
  });

  it('round2 rounds to the cent', () => {
    expect(round2(10.126)).toBe(10.13);
    expect(round2(3)).toBe(3);
  });

  it('pnlText carries the sign and drops the fraction, with no currency sign', () => {
    expect(pnlText(1234.4)).toBe('+1,234');
    expect(pnlText(-5)).toBe('-5');
  });

  it('exposes the candle palette', () => {
    expect(UP).toBe('#089981');
    expect(DOWN).toBe('#f23645');
  });
});

describe('keyboard helpers', () => {
  it('onEscape fires only for Escape, on the target it was given', () => {
    const listeners = {};
    const target = { addEventListener: (type, fn) => { listeners[type] = fn; } };
    const fn = vi.fn();
    onEscape(fn, target);
    listeners.keydown({ key: 'a' });
    expect(fn).not.toHaveBeenCalled();
    listeners.keydown({ key: 'Escape' });
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('inTextField recognises the controls that own the keyboard', () => {
    expect(inTextField({ target: { tagName: 'INPUT' } })).toBe(true);
    expect(inTextField({ target: { tagName: 'TEXTAREA' } })).toBe(true);
    expect(inTextField({ target: { tagName: 'SELECT' } })).toBe(true);
    expect(inTextField({ target: { tagName: 'DIV' } })).toBe(false);
  });
});

describe('plural', () => {
  it('counts one in the singular and any other number in the plural', () => {
    expect(plural(1, 'indicator')).toBe('1 indicator');
    expect(plural(0, 'indicator')).toBe('0 indicators');
    expect(plural(2, 'series descriptor')).toBe('2 series descriptors');
  });
});
