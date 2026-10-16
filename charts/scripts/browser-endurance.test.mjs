import assert from 'node:assert/strict';
import test from 'node:test';
import { assessRun, linearSlope, THRESHOLDS } from './browser-endurance-metrics.mjs';

function report() {
  return {
    workload: { durationSeconds: 60, tickHz: 10, bars: 2000, charts: 2, cycles: 20 },
    elapsedSeconds: 60,
    samples: [0, 30, 60].map(seconds => ({ seconds, heap: 8_000_000, bars: [2000, 2000], ticks: seconds * 10 })),
    timing: { frames: 3000, p95: 17, p99: 34, max: 100, slowFrameRatio: 0.001, longTasks: 0 },
    interaction: { count: 10, p95: 30, max: 40 },
    rendering: { before: [{ candlePixels: 500 }, { candlePixels: 500 }], after: [{ candlePixels: 500 }, { candlePixels: 500 }], changed: [true, true] },
    teardown: { cycles: 20, heapBefore: 3_000_000, heapAfter: 3_100_000, canvasesAfter: 0, nodesBefore: 10, nodesAfter: 10, listenersBefore: 1, listenersAfter: 1 },
    finalCanvases: 0,
    errors: [],
  };
}

test('slope uses elapsed minutes so irregular samples cannot hide retention', () => {
  assert.equal(linearSlope([{ seconds: 0, heap: 0 }, { seconds: 30, heap: 100 }, { seconds: 120, heap: 400 }]) * 60, 200);
  assert.equal(linearSlope([{ seconds: 1, heap: 10 }]), null);
});

test('bounded heap with painted candles and responsive frames passes', () => {
  const gates = assessRun(report());
  assert.ok(gates.length > 10);
  assert.ok(gates.every(gate => gate.pass), JSON.stringify(gates));
});

test('missing frame, memory, interaction and rendering evidence fails closed', () => {
  const value = report();
  value.samples = [];
  value.timing.frames = 0;
  value.interaction.count = 0;
  value.rendering.after = [];
  const failed = assessRun(value).filter(gate => !gate.pass).map(gate => gate.name);
  for (const name of ['memory samples', 'frame evidence', 'pointer evidence', 'painted candles']) assert.ok(failed.includes(name), name);
});

test('bar append, stale canvas, frame stalls, retention and errors trip their gates', () => {
  const value = report();
  value.samples[2].bars[1]++;
  value.samples[2].heap += 30_000_000;
  value.rendering.changed[1] = false;
  value.timing.p99 = THRESHOLDS.frameP99Ms + 1;
  value.teardown.heapAfter += 30_000_000;
  value.teardown.listenersAfter++;
  value.errors.push('page crashed');
  const failed = assessRun(value).filter(gate => !gate.pass).map(gate => gate.name);
  for (const name of ['constant bar count', 'canvas changed', 'frame p99', 'live heap growth', 'live heap slope', 'teardown retention', 'teardown listeners', 'browser errors']) assert.ok(failed.includes(name), name);
});

test('short wall time and suppressed tick delivery cannot pass a long workload', () => {
  const value = report();
  value.elapsedSeconds = 10;
  value.samples[2].ticks = 5;
  const failed = assessRun(value).filter(gate => !gate.pass).map(gate => gate.name);
  assert.ok(failed.includes('elapsed duration'));
  assert.ok(failed.includes('tick delivery'));
});

test('collected heap spikes cannot be hidden by a low final sample', () => {
  const value = report();
  value.samples[1].heap += THRESHOLDS.heapGrowthBytes + 1;
  assert.equal(assessRun(value).find(gate => gate.name === 'live heap growth').pass, false);
});

test('quiescent memory evidence fails if data changes during collection or the count is absent', () => {
  const value = report();
  value.memoryProtocol = { mode: 'quiescent' };
  for (const sample of value.samples) sample.ticksDuringCollection = 0;
  assert.equal(assessRun(value).find(gate => gate.name === 'quiescent sampling')?.pass, true);
  value.samples[1].ticksDuringCollection = 1;
  assert.equal(assessRun(value).find(gate => gate.name === 'quiescent sampling')?.pass, false);
  delete value.samples[1].ticksDuringCollection;
  assert.equal(assessRun(value).find(gate => gate.name === 'quiescent sampling')?.pass, false);
});
