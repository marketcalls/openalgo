/**
 * Markup for the shipped glyphs: whole `<svg>` strings, a sprite, and a CSS
 * cursor. Strings only, so the engine still ships no DOM; a host drops them
 * into `innerHTML`, a template literal, or `style.cursor` and is done.
 *
 * Path data stays in `icons.ts`. Everything here is derived from that registry
 * and its attribute bag, which is what makes it safe to offer: a host that
 * takes the convenience gets the same grid, stroke and caps as one that wraps
 * the path itself, and the tests on the registry hold for both.
 *
 * Unknown ids throw. The registry returns `undefined` so a host can probe, but
 * a string builder has no such value to hand back, and an empty button in a
 * rail is harder to trace than a stack that names the id.
 *
 * A glyph with an accent becomes two paths: the glyph, which already outlines
 * every mark, then the accent with `fill="currentColor" stroke="none"`, which
 * paints the inside of those marks and leaves the outline to the frame.
 */
import {
  CHROME_ICON_ACCENTS, CHROME_ICON_ATTRS, CHROME_ICON_FILLED, CHROME_ICON_SIZE,
  DRAWING_TOOL_ACCENTS, DRAWING_TOOL_ICONS, ICON_ATTRS, ICON_SIZE,
  chromeIcon, drawingToolIcon, type IconAttrs,
} from './icons';

const XMLNS = 'http://www.w3.org/2000/svg';

/** Prefix of every `<symbol id>` in the sprite, and of every `<use href>`. */
export const ICON_SYMBOL_PREFIX = 'oac-icon-';

/** Options shared by the inline builders. */
export interface IconSvgOptions {
  /**
   * Width and height. A number is CSS pixels; a string is written verbatim, so
   * `'1em'` sizes the glyph with the surrounding text. Default: the size the
   * tier is drawn for (`ICON_SIZE` for tools, `CHROME_ICON_SIZE` for chrome).
   */
  size?: number | string;
  /** Stroke width in viewBox units. Default: the tier's `*_STROKE`. */
  stroke?: number;
  /** A class for the host's own styling. */
  className?: string;
}

/** Options for `toolCursor`. */
export interface ToolCursorOptions {
  /** Cursor image size in CSS pixels. Default 20. Browsers reject images over 128. */
  size?: number;
  /** The pointer's active pixel, from the image's top-left. Default: the centre. */
  hotspot?: readonly [number, number];
  /** Glyph colour. Default white. */
  color?: string;
  /**
   * Halo colour. Default: black under a light `color`, white under a dark one,
   * judged from a hex colour. A non-hex `color` gets a black halo unless this
   * is set.
   */
  halo?: string;
  /** The keyword after the image, for a browser that will not take it. Default `crosshair`. */
  fallback?: string;
}

/** Attribute-value escaping. Ids come from the registry; everything else is host input. */
function attr(value: string | number): string {
  return String(value).replace(/[&<>"]/g, (c) => (
    c === '&' ? '&amp;' : c === '<' ? '&lt;' : c === '>' ? '&gt;' : '&quot;'
  ));
}

/** Through the lookups, so an inherited name such as `toString` throws as an unknown id does. */
function glyph(lookup: (id: string) => string | undefined, id: string, tier: string): string {
  const d = lookup(id);
  if (d === undefined) throw new Error(`openalgo-charts: no ${tier} icon "${id}"`);
  return d;
}

/**
 * The paths of one glyph: its line, then its accent filled. The accent names
 * its own fill because the frame's is `none`, and inside a sprite symbol it
 * would otherwise inherit that and leave a ring where a dot belongs. It turns
 * its stroke off because the glyph's path already strokes the same outline;
 * a second pass would darken the anti-aliased edge of every mark.
 */
function body(d: string, accent: string | undefined): string {
  return `<path d="${attr(d)}"/>`
    + (accent === undefined ? '' : `<path d="${attr(accent)}" fill="currentColor" stroke="none"/>`);
}

