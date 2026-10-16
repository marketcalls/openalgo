// Derives the light-theme architecture diagram from docs/architecture-diagram.svg.
//
// The dark SVG stays the one source: README and ARCHITECTURE.md show it, and its
// numbers are corrected by editing its text. A hand-kept light copy would drift
// the way the old PNG did, so the website's light variant is generated from it by
// mapping each colour. A colour the map does not know stops the build instead of
// leaving a dark fill in the light diagram.

/** Every colour in the dark diagram, with the one that takes its role on light. */
export const LIGHT_DIAGRAM_COLORS = {
  // surfaces
  '#080e17': '#f7f9fb', // canvas
  '#152333': '#e6eef5', // version pill
  '#2d465c': '#b6c8d8', // version pill outline
  '#191c22': '#fcf8f1', // host panel
  '#534633': '#dfc9a3', // host panel outline
  '#514737': '#e4d5ba', // host divider
  '#0b1722': '#eef6f7', // base engine panel
  '#31545c': '#a7cbcf', // base engine outline
  '#101e2b': '#ffffff', // pipeline panels
  '#0e1d28': '#ffffff', // lower engine panels
  '#263b4c': '#c8d6e1', // engine panel outlines
  '#121724': '#ffffff', // tier panels
  '#34364e': '#d4d1e8', // tier outlines and rules
  '#273849': '#d2dce5', // footer rule
  // accents
  '#5cd3c5': '#0f8f83', // flow arrows and panel rules
  '#79d9cf': '#0b7a70', // kickers
  '#f0ca87': '#8a5a0f', // host label
  '#c9c5ff': '#5144b8', // tier names
  '#ada8d5': '#665f96', // tier sizes
  // text
  '#e9f0f7': '#0e1a26', // default text
  '#a8b9c9': '#4b5e71', // subtitle
  '#90a7bb': '#526679', // section labels
  '#bbc9d6': '#3a4a59', // host body
  '#b8e9e3': '#0a655d', // public API line
  '#c4d1dc': '#314150', // body
  '#8fb7bb': '#46706f', // notes
  '#c4ccd9': '#35404f', // tier body
  '#93a9bd': '#506579', // footer
};

/** Returns the light variant of the dark diagram, or throws on an unmapped colour. */
export function lightDiagram(svg) {
  const unmapped = new Set();
  const light = svg.replace(/#(?:[0-9a-f]{6}|[0-9a-f]{3})\b/gi, (color) => {
    const mapped = LIGHT_DIAGRAM_COLORS[color.toLowerCase()];
    if (mapped === undefined) unmapped.add(color);
    return mapped ?? color;
  });
  if (unmapped.size > 0) {
    throw new Error(`[sync-lib] add a light colour for ${[...unmapped].join(', ')} in scripts/diagram-light.mjs`);
  }
  return light;
}
