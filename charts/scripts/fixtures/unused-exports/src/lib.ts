export const publicValue = 1;
export interface PublicShape { size: number }

export const usedInSrc = 2;
export const usedByNamespace = 3;
export const usedByDynamicImport = 4;
export const usedByDestructuring = 5;
export const usedByRenamedDestructuring = 6;
export const usedThroughBarrel = 7;
export const usedAsShorthand = 8;

// A test is a use: it pins behaviour a later change must keep.
export const usedByTestOnly = 9;

// Used where it is declared and nowhere else: the export keyword is surplus,
// which the check reports but does not fail.
export const usedLocally = 10;
export const doubled = (): number => usedLocally * 2;

// Referenced by nothing at all.
export const unusedAnywhere = 11;

// A re-export is a door, not a use, and so is an import nothing reads.
export const onlyReexported = 12;
export const onlyImported = 13;
