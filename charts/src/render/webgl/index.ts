/**
 * The WebGL2 render backend (ARCHITECTURE.md section 3.4). Importing this
 * module registers nothing. The `openalgo-charts/webgl` tier entry registers
 * it on import through `registerWebGL2Backend`, and a host whose bundler drops
 * that side effect calls `registerWebGL2Renderer()` from the tier; then
 * `renderer: 'auto'` picks the GPU path up wherever WebGL2 is available.
 */
export {
  WebGL2Backend, GlDevice, sharedGlDevice, isWebGL2Supported, createWebGL2Backend, registerWebGL2Backend,
} from './backend';
export type { GlSurface } from './backend';
export { VertexBatch, FLOATS_PER_VERTEX, VERTICES_PER_QUAD, INDICES_PER_QUAD, SOLID } from './batch';
export { ColorCache, parsePremultiplied, lerpPremultiplied, normaliseWith2d, TRANSPARENT } from './color';
export type { PremultipliedRgba } from './color';
export { compileShapeProgram } from './shaders';
export type { ShapeProgram } from './shaders';
