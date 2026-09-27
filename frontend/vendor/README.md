# Published chart dependency

The frontend now pins published `openalgo-charts` 2.4.5 from the npm registry.
`package-lock.json` records the registry archive URL and its SHA-512 integrity.
The installed package was checked against all 33 files in that archive.

The retained `openalgo-charts-2.4.0-*.tgz` archives are previous development
candidates. They are no longer referenced by the package manifest or lockfile.
Do not replace the published pin with an absolute worktree path.

This release includes portable workspace/template storage, OI studies and
alerts, coordinated replay, comparisons, CSV export and optional instrument,
localization and trading capability contracts. Package availability does not
mean every control has been integrated into `/trading`; the terminal guide
describes the host behavior that is currently wired.
