// The writing-rules fixture: each line below holds one kind of character the
// rules forbid, except the last two, which must pass.
// A comment with an em dash — here.
export const range = 'a range 1–5';
/** An arrow → in a doc comment. */
export const bin = 'bin 🗑';
// ── a section rule stays, and so does a plain read-only hyphen ──
export const hyphen = 'read-only';
