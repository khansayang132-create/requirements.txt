// Local fixture server and a Commander wired to temp folders, so tests never touch real websites.
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Commander } from '../src/actions.js';
import { loadConfig } from '../src/config.js';

const SITE = path.join(path.dirname(fileURLToPath(import.meta.url)), 'fixtures/site');

export async function startServer(port = 0) {
  const posts = [];
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://x');
    if (req.method === 'POST') {
      const chunks = [];
      req.on('data', (c) => chunks.push(c));
      req.on('end', () => {
        posts.push({ path: url.pathname, body: Buffer.concat(chunks).toString() });
        res.writeHead(200, { 'content-type': 'text/html' });
        res.end('<!doctype html><title>Received</title><h1>Order received</h1>');
      });
      return;
    }
    if (url.pathname.startsWith('/download/')) {
      const name = path.basename(url.pathname);
      res.writeHead(200, { 'content-type': 'application/octet-stream', 'content-disposition': `attachment; filename="${name}"` });
      res.end(name === 'empty.txt' ? '' : 'quarterly report\n');
      return;
    }
    if (url.pathname === '/slow') {
      setTimeout(() => {
        res.writeHead(200, { 'content-type': 'text/html' });
        res.end('<title>Slow</title><h1>Finally</h1>');
      }, Number(url.searchParams.get('ms') || 3000));
      return;
    }
    const file = path.join(SITE, url.pathname === '/' ? 'index.html' : path.normalize(url.pathname));
    if (!file.startsWith(SITE) || !fs.existsSync(file)) {
      res.writeHead(404, { 'content-type': 'text/html' });
      res.end('<title>Not found</title><h1>404</h1>');
      return;
    }
    res.writeHead(200, { 'content-type': 'text/html' });
    res.end(fs.readFileSync(file));
  });
  await new Promise((r) => server.listen(port, '127.0.0.1', r));
  const base = `http://127.0.0.1:${server.address().port}`;
  return {
    base,
    posts,
    close: () => new Promise((r) => {
      server.closeAllConnections();
      server.close(r);
    }),
  };
}

export function tempDir(prefix = 'cc-test-') {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

export function makeCommander(overrides = {}) {
  const dir = tempDir();
  const cfg = loadConfig({
    headless: true,
    artifactsDir: path.join(dir, 'artifacts'),
    downloadsDir: path.join(dir, 'downloads'),
    timeouts: { action: 2500, navigation: 6000, download: 6000 },
    maxRetries: 1,
    ...overrides,
  }, {});
  return { commander: new Commander(cfg), cfg, dir };
}
