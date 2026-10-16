// Every name is a type, but the import is not `import type`: with
// verbatimModuleSyntax it is emitted as an empty import that still loads
// inline-b, so this loop is a runtime one.
import { type InlineB } from './inline-b';

export const inlineA = (b: InlineB): number => b.size;
