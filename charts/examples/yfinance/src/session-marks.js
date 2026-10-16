// Session marks: price lines the host places from the chart menu for the
// length of a session. They show the three drawing policies working
// together. The user can select one (to read it, copy it or raise an alert
// from it) but not move, restyle or delete it; it is left out of every saved
// layout; and it stays out of the Objects dock. Only the host takes them
// away again, through its own "Clear session marks" row, which is the one
// place `force` is passed.

/** The policy every session mark carries. */
export const SESSION_MARK_POLICY = Object.freeze({ editable: false, persistent: false, listed: false });

// Dashed and thin, in the theme's line colour, so a mark reads as the
// host's reference rather than one of the user's own lines.
const MARK_STYLE = { lineWidth: 1, lineStyle: 'dashed' };

// A chart-type switch, a reload or a layout restore rebuilds the drawings
// from saved state, which never holds a mark. The host keeps its own list,
// per symbol and for the life of the page, and puts the marks back.
const kept = new Map();   // symbol -> [{ id, time, price }]

function place(draw, mark, paneIndex = 0) {
  // The same id keeps an alert raised on the mark attached to it, unless a
  // restored drawing has taken that id in the meantime.
  return draw.add({
    ...(draw.get(mark.id) ? {} : { id: mark.id }),
    tool: 'horizontal-line', paneIndex, style: { ...MARK_STYLE },
    points: [{ time: mark.time, price: mark.price }],
    policy: { ...SESSION_MARK_POLICY },
  });
}

/**
 * Place a mark at `point` on the price pane, and keep it for `symbol`. Pass
 * the price pane's slot, `chart.primaryPaneIndex()`: it is 0 until the pane is
 * moved below the studies, and a mark belongs beside the candles wherever
 * they are. Only the price is kept, never the slot, so a mark put back later
 * lands on the price pane where it sits then.
 */
export function addSessionMark(draw, point, symbol, paneIndex = 0) {
  const drawing = place(draw, { time: point.time, price: point.price }, paneIndex);
  kept.set(symbol, [...(kept.get(symbol) || []), { id: drawing.id, time: point.time, price: point.price }]);
  return drawing;
}

/** The marks on `draw`: in this host, exactly the drawings that are never saved. */
export function sessionMarks(draw) {
  return draw ? draw.drawings().filter((d) => d.policy?.persistent === false) : [];
}

/** Put back every mark kept for `symbol` that `draw` does not show, on the price pane at `paneIndex`. */
export function restoreSessionMarks(draw, symbol, paneIndex = 0) {
  const marks = kept.get(symbol);
  if (!marks) return;
  const shown = sessionMarks(draw);
  kept.set(symbol, marks.map((mark) => {
    const same = shown.find((d) => d.points[0]?.time === mark.time && d.points[0]?.price === mark.price);
    return { ...mark, id: (same || place(draw, mark, paneIndex)).id };
  }));
}

/** Keep `draw` showing the marks for the symbol `symbolOf()` names across every restore of `chart`. */
export function followSessionMarks(chart, draw, symbolOf) {
  return chart.on('draw:restore', () => restoreSessionMarks(draw, symbolOf(),
    typeof chart.primaryPaneIndex === 'function' ? chart.primaryPaneIndex() : 0));
}

/** Remove every mark on `draw`, and nothing else, and forget those kept for `symbol`. Returns how many went. */
export function clearSessionMarks(draw, symbol) {
  const ids = sessionMarks(draw).map((d) => d.id);
  if (ids.length) draw.removeMany(ids, { force: true });
  kept.delete(symbol);
  return ids.length;
}
