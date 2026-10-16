import React, { useEffect, useRef, useState } from 'react';
import { ChartFrame, Segmented, Toggles, footprintView, useOrderFlowChart } from './OrderFlowChart';
import { OF_BAR_SECONDS, OF_TICK, orderFlowTape, type OrderFlowPrint } from './orderflow-market';

/* eslint-disable @typescript-eslint/no-explicit-any */
type ZoneKind = 'stacked' | 'node' | 'absorption';
const KINDS: readonly (readonly [ZoneKind, string])[] = [['stacked', 'Stacked imbalances'], ['node', 'Multiple nodes'], ['absorption', 'Absorption']];
const KIND_LABEL: Record<string, string> = { stackedBuy: 'Stacked buying', stackedSell: 'Stacked selling', node: 'Multiple node', absorption: 'Absorption' };

/** Bars loaded as history before the tape starts to play: touches in them are not news. */
const HISTORY = 12;
/** Bars kept on the chart; older ones roll off and their delta moves into the offset. */
const WINDOW = 30;
/** Prints per step and steps per second: a one-minute bar plays in about two seconds. */
const PRINTS_PER_STEP = 5;
const STEP_MS = 110;
const LOOP_BARS = 70;

interface Alert { id: number; time: string; kind: string; color: string; range: string }

const clock = typeof Intl === 'undefined' ? null
  : new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
const hhmm = (seconds: number) => clock ? clock.format(new Date(seconds * 1000)) : String(seconds);

interface Engine { advance: (count: number) => void }

