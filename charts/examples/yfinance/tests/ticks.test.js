import { describe, it, expect, beforeEach } from 'vitest';
import * as engine from '/dist/openalgo-charts.mjs';
import { HOST_INSTRUMENTS, instrumentFor, tickScheduleFor, axisMinMove, snapPrice, tickNote, sessionCalendarFor } from '../src/ticks.js';
import { venueCalendar } from '../src/status.js';
import { fakeDocument } from '../../../tests/helpers/fake-dom';
import { initOrders, placeOrder, fillMarket, repriceOrder } from '../src/orders.js';
import { initBracket, makeBracket, setBracketPrice } from '../src/bracket.js';
import { fakeDom, fakeStorage, flatBar } from './helpers.js';

globalThis.requestAnimationFrame = () => 0;

describe('the host tick rules', () => {
  it('supplies a schedule only for the fixture symbol that carries one', () => {
    const ticks = tickScheduleFor('banded');
    expect(ticks.bands).toEqual(HOST_INSTRUMENTS.BANDED.tickBands);
    expect(ticks.minMove).toBe(0.01);
    expect(tickScheduleFor('AAPL')).toBeNull();
    expect(tickScheduleFor('RELIANCE.NS')).toBeNull();
    expect(tickScheduleFor(undefined)).toBeNull();
  });

  it('takes the schedule from instrument metadata the library validates', () => {
    const instrument = instrumentFor('BANDED');
    expect(instrument).toBeInstanceOf(engine.Instrument);
    expect(instrument.metadata.tickBands).toEqual(HOST_INSTRUMENTS.BANDED.tickBands);
    expect(instrument.metadata.priceTick).toBe(instrument.tickSchedule.minMove);
    // Metadata whose price tick is not the grid every band lies on is refused
    // before anything snaps to it.
    expect(() => new engine.Instrument({ ...HOST_INSTRUMENTS.BANDED, priceTick: 0.05 })).toThrow(/minimum move 0\.01/);
    expect(instrumentFor('AAPL')).toBeNull();
  });

  it('gives the price axis the instrument grid over the market guess', () => {
    // The guess for BANDED by its suffix is 0.01 too, so a different fallback
    // shows which one the axis takes.
    expect(axisMinMove('BANDED', 0.05)).toBe(0.01);
    expect(axisMinMove('RELIANCE.NS', 0.05)).toBe(0.05);
    expect(axisMinMove('AAPL', 0.01)).toBe(0.01);
  });

  it('rounds to two decimals without a schedule, exactly as before', () => {
    expect(snapPrice(null, 101.239)).toBe(101.24);
    expect(snapPrice(null, 100.03)).toBe(100.03);
    expect(tickNote(null, 100)).toBe('');
  });

  it('rounds on the band a price is in with a schedule', () => {
    const ticks = tickScheduleFor('BANDED');
    expect(snapPrice(ticks, 99.994)).toBe(99.99);
    expect(snapPrice(ticks, 99.996)).toBe(100);
    expect(snapPrice(ticks, 100.03)).toBe(100.05);
    expect(tickNote(ticks, 99.99)).toBe(', tick 0.01');
    expect(tickNote(ticks, 100)).toBe(', tick 0.05');
  });
});

describe('the host trading hours', () => {
  const ist = (wall) => Date.parse(`${wall}+05:30`) / 1000;
  const nyc = (wall) => engine.zonedStringToUtcSeconds(wall, 'America/New_York');

  it('lays the future out in the venue hours the status line uses', () => {
    const nse = sessionCalendarFor('RELIANCE.NS');
    expect(nse).toBeInstanceOf(engine.SessionCalendar);
    expect(nse.timezone).toBe('Asia/Kolkata');
    expect(nse.calendar.sessions).toEqual(['0915-1530:23456']);
    // Friday after the close: the next opening is Monday's.
    expect(nse.sessionFrom(ist('2026-02-06T16:00:00'))).toEqual({
      date: '2026-02-09', open: ist('2026-02-09T09:15:00'), close: ist('2026-02-09T15:30:00'),
    });
    const us = sessionCalendarFor('AAPL');
    expect(us.calendar.sessions).toEqual(['0930-1600:23456']);
    expect(us.sessionFrom(nyc('2026-02-06 16:00')).open).toBe(nyc('2026-02-09 09:30'));
    expect(sessionCalendarFor('^NSEI').timezone).toBe('Asia/Kolkata');
  });

  it('hands the chart the venue calendar, pre-open and post-close included', () => {
    const us = sessionCalendarFor('AAPL');
    expect(us).toBe(venueCalendar('US'));
    expect(us.phaseAt(nyc('2026-02-06 05:00'))).toBe('pre');
    expect(us.phaseAt(nyc('2026-02-06 17:00'))).toBe('post');
    expect(us.phaseAt(nyc('2026-02-06 21:00'))).toBe('closed');
    // The future is still laid out in the regular session alone.
    expect(us.sessionFrom(nyc('2026-02-09 05:00')).open).toBe(nyc('2026-02-09 09:30'));
    expect(sessionCalendarFor('RELIANCE.NS').phaseAt(ist('2026-02-06T09:00:00'))).toBe('closed');
  });

  it('uses the host instrument where one exists and nothing for a venue that never closes', () => {
    expect(sessionCalendarFor('BANDED')).toBeInstanceOf(engine.Instrument);
    expect(sessionCalendarFor('BTC-USD')).toBeNull();
    expect(sessionCalendarFor('^FTSE')).toBeNull();
  });

  it('puts a chart\'s next bar after Friday\'s close on Monday\'s open', () => {
    const doc = fakeDocument();
    const chart = engine.createChart(doc.createElement('div'), { document: doc, shortcuts: false,
      raf: { schedule: () => 1, cancel: () => {} } });
    const times = [];
    for (const day of ['2026-02-05', '2026-02-06']) {
      for (let t = ist(`${day}T09:15:00`); t <= ist(`${day}T15:25:00`); t += 300) times.push(t);
    }
    chart.addSeries('candlestick').setData(times.map(time => flatBar(time, 100)));
    chart.dataLayer.setSessionCalendar(sessionCalendarFor('RELIANCE.NS'));
    expect(chart.dataLayer.indexToTimeFloat(times.length)).toBe(ist('2026-02-09T09:15:00'));
    expect(chart.dataLayer.indexToTimeFloat(times.length + 1)).toBe(ist('2026-02-09T09:20:00'));
    chart.destroy();
  });
});

