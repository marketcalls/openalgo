// An import type node is erased like `import type`.
// eslint-disable-next-line @typescript-eslint/consistent-type-imports -- the fixture proves the check reads this form
export interface TypeB { previous?: import('./type-a').TypeA }
