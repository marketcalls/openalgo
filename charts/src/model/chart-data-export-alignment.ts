import type { ChartDataCsvOptions, ChartDataCsvRange } from './chart-data-export-types';
import { withinCsvRange, type CsvSnapshot } from './chart-data-export-snapshot';

export interface CsvRow {
  time: number | null;
  logicalIndex?: number;
  origin?: 'axis' | 'interpolated' | 'projected' | 'unknown';
  values: (number | undefined)[];
}

export function alignCsvRows(snapshot: CsvSnapshot, alignment: 'source' | 'display', range: ChartDataCsvRange,
  projectTime: ChartDataCsvOptions['projectTime']): CsvRow[] {
  if (alignment === 'source') return snapshot.times.flatMap((time, index) => withinCsvRange(time, range)
    ? [{ time, values: snapshot.columns.map(column => column.values[index]) }] : []);
  const axis = snapshot.context.axisTimes;
  const byTime = new Map(axis.map((time, index) => [time, index]));
  const positions = snapshot.times.map(time => {
    const index = byTime.get(time);
    if (index === undefined) throw new Error('CSV primary time is absent from the installed axis');
    return index;
  });
  const union = new Map<number, CsvRow>();
  const rowAt = (position: number) => {
    let row = union.get(position);
    if (!row) { row = { time: null, logicalIndex: position, values: [] }; union.set(position, row); }
    return row;
  };
  positions.forEach(rowAt);
  snapshot.columns.forEach((column, columnIndex) => {
    const used = new Set<number>();
    positions.forEach((position, index) => {
      const value = column.values[index];
      if (column.meta.kind !== 'indicator') { rowAt(position).values[columnIndex] = value; return; }
      if (value === undefined) return;
      const target = position + column.offset;
      if (!Number.isFinite(target) || Math.abs(target) > Number.MAX_SAFE_INTEGER || (column.offset !== 0 && target === position)
        || (!Number.isInteger(column.offset) && Number.isInteger(target)) || used.has(target)) {
        throw new RangeError('CSV plot position cannot be represented safely');
      }
      used.add(target);
      rowAt(target).values[columnIndex] = value;
    });
  });
  const rows = [...union.values()].sort((a, b) => a.logicalIndex! - b.logicalIndex!);
  let previousTime: number | undefined;
  for (const row of rows) {
    // Every axis read sits inside the range the test before it checked.
    const position = row.logicalIndex!;
    if (Number.isInteger(position) && position >= 0 && position < axis.length) {
      row.time = axis[position]!; row.origin = 'axis';
    } else if (position >= 0 && position < axis.length - 1) {
      const left = Math.floor(position);
      row.time = axis[left]! + (axis[left + 1]! - axis[left]!) * (position - left); row.origin = 'interpolated';
      if (!(row.time > axis[left]! && row.time < axis[left + 1]!)) throw new RangeError('CSV interpolated time collides with the axis');
    } else {
      row.origin = 'unknown';
      if (projectTime) row.time = projectTime(position, snapshot.context);
      else if (axis.length > 1) {
        const edge = position < 0 ? 0 : axis.length - 1;
        const spacing = position < 0 ? axis[1]! - axis[0]! : axis[edge]! - axis[edge - 1]!;
        row.time = axis[edge]! + (position - edge) * spacing;
      }
      if (row.time !== null) {
        if (typeof row.time !== 'number' || !Number.isFinite(row.time)) throw new TypeError('CSV projected time must be finite or null');
        if (axis.length && (position < 0 ? row.time >= axis[0]! : row.time <= axis[axis.length - 1]!)) {
          throw new RangeError('CSV projected time collides with the axis');
        }
        row.origin = 'projected';
      }
    }
    if (row.time !== null) {
      if (!Number.isFinite(row.time) || (previousTime !== undefined && row.time <= previousTime)) throw new RangeError('CSV times must be strictly increasing');
      previousTime = row.time;
    }
  }
  return rows.filter(row => row.time === null ? range.from === undefined && range.to === undefined : withinCsvRange(row.time, range));
}
