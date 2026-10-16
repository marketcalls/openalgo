import * as lib from './lib';
import { doubled, usedAsShorthand, usedInSrc } from './lib';
import { usedThroughBarrel } from './barrel';

export async function run(): Promise<number> {
  const { usedByDynamicImport } = await import('./lib');
  const { usedByDestructuring, usedByRenamedDestructuring: renamed } = lib;
  const bag = { usedAsShorthand };
  return usedInSrc + lib.usedByNamespace + usedByDynamicImport + usedByDestructuring + renamed
    + usedThroughBarrel + bag.usedAsShorthand + doubled();
}
