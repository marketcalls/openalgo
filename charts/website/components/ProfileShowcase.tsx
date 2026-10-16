import React from 'react';
import manifest from '../public/screenshots/market-profile-v2.1.1/captures.json';
import { useSiteScheme } from './site-scheme';

const ROOT = '/openalgo-charts';
const IMAGE_ROOT = `${ROOT}/screenshots/market-profile-v2.1.1`;
const DEMO = `${ROOT}/demos/market-profile/index.html`;
const ORDERFLOW_DEMO = `${ROOT}/demos/orderflow/index.html`;
// Each embedded demo opens in the palette closest to the page around it: its
// light preset on a light page, and on a dark page the palette it always used.
const PROFILE_THEME = { light: 'ivory', dark: 'blue' } as const;
const ORDERFLOW_QUERY = { light: '?theme=ivory&paused=1', dark: '?paused=1' } as const;
const screenshot = (name: keyof typeof manifest.captures) => {
  const capture = manifest.captures[name];
  return `${IMAGE_ROOT}/${capture.file}?v=${capture.sha256.slice(0, 12)}`;
};
const THEMES = [
  { id: 'dark', name: 'Dark', description: 'Multicolour periods on a dark background.' },
  { id: 'blue', name: 'Blue', description: 'Navy background, purple letters and cyan volume.' },
  { id: 'graphite', name: 'Graphite', description: 'Charcoal, pale letters and muted cyan volume.' },
  { id: 'emerald', name: 'Emerald', description: 'Deep green, mint letters and gold reference lines.' },
  { id: 'ivory', name: 'Ivory', description: 'Warm light background, dark letters and blue-grey volume.' },
] as const;

export function ProfileOverviewScreenshot() {
  return (
    <figure className="oac-profile-overview" style={{ margin: '1.5rem 0' }}>
      <a href={screenshot('compressed-overview')} target="_blank" rel="noreferrer" aria-label="View full-resolution compressed market profile demo screenshot">
        <img src={screenshot('compressed-overview')} alt="Blue market profile demo with six packed synthetic sessions, compact pixel letters at 5 CSS pixels per row, volume bars and open/latest-price markers" width={2880} height={2000} loading="lazy" style={{ width: '100%', height: 'auto' }} />
      </a>
      <figcaption>Current demo in Blue · Compressed (5 px) · Synthetic data. Click to view at full resolution.</figcaption>
    </figure>
  );
}

export function ProfileDemo() {
  const scheme = useSiteScheme();
  const src = `${DEMO}?theme=${PROFILE_THEME[scheme ?? 'light']}`;
  return (
    <div className="oac-profile-demo">
      <div className="oac-profile-demo__head">
        <span>Six synthetic sessions · 2-point rows</span>
        <a href={src} target="_blank" rel="noreferrer">Open full-size demo</a>
      </div>
      {/* Mounted only once the theme is known, so it loads once, in the right palette. */}
      {scheme
        ? <iframe key={scheme} src={src} title="Interactive compact market profile demo" loading="lazy" />
        : <div className="oac-profile-demo__placeholder" aria-hidden="true" />}
    </div>
  );
}

export function OrderflowDemo() {
  const scheme = useSiteScheme();
  const src = `${ORDERFLOW_DEMO}${ORDERFLOW_QUERY[scheme ?? 'light']}`;
  return (
    <>
      <p><a href={src} target="_blank" rel="noreferrer">Open full-size order-flow demo</a></p>
      {scheme
        ? <iframe key={scheme} className="oac-orderflow-demo" src={src} loading="lazy"
            title="Interactive footprint chart with profile, cluster ladder and heatmap styles" />
        : <div className="oac-orderflow-demo" aria-hidden="true" />}
    </>
  );
}

export function ProfileThemeGallery() {
  return (
    <div className="oac-profile-gallery">
      {THEMES.map(theme => (
        <figure className="oac-profile-shot" key={theme.id}>
          <a href={screenshot(theme.id)} target="_blank" rel="noreferrer" aria-label={`View full-resolution ${theme.name} screenshot`}>
            <img src={screenshot(theme.id)} alt={`${theme.name} zoomed close-up of the newest daily TPO profile at 18-pixel rows, with period letters, volume, open and latest-price markers; the session is split`} width={800} height={1320} loading="lazy" />
          </a>
          <figcaption>
            <strong>{theme.name}</strong>
            <p>{theme.description}</p>
            <a href={`${DEMO}?theme=${theme.id}`} target="_blank" rel="noreferrer">Try {theme.name}</a>
          </figcaption>
        </figure>
      ))}
    </div>
  );
}

export function ProfileSplitScreenshots() {
  return (
    <div className="oac-profile-details">
      {(['packed', 'split'] as const).map(mode => (
        <figure className="oac-profile-shot" key={mode}>
          <a href={screenshot(`${mode}-detail`)} target="_blank" rel="noreferrer">
            <img src={screenshot(`${mode}-detail`)} alt={`${mode === 'packed' ? 'Packed' : 'Split'} Graphite close-up at 18-pixel rows of the same daily TPO profile, with lowercase o at the open and # at the latest price`} width={800} height={1320} loading="lazy" />
          </a>
          <figcaption><strong>{mode === 'packed' ? 'Packed: gaps closed' : 'Split: one column per period'}</strong></figcaption>
        </figure>
      ))}
    </div>
  );
}
