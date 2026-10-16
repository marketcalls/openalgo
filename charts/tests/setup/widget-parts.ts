/**
 * The widget fetches some of its UI on first use (src/widget/lazy.ts). Once a
 * part has arrived it opens synchronously, which is what the tests of the
 * parts themselves check, so every part a test file's imports declared is
 * fetched before its tests run. A file that imports no widget code declares
 * none and fetches nothing. The late and failed loads have tests of their own
 * (widget-lazy-parts.test.ts and the widget-lazy-parts e2e spec).
 */
import { beforeAll } from 'vitest';
import { loadWidgetParts } from '../../src/widget/lazy';

beforeAll(async () => { await loadWidgetParts(); });
