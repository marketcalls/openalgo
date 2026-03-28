# Data Requirements

## Canonical Market Data Schema

Required columns:

- `symbol`
- `timeframe`
- `timestamp`
- `datetime`
- `open`
- `high`
- `low`
- `close`
- `volume`

## Notes

- `timestamp` should be Unix seconds.
- `datetime` should be ISO 8601.
- Intraday data should be normalized to `Asia/Kolkata`.
- Intraday bars should be filtered to market hours `09:15-15:30` unless intentionally preserving raw feed history.

## Supported Raw Inputs

- `.xlsx`
- `.csv`
- `.parquet`

## Strategy Data Source

The local project assumes the read-only strategy repository remains at:

`D:\test1`

Those files are loaded dynamically and must not be edited by the starter pack.

## Local Indicator Libraries

If open-source Python indicator libraries are cloned under:

`D:\test1\opensource_indicators\`

the loader adds those source folders to the import path. This supports source-based study and reuse without `pip install`.
