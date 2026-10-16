/**
 * Combined bundle: the base and every tier but trade and widget in a single
 * module instance, so each tier registers into the SAME registries that
 * `createChart` reads (the transform tier's Point & Figure and Kagi renderers,
 * the built-in indicators and drawing tools, the WebGL2 backend). This is
 * built for the documentation site's live demos only. It is NOT a published
 * package entry point: apps import the individual tiers they use, and a page
 * with no bundler loads the script-tag files, one per tier.
 *
 * The trade tier is intentionally excluded (it shares some type names with the
 * base feed types, and the trade demos use only base APIs).
 */
export * from './index';
export * from './transform/index'; // side effect: registers 'point-figure' and 'kagi'
export * from './profile/index';
export * from './indicators/index'; // side effect: registers the built-in indicators
export * from './draw/index'; // side effect: registers the built-in drawing tools
export * from './webgl/index'; // side effect: registers the 'webgl2' render backend
export * from './workspace/index';
