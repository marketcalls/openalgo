import { createMemoryCatalogStorage } from './catalog';
import { WORKSPACE_CATALOG, type WorkspaceStorage } from './repository';

/**
 * Revision-checked workspace storage in memory: for tests, previews and hosts
 * without IndexedDB. Nothing outlives the page. `seed` maps namespaces to
 * catalogs. It keeps the IndexedDB adapter's contract: a stale or skipping
 * write is refused, and a corrupt stored catalog is never replaced.
 */
export function createMemoryWorkspaceStorage(seed: Readonly<Record<string, unknown>> = {}): WorkspaceStorage {
  return createMemoryCatalogStorage(seed, WORKSPACE_CATALOG);
}