function freshApp(ticks) {
  return {
    chart: null, req: { symbol: 'BANDED' }, currentBars: [flatBar(1, 99.98)], ticks,
    orders: [], nextOrderId: 1, position: null, posLine: null, fills: [], markersApi: null,
    bracket: null, bLines: null,
  };
}

describe('orders on a scheduled instrument', () => {
  let app;
  let dom;
  beforeEach(() => {
    dom = fakeDom({ qty: '10', product: 'MIS' });
    fakeStorage();
    app = freshApp(tickScheduleFor('BANDED'));
    initOrders(app);
  });

  it('rests a limit order at the price its band allows', () => {
    placeOrder('BUY', 'LIMIT', 100.03);
    placeOrder('SELL', 'LIMIT', 99.994);
    expect(app.orders.map((o) => o.price)).toEqual([100.05, 99.99]);
    expect(dom.get('status').textContent).toContain('@ 99.99 (MIS), tick 0.01');
  });

  it('reprices a dragged order line across the boundary on the new grid', () => {
    placeOrder('BUY', 'LIMIT', 99.98);
    const moved = [];
    app.orders[0].line = { setPrice: (p) => moved.push(p) };
    repriceOrder('order:1', 100.071);
    expect(app.orders[0].price).toBe(100.05);
    expect(dom.get('status').textContent).toBe('BUY LIMIT order -> 100.05, tick 0.05');
    repriceOrder('order:1', 99.9851);
    expect(app.orders[0].price).toBe(99.99);
    expect(moved).toEqual([100.05, 99.99]);
    repriceOrder('order:9', 50);
    expect(app.orders[0].price).toBe(99.99);
  });

  it('fills a market order at the last price on the grid', () => {
    app.currentBars = [flatBar(2, 100.03)];
    fillMarket('BUY', 10);
    expect(app.position).toEqual({ netQty: 10, avgPrice: 100.05 });
  });

  it('keeps the unscheduled drag on two decimals', () => {
    app.ticks = null;
    placeOrder('BUY', 'LIMIT', 99.98);
    app.orders[0].line = { setPrice: () => {} };
    repriceOrder('order:1', 100.071);
    expect(app.orders[0].price).toBe(100.07);
    expect(dom.get('status').textContent).toBe('BUY LIMIT order -> 100.07');
  });
});

describe('a bracket on a scheduled instrument', () => {
  let app;
  beforeEach(() => {
    fakeDom({ qty: '10' });
    fakeStorage();
    app = freshApp(tickScheduleFor('BANDED'));
    app.chart = {
      addPriceLine: (opts) => { const line = { ...opts, setPrice: (p) => { line.price = p; }, setOptions: () => {} }; return line; },
      removePrimitive: () => {}, priceToCoordinate: () => null,
    };
    initOrders(app);
    initBracket(app);
  });

  it('opens with each leg on the grid of its own band', () => {
    makeBracket('BUY');
    // 99.98 * 1.012 = 101.17976 on the 0.05 band; 99.98 * 0.99 on the 0.01 band.
    expect(app.bracket).toMatchObject({ entry: 99.98, target: 101.2, stop: 98.98 });
  });

  it('keeps each exit one tick of its own band away from the entry', () => {
    makeBracket('BUY');
    setBracketPrice('tp', 50);
    expect(app.bracket.target).toBe(99.99);
    setBracketPrice('entry', 100.03);
    expect(app.bracket).toMatchObject({ entry: 100.05, target: 100.1, stop: 99.05 });
    setBracketPrice('sl', 101);
    // One tick below 100.05 is 100.00, on the band that starts there.
    expect(app.bracket.stop).toBe(100);
    setBracketPrice('tp', 100.12);
    expect(app.bracket.target).toBe(100.1);
    expect(app.bLines.tp.price).toBe(100.1);
  });

  it('mirrors the bounds for a short across the boundary', () => {
    app.currentBars = [flatBar(2, 100)];
    makeBracket('SELL');
    setBracketPrice('tp', 150);
    expect(app.bracket.target).toBe(99.99);
    setBracketPrice('sl', 20);
    expect(app.bracket.stop).toBe(100.05);
  });
});
