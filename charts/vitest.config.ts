import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

const src = (rel: string) => fileURLToPath(new URL(rel, import.meta.url));

export default defineConfig({
  // Tiers import shared runtime state (the registries) from the package entry
  // rather than a deep path, so each tier bundle references one instance
  // instead of inlining its own copy. See rollup.config.js. The subpath form
  // comes first and the bare name is anchored: a plain string alias for
  // 'openalgo-charts' also matches 'openalgo-charts/draw' as a prefix and
  // would resolve it to src/index.ts/draw.
  resolve: {
    alias: [
      { find: /^openalgo-charts\/([a-z]+)$/, replacement: src('./src/$1/index.ts') },
      { find: /^openalgo-charts$/, replacement: src('./src/index.ts') },
    ],
  },
  test: {
    include: ['tests/**/*.test.ts'],
    setupFiles: ['tests/setup/widget-parts.ts'],
    environment: 'node',
    globals: false,
  },
});
