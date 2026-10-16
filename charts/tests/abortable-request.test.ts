import { describe, expect, it, vi } from 'vitest';
import { runAbortable } from '../src/model/abortable-request';

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

describe('abortable requests', () => {
  it('returns synchronous values with a fresh signal when no sources are supplied', async () => {
    const signals: AbortSignal[] = [];
    expect(await runAbortable(signal => { signals.push(signal); return 17; }, [])).toBe(17);
    expect(await runAbortable(signal => { signals.push(signal); return 23; }, [undefined])).toBe(23);
    expect(signals[0]).toBeInstanceOf(AbortSignal);
    expect(signals[0].aborted).toBe(false);
    expect(signals[1]).not.toBe(signals[0]);
  });

  it('preserves one unique source identity and subscribes only once', async () => {
    const source = new AbortController();
    const add = vi.spyOn(source.signal, 'addEventListener');
    const remove = vi.spyOn(source.signal, 'removeEventListener');
    let observed: AbortSignal | undefined;
    const result = runAbortable(signal => { observed = signal; return Promise.resolve(42); },
      [undefined, source.signal, source.signal, undefined]);
    expect(observed).toBe(source.signal);
    expect(await result).toBe(42);
    expect(add).toHaveBeenCalledTimes(1);
    expect(remove).toHaveBeenCalledTimes(1);
    expect(remove.mock.calls[0].slice(0, 2)).toEqual(add.mock.calls[0].slice(0, 2));
  });

  it.each(['caller', 'lifetime'] as const)('aborts the composed provider signal when %s is cancelled', async cancelled => {
    const caller = new AbortController(), lifetime = new AbortController();
    const pending = deferred<number>();
    let observed!: AbortSignal;
    const request = runAbortable(signal => { observed = signal; return pending.promise; },
      [caller.signal, lifetime.signal]);
    const reason = { cancelled };
    const rejected = expect(request).rejects.toBe(reason);
    (cancelled === 'caller' ? caller : lifetime).abort(reason);
    await rejected;
    expect(observed).not.toBe(caller.signal);
    expect(observed).not.toBe(lifetime.signal);
    expect(observed.aborted).toBe(true);
    expect(observed.reason).toBe(reason);
    expect((cancelled === 'caller' ? lifetime : caller).signal.aborted).toBe(false);
  });

  it.each([false, true])('does not invoke work when a source was already aborted (composed %j)', async composed => {
    const source = new AbortController(), other = new AbortController();
    const reason = new Error('Already cancelled');
    source.abort(reason);
    let calls = 0;
    const sources = composed ? [other.signal, source.signal] : [source.signal];
    await expect(runAbortable(() => { calls++; return 42; }, sources)).rejects.toBe(reason);
    expect(calls).toBe(0);
  });

  it('uses argument order when several sources were already aborted', async () => {
    const first = new AbortController(), second = new AbortController();
    second.abort('second'); first.abort(null);
    await expect(runAbortable(() => 42, [first.signal, second.signal])).rejects.toBeNull();
  });

  it('preserves the platform default abort reason', async () => {
    const source = new AbortController();
    source.abort();
    await expect(runAbortable(() => 42, [source.signal])).rejects.toBe(source.signal.reason);
    expect(source.signal.reason.name).toBe('AbortError');
  });

  it('rejects promptly when a provider never observes its signal', async () => {
    const source = new AbortController();
    const pending = deferred<number>();
    const reason = new Error('Stop waiting');
    let rejected: unknown = null;
    const request = runAbortable(() => pending.promise, [source.signal]);
    void request.catch(error => { rejected = error; });
    source.abort(reason);
    await Promise.resolve();
    expect(rejected).toBe(reason);
  });

  it('returns a rejected promise for a synchronous provider exception', async () => {
    const reason = new Error('Provider failed');
    let request!: Promise<never>;
    expect(() => { request = runAbortable(() => { throw reason; }, []); }).not.toThrow();
    await expect(request).rejects.toBe(reason);
  });

  it.each(['resolve', 'reject', 'abort'] as const)('removes every source listener on %s', async settlement => {
    const first = new AbortController(), second = new AbortController();
    const add = [vi.spyOn(first.signal, 'addEventListener'), vi.spyOn(second.signal, 'addEventListener')];
    const remove = [vi.spyOn(first.signal, 'removeEventListener'), vi.spyOn(second.signal, 'removeEventListener')];
    const pending = deferred<number>(), reason = new Error('Request ended');
    let observed!: AbortSignal;
    const request = runAbortable(signal => { observed = signal; return pending.promise; },
      [first.signal, second.signal, first.signal]);
    const completion = settlement === 'resolve' ? expect(request).resolves.toBe(42) : expect(request).rejects.toBe(reason);
    if (settlement === 'resolve') pending.resolve(42);
    else if (settlement === 'reject') pending.reject(reason);
    else first.abort(reason);
    await completion;
    for (let i = 0; i < 2; i++) {
      expect(add[i]).toHaveBeenCalledTimes(1);
      expect(remove[i]).toHaveBeenCalledTimes(1);
      expect(remove[i].mock.calls[0].slice(0, 2)).toEqual(add[i].mock.calls[0].slice(0, 2));
    }
    second.abort('late cancellation');
    expect(observed.aborted).toBe(settlement === 'abort');
    if (settlement === 'abort') expect(observed.reason).toBe(reason);
  });

  it('cleans listeners when work throws before returning a promise', async () => {
    const source = new AbortController();
    const remove = vi.spyOn(source.signal, 'removeEventListener');
    const reason = new Error('Synchronous failure');
    await expect(runAbortable(() => { throw reason; }, [source.signal])).rejects.toBe(reason);
    expect(remove).toHaveBeenCalledTimes(1);
  });

  it.each(['resolve', 'reject'] as const)('consumes a late provider %s after cancellation', async settlement => {
    const source = new AbortController(), pending = deferred<number>();
    const reason = new Error('Cancelled');
    const request = runAbortable(() => pending.promise, [source.signal]);
    const completion = expect(request).rejects.toBe(reason);
    source.abort(reason);
    await completion;
    if (settlement === 'resolve') pending.resolve(42);
    else pending.reject(new Error('Late failure'));
    await new Promise(resolve => setTimeout(resolve, 0));
    await expect(request).rejects.toBe(reason);
  });

  it('keeps cancellation when work aborts synchronously and then returns a rejected promise', async () => {
    const source = new AbortController(), reason = new Error('Synchronous cancellation');
    const request = runAbortable(() => {
      source.abort(reason);
      return Promise.reject(new Error('Provider rejected after abort'));
    }, [source.signal]);
    await expect(request).rejects.toBe(reason);
    await new Promise(resolve => setTimeout(resolve, 0));
  });

  it('keeps cancellation when work aborts synchronously and then throws', async () => {
    const source = new AbortController(), reason = new Error('Synchronous cancellation');
    const request = runAbortable(() => { source.abort(reason); throw new Error('Late throw'); }, [source.signal]);
    await expect(request).rejects.toBe(reason);
  });

  it('settles before a composed abort listener synchronously cancels another source', async () => {
    const caller = new AbortController(), lifetime = new AbortController();
    const pending = deferred<number>();
    const reason = new Error('Lifetime ended');
    let notifications = 0;
    const request = runAbortable(signal => {
      signal.addEventListener('abort', () => {
        notifications++;
        caller.abort(new Error('Nested cancellation'));
        pending.reject(new Error('Nested provider rejection'));
      });
      return pending.promise;
    }, [caller.signal, lifetime.signal]);
    const completion = expect(request).rejects.toBe(reason);
    lifetime.abort(reason);
    await completion;
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(notifications).toBe(1);
    expect(caller.signal.aborted).toBe(true);
  });
});
