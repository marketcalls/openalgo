export const THRESHOLDS = Object.freeze({
  frameP95Ms: 50,
  frameP99Ms: 100,
  maxFrameMs: 1000,
  slowFrameRatio: 0.05,
  pointerP95Ms: 200,
  maxPointerMs: 1000,
  heapGrowthBytes: 8 * 1024 * 1024,
  heapSlopeBytesPerMinute: 256 * 1024,
  retainedBytesPerChart: 64 * 1024,
  candlePixels: 100,
  tickDeliveryRatio: 0.85,
});

export function linearSlope(samples) {
  if (samples.length < 2 || samples.some(p => !Number.isFinite(p.seconds) || !Number.isFinite(p.heap))) return null;
  const x = samples.reduce((sum, p) => sum + p.seconds, 0) / samples.length;
  const y = samples.reduce((sum, p) => sum + p.heap, 0) / samples.length;
  let numerator = 0;
  let denominator = 0;
  for (const p of samples) {
    numerator += (p.seconds - x) * (p.heap - y);
    denominator += (p.seconds - x) ** 2;
  }
  return denominator > 0 ? numerator / denominator : null;
}

export function assessRun(report) {
  const { samples, workload, timing, interaction, rendering, teardown } = report;
  const first = samples[0];
  const last = samples.at(-1);
  const slope = linearSlope(samples);
  const growth = first && last ? Math.max(...samples.map(sample => sample.heap)) - first.heap : null;
  const gate = (name, value, limit, pass) => ({ name, value, limit, pass: Boolean(pass) });
  const atMost = (name, value, limit) => gate(name, value, limit, Number.isFinite(value) && value <= limit);
  const painted = [...rendering.before, ...rendering.after];
  return [
    gate('elapsed duration', report.elapsedSeconds, workload.durationSeconds, report.elapsedSeconds >= workload.durationSeconds),
    gate('memory samples', samples.length, 'at least 3 finite collected samples', samples.length >= 3 && slope !== null),
    ...(report.memoryProtocol?.mode === 'quiescent' ? [gate('quiescent sampling', samples.map(sample => sample.ticksDuringCollection), 'zero updates during every collection', samples.length > 0 && samples.every(sample => sample.ticksDuringCollection === 0))] : []),
    gate('constant bar count', samples.map(p => p.bars), `${workload.bars} per chart`, samples.length > 0 && samples.every(p => p.bars.length === workload.charts && p.bars.every(n => n === workload.bars))),
    gate('tick delivery', last?.ticks, workload.durationSeconds * workload.tickHz * THRESHOLDS.tickDeliveryRatio, last?.ticks >= workload.durationSeconds * workload.tickHz * THRESHOLDS.tickDeliveryRatio),
    gate('frame evidence', timing.frames, 'at least 10 frames per second', timing.frames >= workload.durationSeconds * 10),
    atMost('frame p95', timing.p95, THRESHOLDS.frameP95Ms),
    atMost('frame p99', timing.p99, THRESHOLDS.frameP99Ms),
    atMost('maximum frame gap', timing.max, THRESHOLDS.maxFrameMs),
    atMost('slow frame ratio', timing.slowFrameRatio, THRESHOLDS.slowFrameRatio),
    gate('pointer evidence', interaction.count, 'at least 2 pointer samples', interaction.count >= 2),
    atMost('pointer p95', interaction.p95, THRESHOLDS.pointerP95Ms),
    atMost('maximum pointer latency', interaction.max, THRESHOLDS.maxPointerMs),
    gate('painted candles', painted.map(p => p.candlePixels), `${THRESHOLDS.candlePixels} pixels per chart at start and end`, painted.length === workload.charts * 2 && painted.every(p => p.candlePixels >= THRESHOLDS.candlePixels)),
    gate('canvas changed', rendering.changed, 'every chart changes', rendering.changed.length === workload.charts && rendering.changed.every(Boolean)),
    atMost('live heap growth', growth, THRESHOLDS.heapGrowthBytes),
    atMost('live heap slope', slope === null ? null : slope * 60, THRESHOLDS.heapSlopeBytesPerMinute),
    gate('teardown cycles', teardown.cycles, workload.cycles, teardown.cycles === workload.cycles && workload.cycles > 0),
    atMost('teardown retention', (teardown.heapAfter - teardown.heapBefore) / teardown.cycles, THRESHOLDS.retainedBytesPerChart),
    atMost('teardown nodes', teardown.nodesAfter - teardown.nodesBefore, 10),
    atMost('teardown listeners', teardown.listenersAfter - teardown.listenersBefore, 0),
    gate('teardown canvases', teardown.canvasesAfter, 0, teardown.canvasesAfter === 0),
    gate('final canvases', report.finalCanvases, 0, report.finalCanvases === 0),
    gate('browser errors', report.errors, 0, report.errors.length === 0),
  ];
}
