import { describe, it, expect } from 'vitest';
import {
  epochMsToUtcSeconds,
  istStringToUtcSeconds,
  utcSecondsToIstParts,
  formatIstTime,
  formatIstTimeSeconds,
  formatIstDate,
  formatIstCrosshairLabel,
  isNewIstDay,
  IST_OFFSET_SECONDS,
} from '../src/feed/time';

describe('time conversions (between IST and UTC seconds)', () => {
  it('epoch ms to utc seconds floors to the second', () => {
    expect(epochMsToUtcSeconds(1_700_000_000_999)).toBe(1_700_000_000);
  });

  it('IST string and the equivalent epoch produce the same UTC seconds', () => {
    // 2024-01-15 09:15:00 IST == 2024-01-15 03:45:00 UTC
    const fromIst = istStringToUtcSeconds('2024-01-15 09:15:00');
    const utcMs = Date.UTC(2024, 0, 15, 3, 45, 0);
    expect(fromIst).toBe(Math.floor(utcMs / 1000));
  });

  it('round-trips IST wall-clock through parts', () => {
    const sec = istStringToUtcSeconds('2024-03-15 14:30:45');
    const p = utcSecondsToIstParts(sec);
    expect(p).toMatchObject({ year: 2024, month: 3, day: 15, hour: 14, minute: 30, second: 45 });
  });

  it('IST offset is +5:30', () => {
    expect(IST_OFFSET_SECONDS).toBe(19800);
  });

  it('accepts date-only and T-separated forms', () => {
    expect(istStringToUtcSeconds('2024-01-15')).toBe(istStringToUtcSeconds('2024-01-15 00:00:00'));
    expect(istStringToUtcSeconds('2024-01-15T09:15')).toBe(istStringToUtcSeconds('2024-01-15 09:15:00'));
  });

  it('formats IST labels', () => {
    const sec = istStringToUtcSeconds('2024-01-15 09:05:00');
    expect(formatIstTime(sec)).toBe('09:05');
    expect(formatIstDate(sec)).toBe('15 Jan');
  });

  it('formats sub-minute (seconds / tick) clock labels', () => {
    const sec = istStringToUtcSeconds('2024-01-15 09:15:35');
    expect(formatIstTimeSeconds(sec)).toBe('09:15:35');
    // formatIstTime stays minute-resolution.
    expect(formatIstTime(sec)).toBe('09:15');
  });

  it('crosshair label shows :SS only on sub-minute bars', () => {
    const onMinute = istStringToUtcSeconds('2026-05-21 14:30:00');
    const subMinute = istStringToUtcSeconds('2026-05-21 14:30:05');
    expect(formatIstCrosshairLabel(onMinute)).toBe("Thu 21 May '26 14:30");
    expect(formatIstCrosshairLabel(subMinute)).toBe("Thu 21 May '26 14:30:05");
  });

  it('detects IST day boundaries', () => {
    const a = istStringToUtcSeconds('2024-01-15 15:30:00');
    const b = istStringToUtcSeconds('2024-01-16 09:15:00');
    const c = istStringToUtcSeconds('2024-01-15 09:15:00');
    expect(isNewIstDay(a, b)).toBe(true);
    expect(isNewIstDay(c, a)).toBe(false);
  });
});
