/**
 * The two text checks the trade tier's modules share: the words an error
 * gives as a reason, and whether a value is a string that says something.
 */

/** An error's message, or the thrown value itself when it carries none. */
export const errorText = (err: unknown): string => String((err as Error)?.message ?? err);

/** A string with something in it besides spaces. */
export const nonEmpty = (value: unknown): value is string => typeof value === 'string' && value.trim() !== '';
