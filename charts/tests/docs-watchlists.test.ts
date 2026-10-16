import { expect, it } from 'vitest';
import workspacesGuide from '../docs/workspaces.md?raw';
import widgetGuide from '../docs/widget.md?raw';
import * as watchlists from '../src/workspace/watchlists';
import * as watchlistPanel from '../src/widget/watchlist-panel';
import * as newsPanel from '../src/widget/news-panel';
import * as quoteBoard from '../src/widget/quote-board';
import * as newsReader from '../src/widget/news-reader';

// README sends readers of each tier to these guides, so what the tier exports has to be in them.
it('the workspace guide names every watchlist export', () => {
  const missing = Object.keys(watchlists).filter(name => !workspacesGuide.includes(name));
  expect(missing).toEqual([]);
  expect(workspacesGuide).toContain('WatchlistStore');
});

it('the widget guide names the watchlist and news options, methods and exports', () => {
  const exported = [watchlistPanel, newsPanel, quoteBoard, newsReader].flatMap(module => Object.keys(module));
  const missing = [...exported, 'watchlist:', 'news:', 'openWatchlist()', 'openNews()', 'QuoteFeed', 'NewsFeed']
    .filter(name => !widgetGuide.includes(name));
  expect(missing).toEqual([]);
});
