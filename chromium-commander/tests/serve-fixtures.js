// Serves the test fixture site on 127.0.0.1 for manual and end-to-end checks: node tests/serve-fixtures.js [port]
import { startServer } from './helpers.js';

const srv = await startServer(Number(process.argv[2] || 0));
process.stdout.write(`${srv.base}\n`);
setInterval(() => {
  if (srv.posts.length) process.stderr.write(`POST ${JSON.stringify(srv.posts.splice(0))}\n`);
}, 200);
