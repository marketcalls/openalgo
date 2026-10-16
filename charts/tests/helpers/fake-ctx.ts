/**
 * A recording 2D context for tests. Implements the subset of
 * CanvasRenderingContext2D the renderers use and logs each operation, so draw
 * functions can be validated (call counts, coordinates) without a real browser.
 */
export interface Op {
  type: string;
  args: number[];
  fillStyle?: string;
  strokeStyle?: string;
  lineWidth?: number;
  /** The string a fillText op drew, so label content is assertable. */
  text?: string;
  /**
   * The font in force when the op ran. Recorded because `font` is a context
   * property, not an argument: without it a text size change leaves an
   * identical op stream, which is exactly how an inert font-size option would
   * pass a green suite.
   */
  font?: string;
}

export class RecordingContext {
  public ops: Op[] = [];
  public fillStyle = '#000';
  public strokeStyle = '#000';
  public lineWidth = 1;
  public lineJoin = 'miter';
  public font = '10px sans-serif';
  public textAlign = 'left';
  public textBaseline = 'alphabetic';

  public save(): void { this.ops.push({ type: 'save', args: [] }); }
  public restore(): void { this.ops.push({ type: 'restore', args: [] }); }
  public beginPath(): void { this.ops.push({ type: 'beginPath', args: [] }); }
  public closePath(): void { this.ops.push({ type: 'closePath', args: [] }); }
  public moveTo(x: number, y: number): void { this.ops.push({ type: 'moveTo', args: [x, y] }); }
  public lineTo(x: number, y: number): void { this.ops.push({ type: 'lineTo', args: [x, y] }); }
  public arc(x: number, y: number, r: number): void { this.ops.push({ type: 'arc', args: [x, y, r] }); }
  public quadraticCurveTo(cx: number, cy: number, x: number, y: number): void {
    this.ops.push({ type: 'quadraticCurveTo', args: [cx, cy, x, y] });
  }
  public bezierCurveTo(c1x: number, c1y: number, c2x: number, c2y: number, x: number, y: number): void {
    this.ops.push({ type: 'bezierCurveTo', args: [c1x, c1y, c2x, c2y, x, y] });
  }
  public ellipse(x: number, y: number, rx: number, ry: number): void { this.ops.push({ type: 'ellipse', args: [x, y, rx, ry] }); }
  public stroke(): void { this.ops.push({ type: 'stroke', args: [], strokeStyle: this.strokeStyle, lineWidth: this.lineWidth }); }
  public fill(): void { this.ops.push({ type: 'fill', args: [], fillStyle: this.fillStyle }); }
  public fillRect(x: number, y: number, w: number, h: number): void {
    this.ops.push({ type: 'fillRect', args: [x, y, w, h], fillStyle: this.fillStyle });
  }
  public strokeRect(x: number, y: number, w: number, h: number): void {
    this.ops.push({ type: 'strokeRect', args: [x, y, w, h], strokeStyle: this.strokeStyle });
  }
  public setLineDash(d: number[]): void { this.ops.push({ type: 'setLineDash', args: [...d] }); }
  public rect(x: number, y: number, w: number, h: number): void { this.ops.push({ type: 'rect', args: [x, y, w, h] }); }
  public roundRect(x: number, y: number, w: number, h: number, r: number): void { this.ops.push({ type: 'roundRect', args: [x, y, w, h, r] }); }
  public clip(): void { this.ops.push({ type: 'clip', args: [] }); }
  /**
   * The returned handle names its own stops through `toString`, because that is
   * how a gradient reaches an assertion: it is set as `fillStyle`, so the op
   * records the object, and a gradient that stringifies as `[object Object]`
   * makes every area fill compare equal to every other. Gradients are also
   * cached per context, so the `addColorStop` ops appear on one frame only and
   * cannot be relied on to tell two fills apart.
   */
  public createLinearGradient(x0 = 0, y0 = 0, x1 = 0, y1 = 0): { addColorStop(o: number, c: string): void } {
    // The coordinates are recorded because a vertical gradient's whole meaning
    // is where its axis sits: an indicator band anchored in price space and one
    // anchored to the pane produce the same stops at different y.
    this.ops.push({ type: 'createLinearGradient', args: [x0, y0, x1, y1] });
    const stops: string[] = [];
    return {
      addColorStop: (o: number, c: string) => {
        stops.push(`${o}:${c}`);
        this.ops.push({ type: 'addColorStop', args: [o], text: c });
      },
      toString: () => `gradient(${stops.join(' ')})`,
    } as { addColorStop(o: number, c: string): void };
  }
  public fillText(t: string, x: number, y: number): void {
    this.ops.push({ type: 'fillText', args: [x, y], fillStyle: this.fillStyle, text: t, font: this.font });
  }
  public measureText(t: string): { width: number } { return { width: t.length * 6 }; }
  public setTransform(): void { this.ops.push({ type: 'setTransform', args: [] }); }
  public translate(x: number, y: number): void { this.ops.push({ type: 'translate', args: [x, y] }); }
  public clearRect(x: number, y: number, w: number, h: number): void { this.ops.push({ type: 'clearRect', args: [x, y, w, h] }); }
  public scale(): void { this.ops.push({ type: 'scale', args: [] }); }
  public drawImage(_img: unknown, x: number, y: number): void { this.ops.push({ type: 'drawImage', args: [x, y] }); }

  public count(type: string): number {
    return this.ops.filter((o) => o.type === type).length;
  }
}

/** Construct a recording context typed as a real one for renderer calls. */
export function makeCtx(): { ctx: CanvasRenderingContext2D; rec: RecordingContext } {
  const rec = new RecordingContext();
  return { ctx: rec as unknown as CanvasRenderingContext2D, rec };
}
