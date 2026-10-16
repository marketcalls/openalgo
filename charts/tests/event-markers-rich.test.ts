import { describe, expect, it } from 'vitest';
import { EventMarkers, type ChartEvent, type ChartEventDetails, type EventDetailField, type EventGroup } from '../src/primitives/event-markers';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';
import { DataLayer } from '../src/model/data-layer';
import { TimeScale } from '../src/scale/time-scale';
import { PriceScale } from '../src/scale/price-scale';
import { darkTheme } from '../src/theme';
import { makeCtx } from './helpers/fake-ctx';

function context(spacing = 30, dpr = 1): PrimitiveRenderContext {
  const dataLayer = new DataLayer();
  const id = dataLayer.createSeries();
  dataLayer.setSeriesData(id, [100, 200, 500].map(time => ({ time, open: 1, high: 1, low: 1, close: 1 })));
  const timeScale = new TimeScale({ barSpacing: spacing, rightOffset: 0.5, maxBarSpacing: 200 });
  timeScale.setWidth(300);
  timeScale.setBaseIndex(2);
  return { dataLayer, timeScale, priceScale: new PriceScale(), plotWidth: 300, plotHeight: 200, priceAxisWidth: 56, dpr, theme: darkTheme };
}

const earnings: ChartEvent = { id: 'earnings', time: 200, type: 'earnings', label: 'E', title: 'Results', group: 'company' };

