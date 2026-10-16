import { useState } from 'react';

const version = '?v=2.6.0-architecture-1';
// The light file is generated from the dark one by scripts/sync-lib.mjs.
const diagrams = {
  light: `/openalgo-charts/architecture-diagram-light.svg${version}`,
  dark: `/openalgo-charts/architecture-diagram.svg${version}`,
} as const;
const alt = 'OpenAlgo Charts 2.6.0 architecture: a custom host or widget owns data connections and application authority above the base engine\'s data-to-model-to-render pipeline, alerts, replay and linking, interaction, state and CSV. Eight optional tiers: indicators, draw, profile, transform, trade, workspace, WebGL and widget.';

export default function ArchitectureDiagram() {
  const [actualSize, setActualSize] = useState(false);
  const style = { width: actualSize ? 1280 : '100%', maxWidth: 'none', height: 'auto' } as const;
  // Both variants are rendered and the page's theme class shows one of them
  // (globals.css), so the static export needs no guess about the reader's theme.
  return (
    <figure className="oac-architecture">
      <div className="oac-architecture__controls" role="group" aria-label="Diagram zoom">
        <span>Architecture · 2.6.0</span>
        <button type="button" aria-pressed={!actualSize} onClick={() => setActualSize(false)}>Fit</button>
        <button type="button" aria-pressed={actualSize} onClick={() => setActualSize(true)}>Actual size</button>
        {(['light', 'dark'] as const).map(theme => (
          <a key={theme} className={`oac-architecture__variant--${theme}`} href={diagrams[theme]} target="_blank" rel="noreferrer">Open SVG</a>
        ))}
      </div>
      <div className="oac-architecture__viewport" tabIndex={0} role="region" aria-label="Host boundary, base engine and optional tiers; scroll to explore at actual size">
        {(['light', 'dark'] as const).map(theme => (
          <img key={theme} className={`oac-architecture__variant--${theme}`} src={diagrams[theme]} width={1280} height={1520} style={style} alt={alt} />
        ))}
      </div>
      <figcaption>The host supplies data and application authority; the base engine and eight optional tiers supply chart capabilities. Choose Actual size to read every label, scroll inside the diagram or open the vector image separately.</figcaption>
    </figure>
  );
}
