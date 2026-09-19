# Local chart candidate

`openalgo-charts-2.4.0-566858e.tgz` contains the chart library built from local
commit `566858e` on `feat/production-chart-workspace`. It supplies interval
linking, candle-center crosshair, volume studies and the optional portable
workspace/template repository with atomic browser storage used by this branch.

The frontend uses a relative file dependency; the lockfile records its SHA-512
integrity. This is an intermediate development candidate, not a published npm
release. Replace it with the final verified package when the workspace work is
complete. Do not point the dependency at an absolute worktree path.