/** Grid size from a viewBox, so the cursor's pixel maths follows the registry. */
function gridOf(attrs: IconAttrs): number {
  return Number(attrs.viewBox.split(' ')[2]);
}

/**
 * The `<svg>` around one glyph or one `<use>`. Presentation lives here and
 * nowhere else, so overriding the stroke once changes every glyph.
 */
function frame(inner: string, attrs: IconAttrs, fill: string, opts: IconSvgOptions): string {
  const drawnFor = attrs === CHROME_ICON_ATTRS ? CHROME_ICON_SIZE : ICON_SIZE;
  // Every interpolated value is escaped, including the ones that come from the
  // registry rather than the caller. `opts.stroke` is typed `number`, but a
  // JavaScript host is not held to that, and one escaped attribute beside four
  // unescaped ones is the shape a later edit gets wrong.
  const size = attr(opts.size ?? drawnFor);
  const stroke = attr(opts.stroke ?? attrs.strokeWidth);
  const cls = opts.className !== undefined && opts.className !== ''
    ? ` class="${attr(opts.className)}"` : '';
  return `<svg xmlns="${XMLNS}" viewBox="${attr(attrs.viewBox)}" width="${size}" height="${size}"`
    + ` fill="${attr(fill)}" stroke="${attr(attrs.stroke)}" stroke-width="${stroke}"`
    + ` stroke-linecap="${attr(attrs.strokeLinecap)}" stroke-linejoin="${attr(attrs.strokeLinejoin)}"`
    + `${cls} aria-hidden="true">${inner}</svg>`;
}

/**
 * A complete inline `<svg>` for one tool glyph, stroked in `currentColor`.
 *
 * ```ts
 * button.innerHTML = iconSvg('trend-line');
 * button.innerHTML = iconSvg('trend-line', { size: '1em' });
 * ```
 */
export function iconSvg(id: string, opts: IconSvgOptions = {}): string {
  const d = glyph(drawingToolIcon, id, 'tool');
  return frame(body(d, DRAWING_TOOL_ACCENTS[id]), ICON_ATTRS, ICON_ATTRS.fill, opts);
}

/**
 * A complete inline `<svg>` for one chrome glyph, on the 16 grid. Glyphs in
 * `CHROME_ICON_FILLED` are painted solid as well as stroked.
 */
export function chromeIconSvg(id: string, opts: IconSvgOptions = {}): string {
  const d = glyph(chromeIcon, id, 'chrome');
  const fill = CHROME_ICON_FILLED.has(id) ? 'currentColor' : CHROME_ICON_ATTRS.fill;
  return frame(body(d, CHROME_ICON_ACCENTS[id]), CHROME_ICON_ATTRS, fill, opts);
}

/**
 * One hidden `<svg>` of `<symbol>`s, for a host that shows many glyphs and
 * wants each path in the document once. Inject it once, then place glyphs with
 * `iconUse`. Symbols carry the paths and viewBox, and no stroke: the weight
 * inherits from the `<svg>` around each `<use>`, so one sprite serves every
 * weight. An accent carries its fill, the one attribute it cannot inherit,
 * and no stroke, since the glyph's own path outlines it.
 *
 * Default: every tool glyph. Repeated ids collapse to one symbol, since a
 * duplicate element id is an invalid document.
 */
export function iconSprite(ids: readonly string[] = Object.keys(DRAWING_TOOL_ICONS)): string {
  let symbols = '';
  for (const id of new Set(ids)) {
    const d = glyph(drawingToolIcon, id, 'tool');
    symbols += `<symbol id="${attr(ICON_SYMBOL_PREFIX + id)}" viewBox="${attr(ICON_ATTRS.viewBox)}">`
      + `${body(d, DRAWING_TOOL_ACCENTS[id])}</symbol>`;
  }
  return `<svg xmlns="${XMLNS}" style="display:none" aria-hidden="true">${symbols}</svg>`;
}

