import { describe, expect, it } from 'vitest';
import {
  DrawingTemplateRepository, DrawingTemplateConflictError, WorkspaceDocumentError, createMemoryDrawingTemplateStorage,
  parseDrawingTemplateCatalog, parseDrawingTemplateValues,
  type DrawingTemplateCatalog, type DrawingTemplateStorage,
} from '../src/workspace/index';

function rig(storage: DrawingTemplateStorage = createMemoryDrawingTemplateStorage()) {
  let next = 0;
  let clock = 1000;
  const repo = new DrawingTemplateRepository(storage, 'account-a', { id: () => `tpl-${++next}`, now: () => clock++ });
  return { repo, storage };
}

const thick = { 'style.color': '#f0a020', 'style.lineWidth': 3, 'style.lineStyle': 'dashed' };

describe('drawing template values', () => {
  it('keeps schema paths under style, text and props with bounded values', () => {
    const values = parseDrawingTemplateValues({
      ...thick, 'text.fontSize': 14, 'props.showPrices': false,
      'style.levels': [{ ratio: 0.618, color: '#2962ff', enabled: true, label: '' }, { ratio: 1 }],
    });
    expect(values['style.levels']).toEqual([{ ratio: 0.618, color: '#2962ff', enabled: true, label: '' }, { ratio: 1 }]);
    expect(values['props.showPrices']).toBe(false);
  });

  it('refuses what a drawing says or where it is, and anything unbounded', () => {
    // The words and the anchors are the drawing's, never part of its look.
    expect(() => parseDrawingTemplateValues({ 'text.value': 'Buy here' })).toThrow(WorkspaceDocumentError);
    expect(() => parseDrawingTemplateValues({ points: [] })).toThrow(/not a template setting/);
    expect(() => parseDrawingTemplateValues({ locked: true })).toThrow(/not a template setting/);
    expect(() => parseDrawingTemplateValues({ 'style.a.b': 1 })).toThrow(/not a template setting/);
    expect(() => parseDrawingTemplateValues({ 'style.color': { r: 1 } })).toThrow(/string, a number/);
    expect(() => parseDrawingTemplateValues({ 'style.lineWidth': Infinity })).toThrow(WorkspaceDocumentError);
    expect(() => parseDrawingTemplateValues({ 'style.color': 'x'.repeat(300) })).toThrow(/characters/);
    const many = Object.fromEntries(Array.from({ length: 65 }, (_, i) => [`style.k${i}`, i]));
    expect(() => parseDrawingTemplateValues(many)).toThrow(/64 setting limit/);
  });
});

