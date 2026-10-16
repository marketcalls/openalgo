/**
 * How the chart looks and how it leaves the screen: the brand mark, the
 * background text, applying a batch of appearance options at runtime, and the
 * two exports, a flattened bitmap and a standalone SVG document.
 *
 * Its own module because the branding and background-text options, and the
 * background text primitive itself, belong to these methods alone, and the
 * exports need nothing of the chart beyond its panes, its geometry and a
 * frame's render context. The chart reaches it through `Chart._appearance`,
 * and it reaches the chart through `AppearanceHost`. The brand mark stays on
 * Chart, because a press on it is routed by the input. `setBranding`,
 * `setWatermarkOptions`, `applyOptions`, `takeScreenshot` and `exportSVG`
 * stay public on Chart as delegates and carry the documented contract;
 * `brandingOptions` and `watermarkOptions` read the moved fields there.
 * Members the chart calls are public on this internal class; no entry point
 * exports the class and the chart holds it in a private field, so none of it
 * reaches the published declarations.
 */
import { InvalidationLevel } from './invalidate-mask';
import type { PaneRenderContext } from './pane';
import type { ChartApplyOptions, ChartWatermarkOptions, ExportSvgOptions } from './chart-types';
import type { Chart } from './chart';
import { SvgContext } from '../render/svg-export';
import { LogoWatermark, type LogoWatermarkOptions } from '../primitives/watermark';
import { TextWatermark } from '../primitives/text-watermark';

/**
 * The slice of the chart the branding, the background text, the option batch
 * and the exports read, write and drive. The chart itself is the host: each
 * member carries the name and the type of the chart's own, so the moved code
 * reads as it did in chart.ts, and a member the chart renames or retypes fails
 * to compile here. The writable fields are the chart's own, assigned here.
 */
export interface AppearanceHost {
  readonly _panes: Chart['_panes'];
  readonly _doc: Chart['_doc'];
  readonly _theme: Chart['_theme'];
  readonly _dataContext: Chart['_dataContext'];
  _width: Chart['_width'];
  _height: Chart['_height'];
  _layoutRatio: Chart['_layoutRatio'];
  _branding: Chart['_branding'];
  _crosshairMode: Chart['_crosshairMode'];
  _crosshairSnapToBar: Chart['_crosshairSnapToBar'];
  /** The chart's other collaborators, whose methods this code calls directly. */
  readonly _layout: Chart['_layout'];
  readonly _studies: Chart['_studies'];
  _pixelRatio: Chart['_pixelRatio'];
  _paneLayout: Chart['_paneLayout'];
  _renderContext: Chart['_renderContext'];
  _withinLayoutChange: Chart['_withinLayoutChange'];
  _layoutChanged: Chart['_layoutChanged'];
  brandingOptions: Chart['brandingOptions'];
  addPrimitive: Chart['addPrimitive'];
  removePrimitive: Chart['removePrimitive'];
  setTheme: Chart['setTheme'];
  setGridOptions: Chart['setGridOptions'];
  setCanvasOptions: Chart['setCanvasOptions'];
  setStatusLineOptions: Chart['setStatusLineOptions'];
  setLegendIconSize: Chart['setLegendIconSize'];
  setPriceScaleOptions: Chart['setPriceScaleOptions'];
  setPriceFormatter: Chart['setPriceFormatter'];
  setTimeFormatter: Chart['setTimeFormatter'];
  setTimezone: Chart['setTimezone'];
  invalidate: Chart['invalidate'];
  _emit: Chart['_emit'];
}

export class ChartAppearance {
  private readonly _host: AppearanceHost;
  public _brandingOptions: false | LogoWatermarkOptions = false;
  private _watermark: TextWatermark | null = null;
  public _watermarkOptions: ChartWatermarkOptions = {
    visible: false, text: '', color: '#9aa4b2', opacity: 0.08, fontSize: 64,
  };

  public constructor(host: AppearanceHost) {
    this._host = host;
  }

