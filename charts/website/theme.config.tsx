import React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { useTheme } from 'next-themes';
import { useConfig } from 'nextra-theme-docs';

const REPO = 'https://github.com/marketcalls/openalgo-charts';
const SHARE_IMAGE = 'https://marketcalls.github.io/openalgo-charts/og-chart-workspace.png';

const Logo = () => (
  <span className="oac-brand">
    <span className="oac-brand__mark" aria-hidden="true"><i /></span>
    <span className="oac-brand__word">OpenAlgo<span>Charts</span></span>
  </span>
);

function NavigationExtra() {
  const { resolvedTheme, setTheme } = useTheme();
  return (
    <div className="oac-nav-extra">
      <button type="button" className="oac-theme-toggle" aria-label="Toggle color theme" onClick={() => setTheme(resolvedTheme === 'dark' ? 'light' : 'dark')}>
        <svg className="oac-theme-icon--sun" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" strokeLinecap="round" /></svg>
        <svg className="oac-theme-icon--moon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="M20.5 13.3A8.5 8.5 0 0 1 10.7 3.5a8.5 8.5 0 1 0 9.8 9.8Z" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </button>
      <Link href="/examples" className="oac-nav-cta">Explore charts</Link>
    </div>
  );
}

const config = {
  logo: <Logo />,
  project: { link: REPO },
  docsRepositoryBase: `${REPO}/tree/master/website`,
  primaryHue: 0,
  primarySaturation: 0,
  darkMode: true,
  // A first visit opens in light. The navbar toggle and the sidebar switch still
  // save the reader's choice under `theme`, and a saved choice wins over this
  // default on every later visit.
  // A new storage key: a reader whose browser kept the old default ('dark', or
  // 'system' on a dark OS) from before the site opened in light would never see
  // the light default. Everyone starts light once; a choice made now sticks.
  nextThemes: { defaultTheme: 'light', storageKey: 'oac-theme' },
  navbar: { extraContent: <NavigationExtra /> },
  search: { placeholder: 'Search docs...' },
  sidebar: {
    defaultMenuCollapseLevel: 1,
    toggleButton: true,
  },
  toc: {
    float: true,
    title: 'On this page',
    backToTop: true,
  },
  navigation: { prev: true, next: true },
  feedback: { content: null },
  editLink: { text: 'Edit this page on GitHub' },
  footer: {
    content: (
      <div className="oac-site-footer">
        <div className="oac-site-footer__brand"><Link href="/" aria-label="OpenAlgo Charts home"><Logo /></Link><p>A clearer view of every move.<br />An open world of possibilities.</p></div>
        <div className="oac-site-footer__group"><h2>Explore</h2><Link href="/examples">Interactive examples</Link><Link href="/examples#drawing-tools">Drawing tools</Link><Link href="/examples#custom-indicators">Indicators</Link></div>
        <div className="oac-site-footer__group"><h2>Create</h2><Link href="/docs/getting-started">Get started</Link><Link href="/docs/core-concepts">Documentation</Link><a href="/openalgo-charts/api/index.html">API reference</a><a href={REPO} target="_blank" rel="noreferrer">Contribute on GitHub</a></div>
        <div className="oac-site-footer__bottom"><Link href="/docs/release-notes#264">OpenAlgo Charts 2.6.4</Link><a href={`${REPO}/blob/master/LICENSE`} target="_blank" rel="noreferrer">Free and open source · Apache-2.0</a></div>
      </div>
    ),
  },
  head: function Head() {
    const { frontMatter, title } = useConfig();
    const pagePath = useRouter().asPath.split(/[?#]/, 1)[0];
    const { resolvedTheme } = useTheme();
    const pageTitle = title && title !== 'OpenAlgo Charts' ? `${title} - OpenAlgo Charts` : 'OpenAlgo Charts: Every move. A clearer view.';
    const description =
      (frontMatter as { description?: string }).description ??
      'Explore beautiful interactive charts, powerful indicators, and expressive drawing tools with OpenAlgo Charts.';
    return (
      <>
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>{pageTitle}</title>
        <meta name="description" content={description} />
        <meta property="og:title" content={pageTitle} />
        <meta property="og:description" content={description} />
        <meta property="og:type" content="website" />
        <meta property="og:site_name" content="OpenAlgo Charts" />
        <meta property="og:url" content={`https://marketcalls.github.io/openalgo-charts${pagePath}`} />
        <meta property="og:image" content={SHARE_IMAGE} />
        <meta property="og:image:type" content="image/png" />
        <meta property="og:image:width" content="1200" />
        <meta property="og:image:height" content="630" />
        <meta property="og:image:alt" content="Linked OpenAlgo charts with stock candles, anchored VWAP and volume profiles" />
        <meta name="twitter:card" content="summary_large_image" />
        <meta name="twitter:title" content={pageTitle} />
        <meta name="twitter:description" content={description} />
        <meta name="twitter:image" content={SHARE_IMAGE} />
        <meta name="twitter:image:alt" content="Linked OpenAlgo charts with stock candles, anchored VWAP and volume profiles" />
        {/* The static export renders before any theme is known, so the fallback is the site default. */}
        <meta name="theme-color" content={resolvedTheme === 'dark' ? '#0b0b0b' : '#fcfcfc'} />
      </>
    );
  },
};

export default config;
