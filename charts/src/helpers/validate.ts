/**
 * Shape checks for input the library did not build: a saved layout, restore or
 * pick options, a host's descriptor fields. Pure and dependency free, so every
 * tier imports them by path.
 *
 * Two rules, kept apart on purpose. A reader that only needs keyed fields
 * (the drawing and widget readers) takes any object that is not an array. A
 * reader of options that must be plain data (restore, pick, CSV export, study
 * scales) also refuses an instance of a class, whose getters and prototype
 * would run host code while being read.
 */

/** An object that is not an array: something with keyed fields to read. */
export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * A plain data object: made by a literal, `JSON.parse` or `Object.create(null)`.
 * Arrays, class instances and functions are not.
 */
export function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (value === null || typeof value !== 'object') return false;
  const prototype: unknown = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

/** Whether every own string-keyed property holds a value, so reading one runs no getter. */
export function hasOnlyDataProperties(value: object): boolean {
  return Object.values(Object.getOwnPropertyDescriptors(value)).every(property => 'value' in property);
}