  public setBranding(options: boolean | LogoWatermarkOptions): void {
    if (this._host._branding !== null) this._host.removePrimitive(this._host._branding);
    this._host._branding = null;
    this._brandingOptions = options === false ? false : {
      position: 'bottom-left', margin: 14, opacity: 1, padding: 8,
      label: 'Chart by OpenAlgo', href: 'https://openalgo.in', id: 'chart-branding',
      ...(options === true ? {} : options),
    };
    if (this._brandingOptions !== false) {
      if (typeof this._brandingOptions.padding === 'object') this._brandingOptions.padding = { ...this._brandingOptions.padding };
      this._host._branding = new LogoWatermark(this._brandingOptions);
      this._host.addPrimitive(this._host._branding, { anchor: 'chart-bottom' });
    }
    this._host.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Light));
    this._host._emit('branding:changed', this._host.brandingOptions());
  }

  public setWatermarkOptions(options: boolean | ChartWatermarkOptions): void {
    const patch = typeof options === 'boolean' ? { visible: options } : options;
    if (patch === null || typeof patch !== 'object') return;
    const o = this._watermarkOptions;
    if (typeof patch.visible === 'boolean') o.visible = patch.visible;
    for (const key of ['text', 'color', 'font', 'id'] as const) {
      if (typeof patch[key] === 'string') o[key] = patch[key];
    }
    if (typeof patch.opacity === 'number' && Number.isFinite(patch.opacity)) o.opacity = Math.max(0, Math.min(1, patch.opacity));
    if (typeof patch.fontSize === 'number' && Number.isFinite(patch.fontSize)) o.fontSize = Math.max(10, Math.min(200, patch.fontSize));
    if (patch.zOrder === 'bottom' || patch.zOrder === 'normal' || patch.zOrder === 'top') o.zOrder = patch.zOrder;
    this._syncWatermark();
    this._host._layoutChanged('setWatermarkOptions');
  }

  public _syncWatermark(): void {
    const o = this._watermarkOptions;
    if (!o.visible) {
      if (this._watermark !== null) this._host.removePrimitive(this._watermark);
      this._watermark = null;
      return;
    }
    const text = o.text?.trim() ? o.text : [this._host._dataContext?.symbol, this._host._dataContext?.interval].filter(Boolean).join(' ');
    if (this._watermark === null) {
      this._watermark = new TextWatermark({ ...o, text });
      this._host.addPrimitive(this._watermark, { anchor: 'primary-pane' });
    } else this._watermark.setOptions({ ...o, text });
    this._host.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Light));
  }

  public takeScreenshot(): HTMLCanvasElement {
    const dpr = this._host._pixelRatio();
    const out = this._host._doc.createElement('canvas');
    out.width = Math.max(1, Math.round(this._host._width * dpr));
    out.height = Math.max(1, Math.round(this._host._height * dpr));
    const g = out.getContext('2d');
    if (g === null) return out;
    g.fillStyle = this._host._theme.background;
    g.fillRect(0, 0, out.width, out.height);
    const layout = this._host._paneLayout();
    for (let i = 0; i < this._host._panes.length; i++) {
      if (this._host._layout._layoutWeight(i) <= 0) continue;
      const y = Math.round((layout[i]?.top ?? 0) * dpr);
      for (const layer of [this._host._panes[i]!.base, this._host._panes[i]!.top]) {
        // Hidden or unmeasured buffers are invalid Canvas2D image sources.
        if (layer.element.width > 0 && layer.element.height > 0) g.drawImage(layer.element, 0, y);
      }
    }
    return out;
  }

  public exportSVG(options: ExportSvgOptions): string {
    // The type already says 1; an untyped caller asking for 2 gets told why
    // rather than a document that looks the same and is not.
    if (options.dpr !== undefined && options.dpr !== 1) {
      throw new RangeError('exportSVG: dpr must be 1, SVG has no device pixels');
    }
    const width = Math.max(1, Math.round(options.width ?? this._host._width));
    const height = Math.max(1, Math.round(options.height ?? this._host._height));
    const background = options.background !== false;
    const svg = new SvgContext(width, height, { background: background ? this._host._theme.background : undefined });
    const g = svg.asCanvasContext();
    // The same order as a frame: indicator recomputes land before anything is
    // measured, so a study whose inputs changed this tick exports as it will
    // next paint, not as it last did.
    this._host._studies._flushIndicators();
    const liveWidth = this._host._width;
    const liveHeight = this._host._height;
    const liveRatio = this._host._layoutRatio;
    // The document is at ratio 1 on every screen, so its panes are laid out at
    // 1 too: laid out at the screen's ratio, the same chart would export other
    // pane boundaries on a 1.5x laptop than on a 1x or 2x monitor.
    const relaid = width !== liveWidth || height !== liveHeight || this._host._layout._ratioForLayout() !== 1;
    this._host._layoutRatio = 1;
    if (relaid) {
      this._host._width = width;
      this._host._height = height;
      this._host._layout._relayout(true);
    }
    try {
      if (background && this._host._theme.background !== 'transparent') {
        svg.fillStyle = this._host._theme.background;
        svg.fillRect(0, 0, width, height);
      }
      const layout = this._host._paneLayout();
      const topPane = this._host._layout._topPaneIndex();
      for (let i = 0; i < this._host._panes.length; i++) {
        if (this._host._layout._layoutWeight(i) <= 0) continue; // hidden behind a maximized pane
        const pane = this._host._panes[i]!; // `i` walks the panes, and the layout has a box for each
        const ctx: PaneRenderContext = {
          ...this._host._renderContext(i),
          dpr: 1, hoverId: null, hoverKey: null, dragId: null, paintBackground: background,
        };
        // At ratio 1 the DOM draws the separator as a 1px border on the pane
        // box and lets the canvas start below it, its last row hidden by the
        // overflow clip. The export reproduces that box exactly, or the second
        // pane would sit one pixel higher than it does on screen.
        const first = i === topPane;
        const top = layout[i]!.top + (first ? 0 : 1);
        const paneHeight = layout[i]!.height - (first ? 0 : 1);
        if (!first) {
          svg.fillStyle = this._host._theme.paneSeparator;
          svg.fillRect(0, layout[i]!.top, width, 1);
        }
        svg.pushGroup(
          { 'data-pane': i },
          { translate: { x: 0, y: top }, clip: { x: 0, y: 0, width, height: paneHeight } },
        );
        // A Full frame's sequence for one pane, minus the crosshair.
        pane.autoscale(ctx);
        pane.paintBase(ctx, g);
        pane.paintTop(null, ctx, g);
        svg.popGroup();
      }
    } finally {
      this._host._layoutRatio = liveRatio;
      if (relaid) {
        this._host._width = liveWidth;
        this._host._height = liveHeight;
        this._host._layout._relayout(true);
        // Every auto scale was just measured against the export geometry; a
        // Full frame measures it back against the screen's.
        this._host.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Full));
      }
    }
    return svg.toString();
  }

  public applyOptions(opts: ChartApplyOptions): void {
    this._host._withinLayoutChange(() => {
      if (opts.theme) this._host.setTheme(opts.theme);
      if (opts.grid) this._host.setGridOptions(opts.grid);
      if (opts.canvas) this._host.setCanvasOptions(opts.canvas);
      if (opts.statusLine) this._host.setStatusLineOptions(opts.statusLine);
      if (opts.legendIconSize !== undefined) this._host.setLegendIconSize(opts.legendIconSize);
      if (opts.priceScale) this._host.setPriceScaleOptions(opts.priceScale);
      if (opts.priceFormatter !== undefined) this._host.setPriceFormatter(opts.priceFormatter);
      if ('timeFormatter' in opts) this._host.setTimeFormatter(opts.timeFormatter);
      if (opts.timezone !== undefined) this._host.setTimezone(opts.timezone);
      if (opts.crosshairMode) this._host._crosshairMode = opts.crosshairMode;
      if (typeof opts.crosshairSnapToBar === 'boolean') {
        this._host._crosshairSnapToBar = opts.crosshairSnapToBar;
        this._host.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Cursor));
      }
    });
    this._host._layoutChanged('applyOptions');
  }
}
