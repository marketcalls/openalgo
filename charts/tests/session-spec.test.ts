/**
 * Stated session windows (src/feed/time.ts): the other half of the session
 * helpers, where the caller names the window instead of the bars implying it.
 * An opening range, a cash session inside an extended one, one exchange's hours
 * drawn on another exchange's chart.
 *
 * The window is half-open and the day filter names the day the window OPENS on,
 * so an overnight session stays one session instead of being cut at midnight.
 */
import { describe, it, expect } from 'vitest';
import {
  parseSessionSpec, inSessionAt, sessionFlags, zonedWallClockToUtcSeconds,
} from '../src/feed/time';

const IST = 'Asia/Kolkata';
const NY = 'America/New_York';
// 2026-01-04 is a Sunday, so the 5th is a Monday and the 10th a Saturday.
const ist = (day: number, hour: number, minute: number): number =>
  zonedWallClockToUtcSeconds(2026, 1, day, hour, minute, 0, IST);

describe('parseSessionSpec', () => {
  it('reads a plain window as minutes from midnight', () => {
    expect(parseSessionSpec('0915-1015')).toEqual({ start: 555, end: 615 });
  });

  it('ignores whitespace and reads the day filter', () => {
    expect(parseSessionSpec('  0930 - 1600 : 23456  ')).toEqual({
      start: 570, end: 960, days: [2, 3, 4, 5, 6],
    });
  });

  it('returns null rather than throwing on anything it cannot read', () => {
    // A settings field hands this a half-typed string on every keystroke, so a
    // throw here would take the chart down mid-edit.
    for (const bad of [
      '2400-0100', '0915-2460', '0960-1000', '915-1015', '0915-1015:0',
      '0915-1015:8', '0915_1015', '', '0915-', 'abcd-efgh', '0915-1015:',
    ]) {
      expect(parseSessionSpec(bad)).toBeNull();
    }
  });
});

describe('inSessionAt', () => {
  it('includes the opening minute and excludes the closing one', () => {
    const s = parseSessionSpec('0915-1015') as NonNullable<ReturnType<typeof parseSessionSpec>>;
    expect(inSessionAt(ist(5, 9, 14), s, IST)).toBe(false);
    expect(inSessionAt(ist(5, 9, 15), s, IST)).toBe(true);
    expect(inSessionAt(ist(5, 10, 14), s, IST)).toBe(true);
    // Half-open: a bar stamped exactly at the close belongs to what follows,
    // which is what an opening-range comparison needs.
    expect(inSessionAt(ist(5, 10, 15), s, IST)).toBe(false);
  });

  it('applies the day filter', () => {
    const w = parseSessionSpec('0915-1015:23456') as NonNullable<ReturnType<typeof parseSessionSpec>>;
    expect(inSessionAt(ist(4, 9, 30), w, IST)).toBe(false); // Sunday
    expect(inSessionAt(ist(5, 9, 30), w, IST)).toBe(true); // Monday
    expect(inSessionAt(ist(10, 9, 30), w, IST)).toBe(false); // Saturday
  });

  it('runs a window past midnight when the end is at or before the start', () => {
    const w = parseSessionSpec('2330-0030') as NonNullable<ReturnType<typeof parseSessionSpec>>;
    expect(inSessionAt(ist(5, 23, 29), w, IST)).toBe(false);
    expect(inSessionAt(ist(5, 23, 45), w, IST)).toBe(true);
    expect(inSessionAt(ist(6, 0, 15), w, IST)).toBe(true);
    expect(inSessionAt(ist(6, 0, 30), w, IST)).toBe(false);
  });

  it('attributes a wrapped tail to the day the window opened on', () => {
    const w = parseSessionSpec('2330-0030:2') as NonNullable<ReturnType<typeof parseSessionSpec>>;
    expect(inSessionAt(ist(5, 23, 45), w, IST)).toBe(true); // Monday night
    expect(inSessionAt(ist(6, 0, 15), w, IST)).toBe(true); // still Monday's session
    expect(inSessionAt(ist(6, 23, 45), w, IST)).toBe(false); // Tuesday night
    expect(inSessionAt(ist(7, 0, 15), w, IST)).toBe(false);
  });

  it('treats an empty window as the whole day', () => {
    const w = parseSessionSpec('0915-0915') as NonNullable<ReturnType<typeof parseSessionSpec>>;
    expect(inSessionAt(ist(5, 9, 14), w, IST)).toBe(true);
    expect(inSessionAt(ist(5, 21, 0), w, IST)).toBe(true);
  });

  it('reads the wall clock in the zone it is given', () => {
    const w = parseSessionSpec('0930-1600') as NonNullable<ReturnType<typeof parseSessionSpec>>;
    const t = zonedWallClockToUtcSeconds(2026, 1, 5, 10, 0, 0, NY);
    expect(inSessionAt(t, w, NY)).toBe(true);
    expect(inSessionAt(t, w, IST)).toBe(false); // 20:30 in IST
  });

  it('defaults the zone to the shipped one', () => {
    expect(inSessionAt(ist(5, 9, 30), { start: 555, end: 615 })).toBe(true);
  });

  it('takes a hand-built spec, not only a parsed one', () => {
    expect(inSessionAt(ist(5, 9, 30), { start: 555, end: 615, days: [2] }, IST)).toBe(true);
    expect(inSessionAt(ist(6, 9, 30), { start: 555, end: 615, days: [2] }, IST)).toBe(false);
  });
});

