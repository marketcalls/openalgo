import React, { useEffect, useRef, useState } from 'react';
import { useTheme } from 'next-themes';
import { highlight } from './highlight';

type Tier = 'trade' | 'transform' | 'profile' | 'indicators' | 'draw' | 'webgl' | 'widget';

interface Props {
  /**
   * The example source. It is executed as `fn(el, lib)` where `el` is the chart
   * container and `lib` is the merged library namespace. End with `return chart;`
   * so the demo can be torn down cleanly. This exact string is also displayed.
   */
  code: string;
  /** Extra tiers to load alongside the base bundle. */
  tiers?: Tier[];
  /** Chart area height in px. */
  height?: number;
  /** Hide the code panel (chart only). */
  hideCode?: boolean;
  /** Optional caption under the demo. */
  caption?: React.ReactNode;
}

// One combined module instance (base + every engine tier) so tier-registered
// types (the transform tier's point-figure/kagi renderers, the indicator tier's
// built-in descriptors, the webgl tier's backend) share the registries
// createChart reads. See src/all.ts.
//
// The widget is not in that bundle: it is the one tier that ships DOM and is
// kept out of every other bundle, so a widget demo loads the published tier
// file itself. That file imports its own engine, draw and (here) indicator
// tiers by sibling path, so the widget runs on a second engine instance; the
// demo code only ever hands it plain bar data, which belongs to no instance.
async function loadLib(tiers: readonly Tier[]): Promise<Record<string, unknown>> {
  const lib = await import('../lib/oac/openalgo-charts.all.mjs');
  // The trade tier is not in the combined bundle either. Its broker, account
  // and engine classes hold no registry, so running them on the tier file's
  // own engine instance is safe; only these three are merged in.
  const trade = tiers.includes('trade') ? await import('../lib/oac/openalgo-charts.trade.mjs') : null;
  const extra = trade === null ? {} : { AccountManager: trade.AccountManager, FakeBroker: trade.FakeBroker, OrderEngine: trade.OrderEngine };
  if (!tiers.includes('widget')) return { ...lib, ...extra } as unknown as Record<string, unknown>;
  const [widget] = await Promise.all([
    import('../lib/oac/openalgo-charts.widget.mjs'),
    import('../lib/oac/openalgo-charts.indicators.mjs'),
  ]);
  return { ...lib, ...extra, createWidget: widget.createWidget } as unknown as Record<string, unknown>;
}

export default function RunnableExample({ code, tiers = [], height = 360, hideCode = false, caption }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [err, setErr] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const { resolvedTheme } = useTheme();
  const dark = resolvedTheme !== 'light';

  useEffect(() => {
    let chart: { destroy?: () => void } | undefined;
    let cancelled = false;
    setReady(false);
    setErr(null);
    (async () => {
      try {
        const lib = await loadLib(tiers);
        if (cancelled || !ref.current) return;
        ref.current.innerHTML = '';
        // The library defaults to the light palette, which reads as a white hole
        // punched in a dark docs page. Wrap `createChart` so every example follows
        // the site theme without each one having to ask; an example that passes
        // its own `theme` still wins, since caller options spread last.
        // A copy, not `Object.create(lib)`: a module namespace exposes its
        // exports as getter-only accessors, so an override on a child object
        // throws rather than shadowing.
        const create = lib.createChart as (h: HTMLElement, o: unknown) => unknown;
        const createW = lib.createWidget as ((h: HTMLElement, o: unknown) => unknown) | undefined;
        const themed = {
          ...lib,
          createChart: (host: HTMLElement, opts?: Record<string, unknown>) =>
            create(host, { theme: dark ? lib.darkTheme : lib.lightTheme, ...opts }),
          // The widget names its palette rather than taking a theme object, and
          // defaults to dark where the engine defaults to light; either way a
          // demo should open in the site's theme.
          ...(createW
            ? {
                createWidget: (host: HTMLElement, opts?: Record<string, unknown>) =>
                  createW(host, { theme: dark ? 'dark' : 'light', ...opts }),
              }
            : {}),
        };
        // eslint-disable-next-line @typescript-eslint/no-implied-eval
        const fn = new Function('el', 'lib', code) as (el: HTMLElement, lib: unknown) => { destroy?: () => void };
        chart = fn(ref.current, themed);
        setReady(true);
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
      try { chart?.destroy?.(); } catch { /* ignore */ }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code, tiers.join(','), dark]);

  return (
    <div className="oac-example">
      <div className="oac-example__stage">
        <span className="oac-example__badge">live</span>
        <div className="oac-example__chart" ref={ref} style={{ height }} />
        {!ready && !err && <div className="oac-example__loading">Rendering live chart…</div>}
        {err && <div className="oac-example__err">Demo error: {err}</div>}
      </div>
      {caption && <div className="oac-example__caption">{caption}</div>}
      {!hideCode && (
        <details className="oac-example__source">
          <summary>View example code</summary>
          <pre className="oac-example__code" aria-label="example source">
            <code dangerouslySetInnerHTML={{ __html: highlight(code) }} />
          </pre>
        </details>
      )}
    </div>
  );
}
