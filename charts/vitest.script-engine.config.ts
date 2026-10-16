import { resolve } from 'node:path';
import { defineConfig } from 'vitest/config';

const root = process.env.SCRIPT_ENGINE_ROOT;
if (!root) throw new Error('SCRIPT_ENGINE_ROOT must name a built script engine checkout');

export default defineConfig({
  resolve: {
    alias: [
      { find: /^script-engine-under-test\/adapters\/charts$/, replacement: resolve(root, 'dist/adapters/charts/index.js') },
      { find: /^script-engine-under-test$/, replacement: resolve(root, 'dist/core/index.js') },
    ],
  },
  test: { include: ['integration/script-engine.test.ts'], environment: 'node' },
});
