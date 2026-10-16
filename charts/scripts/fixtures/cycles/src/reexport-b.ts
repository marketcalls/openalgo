import { reexportA } from './reexport-a';

export interface ReexportB { a: number }
export const reexportB = reexportA + 1;
