/**
 * `T` as this library builds one: an optional member may hold `undefined`,
 * which every reader here treats as absent.
 *
 * A type the library hands back to hosts stays exact under
 * `exactOptionalPropertyTypes` (CONTRIBUTING.md), so a literal that writes
 * `undefined` into one is asserted. Written `{ ... } satisfies LooseOptional<T> as T`,
 * the literal is still checked member by member against `T`: a missing,
 * misspelled or mistyped member fails to compile, where a bare `as T` would
 * let each one through. Both erase, so the emitted code is the literal alone.
 */
export type LooseOptional<T> = { [K in keyof T]: undefined extends T[K] ? T[K] | undefined : T[K] };
