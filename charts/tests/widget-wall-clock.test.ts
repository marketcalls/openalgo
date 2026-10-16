/**
 * The one reader behind every date and time field in the widget: the go-to
 * panel, a drawing's anchors, an alert's expiry and the chart data export's
 * bounds. Each field keeps its policy (a blank time, a skipped one, an
 * inclusive end) through the options; what does not read is refused the same
 * way everywhere.
 */
import { describe, expect, it } from 'vitest';
import { formatWallClock, parseWallClock } from '../src/widget/wall-clock';

const at = (y: number, mo: number, d: number, h = 0, mi = 0, s = 0): number => Date.UTC(y, mo - 1, d, h, mi, s) / 1000;

describe('the wall clock', () => {
  it('reads a date and a time on the zone clock, and writes them back', () => {
    expect(parseWallClock('2026-09-28', '09:15', 'Asia/Kolkata')).toBe(at(2026, 9, 28, 3, 45));
    expect(formatWallClock(at(2026, 9, 28, 3, 45), 'Asia/Kolkata')).toEqual({ date: '2026-09-28', time: '09:15', seconds: false });
    expect(formatWallClock(at(2026, 9, 28, 3, 45, 7), 'Asia/Kolkata')).toEqual({ date: '2026-09-28', time: '09:15:07', seconds: true });
    expect(formatWallClock(at(2026, 9, 28, 3, 45, 7), 'Asia/Kolkata', false).time).toBe('09:15');
  });

  it('refuses what does not read, whichever field asks', () => {
    for (const [date, time] of [['2026-02-30', '09:15'], ['2026-13-01', '09:15'], ['2026-09-00', '09:15'], ['28/09/2026', '09:15'],
      ['2026-09-28', '24:00'], ['2026-09-28', '09:60'], ['2026-09-28', '9:15'], ['2026-09-28', '']]) {
      expect(parseWallClock(date, time, 'Asia/Kolkata'), `${date} ${time}`).toBeNull();
    }
  });

  it('keeps each field its own policy for a blank time, an inclusive end and a skipped time', () => {
    expect(parseWallClock('2026-09-28', '', 'Asia/Kolkata', { blank: 'start' })).toBe(at(2026, 9, 27, 18, 30));
    expect(parseWallClock('2026-09-28', '', 'Asia/Kolkata', { blank: 'end' })).toBe(at(2026, 9, 28, 18, 29, 59));
    expect(parseWallClock('2026-09-28', '15:29', 'Asia/Kolkata', { end: true })).toBe(at(2026, 9, 28, 9, 59, 59));
    expect(parseWallClock('2026-09-28', '15:29:30', 'Asia/Kolkata', { end: true })).toBe(at(2026, 9, 28, 9, 59, 30));
    // New York skipped 02:30 on 8 March 2026: an anchor reads the time it maps to, an expiry refuses it.
    expect(parseWallClock('2026-03-08', '02:30', 'America/New_York')).not.toBeNull();
    expect(parseWallClock('2026-03-08', '02:30', 'America/New_York', { rejectSkipped: true })).toBeNull();
    expect(parseWallClock('2026-03-08', '03:30', 'America/New_York', { rejectSkipped: true })).toBe(at(2026, 3, 8, 7, 30));
  });
});
