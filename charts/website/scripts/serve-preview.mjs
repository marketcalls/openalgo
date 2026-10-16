/** Serve the static export under the same base path used by the website. */
import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { extname, isAbsolute, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../out/', import.meta.url));
const base = '/openalgo-charts';
const port = Number(process.argv[2] ?? 4174);
const types = {
  '.html': 'text/html; charset=utf-8', '.js': 'application/javascript', '.mjs': 'application/javascript',
  '.css': 'text/css', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png',
  '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.ico': 'image/x-icon',
  '.woff': 'font/woff', '.woff2': 'font/woff2', '.txt': 'text/plain; charset=utf-8',
};
if (!existsSync(join(root, 'index.html'))) throw new Error('Build the website before starting its preview.');

createServer(async (req, res) => {
  try {
    const pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
    if (pathname === '/' || pathname === base) {
      res.writeHead(302, { Location: `${base}/` }); res.end(); return;
    }
    if (!pathname.startsWith(`${base}/`)) { res.writeHead(404); res.end('Not found'); return; }
    let file = resolve(root, '.' + pathname.slice(base.length));
    const rel = relative(root, file);
    if (rel.startsWith('..') || isAbsolute(rel)) { res.writeHead(403); res.end('Forbidden'); return; }
    if ((await stat(file)).isDirectory()) file = join(file, 'index.html');
    const body = await readFile(file);
    res.writeHead(200, { 'Content-Type': types[extname(file)] ?? 'application/octet-stream' });
    res.end(body);
  } catch {
    res.writeHead(404); res.end('Not found');
  }
}).listen(port, '127.0.0.1', () => console.log(`Website preview: http://127.0.0.1:${port}${base}/`));
