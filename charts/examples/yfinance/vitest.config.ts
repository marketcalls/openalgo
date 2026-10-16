import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { defineConfig } from 'vitest/config';

// The demo's own vitest config. The repository config only collects
// tests/**, and the demo imports the built library by the absolute URL the
// browser uses ('/dist/openalgo-charts.mjs'), so this one runs from the
// package root and maps that URL onto the dist/ directory.
//
//     npx vitest run --config examples/yfinance/vitest.config.ts
const root = fileURLToPath(new URL('../../', import.meta.url));

export default defineConfig({
  root,
  resolve: {
    alias: [{ find: /^\/dist\//, replacement: path.join(root, 'dist') + path.sep }],
  },
  test: {
    include: ['examples/yfinance/tests/**/*.test.js'],
    environment: 'node',
    globals: false,
  },
});
