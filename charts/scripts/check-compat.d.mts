// The types of check-compat.mjs, for tests/check-compat.test.ts.

export interface DeprecationRow {
  names: string[];
  removedIn: string;
}

export interface CompatFinding {
  kind: string;
  where: string;
  pol: number;
  detail?: string;
  via?: string;
  status: 'additive' | 'deprecated' | 'narrowing';
  direction: string;
  removedIn?: string;
  tier: string;
}

export interface CompatTier {
  specifier: string;
  kept: number;
  added: string[];
  findings: Omit<CompatFinding, 'tier'>[];
}

export const KINDS: Readonly<Record<string, string>>;
export function deprecations(text?: string): DeprecationRow[];
export function comparePackages(oldDir: string, newDir: string, rows: readonly DeprecationRow[]): {
  tiers: CompatTier[];
  findings: CompatFinding[];
};
