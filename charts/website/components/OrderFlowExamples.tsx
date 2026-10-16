import React, { useState } from 'react';
import {
  ChartFrame, Segmented, Select, Toggles, aggregate, chartTheme, footprintView, siteColors, useOrderFlowChart,
} from './OrderFlowChart';
import { OF_LOT, OF_TICK, inQuantityUnits, orderFlowTape, type OrderFlowPrint } from './orderflow-market';

/* eslint-disable @typescript-eslint/no-explicit-any */
// One tape for every static example, so the same bar can be read in each of them.
let tape: OrderFlowPrint[] | null = null;
const history = () => (tape ??= orderFlowTape());
let longTape: OrderFlowPrint[] | null = null;
const longHistory = () => (longTape ??= orderFlowTape(40));

/* ------------------------------------------------------------------ basics */

const BASICS_CODE = `const aggregator = new FootprintAggregator({ mode: 'interval', seconds: 60 }, tickSize, rowTicks);
const bars = [];
for (const print of tape) {                 // { time, price, qty, side: 'bid' | 'ask' }
  const { bar, isNew } = aggregator.onTick(print);
  if (isNew) bars.push(bar); else bars[bars.length - 1] = bar;
}
const footprint = new Footprint({ tickSize: tickSize * rowTicks, displayMode: 'bidask', showPoc: true, pocStyle: 'outline' });
chart.addPrimitive(footprint);
footprint.setBars(bars);`;

export function FootprintBasics() {
  const [rowTicks, setRowTicks] = useState<1 | 2 | 4>(1);
  const chart = useOrderFlowChart<{ rowTicks: number }>((lib, host, scheme) => {
    const view = footprintView(lib, host, scheme, { displayMode: 'bidask', stackedImbalances: 0 });
    return {
      apply(state) {
        view.footprint.setOptions({ tickSize: OF_TICK * state.rowTicks });
        view.setBars(aggregate(lib.profile, history(), state.rowTicks));
        view.fit({ minSpacing: 100 });
      },
      destroy: view.destroy,
    };
  }, { rowTicks });
  return (
    <ChartFrame chart={chart} height={380} code={BASICS_CODE} label="Bid by ask footprint with point of control"
      controls={<Segmented label="Row size" value={rowTicks} onChange={setRowTicks}
        options={[[1, '1 point'], [2, '2 points'], [4, '4 points']]} />}
      status={<span>Bid on the left, ask on the right · <b>outlined row</b> is the POC</span>} />
  );
}

/* -------------------------------------------------------------- imbalances */

const IMBALANCE_CODE = `const footprint = new Footprint({
  displayMode: 'imbalance',   // plain cells, imbalanced ones filled
  imbalanceRatio: 3,          // ask at a row against the bid one row lower, and the reverse
  stackedImbalances: 3,       // three in a row on one side draws a bracket
  showEmptyRows: true,        // draw a row the price jumped over as 0 x 0
});`;

export function ImbalanceExample() {
  const [ratio, setRatio] = useState<2 | 3 | 4>(3);
  const [emptyRows, setEmptyRows] = useState(true);
  const [count, setCount] = useState<{ imbalances: number; stacked: number } | null>(null);
  const chart = useOrderFlowChart<{ ratio: number; emptyRows: boolean }>((lib, host, scheme) => {
    const view = footprintView(lib, host, scheme, { displayMode: 'imbalance', stackedImbalances: 3 });
    const bars = aggregate(lib.profile, history());
    view.setBars(bars);
    return {
      apply(state) {
        view.footprint.setOptions({ imbalanceRatio: state.ratio, showEmptyRows: state.emptyRows });
        // The page counts with the same pure functions the footprint draws with.
        let imbalances = 0, stacked = 0;
        for (const bar of bars) {
          imbalances += lib.profile.diagonalImbalances(bar.cells, state.ratio, bar.rowSize).length;
          stacked += lib.profile.stackedImbalances(bar.cells, state.ratio, 3, bar.rowSize).length;
        }
        setCount({ imbalances, stacked });
        view.fit({ minSpacing: 100, first: 0 });
      },
      destroy: view.destroy,
    };
  }, { ratio, emptyRows });
  return (
    <ChartFrame chart={chart} height={400} code={IMBALANCE_CODE} label="Diagonal and stacked imbalances"
      controls={<>
        <Segmented label="Imbalance ratio" value={ratio} onChange={setRatio} options={[[2, '2x'], [3, '3x'], [4, '4x']]} />
        <Toggles label="Rows" value={emptyRows ? ['empty'] : []} onChange={value => setEmptyRows(value.includes('empty'))}
          options={[['empty', 'Show untraded rows']]} />
      </>}
      status={count && <span><b>{count.imbalances}</b> imbalances · <b>{count.stacked}</b> stacked runs in 14 bars</span>} />
  );
}

