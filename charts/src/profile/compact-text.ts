/**
 * Original 3 x 5 pixel alphabet for dense TPOs. Each octal digit is one row,
 * most-significant bit on the left. Lowercase stays distinct: TPO periods
 * 26..51 must never be relabelled as periods 0..25.
 *
 * Paint horizontal runs as integer rectangles. No DOM, font download or
 * platform font rasterizer; the same geometry also works with SvgContext.
 */
const ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789#';
const PATTERNS = [
  '25755', '65656', '34443', '65556', '74747', '74744', '34553',
  '55755', '72227', '11152', '55655', '44447', '57755', '57555',
  '25552', '65644', '25573', '65655', '34216', '72222', '55557',
  '55552', '55775', '55255', '55222', '71247',
  '03137', '44656', '03443', '11353', '02743', '32722', '03531',
  '44655', '20223', '10152', '44565', '62223', '07755', '06555',
  '02552', '06564', '03511', '03444', '03216', '27223', '05553',
  '05552', '05577', '05225', '05531', '07127',
  '75557', '26227', '61247', '61216', '55711', '74616', '34752',
  '71222', '25252', '25716', '57575',
];

// Cache the runs once, instead of decoding glyph bits on every frame.
const GLYPHS = new Map(Array.from(ALPHABET, (letter, i) => {
  const runs: [number, number, number][] = [];
  for (let y = 0; y < 5; y++) {
    // One pattern per letter, each five rows long.
    const bits = Number(PATTERNS[i]![y]);
    for (let x = 0; x < 3; x++) {
      if ((bits & (4 >> x)) === 0) continue;
      const start = x;
      while (x + 1 < 3 && (bits & (4 >> (x + 1))) !== 0) x++;
      runs.push([start, y, x - start + 1]);
    }
  }
  return [letter, runs] as const;
}));

/** All coordinates and limits are physical pixels, not CSS pixels. */
export function drawCompactText(
  ctx: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  maxHeight: number,
  maxWidth: number,
  align: 'left' | 'center' | 'right' = 'center',
): boolean {
  if (text.length === 0 || !Number.isFinite(maxHeight) || !Number.isFinite(maxWidth)) return false;
  const units = text.length * 4 - 1;
  // A price-to-pixel subtraction can turn exactly 5px into 4.99999999999px.
  const scale = Math.floor(Math.min(maxHeight / 5, maxWidth / units) + 1e-7);
  if (scale < 1) return false;
  const width = units * scale;
  const left = Math.round(x - (align === 'center' ? width / 2 : align === 'right' ? width : 0));
  const top = Math.round(y - 5 * scale / 2);
  for (let i = 0; i < text.length; i++) {
    const runs = GLYPHS.get(text[i]!);
    if (runs === undefined) continue;
    for (const [gx, gy, length] of runs) {
      ctx.fillRect(left + (i * 4 + gx) * scale, top + gy * scale, length * scale, scale);
    }
  }
  return true;
}
