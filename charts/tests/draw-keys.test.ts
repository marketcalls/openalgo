/**
 * The keyboard mapping is pure, so every rule is a table. What matters is the
 * negative space: the keys that must NOT become an action, because the host
 * or the browser owns them.
 */
import { describe, it, expect } from 'vitest';
import {
  keyToDrawingAction, NUDGE_STEP_PX, NUDGE_STEP_SHIFT_PX,
  type DrawingKeyContext, type DrawingKeyEvent,
} from '../src/draw/keys';

const selected: DrawingKeyContext = { hasSelection: true, hasTarget: false, editingText: false };
const hovered: DrawingKeyContext = { hasSelection: false, hasTarget: true, editingText: false };
const nothing: DrawingKeyContext = { hasSelection: false, hasTarget: false, editingText: false };
const typing: DrawingKeyContext = { hasSelection: true, hasTarget: true, editingText: true };

const ctrl = (key: string, extra: Partial<DrawingKeyEvent> = {}): DrawingKeyEvent => ({ key, ctrlKey: true, ...extra });
const meta = (key: string, extra: Partial<DrawingKeyEvent> = {}): DrawingKeyEvent => ({ key, metaKey: true, ...extra });

describe('undo and redo', () => {
  it('maps Ctrl+Z to undo and both redo chords to redo', () => {
    expect(keyToDrawingAction(ctrl('z'), nothing)).toEqual({ type: 'undo' });
    expect(keyToDrawingAction(ctrl('Z', { shiftKey: true }), nothing)).toEqual({ type: 'redo' });
    expect(keyToDrawingAction(ctrl('y'), nothing)).toEqual({ type: 'redo' });
  });

  it('treats Cmd as Ctrl', () => {
    expect(keyToDrawingAction(meta('z'), nothing)).toEqual({ type: 'undo' });
    expect(keyToDrawingAction(meta('v'), nothing)).toEqual({ type: 'paste' });
  });

  it('needs no selection: history is chart-wide', () => {
    expect(keyToDrawingAction(ctrl('z'), nothing)).not.toBeNull();
  });
});

describe('clipboard and duplicate', () => {
  it('copy, cut and duplicate need something to act on', () => {
    for (const key of ['c', 'x', 'd']) {
      expect(keyToDrawingAction(ctrl(key), nothing), key).toBeNull();
      expect(keyToDrawingAction(ctrl(key), selected), key).not.toBeNull();
      // A hovered drawing is a target too, so a quick copy needs no click first.
      expect(keyToDrawingAction(ctrl(key), hovered), key).not.toBeNull();
    }
    expect(keyToDrawingAction(ctrl('c'), selected)).toEqual({ type: 'copy' });
    expect(keyToDrawingAction(ctrl('x'), selected)).toEqual({ type: 'cut' });
    expect(keyToDrawingAction(ctrl('d'), selected)).toEqual({ type: 'duplicate' });
  });

  it('paste needs nothing selected: the payload decides', () => {
    expect(keyToDrawingAction(ctrl('v'), nothing)).toEqual({ type: 'paste' });
  });

  it('leaves the browser copy chord alone when there is nothing to copy', () => {
    // Otherwise a host that preventDefaults on every action would stop the
    // user copying text elsewhere on the page.
    expect(keyToDrawingAction(ctrl('c'), nothing)).toBeNull();
  });
});

describe('delete', () => {
  it('maps Delete and Backspace when there is a selection or a target', () => {
    expect(keyToDrawingAction({ key: 'Delete' }, selected)).toEqual({ type: 'delete' });
    expect(keyToDrawingAction({ key: 'Backspace' }, selected)).toEqual({ type: 'delete' });
    expect(keyToDrawingAction({ key: 'Delete' }, hovered)).toEqual({ type: 'delete' });
    expect(keyToDrawingAction({ key: 'Delete' }, nothing)).toBeNull();
  });
});

