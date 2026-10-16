import type { MarketDepth } from '../../src/feed/types';
import type { Bar } from '../../src/model/bar';

export const DEPTH_TICK_SIZE = 0.05;
export type DepthScenario = 'option-option' | 'spot-option';

function noise(index: number, salt: number): number {
  let state = (Math.imul(index + 1000, 1664525) + Math.imul(salt, 1013904223)) >>> 0;
  state ^= state << 13; state >>>= 0;
  state ^= state >>> 17;
  state ^= state << 5; state >>>= 0;
  return state / 4294967296;
}

function chartTicks(sequence: number): number {
  let ticks = 2000;
  const trends = [1, 0, -1, 1, -1];
  for (let i = -100; i <= sequence; i++) {
    const regime = Math.floor((i + 100) / 19) % trends.length;
    ticks += Math.floor(noise(i, 1) * 5) - 2 + trends[regime];
  }
  return Math.max(100, ticks);
}

function chartClose(sequence: number, scenario: DepthScenario): number {
  const change = chartTicks(sequence) - 2000;
  return scenario === 'spot-option'
    ? Math.round((24000 + change * 1.4) * 100) / 100
    : chartTicks(sequence) * DEPTH_TICK_SIZE;
}

export function chartBar(sequence: number, scenario: DepthScenario): Bar {
  const open = chartClose(sequence - 1, scenario);
  const close = chartClose(sequence, scenario);
  const tick = scenario === 'spot-option' ? 0.05 : DEPTH_TICK_SIZE;
  const upper = scenario === 'spot-option' ? 0.8 + noise(sequence, 3) * 2.7 : tick * (1 + Math.floor(noise(sequence, 3) * 3));
  const lower = scenario === 'spot-option' ? 0.8 + noise(sequence, 4) * 2.7 : tick * (1 + Math.floor(noise(sequence, 4) * 3));
  const round = (value: number): number => Math.round(value * 100) / 100;
  return {
    time: 1700000000 + (sequence + 80) * 60,
    open, close,
    high: round(Math.max(open, close) + upper),
    low: round(Math.min(open, close) - lower),
    volume: Math.round(700 + noise(sequence, 5) * 950 + (sequence % 31 === 0 ? 1500 : 0)),
  };
}

export function makeDepth(frame: number, levels: number): MarketDepth {
  const centreTick = chartTicks(frame);
  const side = (direction: number) => Array.from({ length: levels }, (_, index) => ({
    price: ((centreTick + direction * (index + 1)) * 5) / 100,
    qty: 20 + ((index * 37 + frame * 19 + (direction > 0 ? 43 : 0)) % 180)
      + (index % 11 === 0 ? 240 : 0),
  }));
  return { bids: side(-1), asks: side(1), ltp: centreTick * DEPTH_TICK_SIZE };
}
