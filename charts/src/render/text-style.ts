/** Internal structural contract shared by native text renderers. */
interface TextStyle {
  fontSize?: number;
  fontFamily?: string;
  bold?: boolean;
  italic?: boolean;
  textAlign?: 'left' | 'center' | 'right';
}

export function validateTextStyle(style: TextStyle): void {
  if (style.fontSize !== undefined && (typeof style.fontSize !== 'number' || !Number.isFinite(style.fontSize) || style.fontSize <= 0)) {
    throw new TypeError('Text fontSize must be a positive finite number');
  }
  if (style.fontFamily !== undefined && (typeof style.fontFamily !== 'string' || style.fontFamily.trim() === '')) {
    throw new TypeError('Text fontFamily must be a nonempty CSS font-family list');
  }
  for (const key of ['bold', 'italic'] as const) {
    if (style[key] !== undefined && typeof style[key] !== 'boolean') throw new TypeError(`Text ${key} must be boolean`);
  }
  if (style.textAlign !== undefined && !['left', 'center', 'right'].includes(style.textAlign)) {
    throw new TypeError('Text textAlign must be left, center or right');
  }
}

export function hasTextStyle(style: TextStyle): boolean {
  return style.fontSize !== undefined || style.fontFamily !== undefined || style.bold !== undefined
    || style.italic !== undefined || style.textAlign !== undefined;
}

/** CSS font sizes use decimal notation, including very small finite inputs. */
function decimal(value: number): string {
  const text = String(value), at = text.indexOf('e');
  if (at < 0) return text;
  const coefficient = text.slice(0, at), exponent = Number(text.slice(at + 1));
  const digits = coefficient.replace('.', ''), point = (coefficient.indexOf('.') < 0 ? coefficient.length : coefficient.indexOf('.')) + exponent;
  return point <= 0 ? `0.${'0'.repeat(-point)}${digits}`
    : point >= digits.length ? digits + '0'.repeat(point - digits.length) : `${digits.slice(0, point)}.${digits.slice(point)}`;
}

export function textFont(style: TextStyle | undefined, sizePx: number, family: string, bold = false): string {
  return `${style?.italic ? 'italic ' : ''}${(style?.bold ?? bold) ? '600 ' : ''}${decimal(sizePx)}px ${style?.fontFamily ?? family}`;
}
