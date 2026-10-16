/**
 * The draw tier's events on the chart bus, added to the base's `ChartEventMap`
 * by declaration merging. The base declares the map and cannot name a
 * `Drawing` without importing this tier, so the names arrive with the tier: a
 * host that imports `openalgo-charts/draw` (or the widget, which does) gets
 * `chart.on('draw:add', ...)` typed.
 *
 * Two families, two granularities, both kept. `draw:*` reports per drawing and
 * per tool or gesture: `draw:add`, `draw:update` and `draw:remove` fire once for
 * each drawing touched and carry it, and `draw:select` names the primary
 * selection. `drawing:*` reports per mutation and per selection change:
 * `drawing:change` fires once after the per-drawing events with every id, and
 * `drawing:select` carries the whole selection. A host that renders one
 * drawing's properties listens to the first; one that refreshes a list or an
 * undo button listens to the second.
 */
import type { EmptyEvent } from 'openalgo-charts';
import type {
  DrawingChangeEvent, DrawingEvent, DrawingIdEvent, DrawingIdsEvent, DrawingListEvent, DrawingModeEvent, DrawingToolEvent,
} from './controller-types';
import type { DrawingController } from './controller';

declare module 'openalgo-charts' {
  interface ChartEventMap {
    /** A drawing tool became active, or none is (`tool: null`). */
    'draw:tool': DrawingToolEvent;
    /** A drawing was created, once per drawing. */
    'draw:add': DrawingEvent;
    /** A drawing's anchors, style, text or flags changed, once per drawing. */
    'draw:update': DrawingEvent;
    /** A drawing was deleted, once per drawing. */
    'draw:remove': DrawingEvent;
    /** The selection changed; `id` is the primary (first picked) id. Fires with `drawing:select`. */
    'draw:select': DrawingIdEvent;
    /** A copy reached the clipboard (copies, not the live drawings). */
    'draw:copy': DrawingListEvent;
    /** A cut wrote to the clipboard and then deleted. */
    'draw:cut': DrawingListEvent;
    /** The drawings a paste created, after their own `draw:add`. */
    'draw:paste': DrawingListEvent;
    /** Where a drag is carrying drawings, before it commits (copies). */
    'draw:preview': DrawingListEvent;
    /** A drag preview ended, committed or not. */
    'draw:preview-clear': DrawingIdsEvent;
    /** `fromJSON` or a chart restore replaced every drawing. */
    'draw:restore': EmptyEvent;
    /** A controller was destroyed and let go of the chart. */
    'draw:destroy': { controller: DrawingController };
    /** The measure gesture started or ended. */
    'draw:measure': DrawingModeEvent;
    /** The eraser was switched on or off. */
    'draw:eraser': DrawingModeEvent;
    /** One per mutation, after the per-drawing `draw:*` events. */
    'drawing:change': DrawingChangeEvent;
    /** The whole selection, when it changed. */
    'drawing:select': DrawingIdsEvent;
    /** The unselected drawing under the pointer changed. */
    'drawing:hover': DrawingIdEvent;
  }
}
