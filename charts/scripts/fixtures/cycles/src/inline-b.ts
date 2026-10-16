import { inlineA } from './inline-a.js';

export interface InlineB { size: number }
export const measured = inlineA({ size: 2 });
