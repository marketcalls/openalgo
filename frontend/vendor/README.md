# Local chart candidate

`openalgo-charts-2.4.0-d417532.tgz` contains the chart library built from local
commit `d417532` on `feat/production-chart-workspace`. It supplies the interval
linking, candle-center crosshair and volume-study APIs used by this branch.

The frontend uses a relative file dependency; the lockfile records its SHA-512
integrity. This is an intermediate development candidate, not a published npm
release. Replace it with the final verified package when the workspace work is
complete. Do not point the dependency at an absolute worktree path.
