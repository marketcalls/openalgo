/**
 * The one program the WebGL2 backend draws with: flat fills and analytically
 * anti-aliased strokes from the same vertex layout (see batch.ts).
 *
 * Coverage is computed from a signed distance rather than from multisampling,
 * which is why the context is created with `antialias: false`. The distance
 * is a rounded box in the shape's own frame, and because that frame is in
 * device pixels the distance changes by exactly one per pixel, so the
 * coverage of a pixel whose centre sits `d` inside the edge is `0.5 - d`
 * clamped: exact for an axis-aligned edge, which is what a candle is made
 * of, and a close match to a 2D context's stroke elsewhere. The derivative
 * is not read with `fwidth`: at the corner of a box the two neighbours differ
 * along both axes and `fwidth` reports two, which would leave every candle
 * corner three-quarters covered.
 */
import { OFFSET_COLOR, OFFSET_LOCAL, OFFSET_POS, OFFSET_SHAPE, VERTEX_BYTES } from './batch';

const VERTEX_SHADER = `#version 300 es
precision highp float;
uniform vec2 u_resolution;
in vec2 a_pos;
in vec4 a_color;
in vec2 a_local;
in vec3 a_shape;
out vec4 v_color;
out vec2 v_local;
flat out vec3 v_shape;
void main() {
  vec2 clip = vec2(a_pos.x / u_resolution.x * 2.0 - 1.0, 1.0 - a_pos.y / u_resolution.y * 2.0);
  gl_Position = vec4(clip, 0.0, 1.0);
  v_color = a_color;
  v_local = a_local;
  v_shape = a_shape;
}
`;

const FRAGMENT_SHADER = `#version 300 es
precision highp float;
in vec4 v_color;
in vec2 v_local;
flat in vec3 v_shape;
out vec4 fragColor;
void main() {
  vec2 q = abs(v_local) - v_shape.xy;
  float d = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - v_shape.z;
  float cov = clamp(0.5 - d, 0.0, 1.0);
  fragColor = clamp(v_color, 0.0, 1.0) * cov;
}
`;

export interface ShapeProgram {
  program: WebGLProgram;
  aPos: number;
  aColor: number;
  aLocal: number;
  aShape: number;
  uResolution: WebGLUniformLocation | null;
}

function compile(gl: WebGL2RenderingContext, type: number, source: string): WebGLShader {
  const shader = gl.createShader(type);
  if (shader === null) throw new Error('openalgo-charts: could not create a WebGL shader');
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS) && !gl.isContextLost()) {
    const log = gl.getShaderInfoLog(shader) ?? '';
    gl.deleteShader(shader);
    throw new Error(`openalgo-charts: WebGL shader failed to compile: ${log}`);
  }
  return shader;
}

/** Compile and link the shapes program and look up its attribute and uniform slots. */
export function compileShapeProgram(gl: WebGL2RenderingContext): ShapeProgram {
  const vs = compile(gl, gl.VERTEX_SHADER, VERTEX_SHADER);
  const fs = compile(gl, gl.FRAGMENT_SHADER, FRAGMENT_SHADER);
  const program = gl.createProgram();
  if (program === null) throw new Error('openalgo-charts: could not create a WebGL program');
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);
  // The shaders are owned by the program once linked; releasing them here
  // frees the handles without affecting it.
  gl.deleteShader(vs);
  gl.deleteShader(fs);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS) && !gl.isContextLost()) {
    const log = gl.getProgramInfoLog(program) ?? '';
    gl.deleteProgram(program);
    throw new Error(`openalgo-charts: WebGL program failed to link: ${log}`);
  }
  return {
    program,
    aPos: gl.getAttribLocation(program, 'a_pos'),
    aColor: gl.getAttribLocation(program, 'a_color'),
    aLocal: gl.getAttribLocation(program, 'a_local'),
    aShape: gl.getAttribLocation(program, 'a_shape'),
    uResolution: gl.getUniformLocation(program, 'u_resolution'),
  };
}

/**
 * Point the program's attributes at the interleaved vertex layout of the
 * currently bound array buffer. Recorded on the bound vertex array object, so
 * this runs once per context, not per frame.
 */
export function bindShapeAttributes(gl: WebGL2RenderingContext, p: ShapeProgram): void {
  gl.enableVertexAttribArray(p.aPos);
  gl.vertexAttribPointer(p.aPos, 2, gl.FLOAT, false, VERTEX_BYTES, OFFSET_POS);
  gl.enableVertexAttribArray(p.aColor);
  gl.vertexAttribPointer(p.aColor, 4, gl.FLOAT, false, VERTEX_BYTES, OFFSET_COLOR);
  gl.enableVertexAttribArray(p.aLocal);
  gl.vertexAttribPointer(p.aLocal, 2, gl.FLOAT, false, VERTEX_BYTES, OFFSET_LOCAL);
  gl.enableVertexAttribArray(p.aShape);
  gl.vertexAttribPointer(p.aShape, 3, gl.FLOAT, false, VERTEX_BYTES, OFFSET_SHAPE);
}
