import type { Bar } from '../model/bar';
import type { BarsPage, BarsPageRequest, BarsRequest, DataFeed } from './types';
import { dataVariantKey } from './data-variant';
import { MAX_DELAY } from '../helpers/timers';

/** Limits apply to each pool, whose identity belongs to one data feed. */
export interface HistoryRequestPoolOptions {
  maxConcurrent?: number;
  timeoutMs?: number;
}

const DEFAULT_TIMEOUT = 15_000;
function requestError(name: string, message: string): Error {
  const error = new Error(message);
  error.name = name;
  return error;
}
/** A valid timeout, held to the longest a timer can wait: a longer one would fire at once. */
function deadline(ms: number): number {
  if (!Number.isFinite(ms) || ms <= 0) throw new RangeError('History timeout must be positive and finite');
  return Math.min(ms, MAX_DELAY);
}

/** Also fences adapters that do not honor an aborted fetch or body read. */
export function withHistoryDeadline<T>(req: { signal?: AbortSignal | undefined; timeoutMs?: number | undefined }, run: (signal: AbortSignal) => Promise<T>): Promise<T> {
  if (req.signal?.aborted) return Promise.reject(requestError('AbortError', 'History request cancelled'));
  const timeout = deadline(req.timeoutMs ?? DEFAULT_TIMEOUT);
  return new Promise<T>((resolve, reject) => {
    const controller = new AbortController();
    let settled = false;
    const finish = (ok: boolean, value: unknown): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      req.signal?.removeEventListener('abort', cancel);
      if (ok) resolve(value as T);
      else { controller.abort(); reject(value); }
    };
    const cancel = (): void => finish(false, requestError('AbortError', 'History request cancelled'));
    const timer = setTimeout(() => finish(false, requestError('TimeoutError', 'History request timed out')), timeout);
    req.signal?.addEventListener('abort', cancel, { once: true });
    try { void run(controller.signal).then(value => finish(true, value), error => finish(false, error)); }
    catch (error) { finish(false, error); }
  });
}

type Result = Bar[] | BarsPage;
interface Consumer {
  resolve(value: Result): void;
  reject(reason: unknown): void;
  cleanup(): void;
}
interface Job {
  key: string;
  req: BarsRequest | BarsPageRequest;
  page: boolean;
  priority: number;
  controller: AbortController;
  consumers: Set<Consumer>;
  running: boolean;
  done: boolean;
}

function copyResult(result: Result): Result {
  const copyBars = (bars: Bar[]): Bar[] => bars.map(bar => {
    if (bar === null || typeof bar !== 'object') throw new TypeError('Invalid history bar');
    return { ...bar };
  });
  if (Array.isArray(result)) return copyBars(result);
  return { ...result, bars: copyBars(result.bars) };
}

/**
 * Shares in-flight historical requests while each consumer owns its lifetime.
 * Higher priorities run first among queued work; active work is not preempted.
 */
export class HistoryRequestPool {
  private readonly _feed: DataFeed;
  private readonly _max: number;
  private readonly _timeout: number;
  private readonly _jobs = new Map<string, Job>();
  private _active = 0;
  private _draining = false;

  public constructor(feed: DataFeed, options: HistoryRequestPoolOptions = {}) {
    this._feed = feed;
    this._max = options.maxConcurrent ?? 4;
    if (!Number.isInteger(this._max) || this._max < 1) throw new RangeError('History concurrency must be a positive integer');
    this._timeout = deadline(options.timeoutMs ?? DEFAULT_TIMEOUT);
  }

  public getBars(req: BarsRequest, priority = 0): Promise<Bar[]> {
    return this._request(req, false, priority) as Promise<Bar[]>;
  }

  public getBarsPage(req: BarsPageRequest, priority = 0): Promise<BarsPage> {
    if (!this._feed.getBarsPage) return Promise.reject(new Error('This feed does not support history pages'));
    return this._request(req, true, priority) as Promise<BarsPage>;
  }

