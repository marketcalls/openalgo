/**
 * Vector export.
 *
 * `SvgContext` implements the subset of `CanvasRenderingContext2D` the
 * renderers, primitives and drawing tools call, and serialises every call to
 * SVG. The chart's ordinary paint, run once into one of these instead of the
 * pane canvases, comes out as a standalone document: text stays text, lines
 * stay lines, and the file scales without the blur a PNG picks up.
 *
 * The subset is the one the test recorder (`tests/helpers/fake-ctx.ts`) already
 * had to cover for the same code paths, plus what the drawing tools add
 * (curves, ellipses, rounded rectangles). The op set is the contract: anything
 * that draws to a pane through a method not here does not reach the export.
 *
 * What is out of reach for a serialiser, and what it does about it:
 *
 * - `setTransform`, `resetTransform`, `getTransform`: a whole-matrix reset has
 *   no place in a document built from nested groups. `translate`, `scale` and
 *   `rotate` are supported and are what the paint code uses.
 * - `createRadialGradient`, `createConicGradient`, `createPattern`,
 *   `getImageData`, `putImageData`, `createImageData`, `strokeText`,
 *   `drawFocusIfNeeded`, `isPointInPath`, `isPointInStroke`, and `fill`,
 *   `stroke` or `clip` handed a `Path2D`.
 * - `drawImage` of anything that is not an `<img>` with a `src` or a canvas
 *   that can hand over a data URL.
 *
 * Each of these throws under `strict` (the tests run that way, so a renderer
 * that grows a new call fails loudly) and otherwise records its name in
 * `unsupported` and paints nothing, which is the right production answer: a
 * missing logo is a better export than a thrown one. Shadow, composite and
 * smoothing properties are accepted and ignored, since the one primitive that
 * sets a shadow is decoration on a button.
 *
 * `measureText` is approximate: there is no font engine here, so widths come
 * from a per-character table scaled by the font size (see `charWidth`). The
 * paint code uses it to size tag boxes and cull overlapping axis labels, both
 * of which tolerate a few percent.
 */

/** Options for an `SvgContext`. */
export interface SvgContextOptions {
  /**
   * Throw on any call the serialiser cannot express. Off, the call is recorded
   * in `unsupported` and skipped.
   */
  strict?: boolean;
  /**
   * What `clearRect` paints. A canvas clears to transparent, which a document
   * that is appended to cannot do; when the export is opaque the honest stand-in
   * is the background colour. Absent, `clearRect` paints nothing.
   */
  background?: string | undefined;
}

/** A gradient handle: set it as `fillStyle` the way a canvas one is set. */
export class SvgLinearGradient {
  public readonly stops: { offset: number; color: string }[] = [];
  public constructor(
    public readonly id: string,
    public readonly x0: number,
    public readonly y0: number,
    public readonly x1: number,
    public readonly y1: number,
  ) {}

  public addColorStop(offset: number, color: string): void {
    this.stops.push({ offset, color });
  }

  public toString(): string {
    return `url(#${this.id})`;
  }
}

/** The state `save` snapshots and `restore` puts back. */
interface Snapshot {
  fillStyle: string | SvgLinearGradient;
  strokeStyle: string | SvgLinearGradient;
  lineWidth: number;
  lineCap: CanvasLineCap;
  lineJoin: CanvasLineJoin;
  miterLimit: number;
  globalAlpha: number;
  font: string;
  textAlign: CanvasTextAlign;
  textBaseline: CanvasTextBaseline;
  dash: number[];
  dashOffset: number;
}

/**
 * One entry of the group stack. A `save` frame remembers the style state and
 * how many `<g>` elements (transforms, clips) were opened since, so `restore`
 * can close exactly those. A `group` frame is one explicit `pushGroup`.
 */
interface Frame {
  kind: 'save' | 'group';
  open: number;
  state: Snapshot | null;
}

const TWO_PI = Math.PI * 2;

/** Two decimals is below anything a viewer can resolve and keeps the file short. */
function num(n: number): string {
  if (!Number.isFinite(n)) return '0';
  const scaled = n * 100;
  // Values this large have no fractional part to round, but scaling can overflow.
  const r = Number.isFinite(scaled) ? Math.round(scaled) / 100 : n;
  return String(r === 0 ? 0 : r);
}

