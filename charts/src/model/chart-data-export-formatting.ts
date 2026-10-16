import type { ChartDataColumn, ChartDataCsvFormatters } from './chart-data-export-types';
import type { CsvSnapshotColumn } from './chart-data-export-snapshot';
import type { CsvRow } from './chart-data-export-alignment';

const cell = (text: string): string => /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
function protectedText(text: unknown): string {
  if (typeof text !== 'string') throw new TypeError('CSV formatter must return a string');
  const first = text.charCodeAt(0);
  return first <= 31 || first === 127 || /^[\s\ufeff]*[=+@-]/.test(text) ? "'" + text : text;
}
const identity = (kind: 'time' | 'timeLabel' | 'logicalIndex' | 'timeOrigin', key: string): ChartDataColumn => Object.freeze({ key, title: key, kind });

export function serializeCsv(columns: CsvSnapshotColumn[], rows: CsvRow[], alignment: 'source' | 'display', formatters: ChartDataCsvFormatters): string {
  const metadata = [identity('time', 'time'), ...(formatters.time ? [identity('timeLabel', 'time_label')] : []),
    ...(alignment === 'display' ? [identity('logicalIndex', 'logical_index'), identity('timeOrigin', 'time_origin')] : []),
    ...columns.map(column => column.meta)];
  const labels = metadata.map(column => formatters.header ? protectedText(formatters.header(column)) : column.key);
  const counts = new Map<string, number>();
  labels.forEach(label => counts.set(label, (counts.get(label) ?? 0) + 1));
  // `labels` and `headers` hold one entry per `metadata` column.
  const headers = labels.map((label, index) => (formatters.header && counts.get(label)! > 1 ? `${metadata[index]!.key}:${label}` : label));
  // A callback can deliberately use another column's canonical-prefixed label.
  // Resolve that secondary collision as well without changing default headers.
  if ((formatters.header || alignment === 'display') && new Set(headers).size !== headers.length) {
    headers.forEach((label, index) => { headers[index] = `${index + 1}:${metadata[index]!.key}:${label}`; });
  }
  const lines = [headers.map(cell).join(',')];
  for (const row of rows) {
    const time = row.time !== null && Number.isFinite(row.time) ? row.time : null;
    const values = [time === null ? '' : String(time)];
    if (formatters.time) values.push(time === null ? '' : cell(protectedText(formatters.time(time))));
    if (alignment === 'display') values.push(String(row.logicalIndex), row.origin!);
    columns.forEach((column, index) => {
      const value = row.values[index];
      values.push(value === undefined ? '' : formatters.value ? cell(protectedText(formatters.value(value, column.meta))) : String(value));
    });
    lines.push(values.join(','));
  }
  return lines.join('\r\n') + '\r\n';
}