/* ----------------------------------------------------------- display modes */

type Mode = 'delta' | 'deltaPct' | 'deltaShadedVolume' | 'volume' | 'volumeDelta';
const MODES: readonly (readonly [Mode, string])[] = [
  ['deltaShadedVolume', 'Delta-shaded volume'], ['delta', 'Delta'], ['deltaPct', 'Delta %'], ['volume', 'Volume'], ['volumeDelta', 'Volume and delta'],
];

export function DisplayModesExample() {
  const [mode, setMode] = useState<Mode>('deltaShadedVolume');
  const chart = useOrderFlowChart<{ mode: Mode }>((lib, host, scheme) => {
    const view = footprintView(lib, host, scheme, { stackedImbalances: 0 });
    view.setBars(aggregate(lib.profile, history()));
    return {
      apply(state) { view.footprint.setOptions({ displayMode: state.mode }); view.fit({ minSpacing: 88 }); },
      destroy: view.destroy,
    };
  }, { mode });
  return (
    <ChartFrame chart={chart} height={380} label="Single-value footprint display modes"
      code={`footprint.setOptions({ displayMode: '${mode}' });`}
      controls={<Segmented label="Values per row" value={mode} onChange={setMode} options={MODES} />} />
  );
}

/* ------------------------------------------------------------- cell styles */

type CellStyle = 'heatmap' | 'profile' | 'ladder';

export function CellStylesExample() {
  const [style, setStyle] = useState<CellStyle>('profile');
  const [scope, setScope] = useState<'bar' | 'visible'>('bar');
  const chart = useOrderFlowChart<{ style: CellStyle; scope: 'bar' | 'visible' }>((lib, host, scheme) => {
    const view = footprintView(lib, host, scheme, { displayMode: 'bidask', stackedImbalances: 0 });
    view.setBars(aggregate(lib.profile, history()));
    return {
      apply(state) { view.footprint.setOptions({ cellStyle: state.style, intensityScope: state.scope }); view.fit({ minSpacing: 100 }); },
      destroy: view.destroy,
    };
  }, { style, scope });
  return (
    <ChartFrame chart={chart} height={380} label="Footprint cell styles"
      code={`footprint.setOptions({ cellStyle: '${style}', intensityScope: '${scope}' });`}
      controls={<>
        <Segmented label="Cell style" value={style} onChange={setStyle} options={[['heatmap', 'Heatmap'], ['profile', 'Profile'], ['ladder', 'Ladder']]} />
        <Segmented label="Shade against" value={scope} onChange={setScope} options={[['bar', 'Busiest row in the bar'], ['visible', 'Busiest row on screen']]} />
      </>} />
  );
}

/* ----------------------------------------------------------------- signals */

type Layer = 'bigOrders' | 'absorption' | 'nodes' | 'flips' | 'delta' | 'auctions';
const LAYERS: readonly (readonly [Layer, string])[] = [
  ['bigOrders', 'Big limit orders'], ['absorption', 'Absorption'], ['nodes', 'Multiple nodes'],
  ['flips', 'Delta flips'], ['delta', 'Delta and divergence'], ['auctions', 'Unfinished auctions'],
];

