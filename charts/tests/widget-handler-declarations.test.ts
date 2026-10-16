/**
 * The widget's optional handlers keep the method declarations they had in
 * 2.5.10, so a host handler written for the element the widget passes it (a
 * button, a div) still type-checks against them. A declaration moved to a
 * plain function type fails `npm run typecheck` here, before a host meets it.
 */
import { describe, expect, it } from 'vitest';
import type { ContextMenuHooks, MobileOptions, OrderRequest, PanelDockOptions, TopbarOptions } from '../src/widget/index';

describe('the optional handler declarations', () => {
  it('take host handlers with a narrower parameter, as methods do', () => {
    const onButton = (anchor: HTMLButtonElement): boolean => anchor !== null;
    const topbar: Pick<TopbarOptions, 'onDataWindow' | 'onWatchlist' | 'onNews' | 'onGoTo'> = {
      onDataWindow: onButton, onWatchlist: onButton, onNews: onButton, onGoTo: onButton,
    };
    const mobile: Pick<MobileOptions, 'onDataWindow' | 'onWatchlist' | 'onNews' | 'onGoTo' | 'onLayouts'> = {
      onDataWindow: onButton, onWatchlist: onButton, onNews: onButton, onGoTo: onButton, onLayouts: onButton,
    };
    const content = { destroy: (): void => {} };
    const dock: Pick<PanelDockOptions, 'watchlist' | 'news'> = {
      watchlist: (host: HTMLDivElement) => { void host; return content; }, news: (host: HTMLDivElement) => { void host; return content; },
    };
    const hooks: Pick<ContextMenuHooks, 'onOrder' | 'tradingLocked'> = {
      onOrder: (order: OrderRequest & { price: number }) => { void order; }, tradingLocked: () => false,
    };
    expect([topbar, mobile, dock, hooks].every((declared) => Object.keys(declared).length > 0)).toBe(true);
  });
});