describe('rich timeline markers', () => {
  it('selects the visible top badge when unclustered events overlap', () => {
    const markers = new EventMarkers();
    markers.setEvents([{ ...earnings, id: 'a', title: 'Covered' }, { ...earnings, id: 'b', title: 'Visible' }]);
    markers.draw(makeCtx().ctx, context());
    const hit = markers.hitTest(255, 188)!;
    expect(markers.detailsForHit(hit.externalId)?.events[0].title).toBe('Visible');
  });
  it('keeps duplicate host ids from resolving a different event badge', () => {
    const markers = new EventMarkers();
    const rc = context();
    markers.setEvents([{ ...earnings, id: 'same', time: 100, title: 'First' },
      { ...earnings, id: 'same', time: 500, title: 'Second' }]);
    markers.draw(makeCtx().ctx, rc);
    const first = markers.hitTest(rc.timeScale.indexToX(rc.dataLayer.timeToIndexFloat(100)), 188)!;
    const second = markers.hitTest(rc.timeScale.indexToX(rc.dataLayer.timeToIndexFloat(500)), 188)!;
    expect(markers.detailsForHit(first.externalId)?.events[0].title).toBe('First');
    expect(markers.detailsForHit(second.externalId)?.events[0].title).toBe('Second');
    expect(first.externalId).not.toBe(second.externalId);
  });
  it('anchors between bars through session gaps without changing event timestamps', () => {
    const markers = new EventMarkers();
    const rc = context();
    const event = { ...earnings, time: 350 };
    markers.setEvents([event]);
    const { ctx, rec } = makeCtx();
    markers.draw(ctx, rc);
    expect(rec.ops.find(op => op.type === 'arc')?.args).toEqual([270, 188, 8]);
    expect(markers.hitTest(270, 188)?.externalId).toBe('earnings');
    expect(event.time).toBe(350);
  });

  it('owns event objects after assignment', () => {
    const markers = new EventMarkers();
    const event = { ...earnings };
    markers.setEvents([event]);
    event.label = 'Changed';
    const { ctx, rec } = makeCtx();
    markers.draw(ctx, context());
    expect(rec.ops.find(op => op.type === 'fillText')?.text).toBe('E');
  });

  it('owns rich detail blocks all the way down, and tolerates malformed ones', () => {
    const markers = new EventMarkers();
    const blocks = [{ type: 'paragraph', text: [{ text: 'Original', href: 'https://example.com/a' }] }, { type: 'list', items: ['One', [{ text: 'Two' }]] }];
    markers.setEvents([{ ...earnings, details: { summary: 'S', blocks } as ChartEvent['details'] }]);
    blocks[0].text![0].text = 'Changed';
    (blocks[1].items![1] as Array<{ text: string }>)[0].text = 'Changed';
    const stored = markers.events()[0].details as { blocks: typeof blocks };
    expect(stored.blocks).toEqual([{ type: 'paragraph', text: [{ text: 'Original', href: 'https://example.com/a' }] }, { type: 'list', items: ['One', [{ text: 'Two' }]] }]);
    // A copy handed out is the caller's own.
    stored.blocks[0].text![0].text = 'Edited';
    expect((markers.events()[0].details as { blocks: typeof blocks }).blocks[0].text![0].text).toBe('Original');
    expect(() => markers.setEvents([{ ...earnings, details: { blocks: [null, { type: 'list', items: 'x' }, 3] } as unknown as ChartEvent['details'] }])).not.toThrow();
    // Only plain data is copied: anything else a host attached is shared, as before.
    const when = new Date(0);
    markers.setEvents([{ ...earnings, details: { summary: 'S', source: when } as unknown as ChartEvent['details'] }]);
    expect((markers.events()[0].details as unknown as { source: Date }).source).toBe(when);
  });

  it('owns details built without a prototype, which are plain data too', () => {
    const markers = new EventMarkers();
    const details = Object.assign(Object.create(null) as ChartEventDetails, {
      summary: 'Original', fields: [Object.assign(Object.create(null) as EventDetailField, { label: 'Revenue', value: '100' })],
    });
    markers.setEvents([{ ...earnings, details }]);
    details.summary = 'Changed';
    details.fields![0]!.value = 'Changed';
    expect(markers.events()[0].details).toEqual({ summary: 'Original', fields: [{ label: 'Revenue', value: '100' }] });
    const handed = markers.events()[0].details as ChartEventDetails;
    handed.summary = 'Edited';
    expect((markers.events()[0].details as ChartEventDetails).summary).toBe('Original');
  });

  it.each([NaN, Infinity, -Infinity])('rejects a nonfinite timestamp atomically: %s', time => {
    const markers = new EventMarkers();
    markers.setEvents([earnings]);
    expect(() => markers.setEvents([{ ...earnings, time }])).toThrow(/time/i);
    markers.draw(makeCtx().ctx, context());
    expect(markers.hitTest(255, 188)?.externalId).toBe('earnings');
  });

  it('clips all canvas output and excludes hits outside the plot', () => {
    const markers = new EventMarkers();
    const rc = context(30, 2);
    // 0.47 bars past the last bar at the median spacing of 100 seconds, which
    // centres the badge on the plot's right edge so it straddles the clip.
    markers.setEvents([{ ...earnings, time: 547 }]);
    const { ctx, rec } = makeCtx();
    markers.draw(ctx, rc);
    expect(rec.ops.some(op => op.type === 'rect' && op.args.join() === '0,0,600,400')).toBe(true);
    expect(rec.count('clip')).toBe(1);
    expect(markers.hitTest(302, 188)).toBeNull();
    expect(markers.hitTest(299, 188)?.externalId).toBe('earnings');
  });

  it('hides every descendant and restores a child only when all its ancestors are visible', () => {
    const markers = new EventMarkers();
    const groups: EventGroup[] = [{ id: 'all', label: 'All' }, { id: 'company', label: 'Company', parentId: 'all' }];
    markers.setGroups(groups);
    markers.setEvents([earnings, { id: 'other', time: 500, type: 'news', label: 'N' }]);
    markers.setGroupVisible('all', false);
    markers.setGroupVisible('company', true);
    const first = makeCtx();
    markers.draw(first.ctx, context());
    expect(first.rec.ops.filter(op => op.type === 'fillText').map(op => op.text)).toEqual(['N']);
    expect(markers.isGroupVisible('company')).toBe(false);
    markers.setGroupVisible('all', true);
    markers.draw(makeCtx().ctx, context());
    expect(markers.hitTest(255, 188)?.externalId).toBe('earnings');
    groups[1].parentId = 'missing';
    const snapshot = markers.groups();
    snapshot[1].visible = false;
    expect(markers.isGroupVisible('company')).toBe(true);
  });

  it('rejects duplicate, missing-parent and cyclic groups without replacing the prior hierarchy', () => {
    const markers = new EventMarkers();
    markers.setGroups([{ id: 'company', label: 'Company' }]);
    for (const groups of [
      [{ id: 'a', label: 'A', parentId: 'a' }],
      [{ id: 'a', label: 'A', parentId: 'b' }, { id: 'b', label: 'B', parentId: 'a' }],
      [{ id: 'a', label: 'A' }, { id: 'a', label: 'Duplicate' }],
      [{ id: 'a', label: 'A', parentId: 'missing' }],
    ]) expect(() => markers.setGroups(groups)).toThrow();
    expect(markers.groups().map(group => group.id)).toEqual(['company']);
    expect(() => markers.setGroupVisible('missing', false)).toThrow();
  });

  it('keeps the default separate badges and clusters only when enabled', () => {
    const markers = new EventMarkers();
    markers.setEvents([earnings, { ...earnings, id: 'next', time: 210 }]);
    const original = makeCtx();
    markers.draw(original.ctx, context());
    expect(original.rec.count('arc')).toBe(2);
    markers.setOptions({ clustering: true, clusterRadius: 18 });
    const clustered = makeCtx();
    markers.draw(clustered.ctx, context());
    expect(clustered.rec.count('arc')).toBe(1);
    expect(clustered.rec.ops.find(op => op.type === 'fillText')?.text).toBe('2');
    const hit = markers.hitTest(255.5, 188)!;
    expect(markers.detailsForHit(hit.externalId)?.events.map(event => event.id)).toEqual(['earnings', 'next']);
    expect(markers.detailsForHit(hit.externalId)?.cluster).toBe(true);
  });

  it('splits clusters when zoom makes members distinct and preserves identity across input order and panning', () => {
    const markers = new EventMarkers({ clustering: true, clusterRadius: 18 });
    const events = [earnings, { ...earnings, id: 'next', time: 250 }];
    const rc = context();
    markers.setEvents(events);
    markers.draw(makeCtx().ctx, rc);
    const id = markers.hitTest(257.5, 188)!.externalId;
    markers.setEvents(events.slice().reverse());
    rc.timeScale.setWidth(290);
    rc.plotWidth = 290;
    markers.draw(makeCtx().ctx, rc);
    expect(markers.hitTest(247.5, 188)!.externalId).toBe(id);
    rc.timeScale.setBarSpacing(120);
    const zoomed = makeCtx();
    markers.draw(zoomed.ctx, rc);
    expect(zoomed.rec.count('arc')).toBe(2);
    expect(markers.detailsForHit(id)).toBeNull();
    expect(markers.hitTest(rc.timeScale.indexToX(1), 188)?.externalId).toBe('earnings');
  });

  it('returns isolated member details and stable handles for events without caller ids', () => {
    const markers = new EventMarkers();
    const details = { summary: 'Report', fields: [{ label: 'Revenue', value: '100' }] };
    markers.setEvents([{ time: 200, type: 'earnings', label: 'E', details }]);
    details.fields[0].value = '200';
    markers.draw(makeCtx().ctx, context());
    const id = markers.hitTest(255, 188)!.externalId;
    const result = markers.detailsForHit(id)!;
    expect(result.events[0].details).toEqual({ summary: 'Report', fields: [{ label: 'Revenue', value: '100' }] });
    result.events[0].title = 'Changed';
    const copied = markers.events();
    if (typeof copied[0].details === 'object') copied[0].details.fields![0].value = 'Changed';
    expect(markers.detailsForHit(id)?.events[0].title).toBeUndefined();
    expect(markers.events()[0].details).toEqual({ summary: 'Report', fields: [{ label: 'Revenue', value: '100' }] });
    markers.draw(makeCtx().ctx, context());
    expect(markers.hitTest(255, 188)!.externalId).toBe(id);
  });

  it('invalidates stale hit geometry immediately on data, visibility, options and detach changes', () => {
    const markers = new EventMarkers();
    markers.setGroups([{ id: 'company', label: 'Company' }]);
    markers.setEvents([earnings]);
    for (const invalidate of [
      () => markers.setEvents([earnings]),
      () => markers.setGroupVisible('company', true),
      () => markers.setOptions({ clustering: true }),
      () => markers.detached(),
    ]) {
      markers.draw(makeCtx().ctx, context());
      expect(markers.detailsForHit('earnings')).not.toBeNull();
      invalidate();
      expect(markers.hitTest(255, 188)).toBeNull();
      expect(markers.detailsForHit('earnings')).toBeNull();
    }
  });

  it('validates clustering distance and leaves prior options intact', () => {
    const markers = new EventMarkers({ clustering: true, clusterRadius: 20 });
    for (const value of [NaN, Infinity, -1, 0, 201]) expect(() => markers.setOptions({ clusterRadius: value })).toThrow();
    expect(markers.options()).toEqual({ clustering: true, clusterRadius: 20 });
  });
});
