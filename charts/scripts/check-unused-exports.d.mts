// The types of check-unused-exports.mjs, for tests/check-unused-exports.test.ts.

export function findUnusedExports(root: string, options?: { references?: readonly string[]; tsconfig?: string }): {
  total: number;
  public: number;
  unused: string[];
  testOnly: string[];
  localOnly: string[];
};
export function allowlistProblems(unused: readonly string[], allowed: readonly string[]): string[];
