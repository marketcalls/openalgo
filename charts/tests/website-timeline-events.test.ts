import ts from 'typescript';
import { afterEach, expect, it, vi } from 'vitest';
import { STOCK_BARS_SOURCE } from '../website/components/synthetic-market';
import timelineSource from '../website/components/TimelineEventsDemo.tsx?raw';

class ElementStub {
  public children: ElementStub[] = [];
  public className = '';
  public textContent = '';
  public type = '';
  public href = '';
  public target = '';
  public rel = '';
  public classList = { add: (name: string) => { this.className = name; } };
  private attributes = new Map<string, string>();
  private listeners = new Map<string, () => void>();

  public constructor(public readonly tag: string) {}
  public set innerHTML(_markup: string) { throw new Error('Host detail rendered HTML'); }
  public append(...nodes: ElementStub[]): void { this.children.push(...nodes); }
  public appendChild(node: ElementStub): void { this.children.push(node); }
  public replaceChildren(...nodes: ElementStub[]): void { this.children = [...nodes]; }
  public setAttribute(name: string, value: string): void { this.attributes.set(name, value); }
  public getAttribute(name: string): string | undefined { return this.attributes.get(name); }
  public addEventListener(name: string, callback: () => void): void { this.listeners.set(name, callback); }
  public click(): void { this.listeners.get('click')?.(); }
  public find(tag: string): ElementStub[] {
    return [...(this.tag === tag ? [this] : []), ...this.children.flatMap(child => child.find(tag))];
  }
  public visibleText(): string { return [this.textContent, ...this.children.map(child => child.visibleText())].join(' '); }
}

function exampleCode(): string {
  const source = ts.createSourceFile('TimelineEventsDemo.tsx', timelineSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let code = '';
  const visit = (node: ts.Node): void => {
    if (ts.isVariableDeclaration(node) && node.name.getText(source) === 'code' && node.initializer && ts.isTemplateExpression(node.initializer)) {
      code = node.initializer.head.text;
      for (const span of node.initializer.templateSpans) {
        expect(span.expression.getText(source)).toBe('STOCK_BARS_SOURCE');
        code += STOCK_BARS_SOURCE + span.literal.text;
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  expect(code).not.toBe('');
  return code;
}

afterEach(() => vi.unstubAllGlobals());

it('renders clustered sample events as host-owned safe text and controls group visibility', () => {
  vi.stubGlobal('document', { createElement: (tag: string) => new ElementStub(tag) });
  const chart = {
    timeScale: { fitContent: vi.fn() },
    setEventMarkerOptions: vi.fn(),
    setEventGroups: vi.fn(),
    setEvents: vi.fn(),
    setEventGroupVisible: vi.fn(),
    on: vi.fn(),
  };
  let onEventClick: ((hit: { events: Array<{ id: string; title: string; label: string; time: number }> }) => void) | undefined;
  const unsubscribe = vi.fn();
  chart.on.mockImplementation((_name, callback) => { onEventClick = callback; return unsubscribe; });
  const widget = { series: { setData: vi.fn() }, chart, destroy: vi.fn() };
  const host = new ElementStub('div');
  const example = new Function('el', 'lib', exampleCode())(host, { createWidget: () => widget });

  const events = chart.setEvents.mock.calls[0][0];
  expect(events).toHaveLength(5);
  expect(events.slice(0, 3).map((event: { group: string }) => event.group)).toEqual(['company', 'company', 'company']);
  expect(chart.setEventGroups.mock.calls[0][0]).toContainEqual({ id: 'company', label: 'Company', parentId: 'sample-feed' });
  expect(chart.setEventMarkerOptions).toHaveBeenCalledWith({ clustering: true, clusterRadius: 26 });
  expect(widget.series.setData.mock.calls[0][0]).toHaveLength(110);

  onEventClick?.({ events: events.slice(0, 3) });
  const details = host.children[2];
  expect(details.visibleText()).toContain('Illustrative company update');
  expect(details.find('button')).toHaveLength(3);
  details.find('button')[1].click();
  expect(details.visibleText()).toContain('sample follow-up call');
  expect(details.find('a')[0].href).toBe('https://github.com/marketcalls/openalgo-charts');
  expect(details.find('a')[0].rel).toBe('noopener noreferrer');

  host.children[0].find('button')[1].click();
  expect(chart.setEventGroupVisible).toHaveBeenCalledWith('company', false);
  expect(details.visibleText()).toContain('Select an event badge');
  example.destroy();
  expect(unsubscribe).toHaveBeenCalledOnce();
  expect(widget.destroy).toHaveBeenCalledOnce();
});
