import type { BarConfirmationOptions, SeriesApi, SeriesDataState, SeriesUpdateOptions } from './series';

/** Reject malformed metadata before the data layer can accept any bars. */
export function validateSeriesOptions(options: BarConfirmationOptions | undefined, update = false): void {
  if (options === undefined) return;
  if (options === null || typeof options !== 'object' || Array.isArray(options)) {
    throw new TypeError('Series options must be an object');
  }
  if (options.confirmation !== undefined && options.confirmation !== 'auto'
    && options.confirmation !== 'forming' && options.confirmation !== 'confirmed') {
    throw new TypeError('Series confirmation must be auto, forming or confirmed');
  }
  const source = (options as SeriesUpdateOptions).source;
  if (update && source !== undefined && source !== 'live' && source !== 'history') {
    throw new TypeError('Series update source must be live or history');
  }
}

/** Revisions belong to the source series, independently of the shared time axis. */
export class SeriesProvenance {
  private _state: SeriesDataState;
  private _tailTime: number | undefined;

  public constructor(sourceId: number) {
    this._state = Object.freeze({ sourceId, revision: 0, historyRevision: 0, provenance: 'history', change: 'reset' });
  }

  public snapshot(): SeriesDataState { return this._state; }

  public record(change: SeriesDataState['change'], tailTime: number | undefined, options?: SeriesUpdateOptions): void {
    const history = change === 'reset' || change === 'prepend' || change === 'correction' || options?.source === 'history';
    // A late correction describes an older bar, never the current tail.
    const requested = change === 'correction' ? undefined : options?.confirmation;
    const confirmation = requested === 'auto' ? undefined
      : requested ?? (change !== 'reset' && tailTime === this._tailTime ? this._state.confirmation : undefined);
    this._tailTime = tailTime;
    this._state = Object.freeze({
      sourceId: this._state.sourceId,
      revision: this._state.revision + 1,
      historyRevision: this._state.historyRevision + (history ? 1 : 0),
      provenance: history ? 'history' : 'live', change,
      ...(tailTime === undefined || confirmation === undefined ? {} : { confirmation, confirmationSource: 'provider' as const }),
    });
  }

  public contextChanged(): void { this.record('reset', this._tailTime); }
}

const states = new WeakMap<SeriesApi, SeriesProvenance>();

export function bindSeriesProvenance(series: SeriesApi, state: SeriesProvenance): void { states.set(series, state); }

/** Replay snapshots native confirmation without requiring a new public series method. */
export function seriesConfirmation(series: SeriesApi): BarConfirmationOptions | undefined {
  const confirmation = states.get(series)?.snapshot().confirmation;
  return confirmation === undefined ? undefined : { confirmation };
}
