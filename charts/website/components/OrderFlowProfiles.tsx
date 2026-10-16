import React, { useState } from 'react';
import { ChartFrame, Segmented, Toggles, chartTheme, siteColors, useOrderFlowChart, type Scheme } from './OrderFlowChart';
import { profileSessions, type ProfileBar } from './orderflow-market';

/* eslint-disable @typescript-eslint/no-explicit-any */
let sessions: ProfileBar[] | null = null;
const bars = () => (sessions ??= profileSessions(3));
const TICK = 0.05;

// The light palette is the full-size demo's light preset: the default period
// hues are made for a dark background and wash out on white.
function profilePalette(scheme: Scheme) {
  return scheme === 'dark' ? {
    labelColor: '#c9ced8', countColor: '#d7dce8', volumeColor: '#2f7f8f', fillValueArea: true, valueAreaFillOpacity: 0.07,
  } : {
    periodColors: ['#243d58', '#395477', '#275f70', '#226756', '#506331', '#765722', '#855134', '#87454e', '#754b71', '#65517f', '#405b85', '#356269'],
    color: '#405b72', vaColor: '#193e56', volumeColor: '#84a7bb', countColor: '#263545', fillValueArea: true,
    valueAreaFillColor: '#547e99', valueAreaFillOpacity: 0.06, pocColor: '#a24929', vahColor: '#8495a2', valColor: '#8495a2',
    ibColor: '#537552', poorColor: '#996318', sessionOpenColor: '#075fc0', lastPriceColor: '#b03220',
    buyTailColor: '#267954', sellTailColor: '#b54436', labelColor: '#45566b', singlePrintColor: '#b54436',
  };
}

/* ------------------------------------------------------------ market profile */

type ColorMode = 'period' | 'valueArea' | 'volume';
type MpLayer = 'ib' | 'volume' | 'split';

export function MarketProfileExample() {
  const [rowPoints, setRowPoints] = useState<2 | 4 | 5>(4);
  const [color, setColor] = useState<ColorMode>('period');
  const [layers, setLayers] = useState<MpLayer[]>(['ib', 'volume']);
  const [summary, setSummary] = useState('');
  const chart = useOrderFlowChart<{ rowPoints: number; color: ColorMode; layers: MpLayer[] }>((lib, host, scheme) => {
    const { core, profile } = lib;
    const chart = core.createChart(host, { theme: chartTheme(core, scheme), priceAxisWidth: 62, timeAxisHeight: 26,
      priceScale: { marginTop: 0.05, marginBottom: 0.05 } });
    try {
      // The letters are the picture; the bars are only there to give the profile its sessions and time axis.
      const price = chart.addSeries('candlestick');
      price.setData(bars());
      price.applyOptions({ visible: false });
      const mp = new profile.MarketProfile(null, {
        blockDisplay: 'compact', letterWidth: 7, profileSpacing: 12, showPocLabel: false, showValueAreaLabels: false,
        showSessionLabel: false, showSessionOpen: true, showLastPrice: true, volumeProfileWidth: 46, ...profilePalette(scheme),
      });
      chart.addPrimitive(mp, 0);
      let rows = 0;
      return {
        apply(state) {
          if (state.rowPoints !== rows) {
            rows = state.rowPoints;
            const result = profile.computeMarketProfile(bars(), {
              tickSize: TICK, rowTicks: Math.round(state.rowPoints / TICK), session: 'day', blockMinutes: 30,
              valueAreaPercent: 0.7, initialBalancePeriods: 2,
            });
            mp.setData(result);
            const last = result.sessions[result.sessions.length - 1];
            if (last) setSummary(`Latest day: POC ${last.poc.toFixed(0)} · value area ${last.val.toFixed(0)} to ${last.vah.toFixed(0)} · initial balance ${last.initialBalance.low.toFixed(0)} to ${last.initialBalance.high.toFixed(0)}`);
          }
          mp.setOptions({
            colorMode: state.color, showInitialBalance: state.layers.includes('ib'),
            showVolumeProfile: state.layers.includes('volume'), split: state.layers.includes('split'),
          });
          // A little room each side, so the first date label and the last profile clear the edges.
          chart.timeScale.setVisibleLogicalRange({ from: -8, to: bars().length + 5 });
        },
        destroy() { chart.destroy(); },
      };
    } catch (error) {
      chart.destroy();
      throw error;
    }
  }, { rowPoints, color, layers });
  return (
    <ChartFrame chart={chart} height={420} label="Market profile with TPO letters"
      code={`const result = computeMarketProfile(bars, {
  tickSize: 0.05, rowTicks: ${Math.round(rowPoints / TICK)},        // ${rowPoints}-point rows
  session: 'day', blockMinutes: 30,      // one letter per 30 minutes: A, B, C ...
  valueAreaPercent: 0.7, initialBalancePeriods: 2,
});
chart.addPrimitive(new MarketProfile(result, {
  colorMode: '${color}', showInitialBalance: ${layers.includes('ib')}, showVolumeProfile: ${layers.includes('volume')}, split: ${layers.includes('split')},
}));`}
      controls={<>
        <Segmented label="Row" value={rowPoints} onChange={setRowPoints} options={[[2, '2 points'], [4, '4 points'], [5, '5 points']]} />
        <Segmented label="Colour by" value={color} onChange={setColor} options={[['period', 'Period'], ['valueArea', 'Value area'], ['volume', 'Volume']]} />
        <Toggles label="Show" value={layers} onChange={setLayers} options={[['ib', 'Initial balance'], ['volume', 'Volume'], ['split', 'Split periods']]} />
      </>}
      status={summary && <span>{summary}</span>} />
  );
}

