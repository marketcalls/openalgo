// A study the host places and protects. It shows the study policies working
// together: the user keeps the view of it (hide and show it, read its
// values, raise an alert on it), but no legend button, Objects dock row,
// menu, chip or settings dialog removes it, changes its settings or moves
// it off its pane or out of its place in the stack. It is listed, so the
// dock shows exactly which actions the policy withholds. The policy is
// saved with the layout, so a reload brings the study back protected, and a
// layout the user imports or loads keeps it (`keepHostStudy`).
// Only the host takes it away again, through its own "Remove Protected
// VWAP" row, which is the one place `force` is passed.

/** The policy the host study carries. */
export const HOST_STUDY_POLICY = Object.freeze({ removable: false, configurable: false, movable: false });

/** The host's protected study on `chart`, if it holds one. */
export function hostStudy(chart) {
  if (!chart) return undefined;
  return chart.indicators().find((study) => study.indicatorId === 'vwap' && typeof study.policy === 'function'
    && Object.keys(HOST_STUDY_POLICY).every((flag) => study.policy()[flag] === false));
}

/** Add the protected study, or return the one already there. */
export function addHostStudy(chart) {
  return hostStudy(chart) ?? chart.addIndicator('vwap', {}, { policy: { ...HOST_STUDY_POLICY } });
}

/** Take the protected study away: the host's act, so it passes `force`. */
export function removeHostStudy(chart) {
  const study = hostStudy(chart);
  return study !== undefined && chart.removeIndicator(study.id, { force: true });
}

/** Whether a saved study entry is the host's protected study. */
function isHostStudyState(entry) {
  return entry?.indicatorId === 'vwap' && Object.keys(HOST_STUDY_POLICY).every((flag) => entry.policy?.[flag] === false);
}

/**
 * A layout the user asked to apply (an imported file, the saved layout),
 * carrying the host's protected study as it is on `chart` now. Applying one
 * is the user's act, so it neither takes that study away nor brings a second
 * one. A layout that already holds the study, the host's own save, is left
 * as it is, and so is a chart without it.
 */
export function keepHostStudy(chart, state) {
  const study = hostStudy(chart);
  const indicators = Array.isArray(state?.indicators) ? state.indicators : [];
  if (!study || indicators.some(isHostStudyState)) return state;
  const entry = (chart.getState().indicators || []).find((item) => item.instanceId === study.id);
  if (!entry) return state;
  const { instanceId, ...rest } = entry;
  // On the price pane, wherever the layout puts it; its id only while no study there has it.
  const kept = { ...rest, paneIndex: Number.isInteger(state.primaryPane) ? state.primaryPane : 0 };
  if (!indicators.some((item) => item?.instanceId === instanceId)) kept.instanceId = instanceId;
  return { ...state, indicators: [...indicators, kept] };
}

/** What a user control may do with a study: a missing `policy` (an older engine) allows everything. */
export function studyAllows(study, flag) {
  return typeof study?.policy !== 'function' || study.policy()[flag] !== false;
}
