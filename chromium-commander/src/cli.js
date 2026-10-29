#!/usr/bin/env node
// Command line for people and CI:
//   node src/cli.js doctor                      environment check + real headless launch
//   node src/cli.js smoke <url>                 open, inspect, screenshot (prints the result JSON)
//   node src/cli.js run <workflow.json> [--allow-sensitive] [--headed]
//   node src/cli.js actions                     list available actions
// Ctrl+C cancels a running workflow after the current step and closes the browser.
import fs from 'node:fs';
import { createRequire } from 'node:module';
import { chromium } from 'playwright';
import { ACTIONS, Commander } from './actions.js';
import { loadConfig } from './config.js';
import { runWorkflow } from './workflow.js';

const require = createRequire(import.meta.url);
const out = (obj) => process.stdout.write(`${JSON.stringify(obj, null, 2)}\n`);

async function doctor() {
  const cfg = loadConfig();
  const exe = cfg.executablePath || chromium.executablePath();
  const report = {
    node: process.version,
    platform: `${process.platform} ${process.arch}`,
    playwright: require('playwright/package.json').version,
    chromium_executable: exe,
    chromium_installed: fs.existsSync(exe),
    display: process.env.DISPLAY || process.env.WAYLAND_DISPLAY || null,
    headless: cfg.headless,
    approval: cfg.approval,
    upload_roots: cfg.uploadRoots,
    allowed_hosts: cfg.allowedHosts,
  };
  const commander = new Commander(cfg);
  try {
    const r = await commander.execute('open_url', { url: 'about:blank' });
    report.launch = r.ok ? 'ok' : `${r.status}: ${r.error?.message}`;
    report.browser_version = commander.mgr.browser?.version() ?? null;
  } finally {
    await commander.close();
  }
  out(report);
  return report.launch === 'ok' ? 0 : 1;
}

async function smoke(url) {
  const commander = new Commander(loadConfig());
  try {
    const open = await commander.execute('open_url', { url });
    const inspect = open.ok ? await commander.execute('inspect_page', { include: ['controls'] }) : null;
    const shot = open.ok ? await commander.execute('capture_screenshot', { label: 'smoke' }) : null;
    out({ open, controls: inspect?.observed?.controls?.slice(0, 20), screenshot: shot?.observed?.path, screenshot_status: shot?.status });
    return open.ok && shot?.status === 'VERIFIED' ? 0 : 1;
  } finally {
    await commander.close();
  }
}

async function run(file, flags) {
  const def = JSON.parse(fs.readFileSync(file, 'utf8'));
  const commander = new Commander(loadConfig(flags.headed ? { headless: false } : {}), { log: (m) => process.stderr.write(`${m}\n`) });
  const abort = new AbortController();
  process.once('SIGINT', () => {
    process.stderr.write('cancelling after the current step...\n');
    abort.abort();
  });
  try {
    const report = await runWorkflow(commander, def, {
      allowSensitive: flags['allow-sensitive'],
      signal: abort.signal,
      onStep: (i, r) => process.stderr.write(`step ${i + 1} ${r.action}: ${r.status}${r.error ? ` (${r.error.code})` : ''}\n`),
    });
    out(report);
    return report.status === 'completed' ? 0 : 1;
  } finally {
    await commander.close();
  }
}

const [cmd, ...rest] = process.argv.slice(2);
const flags = Object.fromEntries(rest.filter((a) => a.startsWith('--')).map((a) => [a.slice(2), true]));
const positional = rest.filter((a) => !a.startsWith('--'));

const commands = {
  doctor: () => doctor(),
  smoke: () => (positional[0] ? smoke(positional[0]) : usage()),
  run: () => (positional[0] ? run(positional[0], flags) : usage()),
  actions: () => {
    for (const [name, def] of Object.entries(ACTIONS)) process.stdout.write(`${name.padEnd(30)} ${def.description.split('. ')[0]}\n`);
    return 0;
  },
};

function usage() {
  process.stderr.write('usage: cli.js doctor | smoke <url> | run <workflow.json> [--allow-sensitive] [--headed] | actions\n');
  return 2;
}

Promise.resolve().then(() => (commands[cmd] ?? usage)()).then((code) => process.exit(code), (err) => {
  process.stderr.write(`${err.code ? `${err.code}: ` : ''}${err.message}\n${err.hint ? `hint: ${err.hint}\n` : ''}`);
  process.exit(1);
});