export function ZonesLiveExample() {
  const [kinds, setKinds] = useState<ZoneKind[]>(['stacked', 'node', 'absorption']);
  const [lookback, setLookback] = useState<0 | 10 | 5>(0);
  const [playing, setPlaying] = useState(false);
  const [onScreen, setOnScreen] = useState(false);
  const [generation, setGeneration] = useState(0);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [status, setStatus] = useState({ time: '', last: 0, zones: 0 });
  const engine = useRef<Engine | null>(null);
  const section = useRef<HTMLDivElement>(null);

  // Plays by itself only for a reader who has not asked the system for less motion.
  useEffect(() => {
    const reduced = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!reduced) setPlaying(true);
  }, []);

  // A tape playing below the fold would spend the reader's battery on nothing.
  useEffect(() => {
    const element = section.current;
    if (!element || typeof IntersectionObserver === 'undefined') { setOnScreen(true); return; }
    const observer = new IntersectionObserver(entries => setOnScreen(entries.some(entry => entry.isIntersecting)), { threshold: 0.2 });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const chart = useOrderFlowChart<{ kinds: ZoneKind[]; lookback: number }>((lib, host, scheme, initial) => {
    const view = footprintView(lib, host, scheme, {
      displayMode: 'bidask', cellStyle: 'heatmap', showZones: true, zoneKinds: initial.kinds, zoneLookback: initial.lookback,
      stackedImbalances: 3, multipleNodeBars: 2, absorptionMultiple: 2, lastPriceColor: scheme === 'dark' ? '#40e0d0' : '#1b8fa0',
    });
    const footprint = view.footprint;
    const loop = orderFlowTape(LOOP_BARS);
    const aggregator = new lib.profile.FootprintAggregator({ mode: 'interval', seconds: OF_BAR_SECONDS }, OF_TICK, 1);
    const bars: any[] = [];
    let cursor = 0, cvdOffset = 0, sequence = 0;
    // The tape repeats, but its clock keeps running, so every pass makes new zones.
    const print = (index: number): OrderFlowPrint => {
      const base = loop[index % loop.length]!;
      return { ...base, time: base.time + Math.floor(index / loop.length) * LOOP_BARS * OF_BAR_SECONDS };
    };
    const take = (): boolean => {
      const { bar, isNew } = aggregator.onTick(print(cursor++));
      if (isNew) {
        bars.push(bar);
        if (bars.length > WINDOW) cvdOffset += bars.shift().delta;
      } else bars[bars.length - 1] = bar;
      return isNew;
    };
    const paint = (refit: boolean) => {
      footprint.setOptions({ cvdOffset });
      view.setBars(bars);
      if (refit) view.fit({ minSpacing: 96 });
      const newest = bars[bars.length - 1];
      // signals() keeps every kind; count only the ones the chart extends.
      const kinds: string[] = footprint.options().zoneKinds;
      const group = (kind: string) => (kind === 'stackedBuy' || kind === 'stackedSell' ? 'stacked' : kind);
      const zones = footprint.signals().zones.filter((zone: any) => zone.endTime === null && kinds.includes(group(zone.kind))).length;
      setStatus({ time: hhmm(newest.time), last: newest.close, zones });
    };
    const unsubscribe = footprint.onZoneAlert(({ zone, time }: any) => {
      const o = footprint.options();
      const color = zone.kind === 'stackedBuy' ? (o.imbalanceBuyColor ?? o.buyColor) : zone.kind === 'stackedSell' ? (o.imbalanceSellColor ?? o.sellColor)
        : zone.kind === 'node' ? o.nodeColor : o.absorptionColor;
      const entry = { id: ++sequence, time: hhmm(time), kind: KIND_LABEL[zone.kind] ?? zone.kind, color, range: `${zone.low.toFixed(1)} to ${zone.high.toFixed(1)}` };
      setAlerts(list => [entry, ...list].slice(0, 30));
    });
    // Whole bars of history first, stopping on the first print of the bar after
    // them; the footprint treats whatever its first bars touched as already seen.
    while (!(take() && bars.length > HISTORY));
    paint(true);
    setAlerts([]);
    engine.current = {
      advance(count) {
        let fresh = false;
        for (let i = 0; i < count; i++) fresh = take() || fresh;
        paint(fresh);
      },
    };
    return {
      apply(state) { footprint.setOptions({ zoneKinds: state.kinds, zoneLookback: state.lookback }); },
      destroy() { engine.current = null; unsubscribe(); view.destroy(); },
    };
  }, { kinds, lookback }, generation);

  useEffect(() => {
    if (!chart.ready || !playing || !onScreen) return;
    const timer = window.setInterval(() => engine.current?.advance(PRINTS_PER_STEP), STEP_MS);
    return () => window.clearInterval(timer);
  }, [chart.ready, playing, onScreen]);

  const code = `const footprint = new Footprint({
  showZones: true,
  zoneKinds: [${kinds.map(kind => `'${kind}'`).join(', ')}],
  zoneLookback: ${lookback},   // ${lookback === 0 ? 'zones may start in any loaded bar' : `zones start only in the newest ${lookback} bars`}
  stackedImbalances: 3, multipleNodeBars: 2, absorptionMultiple: 2,
});
const unsubscribe = footprint.onZoneAlert(({ zone, time }) => {
  log(time, zone.kind, zone.low, zone.high);   // once per zone, when price comes back to it
});
const { bar, isNew } = aggregator.onTick(print);   // then footprint.setBars(bars) as each print lands`;

  const side = (
    <div className="oac-of__side">
      <h4>Zone alerts</h4>
      <ol className="oac-of__log" role="log" aria-live="polite" aria-label="Zone alerts">
        {alerts.length === 0 && <li className="oac-of__empty">{playing ? 'Waiting for price to come back into a zone.' : 'Press Play to run the tape. Alerts appear here.'}</li>}
        {alerts.map(alert => (
          <li key={alert.id}>
            <time>{alert.time}</time>
            <span><i className="oac-of__kind" style={{ background: alert.color }} />{alert.kind}</span>
            <small>{alert.range}</small>
          </li>
        ))}
      </ol>
    </div>
  );

  return (
    <div ref={section}>
      <ChartFrame chart={chart} height={420} code={code} side={side} label="Zones extended to the right, with live zone alerts"
        controls={<>
          <div className="oac-of__group">
            <span className="oac-of__label">Tape</span>
            <div className="oac-of__actions">
              <button type="button" className="oac-of__button oac-of__button--primary" disabled={!chart.ready}
                onClick={() => setPlaying(value => !value)} aria-pressed={playing}>{playing ? 'Pause' : 'Play'}</button>
              <button type="button" className="oac-of__button" disabled={!chart.ready}
                onClick={() => setGeneration(value => value + 1)}>Restart</button>
            </div>
          </div>
          <Toggles label="Zone kinds" value={kinds} onChange={setKinds} options={KINDS} />
          <Segmented label="Zones start in" value={lookback} onChange={setLookback} options={[[0, 'Every bar'], [10, 'Last 10'], [5, 'Last 5']]} />
        </>}
        status={status.time && <span>{playing ? (onScreen ? 'Playing' : 'Paused off screen') : 'Paused'} · bar <b>{status.time}</b> · last <b>{status.last.toFixed(0)}</b> · <b>{status.zones}</b> zones extending</span>} />
    </div>
  );
}