function esc(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

/**
 * Advance width of one character as a fraction of the em, for a proportional
 * UI face. A handful of narrow and wide glyphs are told apart; everything else
 * takes the average, which is where digits and lower-case letters sit.
 */
function charWidth(ch: string): number {
  if (/[ .,:;'|!iIljtfr[\]()-]/.test(ch)) return 0.3;
  if (/[mwMW@%]/.test(ch)) return 0.9;
  if (/[A-Z]/.test(ch)) return 0.68;
  return 0.55;
}

interface ParsedFont {
  size: number;
  family: string;
  weight: string | null;
  style: string | null;
}

/**
 * Read a canvas font shorthand back into its parts. The paint code writes
 * `[weight] <size>px <family>`, and that is what the parse is built for; the
 * optional style and variant tokens are accepted so a host font survives too.
 */
function parseFont(font: string): ParsedFont {
  const tokens = font.trim().split(/\s+/);
  let weight: string | null = null;
  let style: string | null = null;
  let size = 10;
  let i = 0;
  for (; i < tokens.length; i++) {
    const t = tokens[i]!;
    // The unit is what tells a size from a numeric weight ('600 11px ...').
    const m = /^(\d+(?:\.\d+)?)(px|pt)(?:\/\S+)?$/.exec(t);
    if (m !== null) {
      size = parseFloat(m[1]!) * (m[2] === 'pt' ? 4 / 3 : 1); // both groups take part in every match
      i++;
      break;
    }
    if (t === 'italic' || t === 'oblique') style = t;
    else if (/^(\d{3}|bold|bolder|lighter)$/.test(t)) weight = t;
    // 'normal' and 'small-caps' carry nothing the export needs
  }
  return { size, family: tokens.slice(i).join(' ') || 'sans-serif', weight, style };
}

const BASELINES: Partial<Record<CanvasTextBaseline, string>> = {
  top: 'text-before-edge',
  hanging: 'hanging',
  middle: 'central',
  ideographic: 'ideographic',
  bottom: 'text-after-edge',
};

const ANCHORS: Partial<Record<CanvasTextAlign, string>> = {
  center: 'middle',
  right: 'end',
  end: 'end',
};

/**
 * A 2D context that writes SVG. Construct one at the document's media size,
 * hand it (cast) to whatever paints, and read `toString()`.
 */
export class SvgContext {
  public fillStyle: string | SvgLinearGradient = '#000';
  public strokeStyle: string | SvgLinearGradient = '#000';
  public lineWidth = 1;
  public lineCap: CanvasLineCap = 'butt';
  public lineJoin: CanvasLineJoin = 'miter';
  public miterLimit = 10;
  public globalAlpha = 1;
  public font = '10px sans-serif';
  public textAlign: CanvasTextAlign = 'start';
  public textBaseline: CanvasTextBaseline = 'alphabetic';
  // Accepted so a renderer that sets them keeps working; nothing reads them.
  public shadowColor = 'rgba(0, 0, 0, 0)';
  public shadowBlur = 0;
  public shadowOffsetX = 0;
  public shadowOffsetY = 0;
  public globalCompositeOperation = 'source-over';
  public imageSmoothingEnabled = true;
  /**
   * Deliberately undefined: a primitive that wants an offscreen canvas asks the
   * context for its element, and the honest answer is that there is none.
   */
  public readonly canvas: undefined = undefined;
  /** Names of the calls that could not be exported, first occurrence only. */
  public readonly unsupported: string[] = [];

  private readonly _out: string[] = [];
  private readonly _frames: Frame[] = [];
  private readonly _gradients: SvgLinearGradient[] = [];
  private readonly _clips: string[] = [];
  private _rootOpen = 0;
  private _path = '';
  /** Whether the current subpath has a current point (a lone `arc` needs to know). */
  private _hasPoint = false;
  private _dash: number[] = [];
  /** Where along the dash list a stroke starts, as a canvas reads it. */
  public lineDashOffset = 0;
  private _ids = 0;
  private readonly _strict: boolean;
  private readonly _background: string | undefined;
  private _fontCache: { font: string; parsed: ParsedFont } | null = null;

  public constructor(
    public readonly width: number,
    public readonly height: number,
    options: SvgContextOptions = {},
  ) {
    this._strict = options.strict === true;
    this._background = options.background;
  }

  /** This context typed as the canvas one the paint code is written against. */
  public asCanvasContext(): CanvasRenderingContext2D {
    return this as unknown as CanvasRenderingContext2D;
  }

  // ── state ────────────────────────────────────────────────────────────────

  public save(): void {
    this._frames.push({ kind: 'save', open: 0, state: this._snapshot() });
  }

  public restore(): void {
    let i = this._frames.length - 1;
    while (i >= 0 && this._frames[i]!.kind !== 'save') i--; // i counts down from the last frame
    if (i < 0) return; // a canvas ignores a restore with nothing saved
    if (i !== this._frames.length - 1 && this._strict) {
      throw new Error('SvgContext: restore() reached across an open pushGroup()');
    }
    this._closeTo(i);
  }

  /**
   * Open an explicit `<g>` with the given attributes, optionally translated
   * and clipped to a rectangle in the group's own coordinates. The chart wraps
   * each pane in one so the export carries the same per-pane offset and clip
   * the DOM stacking gives the canvases. Balanced by `popGroup`.
   */
  public pushGroup(
    attrs: Record<string, string | number>,
    options: { translate?: { x: number; y: number }; clip?: { x: number; y: number; width: number; height: number } } = {},
  ): void {
    let tag = '<g';
    for (const k in attrs) tag += ` ${k}="${esc(String(attrs[k]))}"`;
    const { translate, clip } = options;
    if (translate !== undefined) tag += ` transform="translate(${num(translate.x)} ${num(translate.y)})"`;
    if (clip !== undefined) {
      const id = this._clipId(`<rect x="${num(clip.x)}" y="${num(clip.y)}" width="${num(clip.width)}" height="${num(clip.height)}"/>`);
      tag += ` clip-path="url(#${id})"`;
    }
    this._out.push(tag + '>');
    this._frames.push({ kind: 'group', open: 1, state: null });
  }

  public popGroup(): void {
    let i = this._frames.length - 1;
    while (i >= 0 && this._frames[i]!.kind !== 'group') i--; // i counts down from the last frame
    if (i < 0) {
      if (this._strict) throw new Error('SvgContext: popGroup() without a pushGroup()');
      return;
    }
    if (i !== this._frames.length - 1 && this._strict) {
      throw new Error('SvgContext: popGroup() reached across an open save()');
    }
    this._closeTo(i);
  }

  public translate(x: number, y: number): void {
    if (x === 0 && y === 0) return;
    this._openGroup(`transform="translate(${num(x)} ${num(y)})"`);
  }

  public scale(x: number, y: number): void {
    if (x === 1 && y === 1) return;
    this._openGroup(`transform="scale(${num(x)} ${num(y)})"`);
  }

  public rotate(angle: number): void {
    if (angle === 0) return;
    this._openGroup(`transform="rotate(${num((angle * 180) / Math.PI)})"`);
  }

  public setLineDash(segments: number[]): void {
    this._dash = segments.slice();
  }

  public getLineDash(): number[] {
    return this._dash.slice();
  }

  // ── paths ────────────────────────────────────────────────────────────────

  public beginPath(): void {
    this._path = '';
    this._hasPoint = false;
  }

  public closePath(): void {
    if (this._path !== '') this._path += 'Z';
  }

  public moveTo(x: number, y: number): void {
    this._path += `M${num(x)} ${num(y)}`;
    this._hasPoint = true;
  }

  public lineTo(x: number, y: number): void {
    this._path += `${this._hasPoint ? 'L' : 'M'}${num(x)} ${num(y)}`;
    this._hasPoint = true;
  }

  public quadraticCurveTo(cx: number, cy: number, x: number, y: number): void {
    if (!this._hasPoint) this.moveTo(cx, cy);
    this._path += `Q${num(cx)} ${num(cy)} ${num(x)} ${num(y)}`;
  }

  public bezierCurveTo(c1x: number, c1y: number, c2x: number, c2y: number, x: number, y: number): void {
    if (!this._hasPoint) this.moveTo(c1x, c1y);
    this._path += `C${num(c1x)} ${num(c1y)} ${num(c2x)} ${num(c2y)} ${num(x)} ${num(y)}`;
  }

  public rect(x: number, y: number, w: number, h: number): void {
    this._path += `M${num(x)} ${num(y)}h${num(w)}v${num(h)}h${num(-w)}Z`;
    this._hasPoint = true;
  }

  /**
   * The radii argument takes the forms the paint code uses: one number, or an
   * array of up to four (top-left, top-right, bottom-right, bottom-left, the
   * CSS order). Radii are scaled down together when they would overlap, as the
   * canvas does, so a pill shorter than its radius stays a pill.
   */
  public roundRect(x: number, y: number, w: number, h: number, radii: number | number[] = 0): void {
    const r = Array.isArray(radii) ? radii : [radii];
    let [tl, tr, br, bl] = [r[0] ?? 0, r[1] ?? r[0] ?? 0, r[2] ?? r[0] ?? 0, r[3] ?? r[1] ?? r[0] ?? 0];
    const k = Math.min(1, w / Math.max(1e-9, tl + tr, bl + br), h / Math.max(1e-9, tl + bl, tr + br));
    tl *= k; tr *= k; br *= k; bl *= k;
    const a = (rr: number, ex: number, ey: number): string => (rr > 0 ? `A${num(rr)} ${num(rr)} 0 0 1 ${num(ex)} ${num(ey)}` : '');
    this._path +=
      `M${num(x + tl)} ${num(y)}H${num(x + w - tr)}${a(tr, x + w, y + tr)}` +
      `V${num(y + h - br)}${a(br, x + w - br, y + h)}` +
      `H${num(x + bl)}${a(bl, x, y + h - bl)}` +
      `V${num(y + tl)}${a(tl, x + tl, y)}Z`;
    this._hasPoint = true;
  }

  public arc(x: number, y: number, r: number, a0: number, a1: number, ccw = false): void {
    this.ellipse(x, y, r, r, 0, a0, a1, ccw);
  }

  public ellipse(x: number, y: number, rx: number, ry: number, rotation: number, a0: number, a1: number, ccw = false): void {
    const cos = Math.cos(rotation);
    const sin = Math.sin(rotation);
    const at = (t: number): [number, number] => {
      const px = rx * Math.cos(t);
      const py = ry * Math.sin(t);
      return [x + px * cos - py * sin, y + px * sin + py * cos];
    };
    // The sweep the canvas would draw: anything of a full turn or more is the
    // whole ellipse, otherwise the angular distance in the requested direction.
    let full = false;
    let delta: number;
    if (!ccw) {
      full = a1 - a0 >= TWO_PI;
      delta = ((a1 - a0) % TWO_PI + TWO_PI) % TWO_PI;
    } else {
      full = a0 - a1 >= TWO_PI;
      delta = -(((a0 - a1) % TWO_PI + TWO_PI) % TWO_PI);
    }
    const [sx, sy] = at(a0);
    // An arc joins the subpath in progress; on its own it starts one.
    this._path += `${this._hasPoint ? 'L' : 'M'}${num(sx)} ${num(sy)}`;
    this._hasPoint = true;
    const rot = num((rotation * 180) / Math.PI);
    const arcTo = (t: number, large: boolean, sweep: boolean): void => {
      const [ex, ey] = at(t);
      this._path += `A${num(rx)} ${num(ry)} ${rot} ${large ? 1 : 0} ${sweep ? 1 : 0} ${num(ex)} ${num(ey)}`;
    };
    if (full) {
      // One arc command cannot describe a closed loop (start equals end), so a
      // full turn is two halves.
      const half = ccw ? -Math.PI : Math.PI;
      arcTo(a0 + half, false, !ccw);
      arcTo(a0 + 2 * half, false, !ccw);
    } else if (delta !== 0) {
      arcTo(a0 + delta, Math.abs(delta) > Math.PI, delta > 0);
    }
  }

  public fill(rule?: CanvasFillRule | Path2D, _rule?: CanvasFillRule): void {
    if (typeof rule === 'object') { this._unsupported('fill(Path2D)'); return; }
    if (this._path === '') return;
    const paint = this._paint(this.fillStyle);
    if (paint === null) return;
    this._out.push(`<path d="${this._path}" fill="${paint}"${rule === 'evenodd' ? ' fill-rule="evenodd"' : ''}${this._opacity()}/>`);
  }

  public stroke(path?: Path2D): void {
    if (path !== undefined) { this._unsupported('stroke(Path2D)'); return; }
    if (this._path === '') return;
    const attrs = this._strokeAttrs();
    if (attrs === null) return;
    this._out.push(`<path d="${this._path}" fill="none"${attrs}${this._opacity()}/>`);
  }

  public clip(rule?: CanvasFillRule | Path2D): void {
    if (typeof rule === 'object') { this._unsupported('clip(Path2D)'); return; }
    if (this._path === '') return;
    const id = this._clipId(`<path d="${this._path}"${rule === 'evenodd' ? ' clip-rule="evenodd"' : ''}/>`);
    this._openGroup(`clip-path="url(#${id})"`);
  }

  // ── rectangles ───────────────────────────────────────────────────────────

  public fillRect(x: number, y: number, w: number, h: number): void {
    const paint = this._paint(this.fillStyle);
    if (paint === null) return;
    this._rect(x, y, w, h, ` fill="${paint}"`);
  }

  public strokeRect(x: number, y: number, w: number, h: number): void {
    const attrs = this._strokeAttrs();
    if (attrs === null) return;
    this._rect(x, y, w, h, ` fill="none"${attrs}`);
  }

  public clearRect(x: number, y: number, w: number, h: number): void {
    if (this._background === undefined) return;
    this._rect(x, y, w, h, ` fill="${esc(this._background)}"`);
  }

  // ── text ─────────────────────────────────────────────────────────────────

  public fillText(text: string, x: number, y: number): void {
    if (text === '') return;
    const paint = this._paint(this.fillStyle);
    if (paint === null) return;
    const f = this._font();
    let attrs = ` font-family="${esc(f.family)}" font-size="${num(f.size)}"`;
    if (f.weight !== null) attrs += ` font-weight="${f.weight}"`;
    if (f.style !== null) attrs += ` font-style="${f.style}"`;
    const anchor = ANCHORS[this.textAlign];
    if (anchor !== undefined) attrs += ` text-anchor="${anchor}"`;
    const baseline = BASELINES[this.textBaseline];
    if (baseline !== undefined) attrs += ` dominant-baseline="${baseline}"`;
    this._out.push(`<text x="${num(x)}" y="${num(y)}"${attrs} fill="${paint}"${this._opacity()}>${esc(text)}</text>`);
  }

  public measureText(text: string): TextMetrics {
    const f = this._font();
    let w = 0;
    for (const ch of text) w += charWidth(ch);
    const bold = f.weight !== null && (f.weight === 'bold' || f.weight === 'bolder' || parseInt(f.weight, 10) >= 600);
    const width = w * f.size * (bold ? 1.05 : 1);
    return {
      width,
      actualBoundingBoxLeft: 0,
      actualBoundingBoxRight: width,
      actualBoundingBoxAscent: f.size * 0.8,
      actualBoundingBoxDescent: f.size * 0.2,
      fontBoundingBoxAscent: f.size * 0.8,
      fontBoundingBoxDescent: f.size * 0.2,
    } as TextMetrics;
  }

  // ── gradients and images ─────────────────────────────────────────────────

  public createLinearGradient(x0: number, y0: number, x1: number, y1: number): SvgLinearGradient {
    const g = new SvgLinearGradient(`g${++this._ids}`, x0, y0, x1, y1);
    this._gradients.push(g);
    return g;
  }

  /**
   * An `<img>` becomes an `<image>` of its `src`; a canvas becomes one of its
   * data URL. The nine-argument crop is a nested `<svg>` whose viewBox is the
   * source rectangle. Anything else (an `ImageBitmap`, a video frame) has no
   * URL to point at and is skipped.
   */
  public drawImage(source: CanvasImageSource, ...args: number[]): void {
    const href = this._imageHref(source);
    if (href === null) { this._unsupported('drawImage'); return; }
    const natural = source as { naturalWidth?: number; naturalHeight?: number; width?: number; height?: number };
    const nw = natural.naturalWidth ?? (typeof natural.width === 'number' ? natural.width : 0);
    const nh = natural.naturalHeight ?? (typeof natural.height === 'number' ? natural.height : 0);
    const op = this._opacity();
    if (args.length >= 8) {
      const [sx, sy, sw, sh, dx, dy, dw, dh] = args as [number, number, number, number, number, number, number, number];
      this._out.push(
        `<svg x="${num(dx)}" y="${num(dy)}" width="${num(dw)}" height="${num(dh)}" viewBox="${num(sx)} ${num(sy)} ${num(sw)} ${num(sh)}" preserveAspectRatio="none">` +
        `<image href="${esc(href)}" width="${num(nw)}" height="${num(nh)}" preserveAspectRatio="none"${op}/></svg>`,
      );
      return;
    }
    // Every canvas form passes dx and dy (and `num` writes 0 for a missing one).
    const [dx, dy] = args as [number, number];
    const dw = args.length >= 4 ? args[2]! : nw;
    const dh = args.length >= 4 ? args[3]! : nh;
    this._out.push(`<image href="${esc(href)}" x="${num(dx)}" y="${num(dy)}" width="${num(dw)}" height="${num(dh)}" preserveAspectRatio="none"${op}/>`);
  }

  // ── calls with no vector form ────────────────────────────────────────────

  public setTransform(): void { this._unsupported('setTransform'); }
  public resetTransform(): void { this._unsupported('resetTransform'); }
  public getTransform(): undefined { this._unsupported('getTransform'); return undefined; }
  public createRadialGradient(): undefined { this._unsupported('createRadialGradient'); return undefined; }
  public createConicGradient(): undefined { this._unsupported('createConicGradient'); return undefined; }
  public createPattern(): null { this._unsupported('createPattern'); return null; }
  public getImageData(): undefined { this._unsupported('getImageData'); return undefined; }
  public putImageData(): void { this._unsupported('putImageData'); }
  public createImageData(): undefined { this._unsupported('createImageData'); return undefined; }
  public strokeText(): void { this._unsupported('strokeText'); }
  public drawFocusIfNeeded(): void { this._unsupported('drawFocusIfNeeded'); }
  public isPointInPath(): boolean { this._unsupported('isPointInPath'); return false; }
  public isPointInStroke(): boolean { this._unsupported('isPointInStroke'); return false; }

  // ── output ───────────────────────────────────────────────────────────────

  /**
   * The document. Groups still open (a paint that ended inside a `save`) are
   * closed here without being popped, so the string is the same however many
   * times it is read.
   */
  public toString(): string {
    const w = num(this.width);
    const h = num(this.height);
    let defs = '';
    for (const c of this._clips) defs += c;
    for (const g of this._gradients) {
      defs += `<linearGradient id="${g.id}" gradientUnits="userSpaceOnUse" x1="${num(g.x0)}" y1="${num(g.y0)}" x2="${num(g.x1)}" y2="${num(g.y1)}">`;
      for (const s of g.stops) defs += `<stop offset="${num(s.offset)}" stop-color="${esc(s.color)}"/>`;
      defs += '</linearGradient>';
    }
    let close = '';
    for (let i = this._frames.length - 1; i >= 0; i--) close += '</g>'.repeat(this._frames[i]!.open);
    close += '</g>'.repeat(this._rootOpen);
    return (
      `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" xml:space="preserve">` +
      (defs === '' ? '' : `<defs>${defs}</defs>`) +
      this._out.join('') + close + '</svg>'
    );
  }

  // ── internals ────────────────────────────────────────────────────────────

  private _snapshot(): Snapshot {
    return {
      fillStyle: this.fillStyle, strokeStyle: this.strokeStyle, lineWidth: this.lineWidth,
      lineCap: this.lineCap, lineJoin: this.lineJoin, miterLimit: this.miterLimit,
      globalAlpha: this.globalAlpha, font: this.font, textAlign: this.textAlign,
      textBaseline: this.textBaseline, dash: this._dash.slice(), dashOffset: this.lineDashOffset,
    };
  }

  private _apply(s: Snapshot): void {
    this.fillStyle = s.fillStyle; this.strokeStyle = s.strokeStyle; this.lineWidth = s.lineWidth;
    this.lineCap = s.lineCap; this.lineJoin = s.lineJoin; this.miterLimit = s.miterLimit;
    this.globalAlpha = s.globalAlpha; this.font = s.font; this.textAlign = s.textAlign;
    this.textBaseline = s.textBaseline; this._dash = s.dash; this.lineDashOffset = s.dashOffset;
  }

  /** Close every frame above index `i` and frame `i` itself, oldest last. */
  private _closeTo(i: number): void {
    while (this._frames.length > i) {
      const f = this._frames.pop() as Frame;
      this._out.push('</g>'.repeat(f.open));
      if (f.state !== null) this._apply(f.state);
    }
  }

  /** Open a `<g>` that the enclosing frame (or the root) will close. */
  private _openGroup(attrs: string): void {
    this._out.push(`<g ${attrs}>`);
    const top = this._frames[this._frames.length - 1];
    if (top !== undefined) top.open++;
    else this._rootOpen++;
  }

  private _clipId(content: string): string {
    const id = `c${++this._ids}`;
    this._clips.push(`<clipPath id="${id}">${content}</clipPath>`);
    return id;
  }

  private _rect(x: number, y: number, w: number, h: number, attrs: string): void {
    if (w === 0 || h === 0) return;
    if (w < 0) { x += w; w = -w; }
    if (h < 0) { y += h; h = -h; }
    this._out.push(`<rect x="${num(x)}" y="${num(y)}" width="${num(w)}" height="${num(h)}"${attrs}${this._opacity()}/>`);
  }

  /** The `fill`/`stroke` attribute value for a style, or null for nothing visible. */
  private _paint(style: string | SvgLinearGradient): string | null {
    if (this.globalAlpha <= 0) return null;
    if (typeof style !== 'string') return style instanceof SvgLinearGradient ? style.toString() : null;
    if (style === 'transparent') return null;
    return esc(style);
  }

  private _strokeAttrs(): string | null {
    if (!(this.lineWidth > 0)) return null;
    const paint = this._paint(this.strokeStyle);
    if (paint === null) return null;
    let attrs = ` stroke="${paint}" stroke-width="${num(this.lineWidth)}"`;
    if (this.lineCap !== 'butt') attrs += ` stroke-linecap="${this.lineCap}"`;
    if (this.lineJoin !== 'miter') attrs += ` stroke-linejoin="${this.lineJoin}"`;
    // A dash list that is all zeros draws solid on a canvas.
    if (this._dash.some((d) => d > 0)) {
      attrs += ` stroke-dasharray="${this._dash.map(num).join(' ')}"`;
      if (this.lineDashOffset !== 0) attrs += ` stroke-dashoffset="${num(this.lineDashOffset)}"`;
    }
    return attrs;
  }

  private _opacity(): string {
    return this.globalAlpha < 1 ? ` opacity="${num(this.globalAlpha)}"` : '';
  }

  private _font(): ParsedFont {
    if (this._fontCache === null || this._fontCache.font !== this.font) {
      this._fontCache = { font: this.font, parsed: parseFont(this.font) };
    }
    return this._fontCache.parsed;
  }

  private _imageHref(source: CanvasImageSource): string | null {
    const s = source as { src?: unknown; toDataURL?: unknown };
    if (typeof s.src === 'string' && s.src !== '') return s.src;
    if (typeof s.toDataURL === 'function') {
      try {
        return (s.toDataURL as () => string).call(source);
      } catch {
        return null; // a tainted canvas refuses; the image is simply left out
      }
    }
    return null;
  }

  private _unsupported(name: string): void {
    if (this._strict) throw new Error(`SvgContext: ${name} has no SVG form and cannot be exported`);
    if (!this.unsupported.includes(name)) this.unsupported.push(name);
  }
}
