// Minimal static server for Playwright: serves the repo root with a JS MIME type
// for .mjs (browsers reject text/plain ES modules). No dependencies.
const http = require('http');
const fs = require('fs');
const path = require('path');

const PORT = Number(process.env.OAC_E2E_PORT || 4173);
const ROOT = path.resolve(__dirname, '..', '..');
const MIME = {
  '.html': 'text/html', '.mjs': 'application/javascript', '.js': 'application/javascript',
  '.css': 'text/css', '.json': 'application/json', '.map': 'application/json',
};

http.createServer((req, res) => {
  const rel = decodeURIComponent((req.url || '/').split('?')[0]);
  const fp = path.join(ROOT, rel === '/' ? '/tests/e2e/fixture.html' : rel);
  if (!fp.startsWith(ROOT)) { res.writeHead(403); res.end('forbidden'); return; }
  fs.readFile(fp, (err, data) => {
    if (err) { res.writeHead(404); res.end('not found'); return; }
    res.writeHead(200, { 'Content-Type': MIME[path.extname(fp)] || 'application/octet-stream' });
    res.end(data);
  });
}).listen(PORT, () => console.log(`e2e static server: http://127.0.0.1:${PORT}`));
