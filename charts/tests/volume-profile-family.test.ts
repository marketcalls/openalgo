import { describe, it, expect } from 'vitest';
import { computeVolumeProfileSessions } from '../src/profile/volume-profile-family';
import { istStringToUtcSeconds } from '../src/feed/time';
import type { Bar } from '../src/model/bar';

// helper: explicit direction via open/close
const b = (time: number, low: number, high: number, open: number, close: number, volume: number): Bar =>
  ({ time, low, high, open, close, volume });

describe('computeVolumeProfileSessions', () => {
  const t0 = istStringToUtcSeconds('2024-01-15 09:15:00');

  it('builds a composite profile with POC and value area by volume', () => {
    const bars = [
      b(t0, 100, 102, 100, 102, 300),          // up
      b(t0 + 1800, 101, 103, 103, 101, 200),   // down
    ];
    const { sessions } = computeVolumeProfileSessions(bars, { tickSize: 1, session: 'composite' });
    expect(sessions).toHaveLength(1);
    const s = sessions[0];
    expect(s.totalVolume).toBe(500);
    expect(s.levels[0].price).toBeGreaterThan(s.levels[s.levels.length - 1].price); // high -> low
    expect(s.vah).toBeGreaterThanOrEqual(s.poc);
    expect(s.poc).toBeGreaterThanOrEqual(s.val);
    const totalLevelVol = s.levels.reduce((sum, l) => sum + l.volume, 0);
    expect(Math.round(totalLevelVol)).toBe(500);
  });

  it('splits buy/sell by bar direction and computes delta', () => {
    const bars = [
      b(t0, 100, 102, 100, 102, 300),          // up   -> buy 300
      b(t0 + 1800, 100, 102, 102, 100, 100),   // down -> sell 100
    ];
    const { sessions } = computeVolumeProfileSessions(bars, { tickSize: 1, session: 'composite' });
    const s = sessions[0];
    expect(s.buyVolume).toBe(300);
    expect(s.sellVolume).toBe(100);
    expect(s.delta).toBe(200);
    // per-level delta sums to the session delta
    const levelDelta = s.levels.reduce((sum, l) => sum + l.delta, 0);
    expect(Math.round(levelDelta)).toBe(200);
  });

  it('leaves buy/sell zero when direction split is disabled', () => {
    const bars = [b(t0, 100, 102, 100, 102, 300)];
    const { sessions } = computeVolumeProfileSessions(bars, { tickSize: 1, deltaFromBarDirection: false });
    const s = sessions[0];
    expect(s.buyVolume).toBe(0);
    expect(s.sellVolume).toBe(0);
    expect(s.delta).toBe(0);
    expect(s.totalVolume).toBe(300);
  });

  it('segments by IST day', () => {
    const day2 = istStringToUtcSeconds('2024-01-16 09:15:00');
    const bars = [b(t0, 100, 102, 100, 102, 100), b(day2, 110, 112, 110, 112, 100)];
    const { sessions } = computeVolumeProfileSessions(bars, { tickSize: 1, session: 'day' });
    expect(sessions).toHaveLength(2);
  });
});
