/** Visual settings use the chart-settings wire format without its data or trading fields. */
export type LinkAppearanceValues = Record<string, string | number | boolean>;

/** The host owns reading and applying settings so linking needs no chart class or DOM. */
export interface LinkAppearanceAdapter {
  read(): Readonly<LinkAppearanceValues>;
  apply(values: Readonly<LinkAppearanceValues>): void;
}

/**
 * The chart settings keys a linked chart follows. Every other key is left out
 * on purpose, and tests/link-appearance.test.ts lists each with its reason, so
 * a setting added later fails there until it is decided.
 */
const VISUAL_KEYS = new Set([
  ...('precision priceLineVisible lastValueVisible colorByPreviousClose upColor downColor bodyVisible '
    + 'borderUpColor borderDownColor borderVisible wickUpColor wickDownColor wickVisible '
    + 'topColor bottomColor closeColor color lineWidth lineStyle areaTopColor areaBottomColor')
    .split(' ').map(key => `symbol.${key}`),
  ...('titleMode title logo marketStatus chartValues barChange volume openInterest lastDayChange lastValueLabel '
    + 'background backgroundColor backgroundOpacity').split(' ').map(key => `statusLine.${key}`),
  ...('visible color opacity fontSize').split(' ').map(key => `watermark.${key}`),
  ...('mode autoScale priceOnly inverted').split(' ').map(key => `scales.${key}`),
  'axisChrome.sessionClock', 'axisChrome.barCountdown',
  ...('grid.vertLines grid.vertColor grid.vertStyle grid.horzLines grid.horzColor grid.horzStyle '
    + 'grid.lineWidth grid.spacing crosshairMode crosshairSnapToBar crosshair.color crosshair.style '
    + 'crosshair.width scales.textColor scales.fontSize scales.lineColor margins.top margins.bottom')
    .split(' ').map(key => `canvas.${key}`),
]);

/** Retain supported appearance fields, excluding instrument text, data, navigation and trades. */
export function filterLinkAppearance(values: Readonly<Partial<LinkAppearanceValues>>): LinkAppearanceValues {
  const out: LinkAppearanceValues = {};
  for (const [key, value] of Object.entries(values)) {
    if (!VISUAL_KEYS.has(key)) continue;
    if (typeof value === 'string' || typeof value === 'boolean'
      || (typeof value === 'number' && Number.isFinite(value))) out[key] = value;
  }
  return out;
}
