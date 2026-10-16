// The types of check-cycles.mjs, for tests/check-cycles.test.ts.

export interface ImportEdge {
  from: string;
  to: string;
  kind: 'value' | 'inline-type' | 'type' | 'dynamic';
  line: number;
}

export function measureCycles(root: string, options?: { dir?: string; tsconfig?: string }): {
  modules: string[];
  edges: ImportEdge[];
  unresolved: string[];
  runtime: string[][];
  typeInclusive: string[][];
};
export function ratchetProblems(sizes: readonly number[], ratchet: readonly number[]): string[];
