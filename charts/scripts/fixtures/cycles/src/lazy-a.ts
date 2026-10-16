// A dynamic import runs after both modules have loaded, so it closes no loop.
export const loadLazyB = () => import('./lazy-b');
