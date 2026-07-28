# custom/

Reusable custom indicator modules from `/custom-indicator`.

Unlike the other folders these are real modules you import from charts,
scanners and dashboards — not one-off scripts. Named after the indicator:
`squeeze_momentum.py`, `vwap_bands.py`.

Check `openalgo.ta` first — it ships 127 indicators in the Rust core, and
reimplementing one is both slower and a chance to get it wrong.

If a module here graduates into something the platform should ship, move it
into the codebase proper rather than un-ignoring it.