function layerOptions(layers: readonly Layer[]) {
  const on = (layer: Layer) => layers.includes(layer);
  return {
    bigOrderMultiple: on('bigOrders') ? 3 : 0, absorptionMultiple: on('absorption') ? 2 : 0, multipleNodeBars: on('nodes') ? 2 : 0,
    flipBars: on('flips') ? 2 : 0, showDeltaLabels: on('delta'), markDivergence: on('delta'), showUnfinishedAuctions: on('auctions'),
  };
}

const SIGNALS_CODE = `footprint.setOptions({
  bigOrderMultiple: 3,        // a print of 3x the average cell near the bar's high or low
  absorptionMultiple: 2,      // bid and ask both at 2x their average cell
  multipleNodeBars: 2,        // two bars in a row share a point of control
  flipBars: 2,                // delta turns after two bars of the other sign
  showDeltaLabels: true, markDivergence: true,
  showUnfinishedAuctions: true,
});
const { bars, auctions } = footprint.signals();   // the same findings, for alerts or a scanner`;

export function SignalsExample() {
  const [layers, setLayers] = useState<Layer[]>(LAYERS.map(([id]) => id));
  const [found, setFound] = useState('');
  const chart = useOrderFlowChart<{ layers: Layer[] }>((lib, host, scheme) => {
    const view = footprintView(lib, host, scheme, { displayMode: 'bidask', cellStyle: 'profile', stackedImbalances: 0 },
      { priceScale: { minMove: OF_TICK, marginTop: 0.06, marginBottom: 0.12 } });
    view.setBars(aggregate(lib.profile, history()));
    return {
      apply(state) {
        view.footprint.setOptions(layerOptions(state.layers));
        const signals = view.footprint.signals();
        const sum = (test: (bar: any) => boolean) => signals.bars.filter(test).length;
        const parts = [
          state.layers.includes('bigOrders') && `${sum(bar => bar.bigBid !== null || bar.bigAsk !== null)} big orders`,
          state.layers.includes('absorption') && `${sum(bar => bar.absorption.length > 0)} absorption bars`,
          state.layers.includes('nodes') && `${sum(bar => bar.node)} node bars`,
          state.layers.includes('flips') && `${sum(bar => bar.flip !== 0)} flip`,
          state.layers.includes('delta') && `${sum(bar => bar.divergence)} divergences`,
          state.layers.includes('auctions') && `${signals.auctions.length} unfinished auctions`,
        ].filter(Boolean);
        setFound(parts.length ? parts.join(' · ') : 'Every layer is off');
        view.fit({ minSpacing: 92, first: 1 });
      },
      destroy: view.destroy,
    };
  }, { layers });
  return (
    <ChartFrame chart={chart} height={420} code={SIGNALS_CODE} label="Order flow signals"
      controls={<Toggles label="Layers" value={layers} onChange={setLayers} options={LAYERS} />}
      status={found && <span>{found}</span>} />
  );
}

/* ---------------------------------------------------------- statistics table */

const TABLE_ROWS = ['session', 'askVolume', 'bidVolume', 'delta', 'deltaPct', 'maxDelta', 'minDelta', 'cvd', 'cvdRatio', 'volume', 'cumVolume'];
const TABLE_CODE = `const footprint = new Footprint({
  tableRows: ['session', 'askVolume', 'bidVolume', 'delta', 'deltaPct', 'maxDelta', 'minDelta',
              'cvd', 'cvdRatio', 'volume', 'cumVolume'],
  sessionWindow: TRADING_HOURS.india,   // letters and resets count from this session's open
  cvdReset: 'session',                  // cumulative delta and volume restart at each open
  tpoMinutes: 5,                        // one letter per five minutes, so 14 bars span A to C
});
// Leave room under the columns for the table.
chart.setPriceScaleOptions({ marginBottom: (rows * rowHeight + 24) / plotHeight });`;

const TABLE_HEIGHT = 470, ROW_HEIGHT = 15, LABEL_WIDTH = 140;