/** An `<svg>` that references a symbol from `iconSprite`. Same frame as `iconSvg`. */
export function iconUse(id: string, opts: IconSvgOptions = {}): string {
  glyph(drawingToolIcon, id, 'tool');
  return frame(`<use href="#${attr(ICON_SYMBOL_PREFIX + id)}"/>`, ICON_ATTRS, ICON_ATTRS.fill, opts);
}

/**
 * The cursor's line, in grid units. Heavier than the rail's on purpose: a
 * cursor sits over candles, grid lines and other drawings rather than on a
 * quiet panel, where a line as fine as the rail's would be lost.
 */
const CURSOR_STROKE = 2;

/** Black or white, whichever a hex colour will stand out against. */
function contrastOf(color: string): string {
  const m = /^#([0-9a-f]{3,8})$/i.exec(color.trim());
  if (!m) return '#000';
  const hex = m[1]!; // the one group is in every match
  // Short forms double each digit; alpha, when present, does not affect luminance.
  const wide = hex.length < 6 ? hex.split('').map((c) => c + c).join('') : hex;
  const r = parseInt(wide.slice(0, 2), 16);
  const g = parseInt(wide.slice(2, 4), 16);
  const b = parseInt(wide.slice(4, 6), 16);
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 > 0.5 ? '#000' : '#fff';
}

/**
 * A CSS `cursor` value carrying the tool's glyph, for the canvas while that
 * tool is the active one.
 *
 * The glyph is drawn twice: once in `halo`, one pixel wider on each side, and
 * once in `color` on top with its marks filled, so it reads on a light chart
 * and a dark one without the host choosing per theme. The value is
 * `url("data:image/svg+xml,...") x y, fallback`, ready for `canvas.style.cursor`.
 */
export function toolCursor(id: string, opts: ToolCursorOptions = {}): string {
  const d = glyph(drawingToolIcon, id, 'tool');
  const size = opts.size ?? 20;
  if (!(Number.isFinite(size) && size > 0 && size <= 128)) {
    throw new RangeError(`openalgo-charts: cursor size ${size} is outside 1..128`);
  }
  const [hx, hy] = opts.hotspot ?? [size / 2, size / 2];
  const color = opts.color ?? '#fff';
  const halo = opts.halo ?? contrastOf(color);
  const fallback = opts.fallback ?? 'crosshair';
  // One CSS pixel is this many grid units at the requested size; the halo
  // clears the glyph by a pixel on each side.
  const unit = gridOf(ICON_ATTRS) / size;
  const haloWidth = Math.round((CURSOR_STROKE + 2 * unit) * 100) / 100;
  // The glyph's path outlines its marks, so the halo around it clears the
  // dots and heads as well, and a dot keeps its edge on a chart of its own
  // colour. The accent then fills the marks in the glyph's colour, so the
  // cursor draws the same tool as the rail button that picked it.
  const accent = DRAWING_TOOL_ACCENTS[id];
  const svg = `<svg xmlns="${XMLNS}" viewBox="${ICON_ATTRS.viewBox}" width="${size}" height="${size}"`
    + ` fill="none" stroke-linecap="${ICON_ATTRS.strokeLinecap}" stroke-linejoin="${ICON_ATTRS.strokeLinejoin}">`
    + `<path d="${d}" stroke="${attr(halo)}" stroke-width="${haloWidth}"/>`
    + `<path d="${d}" stroke="${attr(color)}" stroke-width="${CURSOR_STROKE}"/>`
    + (accent === undefined ? '' : `<path d="${accent}" fill="${attr(color)}"/>`)
    + '</svg>';
  return `url("data:image/svg+xml,${encodeURIComponent(svg)}") ${Math.round(hx)} ${Math.round(hy)}, ${fallback}`;
}
