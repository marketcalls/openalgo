// Tiny, dependency-free JS/TS tokenizer used to syntax-highlight the source of a
// live example. The same string is both displayed (highlighted here) and
// executed (see RunnableExample), so the demo code can never drift from what the
// reader sees. Colors are defined in styles/globals.css (.tok-*).

const KEYWORDS = new Set([
  'const', 'let', 'var', 'function', 'return', 'if', 'else', 'for', 'while',
  'new', 'import', 'from', 'export', 'await', 'async', 'class', 'extends',
  'super', 'this', 'true', 'false', 'null', 'undefined', 'typeof',
  'instanceof', 'in', 'of', 'void', 'switch', 'case', 'break', 'continue',
  'default', 'try', 'catch', 'finally', 'throw', 'delete', 'yield', 'as',
]);

function esc(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

const isIdStart = (c: string): boolean => /[A-Za-z_$]/.test(c);
const isId = (c: string): boolean => /[A-Za-z0-9_$]/.test(c);

export function highlight(code: string): string {
  let out = '';
  let i = 0;
  const n = code.length;
  while (i < n) {
    const c = code[i];

    // line comment
    if (c === '/' && code[i + 1] === '/') {
      let j = i;
      while (j < n && code[j] !== '\n') j++;
      out += `<span class="tok-com">${esc(code.slice(i, j))}</span>`;
      i = j;
      continue;
    }
    // block comment
    if (c === '/' && code[i + 1] === '*') {
      let j = i + 2;
      while (j < n && !(code[j] === '*' && code[j + 1] === '/')) j++;
      j = Math.min(n, j + 2);
      out += `<span class="tok-com">${esc(code.slice(i, j))}</span>`;
      i = j;
      continue;
    }
    // string / template literal
    if (c === '"' || c === "'" || c === '`') {
      const q = c;
      let j = i + 1;
      while (j < n) {
        if (code[j] === '\\') { j += 2; continue; }
        if (code[j] === q) { j++; break; }
        j++;
      }
      out += `<span class="tok-str">${esc(code.slice(i, j))}</span>`;
      i = j;
      continue;
    }
    // number
    if (/[0-9]/.test(c)) {
      let j = i;
      while (j < n && /[0-9._a-fA-FxXeE]/.test(code[j])) j++;
      out += `<span class="tok-num">${esc(code.slice(i, j))}</span>`;
      i = j;
      continue;
    }
    // identifier / keyword / function call
    if (isIdStart(c)) {
      let j = i;
      while (j < n && isId(code[j])) j++;
      const word = code.slice(i, j);
      let k = j;
      while (k < n && /\s/.test(code[k])) k++;
      if (KEYWORDS.has(word)) out += `<span class="tok-kw">${esc(word)}</span>`;
      else if (code[k] === '(') out += `<span class="tok-fn">${esc(word)}</span>`;
      else if (/^[A-Z]/.test(word)) out += `<span class="tok-type">${esc(word)}</span>`;
      else out += esc(word);
      i = j;
      continue;
    }

    out += esc(c);
    i++;
  }
  return out;
}