export function StatsTableExample() {
  const chart = useOrderFlowChart<Record<string, never>>((lib, host, scheme) => {
    const plot = TABLE_HEIGHT - 26;
    const view = footprintView(lib, host, scheme, {
      displayMode: 'bidask', stackedImbalances: 0, tableRows: TABLE_ROWS, statsRowHeight: ROW_HEIGHT, tableLabelWidth: LABEL_WIDTH,
      sessionWindow: lib.profile.TRADING_HOURS.india, tpoMinutes: 5, cvdReset: 'session',
    }, { priceScale: { minMove: OF_TICK, marginTop: 0.05, marginBottom: Math.min(0.6, (TABLE_ROWS.length * ROW_HEIGHT + 24) / plot) } }, 'top-left');
    view.setBars(aggregate(lib.profile, history()));
    return {
      apply() { view.fit({ minSpacing: 92, reserveLeft: LABEL_WIDTH, first: 0 }); },
      destroy: view.destroy,
    };
  }, {});
  return (
    <ChartFrame chart={chart} height={TABLE_HEIGHT} code={TABLE_CODE} label="Footprint statistics table"
      status={<span>Session letter, volume by side, delta and the running totals for each bar</span>} />
  );
}

/* --------------------------------------------------- visible-range profile */

const PROFILE_WIDTH = 110;
const PROFILE_CODE = `const footprint = new Footprint({
  showVisibleProfile: true,     // volume at price of the bars on screen, ask and bid split
  profileWidth: 110,
  profileAskColor: '#159d87',
  profileBidColor: '#cc374b',
});`;

export function VisibleProfileExample() {
  const chart = useOrderFlowChart<Record<string, never>>((lib, host, scheme) => {
    const colors = siteColors(scheme);
    const view = footprintView(lib, host, scheme, {
      displayMode: 'bidask', stackedImbalances: 0, showVisibleProfile: true, profileWidth: PROFILE_WIDTH,
      profileAskColor: colors.buyColor, profileBidColor: colors.sellColor,
    }, {}, 'bottom-right');
    view.setBars(aggregate(lib.profile, longHistory()));
    return {
      apply() { view.fit({ minSpacing: 96, reserveLeft: PROFILE_WIDTH + 12, first: 0 }); },
      destroy: view.destroy,
    };
  }, {});
  return (
    <ChartFrame chart={chart} height={400} code={PROFILE_CODE} label="Visible-range volume profile beside the footprints"
      status={<span>Drag the chart to the left for newer bars: the profile is rebuilt from the bars on screen</span>} />
  );
}

/* ------------------------------------------------------------------ themes */

type ThemeName = 'ocean' | 'ember' | 'forest' | 'neon' | 'monochrome' | 'daylight';
const THEMES: readonly (readonly [ThemeName, string])[] = [
  ['ocean', 'Ocean'], ['ember', 'Ember'], ['forest', 'Forest'], ['neon', 'Neon'], ['monochrome', 'Monochrome'], ['daylight', 'Daylight (light chart)'],
];
// A theme sets footprint colours only, so the host picks the background it was made for.
const BACKGROUND: Record<ThemeName, { background: string; grid: string; axisLine: string }> = {
  ocean: { background: '#0b1622', grid: '#122130', axisLine: '#1f3346' },
  ember: { background: '#140e0b', grid: '#211812', axisLine: '#3a2a1d' },
  forest: { background: '#0c1510', grid: '#142219', axisLine: '#24382b' },
  neon: { background: '#07070d', grid: '#11111c', axisLine: '#24243a' },
  monochrome: { background: '#101010', grid: '#1a1a1a', axisLine: '#303030' },
  daylight: { background: '#fbfbf9', grid: '#eef0f2', axisLine: '#d8dce0' },
};