describe('nudge', () => {
  it('moves the selection one pixel per arrow, ten with Shift', () => {
    expect(keyToDrawingAction({ key: 'ArrowLeft' }, selected)).toEqual({ type: 'nudge', dx: -NUDGE_STEP_PX, dy: 0 });
    expect(keyToDrawingAction({ key: 'ArrowRight' }, selected)).toEqual({ type: 'nudge', dx: NUDGE_STEP_PX, dy: 0 });
    expect(keyToDrawingAction({ key: 'ArrowUp' }, selected)).toEqual({ type: 'nudge', dx: 0, dy: -NUDGE_STEP_PX });
    expect(keyToDrawingAction({ key: 'ArrowDown' }, selected)).toEqual({ type: 'nudge', dx: 0, dy: NUDGE_STEP_PX });
    expect(keyToDrawingAction({ key: 'ArrowDown', shiftKey: true }, selected))
      .toEqual({ type: 'nudge', dx: 0, dy: NUDGE_STEP_SHIFT_PX });
    expect(NUDGE_STEP_PX).toBe(1);
    expect(NUDGE_STEP_SHIFT_PX).toBe(10);
  });

  it('never nudges a merely hovered drawing, nor an empty chart', () => {
    // Arrows without a selection belong to the host (scrolling the chart).
    expect(keyToDrawingAction({ key: 'ArrowLeft' }, hovered)).toBeNull();
    expect(keyToDrawingAction({ key: 'ArrowLeft' }, nothing)).toBeNull();
  });

  it('leaves Ctrl+Arrow to the host', () => {
    expect(keyToDrawingAction(ctrl('ArrowLeft'), selected)).toBeNull();
  });
});

describe('what is never an action', () => {
  it('everything, while the user is typing', () => {
    for (const e of [ctrl('z'), ctrl('c'), ctrl('v'), { key: 'Delete' }, { key: 'Backspace' }, { key: 'ArrowLeft' }]) {
      expect(keyToDrawingAction(e, typing), e.key).toBeNull();
    }
  });

  it('a bare letter, so typing a tool shortcut elsewhere is unaffected', () => {
    for (const key of ['z', 'c', 'x', 'v', 'd', 'y']) {
      expect(keyToDrawingAction({ key }, selected), key).toBeNull();
    }
  });

  it('a chord with an extra modifier, so it cannot shadow a host or browser chord', () => {
    expect(keyToDrawingAction(ctrl('c', { shiftKey: true }), selected)).toBeNull();
    expect(keyToDrawingAction(ctrl('v', { shiftKey: true }), selected)).toBeNull();
    expect(keyToDrawingAction(ctrl('d', { shiftKey: true }), selected)).toBeNull();
    expect(keyToDrawingAction(ctrl('y', { shiftKey: true }), selected)).toBeNull();
    expect(keyToDrawingAction(ctrl('z', { altKey: true }), selected)).toBeNull();
    expect(keyToDrawingAction({ key: 'Delete', altKey: true }, selected)).toBeNull();
    expect(keyToDrawingAction({ key: 'Delete', shiftKey: true }, selected)).toBeNull();
  });

  it('an unbound key or an empty one', () => {
    expect(keyToDrawingAction(ctrl('q'), selected)).toBeNull();
    expect(keyToDrawingAction({ key: 'Enter' }, selected)).toBeNull();
    expect(keyToDrawingAction({ key: '' }, selected)).toBeNull();
  });
});

describe('placement, while a tool is armed', () => {
  const placing: DrawingKeyContext = { ...selected, placing: true };

  it('Escape cancels, Enter finishes, Backspace drops the last anchor', () => {
    expect(keyToDrawingAction({ key: 'Escape' }, placing)).toEqual({ type: 'cancel' });
    expect(keyToDrawingAction({ key: 'Enter' }, placing)).toEqual({ type: 'finish' });
    expect(keyToDrawingAction({ key: 'Backspace' }, placing)).toEqual({ type: 'popAnchor' });
  });

  it('Backspace never reaches the delete branch, even with a selection to delete', () => {
    // The anchor being placed is what the user means; the selection is not.
    expect(keyToDrawingAction({ key: 'Backspace' }, placing)).toEqual({ type: 'popAnchor' });
    expect(keyToDrawingAction({ key: 'Delete' }, placing)).toEqual({ type: 'delete' });
  });

  it('without a tool armed the three keys keep their old meaning', () => {
    expect(keyToDrawingAction({ key: 'Backspace' }, selected)).toEqual({ type: 'delete' });
    expect(keyToDrawingAction({ key: 'Backspace' }, hovered)).toEqual({ type: 'delete' });
    expect(keyToDrawingAction({ key: 'Escape' }, selected)).toBeNull();
    expect(keyToDrawingAction({ key: 'Enter' }, selected)).toBeNull();
    expect(keyToDrawingAction({ key: 'Escape' }, { ...selected, placing: false })).toBeNull();
  });

  it('a chord with a modifier is not a placement key', () => {
    expect(keyToDrawingAction({ key: 'Enter', shiftKey: true }, placing)).toBeNull();
    expect(keyToDrawingAction(ctrl('Backspace'), placing)).toBeNull();
    expect(keyToDrawingAction({ key: 'Escape', altKey: true }, placing)).toBeNull();
  });

  it('still yields nothing while the user is typing', () => {
    expect(keyToDrawingAction({ key: 'Escape' }, { ...typing, placing: true })).toBeNull();
  });
});
