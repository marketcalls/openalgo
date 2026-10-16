import React, { useEffect, useRef, useState } from 'react';
import { useTheme } from 'next-themes';
import { BTC_USD_INTERVALS, BTC_USD_SOURCE, createBtcUsdFeed } from '../lib/market-data/btc-usd.mjs';

type MarketStatus = {
  state: 'loading' | 'connected' | 'error' | 'stale';
  interval: string;
  updatedAt?: number;
  barTime?: number;
  close?: number;
  message?: string;
};

type Widget = ReturnType<(typeof import('../lib/oac/openalgo-charts.widget.mjs'))['createWidget']>;

const priceFormat = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 });

export default function BtcUsdChart() {
  const host = useRef<HTMLDivElement>(null);
  const retry = useRef<(() => Promise<void>) | null>(null);
  const [market, setMarket] = useState<MarketStatus>({ state: 'loading', interval: '1h' });
  const [ready, setReady] = useState(false);
  const { resolvedTheme } = useTheme();
  const dark = resolvedTheme !== 'light';

  useEffect(() => {
    let cancelled = false;
    let widget: Widget | undefined;
    let feed: ReturnType<typeof createBtcUsdFeed> | undefined;
    let lastInterval: string | undefined;
    const unsubscribers: Array<() => void> = [];
    setReady(false);
    setMarket({ state: 'loading', interval: '1h' });
    (async () => {
      try {
        const [module] = await Promise.all([
          import('../lib/oac/openalgo-charts.widget.mjs'),
          import('../lib/oac/openalgo-charts.indicators.mjs'),
        ]);
        if (cancelled || !host.current) return;
        widget = module.createWidget(host.current, {
          symbol: 'BTCUSD', interval: '1h', intervals: BTC_USD_INTERVALS,
          theme: dark ? 'dark' : 'light', timezone: 'UTC', persist: false,
        });
        widget.chart.addIndicator('supertrend', { period: 10, multiplier: 3 });
        const momentum = widget.chart.addIndicator('macd', {
          fastPeriod: 12, slowPeriod: 26, signalPeriod: 9,
          macdColor: '#70a4ff', signalColor: '#f7b45d',
        });
        widget.chart.setPaneWeight(0, 3);
        widget.chart.setPaneWeight(momentum.paneIndex, 1);
        const symbolInput = widget.root.querySelector('input[aria-label="Symbol"]') as HTMLInputElement | null;
        if (symbolInput) {
          symbolInput.readOnly = true;
          symbolInput.setAttribute('aria-label', 'Symbol: BTC/USD');
          symbolInput.title = 'This chart follows Bitcoin / US Dollar.';
        }
        feed = createBtcUsdFeed({
          onBars: (bars, interval) => {
            if (cancelled || !widget) return;
            widget.series.setData(bars);
            if (lastInterval !== interval) widget.chart.resetScale();
            lastInterval = interval;
          },
          onStatus: (status: MarketStatus) => { if (!cancelled) setMarket(status); },
        });
        retry.current = () => feed!.refresh();
        unsubscribers.push(widget.on('interval', ({ interval }) => {
          widget!.series.setData([]);
          lastInterval = undefined;
          void feed!.selectInterval(interval);
        }));
        unsubscribers.push(widget.on('symbol', ({ symbol }) => {
          if (symbol !== 'BTCUSD') widget!.setSymbol('BTCUSD');
        }));
        setReady(true);
        await feed.selectInterval('1h');
      } catch (error) {
        if (!cancelled) setMarket({ state: 'error', interval: '1h', message: error instanceof Error ? error.message : 'The chart could not be loaded.' });
      }
    })();
    return () => {
      cancelled = true;
      retry.current = null;
      unsubscribers.forEach(unsubscribe => unsubscribe());
      feed?.destroy();
      widget?.destroy();
    };
  }, [dark]);

  const unavailable = market.state === 'error' || market.state === 'stale';
  const statusLabel = market.state === 'loading' ? 'Connecting to market data'
    : market.state === 'stale' ? 'Disconnected · Last known data'
      : market.state === 'error' ? 'Market data unavailable' : 'Real market data';
  const syncTime = market.updatedAt ? new Date(market.updatedAt).toLocaleTimeString('en-GB', { hour12: false }) : null;
  const candleTime = market.barTime ? new Date(market.barTime * 1000).toISOString().replace('T', ' ').slice(0, 16) + ' UTC' : undefined;

  return (
    <div id="playground" className="oac-playground oac-btc-chart oac-intro oac-intro--chart" role="region" aria-label="Live BTC/USD chart">
      <div className="oac-playground__rim" aria-hidden="true" />
      <div className="oac-playground__header">
        <div className="oac-playground__name"><span className="oac-btc-symbol" aria-hidden="true">₿</span><span>Bitcoin <span className="oac-btc-pair">/ US Dollar</span></span>{market.close !== undefined && <span className="oac-btc-price" title={candleTime ? `Latest available candle: ${candleTime}` : undefined}>{priceFormat.format(market.close)}</span>}</div>
        <span className="oac-playground__demo-label oac-market-status" role="status" data-state={market.state}><span className="oac-status-dot" /> {statusLabel}</span>
      </div>
      <div className="oac-example">
        <div className="oac-example__stage">
          <div className="oac-example__chart" ref={host} style={{ height: 660 }} />
          {(!ready || market.state === 'loading') && !unavailable && <div className="oac-example__loading">Loading BTC/USD market data…</div>}
          {market.state === 'error' && <div className="oac-btc-unavailable" role="alert"><strong>BTC/USD data is unavailable.</strong><span>Check your connection and try again.</span>{ready && <button type="button" onClick={() => void retry.current?.()}>Retry connection</button>}</div>}
        </div>
      </div>
      {market.state === 'stale' && <div className="oac-btc-stale" role="alert"><span>Connection interrupted. Showing the last received candles.</span><button type="button" onClick={() => void retry.current?.()}>Retry</button></div>}
      <div className="oac-playground__footer oac-btc-footer">
        <span>Draw an idea. Add an indicator.</span>
        <span className="oac-btc-source"><a href={BTC_USD_SOURCE} target="_blank" rel="noreferrer">Source: Gemini</a><span>Refreshes every 15s</span>{syncTime && <span title={candleTime ? `Latest available candle: ${candleTime}` : undefined}>Synced {syncTime}</span>}</span>
      </div>
    </div>
  );
}