describe('drawing template repository', () => {
  it('saves named templates per tool, overwrites a repeated name and renames and removes by identity', async () => {
    const { repo, storage } = rig();
    const first = await repo.saveTemplate('Thick amber', 'trend-line', thick);
    expect(first).toMatchObject({ id: 'tpl-1', name: 'Thick amber', tool: 'trend-line', createdAt: 1000, updatedAt: 1000 });
    // The same name on the same tool is the same template, whatever the case.
    const again = await repo.saveTemplate('  thick AMBER ', 'trend-line', { ...thick, 'style.lineWidth': 4 });
    expect(again.id).toBe('tpl-1');
    expect(again.values['style.lineWidth']).toBe(4);
    // The same name on another tool is another template.
    const box = await repo.saveTemplate('Thick amber', 'rectangle', thick);
    expect(box.id).toBe('tpl-2');
    await expect(repo.renameTemplate(box.id, 'Thin')).resolves.toMatchObject({ name: 'Thin' });
    await repo.saveTemplate('Other', 'trend-line', thick);
    await expect(repo.renameTemplate('tpl-3', 'THICK amber')).rejects.toThrow(/already exists/);
    await repo.removeTemplate(first.id);
    const catalog = await repo.load();
    expect(catalog.templates.map(item => [item.name, item.tool])).toEqual([['Thin', 'rectangle'], ['Other', 'trend-line']]);
    // Six writes: the refused rename wrote nothing.
    expect(catalog.revision).toBe(6);
    // Another repository over the same storage sees the committed catalog; another namespace sees none of it.
    expect(await new DrawingTemplateRepository(storage, 'account-a').load()).toEqual(catalog);
    expect((await new DrawingTemplateRepository(storage, 'account-b').load()).templates).toEqual([]);
    await expect(repo.removeTemplate('tpl-1')).rejects.toThrow(/does not exist/);
  });

  it('keeps one default per tool and forgets it on null', async () => {
    const { repo } = rig();
    await repo.setDefault('trend-line', thick);
    await repo.setDefault('rectangle', { 'style.fill': true });
    await repo.setDefault('trend-line', { 'style.color': '#26a69a' });
    let catalog = await repo.load();
    expect(catalog.defaults).toEqual([
      { tool: 'trend-line', values: { 'style.color': '#26a69a' }, updatedAt: 1002 },
      { tool: 'rectangle', values: { 'style.fill': true }, updatedAt: 1001 },
    ]);
    await repo.setDefault('trend-line', null);
    catalog = await repo.load();
    expect(catalog.defaults.map(item => item.tool)).toEqual(['rectangle']);
    await expect(repo.setDefault('rectangle', { 'text.value': 'x' })).rejects.toBeInstanceOf(WorkspaceDocumentError);
  });

  it('tells subscribers each committed catalog before the change resolves', async () => {
    const { repo } = rig();
    const seen: number[] = [];
    const off = repo.subscribe(catalog => { seen.push(catalog.revision); });
    await repo.setDefault('ray', thick);
    await repo.saveTemplate('A', 'ray', thick);
    off();
    await repo.saveTemplate('B', 'ray', thick);
    expect(seen).toEqual([1, 2]);
  });

  it('refuses a change prepared from a stale revision, and a racing writer, and stays usable', async () => {
    const { repo } = rig();
    await repo.saveTemplate('A', 'ray', thick);
    const seen = (await repo.load()).revision;
    await repo.saveTemplate('B', 'ray', thick);
    await expect(repo.removeTemplate('tpl-1', { expectedRevision: seen })).rejects.toBeInstanceOf(DrawingTemplateConflictError);
    expect((await repo.load()).templates).toHaveLength(2);

    const memory = createMemoryDrawingTemplateStorage();
    let race = false;
    const storage: DrawingTemplateStorage = {
      read: namespace => memory.read(namespace),
      async write(namespace, catalog, expected, options) {
        if (race) {
          race = false;
          // Another tab commits between this session's read and its write.
          const current = parseDrawingTemplateCatalog(await memory.read(namespace) ?? { version: 1, revision: 0, templates: [], defaults: [] });
          await memory.write(namespace, { ...current, revision: current.revision + 1 }, current.revision);
        }
        return memory.write(namespace, catalog, expected, options);
      },
    };
    const raced = rig(storage).repo;
    race = true;
    await expect(raced.setDefault('ray', thick)).rejects.toBeInstanceOf(DrawingTemplateConflictError);
    await raced.setDefault('ray', thick);
    expect((await raced.load()).defaults).toHaveLength(1);
  });

  it('never replaces corrupt storage and validates every candidate before writing', async () => {
    const corrupt: Record<string, unknown> = {
      'account-a': { version: 1, revision: 2, templates: [], defaults: [{ tool: 'ray', values: {}, updatedAt: 0 }, { tool: 'ray', values: {}, updatedAt: 0 }] },
    };
    const memory = createMemoryDrawingTemplateStorage(corrupt);
    const writes: number[] = [];
    const storage: DrawingTemplateStorage = {
      read: namespace => memory.read(namespace),
      write: async (namespace, catalog, expected) => { writes.push(expected); return memory.write(namespace, catalog, expected); },
    };
    const repo = new DrawingTemplateRepository(storage, 'account-a', { id: () => 'x' });
    await expect(repo.load()).rejects.toThrow(/Duplicate tool default/);
    await expect(repo.setDefault('ray', thick)).rejects.toBeInstanceOf(WorkspaceDocumentError);
    expect(writes).toEqual([]);
    const { repo: clean } = rig();
    await expect(clean.saveTemplate('', 'ray', thick)).rejects.toThrow(/name/);
    await expect(clean.saveTemplate('A', '', thick)).rejects.toThrow(/drawing tool/);
    const version: DrawingTemplateCatalog = { version: 2 as 1, revision: 0, templates: [], defaults: [] };
    expect(() => parseDrawingTemplateCatalog(version)).toThrow(/version/);
    expect((await clean.load()).revision).toBe(0);
  });
});