  private _request(req: BarsRequest | BarsPageRequest, page: boolean, priority: number): Promise<Result> {
    if (req.signal?.aborted) return Promise.reject(requestError('AbortError', 'History request cancelled'));
    if (!Number.isFinite(priority)) return Promise.reject(new RangeError('History priority must be finite'));
    let timeout: number;
    try { timeout = deadline(req.timeoutMs ?? this._timeout); }
    catch (error) { return Promise.reject(error); }
    let key: string;
    try {
      // Two variants of one series are two answers, so they never share a job.
      key = JSON.stringify([page, req.symbol, req.exchange, req.interval, req.from, req.to,
        req.countBack, req.noCache === true, 'before' in req ? req.before : null, dataVariantKey(req.variant)]);
    } catch (error) { return Promise.reject(error); }
    let job = this._jobs.get(key);
    if (!job) {
      // Consumer timers own the deadline. A provider's shorter default must
      // not expire shared work while another consumer still needs it.
      job = { key, req: { ...req, signal: undefined, timeoutMs: MAX_DELAY }, page, priority,
        controller: new AbortController(), consumers: new Set(), running: false, done: false };
      this._jobs.set(key, job);
    }
    const shared = job;
    shared.priority = Math.max(shared.priority, priority);
    const promise = new Promise<Result>((resolve, reject) => {
      const leave = (error: Error): void => {
        if (!shared.consumers.delete(consumer)) return;
        consumer.cleanup();
        reject(error);
        if (shared.consumers.size === 0) {
          this._remove(shared);
          shared.controller.abort();
          this._drain();
        }
      };
      const cancel = (): void => leave(requestError('AbortError', 'History request cancelled'));
      const timer = setTimeout(() => leave(requestError('TimeoutError', 'History request timed out')), timeout);
      const consumer: Consumer = { resolve, reject, cleanup: () => {
        clearTimeout(timer);
        req.signal?.removeEventListener('abort', cancel);
      } };
      shared.consumers.add(consumer);
      req.signal?.addEventListener('abort', cancel, { once: true });
    });
    this._drain();
    return promise;
  }

  private _remove(job: Job): void {
    if (job.done) return;
    job.done = true;
    if (this._jobs.get(job.key) === job) this._jobs.delete(job.key);
    if (job.running) this._active--;
  }

  private _finish(job: Job, ok: boolean, value: unknown): void {
    if (job.done) return;
    let result: Result | undefined;
    if (ok) {
      try {
        if (job.page === Array.isArray(value)) throw new TypeError('Invalid history result shape');
        result = copyResult(value as Result);
      } catch (error) { ok = false; value = error; }
    }
    this._remove(job);
    for (const consumer of job.consumers) {
      consumer.cleanup();
      if (ok) consumer.resolve(copyResult(result as Result));
      else consumer.reject(value);
    }
    job.consumers.clear();
    this._drain();
  }

  private _drain(): void {
    if (this._draining) return;
    this._draining = true;
    try {
      while (this._active < this._max) {
        let next: Job | undefined;
        for (const job of this._jobs.values()) {
          if (!job.running && (!next || job.priority > next.priority)) next = job;
        }
        if (!next) return;
        const job = next;
        job.running = true;
        this._active++;
        const req = { ...job.req, signal: job.controller.signal };
        try {
          const promise = job.page ? this._feed.getBarsPage!(req as BarsPageRequest) : this._feed.getBars(req);
          void promise.then(result => this._finish(job, true, result), error => this._finish(job, false, error));
        } catch (error) { this._finish(job, false, error); }
      }
    } finally { this._draining = false; }
  }
}

const sharedPools = new WeakMap<DataFeed, HistoryRequestPool>();
/** Reuse one pool only for consumers of this exact feed instance. */
export function sharedHistoryRequests(feed: DataFeed): HistoryRequestPool {
  let pool = sharedPools.get(feed);
  if (!pool) { pool = new HistoryRequestPool(feed); sharedPools.set(feed, pool); }
  return pool;
}