describe('sessionFlags', () => {
  const times = [ist(5, 9, 14), ist(5, 9, 15), ist(5, 10, 14), ist(5, 10, 15), ist(4, 9, 30)];

  it('marks the bars inside the window', () => {
    expect(sessionFlags(times, '0915-1015', IST)).toEqual([false, true, true, false, true]);
  });

  it('reads a string and a parsed spec the same way', () => {
    const spec = parseSessionSpec('0915-1015') as NonNullable<ReturnType<typeof parseSessionSpec>>;
    expect(sessionFlags(times, spec, IST)).toEqual(sessionFlags(times, '0915-1015', IST));
  });

  it('marks nothing for a spec it cannot read', () => {
    // A chart that keeps drawing beats one that dies on a stray character; a
    // caller that has to tell a bad spec from an empty window parses it itself.
    expect(sessionFlags(times, 'nonsense', IST)).toEqual([false, false, false, false, false]);
    expect(sessionFlags([], '0915-1015', IST)).toEqual([]);
  });
});

/**
 * 2.2.3: the spec is a string a user types into a settings field, and a
 * half-typed one arrives on every keystroke, so a pathological one must not
 * stall the input. Before the fix the trailing `\s*` sat beside the optional
 * group's own `\s*`, and a long run of spaces on a spec that ultimately fails
 * split between them in quadratically many ways: 32k spaces took over half a
 * second, 64k over two.
 */
describe('parseSessionSpec is linear on a hostile input', () => {
  it('rejects a long run of trailing spaces without backtracking', () => {
    const hostile = `0915-1530${' '.repeat(50_000)}!`;
    const started = Date.now();
    expect(parseSessionSpec(hostile)).toBeNull();
    // The old pattern needed seconds here. A wide bound keeps this from being
    // a flaky benchmark while still failing loudly if the blowup comes back.
    expect(Date.now() - started).toBeLessThan(250);
  });

  it('still parses every accepted spelling unchanged', () => {
    expect(parseSessionSpec('0915-1530')).toEqual({ start: 555, end: 930 });
    expect(parseSessionSpec('  0915  -  1530  ')).toEqual({ start: 555, end: 930 });
    expect(parseSessionSpec('0915-1530:135')).toEqual({ start: 555, end: 930, days: [1, 3, 5] });
    expect(parseSessionSpec('0915-1530 : 135 ')).toEqual({ start: 555, end: 930, days: [1, 3, 5] });
    expect(parseSessionSpec('0915-1530:')).toBeNull();
    expect(parseSessionSpec('915-1530')).toBeNull();
  });
});
