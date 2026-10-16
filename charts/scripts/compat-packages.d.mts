// The types of compat-packages.mjs, for tests/saved-documents.test.ts.

export const BASELINES: readonly { version: string; why: string }[];
export function packedRelease(version: string): string;
