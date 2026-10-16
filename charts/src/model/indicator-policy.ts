/**
 * Study policies: what a user may do with a study. A host that places a study
 * of its own (a strategy's signal line, a session band, a study a desk
 * mandates) needs restrictions the user cannot lift, one at a time, while the
 * host itself keeps changing the study. It mirrors the drawing policy: each
 * flag defaults to true, so a study without a policy behaves as it always has.
 */

/**
 * `false` restricts the matching user action. Every native call that performs
 * one treats the caller as the user unless it passes `{ force: true }`
 * ({@link IndicatorEditOptions}); a restore always applies.
 */
export interface IndicatorPolicy {
  /** `false`: no legend close button, inventory remove or plain `remove` call takes it off the chart. */
  removable?: boolean;
  /** `false`: no settings button, settings dialog, `setSettings` or scale assignment changes it. */
  configurable?: boolean;
  /** `false`: it keeps its pane and its place in the pane's stack. Other objects still move past it. */
  movable?: boolean;
  /** `false`: left out of the object inventory (`ChartObjects`) and every panel built on it. */
  listed?: boolean;
}

/**
 * Whether a study is its host's rather than the user's: one the user may not
 * remove, or cannot see. A template never holds such a study, and a template
 * that replaces the studies keeps it. The one statement of the rule: the
 * workspace tier's parser and planners and the widget's templates menu take it
 * by path, since this module is pure; the base itself never calls it.
 */
export function hostOwnedStudy(policy: Readonly<IndicatorPolicy> | undefined): boolean {
  return policy?.removable === false || policy?.listed === false;
}

/** `force: true` marks a call as the owning host's, which a study's policy does not restrict. */
export interface IndicatorEditOptions {
  force?: boolean;
}

const FLAGS = ['removable', 'configurable', 'movable', 'listed'] as const;

/**
 * Validate a policy and keep only its restrictions, so an unrestricted study
 * saves nothing and two policies that mean the same compare equal. A flag
 * that is not a boolean throws; a key this build does not know is dropped,
 * the way the drawing migration keeps only its own flags.
 */
export function parseIndicatorPolicy(input: unknown): IndicatorPolicy {
  if (input === null || typeof input !== 'object' || Array.isArray(input)) throw new TypeError('Invalid indicator policy');
  const out: IndicatorPolicy = {};
  for (const flag of FLAGS) {
    const value = (input as Record<string, unknown>)[flag];
    if (value === undefined) continue;
    if (typeof value !== 'boolean') throw new TypeError(`Invalid indicator policy flag: ${flag}`);
    if (!value) out[flag] = false;
  }
  return Object.freeze(out);
}
