# Chart data download

`exportChartDataCsv(chart, options?)` from `openalgo-charts` returns a CSV string.
By default it reads all currently installed primary bars, including the revealed
replay prefix. An explicit range can select rows; it does not fetch history or
infer a selection from the viewport. The host owns
authentication, source selection, the download filename and browser file delivery.

```ts
import { exportChartDataCsv } from 'openalgo-charts';

const csv = exportChartDataCsv(chart);
const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
```

Default source rows have fixed `time,open,high,low,close,volume,oi` fields. Time is UTC seconds;
numbers retain their input precision. Missing and nonfinite observations are
empty cells; a zero reading stays `0`. OI is the bar's level and is never summed.
Transformed charts export their installed transformed OHLC values. No drawings,
orders, positions, account state or credentials are included.

Each configured study contributes its declared plots, including hidden studies.
Column names are `indicator:<instanceId>:<plotKey>`, keeping repeated studies
distinct. Warmup/missing values are blank. These are computed values at the input
row, before visual plot offsets. Set `{ indicators: false }` to omit them.

Select studies with `{ indicators: [study.id, anotherStudy.id] }`. IDs identify
instances, so repeated descriptors or display names are unambiguous. Selected
studies follow the array order and retain their declared plot order; hidden
studies remain eligible. `[]` selects none. Duplicate, unknown or removed IDs
throw rather than substituting a different study.

`range: { from, to }` accepts finite inclusive UTC-second bounds. Either bound
may be omitted; fractions and negative epoch values are preserved. Equal bounds
select an exact installed timestamp, and a nonoverlapping range returns only
headers. Indicators calculate over the full installed history before row
selection, so choosing recent rows does not restart their warmup.

```ts
const csv = exportChartDataCsv(chart, {
  indicators: [fastStudy.id],
  range: { from: 1700000060, to: 1700000600 },
});
```

`ChartDataCsvRange` describes the bounds. Invalid, accessor-backed or inherited
range fields are rejected without reading their getters. Study selectors must
be arrays of distinct nonempty strings. Invalid option shapes are rejected
before native chart reads; resolving an unknown ID requires the native study
lookup, which can flush pending calculations.

Comparisons added through `addComparison` or `comparisonController` contribute
`comparison:<ordinal>:<symbol>:close` columns. Values are eligible aligned closes
in their original price units, even when the axis displays percentages. Calendar
gaps, unavailable common baselines and unrevealed replay candles remain blank.
Export does not create a comparison controller. For an explicitly constructed
`ComparisonController`, pass `{ comparisons: controller.list() }`; pass an empty
list to omit comparisons. These fields are declared by `ChartDataCsvOptions`.

Default headers have fixed prefixes and CSV quoting for commas, quotes and newlines.
Without formatters, data cells contain only finite numbers or blanks. Output uses
CRLF row separators and a final newline. An
empty chart returns its headers with no data rows.

## Display alignment

Set `alignment: 'display'` to align selected study values with their rendered
plot positions. This reads each plot's effective `barOffset`, including direct
`study.series(key).applyOptions({ barOffset })` changes, on the chart's shared
logical axis. Source OHLCV/OI and comparison closes stay at installed primary
positions. Standalone series, tables, markers and drawing coordinates do not add
export columns.

Display rows start with `time,logical_index,time_origin`. The origin is `axis`
for a loaded timestamp, `interpolated` between loaded positions, `projected`
beyond either end, or `unknown` when no timestamp can be assigned. Offsets can
be fractional. Rows form a sparse union of installed primary positions and
positions with finite selected plot values; an offset does not create all the
empty intervening rows. Positions that lose displacement precision are rejected.
Candle plots expand into independent `:open`, `:high`, `:low` and `:close` fields.

Outside the loaded axis, the default timestamp uses the nearest observed spacing
when at least two timestamps exist. This is a spacing estimate, not an exchange
calendar or a future observation. With a single timestamp, projected time stays
blank. Override only this outside-axis projection with
`projectTime(logicalIndex, context)`, returning finite UTC seconds or `null`.
`ChartDataProjectionContext` provides a frozen copy of installed `axisTimes` and,
during replay, the revealed boundary. Colliding or reversed timestamps throw.

```ts
const csv = exportChartDataCsv(chart, {
  indicators: [study.id],
  alignment: 'display',
  range: { from: startTime, to: endTime },
});
```

Range filtering follows alignment. Unknown-time rows are included only without
time bounds. Replay clips the captured axis to the revealed boundary; an already
known study value may project beyond it, with blank future primary and comparison
cells. Export never reads unrevealed replay history or fetches missing data.

## Presentation callbacks

`ChartDataCsvFormatters` accepts `time`, `value` and `header` callbacks. A time
formatter adds `time_label` next to the unchanged numeric `time`. The value
formatter receives only finite primary, study and comparison values; absent
cells remain blank. Raw time and logical-index identities are never rounded by
the value formatter. Header/value callbacks receive frozen `ChartDataColumn`
metadata with the canonical key and its source identity. Duplicate display
headers are disambiguated; select studies by instance ID rather than label.

```ts
const csv = exportChartDataCsv(chart, {
  formatters: {
    time: utcSeconds => new Date(utcSeconds * 1000).toISOString(),
    value: (value, column) => column.kind === 'primary' && column.field === 'close'
      ? value.toFixed(2) : String(value),
  },
});
```

All callbacks must return strings. Their exceptions or invalid returns abort the
export. Source fields, selected arrays, offsets and comparison readings are
captured before presentation callbacks, so callback mutations cannot change the
captured rows. Source replacement during the initial study calculation aborts
the snapshot. Callback text receives CSV quoting and an apostrophe prefix when
it could be read as a spreadsheet formula. Raw negative numeric cells retain
their original numeric representation.

Hosts should capture the selected chart and its source when opening a download
menu, then reject the action if that owner changed or history is loading/failed.
Do not substitute a full replay history or an old source's cached bars. Treat a
browser download error as a failure and show it to the user.

The packaged widget and reference demo open a CSV options dialog from Capture
or the layout controls. Both retain the offered study IDs and visible bounds,
allow custom UTC bounds, and offer source or display alignment. The reference
demo can also omit comparison closes. Loading, replaced-source and removed-study
errors remain visible without starting a file download.