/* ------------------------------------------------------------ volume profile */

type VpMode = 'total' | 'buySell' | 'delta';
type VpSession = 'day' | 'composite';

export function VolumeProfileExample() {
  const [mode, setMode] = useState<VpMode>('buySell');
  const [session, setSession] = useState<VpSession>('day');
  const [summary, setSummary] = useState('');
  const chart = useOrderFlowChart<{ mode: VpMode; session: VpSession }>((lib, host, scheme) => {
    const { core, profile } = lib;
    const colors = siteColors(scheme);
    const chart = core.createChart(host, { theme: chartTheme(core, scheme), priceAxisWidth: 62, timeAxisHeight: 26 });
    try {
      const price = chart.addSeries('candlestick', { style: {
        upColor: colors.buyColor, downColor: colors.sellColor, wickUpColor: colors.buyColor, wickDownColor: colors.sellColor,
        borderUpColor: colors.buyColor, borderDownColor: colors.sellColor,
      } });
      price.setData(bars());
      const vp = new profile.VolumeProfile(null, {
        // Lines without labels: three sessions side by side leave no room for them
        // at a session's edge, so the page prints the latest day's levels instead.
        width: 90, opacity: 0.8, buyColor: colors.buyColor, sellColor: colors.sellColor, showPocLabel: false, showValueAreaLabels: false,
        barColor: scheme === 'dark' ? '#4b6a86' : '#9db4c8', valueAreaFillColor: scheme === 'dark' ? '#4a6fa5' : '#7d9cc4',
      });
      chart.addPrimitive(vp, 0);
      let grouping: VpSession | null = null;
      return {
        apply(state) {
          if (state.session !== grouping) {
            grouping = state.session;
            const result = profile.computeVolumeProfileSessions(bars(), { tickSize: 2, session: state.session, valueAreaPercent: 0.7 });
            vp.setData(result);
            const last = result.sessions[result.sessions.length - 1];
            if (last) setSummary(`${state.session === 'day' ? 'Latest day' : 'All three days'}: POC ${last.poc.toFixed(0)} · value area ${last.val.toFixed(0)} to ${last.vah.toFixed(0)}`);
          }
          vp.setOptions({ displayMode: state.mode, width: state.session === 'composite' ? 160 : 90 });
          // A little room each side, so the first date label and the last profile clear the edges.
          chart.timeScale.setVisibleLogicalRange({ from: -8, to: bars().length + 5 });
        },
        destroy() { chart.destroy(); },
      };
    } catch (error) {
      chart.destroy();
      throw error;
    }
  }, { mode, session });
  return (
    <ChartFrame chart={chart} height={400} label="Volume profile per session"
      code={`const result = computeVolumeProfileSessions(bars, { tickSize: 2, session: '${session}', valueAreaPercent: 0.7 });
chart.addPrimitive(new VolumeProfile(result, {
  displayMode: '${mode}', side: 'right', showPocLabel: false, showValueAreaLabels: false,
}));`}
      controls={<>
        <Segmented label="Sessions" value={session} onChange={setSession} options={[['day', 'Each day'], ['composite', 'All three days']]} />
        <Segmented label="Bars show" value={mode} onChange={setMode} options={[['total', 'Total volume'], ['buySell', 'Buy and sell'], ['delta', 'Delta']]} />
      </>}
      status={summary && <span>{summary} · buy and sell split by bar direction</span>} />
  );
}
