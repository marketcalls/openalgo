/**
 * The price-scale logic behind the chart-wide and one-axis setters: the patch
 * a pane receives from a chart-wide setting, promoting a pane to quoting the
 * instrument, whether a legacy side swap can move an axis, measuring one scale
 * on demand, and the state a menu raised over one price axis reads.
 *
 * Its own module because these are the rules that decide which scales a
 * setting reaches, and they read nothing of the chart beyond what
 * `ScalesHost` names. The chart reaches it through `Chart._scales`, and it
 * reaches the chart through `ScalesHost`. The chart-wide defaults, the
 * formatter and the set of panes that quote the instrument stay on Chart,
 * because the panes and the series read them too. `priceAxisState` stays
 * public on Chart as a delegate and carries the documented contract.
 * `movePriceAxis` keeps its body on Chart: the deprecation policy test holds
 * `priceAxisMoved` to be emitted only inside a method that carries the
 * deprecation tag, and a method here would carry none. Members the chart
 * calls are public on this internal class; no entry point exports the class
 * and the chart holds it in a private field, so none of it reaches the
 * published declarations.
 */
import type { Pane } from './pane';
import type { Chart, PriceAxisState } from './chart';
import { NON_INSTRUMENT_PRECISION } from './chart-panes';
import type { PriceScaleOptions } from '../scale/price-scale';
import type { PriceScaleId } from '../model/series';
import { isPriceScaleId } from '../model/price-axis-layout';

/**
 * The slice of the chart the price-scale logic reads. The chart itself is the
 * host: each member carries the name and the type of the chart's own, so the
 * moved code reads as it did in chart.ts, and a member the chart renames or
 * retypes fails to compile here.
 */
export interface ScalesHost {
  readonly _panes: Chart['_panes'];
  readonly _pricePanes: Chart['_pricePanes'];
  readonly _priceScaleOptions: Chart['_priceScaleOptions'];
  readonly _indicators: Chart['_indicators'];
  readonly _seriesRecords: Chart['_seriesRecords'];
  readonly _seriesOwners: Chart['_seriesOwners'];
  _renderContext: Chart['_renderContext'];
}

export class ChartScales {
  private readonly _host: ScalesHost;

  public constructor(host: ScalesHost) {
    this._host = host;
  }

  /**
   * A chart-wide price-scale patch as one pane should receive it.
   *
   * Every field in it describes the axis, except `minMove`, which describes the
   * **instrument**: it is the step the symbol trades in, 0.05 on an NSE equity.
   * A pane that plots something else is quoted in its own units, so handing it
   * that step is not a coarse answer but an answer to a different question. It
   * shipped as one: a host setting the instrument's 0.10 tick chart-wide made
   * `PriceScale.precision` report one decimal on *every* pane, so a William VIX
   * Fix reading 0.61 was labelled "0.6" and an RSI ladder read "70.0, 50.0,
   * 30.0". Withheld, those axes fall back to inferring precision from the range
   * they actually cover, which is the reading their own numbers imply.
   *
   * Only the chart-wide setters filter. An axis named outright
   * (`setPriceAxisOptions`, a series' `priceFormat`) is the caller saying what
   * that one axis quotes, and is obeyed.
   */
  public _scalePatchFor(pane: Pane, patch: Partial<PriceScaleOptions>): Partial<PriceScaleOptions> {
    if (patch.minMove === undefined || this._host._pricePanes.has(pane)) return patch;
    const out = { ...patch };
    delete out.minMove;
    // Withholding the tick is only half the answer. Left to the span alone a
    // bounded oscillator reads too coarse (an RSI over 0..100 implies a step of
    // 1 and prints "62" for 62.24), so the pane that does not quote the
    // instrument gets the floor instead of the tick, not neither.
    out.minPrecision = NON_INSTRUMENT_PRECISION;
    return out;
  }

  /**
   * Record that a pane quotes the instrument, and hand it the tick it was not
   * given while it did not.
   *
   * The primary pane is one from birth. Any other pane starts out an
   * indicator's, so a host adding a second symbol to a pane of its own has to
   * be able to promote one after the fact, or the comparison would lose the
   * tick-sized axis it has always had.
   */
  public _claimPricePane(pane: Pane): void {
    if (this._host._pricePanes.has(pane)) return;
    this._host._pricePanes.add(pane);
    const minMove = this._host._priceScaleOptions?.minMove;
    // The floor comes off as the tick goes on: a declared tick is the stronger
    // statement, and a promoted pane must end up indistinguishable from one
    // that quoted the instrument all along.
    for (const scale of pane.axisScales()) {
      scale.setOptions(minMove !== undefined ? { minMove, minPrecision: 0 } : { minPrecision: 0 });
    }
  }

  public priceAxisState(paneIndex: number, scaleId: PriceScaleId): PriceAxisState | null {
    const pane = this._host._panes[paneIndex];
    if (pane === undefined || !isPriceScaleId(scaleId)) return null;
    const scale = pane.scaleFor(scaleId);
    const side = pane.axisPlacement(scaleId).side === 'left' ? 'left' : 'right';
    const other: 'right' | 'left' = scaleId === 'left' ? 'right' : 'left';
    return {
      paneIndex,
      scaleId,
      side,
      active: pane.usesScale(scaleId),
      autoFit: scale.autoScale,
      inverted: scale.options.inverted,
      mode: scale.options.mode,
      scaled: scale.scaled,
      lockRatio: pane.ratioLocked(scaleId),
      movable: (scaleId === 'right' || scaleId === 'left') && this._canMovePriceAxis(paneIndex, scaleId, other),
    };
  }

  public _canMovePriceAxis(paneIndex: number, from: 'right' | 'left', to: 'right' | 'left'): boolean {
    const pane = this._host._panes[paneIndex];
    if (!pane || from === to || !pane.usesScale(from) || pane.usesScale(to)) return false;
    // The legacy transfer supports uniform local studies. Mixed studies and
    // price overlays use explicit plot assignments or stable axis placement.
    for (const instance of this._host._indicators) {
      const resources = instance.renderResources();
      const series = resources.series.filter(item => this._host._seriesOwners.get(item.api)?.pane === pane);
      const primitives = resources.primitives.filter(item => pane.hasPrimitive(item.primitive) && pane.primitiveScaleId(item.primitive) !== null);
      const movingSeries = series.filter(item => this._host._seriesRecords.get(item.api)?.scaleId === from);
      const movingPrimitives = primitives.filter(item => pane.primitiveScaleId(item.primitive) === from);
      if (!movingSeries.length && !movingPrimitives.length) continue;
      if (movingSeries.some(item => item.overlay) || movingPrimitives.some(item => item.overlay)) return false;
      if (series.some(item => !item.overlay && this._host._seriesRecords.get(item.api)?.scaleId !== from)
        || primitives.some(item => !item.overlay && pane.primitiveScaleId(item.primitive) !== from)) return false;
    }
    return true;
  }

  /** Measure one scale on demand, the way `_ensureScaled` does for the pane's right one. */
  public _ensureScaledFor(paneIndex: number, scaleId: PriceScaleId): void {
    const pane = this._host._panes[paneIndex];
    if (pane === undefined || pane.scaleFor(scaleId).scaled) return;
    pane.autoscale(this._host._renderContext(paneIndex));
  }
}
