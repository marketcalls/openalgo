// The shell bar's icons: each action keeps a picture of its own.
import { describe, it, expect } from 'vitest';
import { ticon } from '../src/toolbar.js';

describe('toolbar icons', () => {
  it('draws grid lines for Grid and a divided frame for the grid view, not one icon for both', () => {
    expect(ticon('grid')).toContain('M3 8h14');
    expect(ticon('gridView')).toContain('<rect');
    expect(ticon('grid')).not.toBe(ticon('gridView'));
  });
});