export function ThemesExample() {
  const [theme, setTheme] = useState<ThemeName>('ocean');
  const chart = useOrderFlowChart<{ theme: ThemeName }>((lib, host, scheme) => {
    const view = footprintView(lib, host, scheme, {
      displayMode: 'bidask', cellStyle: 'profile', stackedImbalances: 3, multipleNodeBars: 2, showUnfinishedAuctions: true,
      showDeltaLabels: true, markDivergence: true, tableRows: ['session', 'delta', 'volume'], statsRowHeight: 15, tableLabelWidth: 110,
      sessionWindow: lib.profile.TRADING_HOURS.india, tpoMinutes: 5, buyTextColor: undefined, sellTextColor: undefined,
    }, { priceScale: { minMove: OF_TICK, marginTop: 0.05, marginBottom: 0.24 } }, 'top-left');
    view.setBars(aggregate(lib.profile, history()));
    return {
      apply(state) {
        const light = state.theme === 'daylight';
        view.chart.setTheme({ ...chartTheme(lib.core, light ? 'light' : 'dark'), ...BACKGROUND[state.theme],
          lastPriceText: BACKGROUND[state.theme].background });
        view.footprint.setOptions({ ...lib.profile.FOOTPRINT_THEMES[state.theme] });
        view.fit({ minSpacing: 96, reserveLeft: 110, first: 0 });
      },
      destroy: view.destroy,
    };
  }, { theme });
  return (
    <ChartFrame chart={chart} height={420} label="Footprint colour themes"
      code={`import { Footprint, FOOTPRINT_THEMES } from 'openalgo-charts/profile';

const footprint = new Footprint({ ...FOOTPRINT_THEMES.${theme}, displayMode: 'bidask' });
footprint.setOptions(FOOTPRINT_THEMES.${theme === 'ocean' ? 'daylight' : 'ocean'});   // switch later without rebuilding`}
      controls={<Select label="Theme" value={theme} onChange={setTheme} options={THEMES} />}
      status={<span>{theme === 'daylight' ? 'Made for a light chart' : 'Made for a dark chart'}</span>} />
  );
}

/* --------------------------------------------------- trade size and lots */

const LOT_TAPE = () => inQuantityUnits(history());

export function TradeFilterExample() {
  const [minLots, setMinLots] = useState<0 | 5 | 10 | 20>(0);
  const [units, setUnits] = useState<'raw' | 'lots'>('lots');
  const [counted, setCounted] = useState<string>('');
  const chart = useOrderFlowChart<{ minLots: number; units: 'raw' | 'lots' }>((lib, host, scheme) => {
    const view = footprintView(lib, host, scheme, {
      displayMode: 'bidask', stackedImbalances: 0, statsPosition: 'bar', statsRows: ['volume', 'delta', 'trades'], statsRowHeight: 16,
    }, { priceScale: { minMove: OF_TICK, marginTop: 0.05, marginBottom: 0.2 } });
    const prints = LOT_TAPE();
    let filter = -1;
    return {
      apply(state) {
        if (state.minLots !== filter) {
          filter = state.minLots;
          const bars = aggregate(lib.profile, prints, 1, state.minLots * OF_LOT);
          view.setBars(bars);
          const kept = bars.reduce((sum: number, bar: any) => sum + bar.tradeCount, 0);
          setCounted(`${kept} of ${prints.length} prints counted`);
        }
        view.footprint.setOptions({ volumeDivisor: state.units === 'lots' ? OF_LOT : 1 });
        view.fit({ minSpacing: 104 });
      },
      destroy: view.destroy,
    };
  }, { minLots, units });
  return (
    <ChartFrame chart={chart} height={420} label="Trade size filter and lot display"
      code={`// The feed reports quantity; one lot is ${OF_LOT}.
const aggregator = new FootprintAggregator({ mode: 'interval', seconds: 60 }, tickSize, 1, { minTradeSize: ${minLots * OF_LOT} });
const footprint = new Footprint({ volumeDivisor: ${units === 'lots' ? OF_LOT : 1} });   // ${units === 'lots' ? 'print lots' : 'print raw quantity'}`}
      controls={<>
        <Select label="Count prints of at least" value={minLots} onChange={setMinLots}
          options={[[0, 'Every print'], [5, '5 lots'], [10, '10 lots'], [20, '20 lots']]} />
        <Segmented label="Show quantities as" value={units} onChange={setUnits} options={[['lots', 'Lots'], ['raw', 'Raw quantity']]} />
      </>}
      status={counted && <span>{counted}</span>} />
  );
}
