// BrowserManager owns the Chromium lifecycle: launch (isolated context by default, a persistent profile
// or a remote CDP browser only when configured), tab ids, dialogs, downloads and disconnect detection.
// Security features stay on: no --disable-web-security, no ignoreHTTPSErrors, no bypassCSP.
import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

export class CommanderError extends Error {
  constructor(code, message, hint) {
    super(message);
    this.code = code;
    this.hint = hint;
  }
}

export function safeFileName(name) {
  const base = path.basename(String(name || 'download')).replace(/[^\w.\- ]+/g, '_').replace(/^\.+/, '').trim();
  return (base || 'download').slice(0, 120);
}

export function uniquePath(dir, name) {
  const ext = path.extname(name);
  const stem = name.slice(0, name.length - ext.length);
  let candidate = path.join(dir, name);
  for (let i = 1; fs.existsSync(candidate); i++) candidate = path.join(dir, `${stem} (${i})${ext}`);
  return candidate;
}

export class BrowserManager {
  constructor(cfg, { log = () => {} } = {}) {
    this.cfg = cfg;
    this.log = log;
    this.browser = null;
    this.context = null;
    this.tabs = new Map(); // id -> page
    this.activeId = null;
    this.nextTab = 1;
    this.dialogs = [];
    this.nextDialog = null; // { mode, promptText } one-shot
    this.downloads = [];
    this.lastNavMethod = new WeakMap(); // page -> method of its last main-frame navigation
    this.downloadWaiters = new Set();
    this.disconnects = 0;
    this.launching = null;
  }

  get connected() {
    if (!this.context) return false;
    if (this.browser) return this.browser.isConnected();
    return !this.contextClosed;
  }

  mode() {
    if (this.cfg.cdpEndpoint) return 'remote-cdp';
    if (this.cfg.persistentProfileDir) return 'persistent-profile';
    return 'isolated';
  }

  // Launches on first use and relaunches after a disconnect. Returns { relaunched }.
  async ensure() {
    if (this.connected) return { relaunched: false };
    const wasRunning = this.context !== null;
    if (!this.launching) this.launching = this.launch().finally(() => (this.launching = null));
    await this.launching;
    return { relaunched: wasRunning };
  }

  async launch() {
    const { cfg } = this;
    if (!cfg.headless && process.platform === 'linux' && !process.env.DISPLAY && !process.env.WAYLAND_DISPLAY) {
      throw new CommanderError('NO_DISPLAY', 'A visible browser was requested but this machine has no graphical display.',
        'Run headless (CC_HEADLESS=1), or start under a virtual display: xvfb-run -a node src/mcp-server.js');
    }
    this.reset();
    const contextOptions = { acceptDownloads: true, viewport: cfg.viewport };
    try {
      if (cfg.cdpEndpoint) {
        this.browser = await chromium.connectOverCDP(cfg.cdpEndpoint, { timeout: cfg.timeouts.navigation });
        this.context = this.browser.contexts()[0] ?? (await this.browser.newContext(contextOptions));
      } else if (cfg.persistentProfileDir) {
        fs.mkdirSync(cfg.persistentProfileDir, { recursive: true, mode: 0o700 });
        this.context = await chromium.launchPersistentContext(cfg.persistentProfileDir, {
          ...contextOptions, headless: cfg.headless, executablePath: cfg.executablePath || undefined,
        });
      } else {
        this.browser = await chromium.launch({ headless: cfg.headless, executablePath: cfg.executablePath || undefined });
        this.context = await this.browser.newContext(contextOptions);
      }
    } catch (err) {
      throw classifyLaunchError(err);
    }
    this.context.setDefaultTimeout(cfg.timeouts.action);
    this.context.setDefaultNavigationTimeout(cfg.timeouts.navigation);
    this.contextClosed = false;
    this.context.on('close', () => {
      this.contextClosed = true;
      this.disconnects++;
    });
    this.browser?.on('disconnected', () => this.disconnects++);
    this.context.on('page', (page) => this.track(page, true));
    for (const page of this.context.pages()) this.track(page, false);
    if (!this.tabs.size) await this.context.newPage(); // 'page' event tracks and activates it
    this.log(`browser launched (${this.mode()}, headless=${cfg.headless})`);
  }

  reset() {
    this.browser = null;
    this.context = null;
    this.tabs.clear();
    this.activeId = null;
  }

  track(page, activate) {
    for (const p of this.tabs.values()) if (p === page) return;
    const id = `t${this.nextTab++}`;
    this.tabs.set(id, page);
    if (activate || !this.activeId) this.activeId = id;
    page.on('close', () => {
      this.tabs.delete(id);
      if (this.activeId === id) this.activeId = [...this.tabs.keys()].pop() ?? null;
    });
    page.on('dialog', (dialog) => this.onDialog(id, dialog));
    page.on('request', (req) => {
      if (req.isNavigationRequest() && req.frame() === page.mainFrame()) this.lastNavMethod.set(page, req.method());
    });
    page.on('download', (download) => this.onDownload(id, download));
  }

  async onDialog(tabId, dialog) {
    const plan = this.nextDialog;
    this.nextDialog = null;
    const accept = dialog.type() === 'alert' || dialog.type() === 'beforeunload' || plan?.mode === 'accept';
    const record = { tab: tabId, type: dialog.type(), message: dialog.message().slice(0, 500), handled: accept ? 'accepted' : 'dismissed', at: new Date().toISOString() };
    this.dialogs.push(record);
    try {
      if (accept) await dialog.accept(plan?.promptText);
      else await dialog.dismiss();
    } catch (err) {
      record.error = err.message;
    }
  }

  async onDownload(tabId, download) {
    const dir = this.cfg.downloadsDir;
    fs.mkdirSync(dir, { recursive: true });
    const name = safeFileName(download.suggestedFilename());
    const record = { tab: tabId, url: download.url(), suggested_name: name, path: null, size: null, status: 'in_progress', started_at: new Date().toISOString() };
    this.downloads.push(record);
    try {
      const target = uniquePath(dir, name);
      await download.saveAs(target);
      const failure = await download.failure();
      if (failure) throw new Error(failure);
      record.path = target;
      record.size = fs.statSync(target).size;
      record.status = 'complete';
    } catch (err) {
      record.status = 'failed';
      record.error = err.message;
    }
    for (const waiter of this.downloadWaiters) waiter(record);
  }

  waitForDownloadDone(timeout) {
    let done;
    const promise = new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.downloadWaiters.delete(done);
        reject(new CommanderError('DOWNLOAD_TIMEOUT', `no download finished within ${timeout} ms`));
      }, timeout);
      done = (record) => {
        clearTimeout(timer);
        this.downloadWaiters.delete(done);
        resolve(record);
      };
      this.downloadWaiters.add(done);
    });
    return { promise, cancel: () => this.downloadWaiters.delete(done) };
  }

  page() {
    const page = this.tabs.get(this.activeId);
    if (!page) throw new CommanderError('NO_PAGE', 'no open tab', 'open one with open_tab or open_url');
    return page;
  }

  async newTab(url) {
    const page = await this.context.newPage();
    this.activate(page);
    if (url) await page.goto(url, { waitUntil: 'domcontentloaded' });
    return this.idOf(page);
  }

  idOf(page) {
    for (const [id, p] of this.tabs) if (p === page) return id;
    return null;
  }

  activate(page) {
    const id = this.idOf(page);
    if (id) this.activeId = id;
  }

  switchTab(id) {
    const page = this.tabs.get(id);
    if (!page) throw new CommanderError('TAB_NOT_FOUND', `no tab with id ${id}`, 'call list_tabs');
    this.activeId = id;
    return page;
  }

  async listTabs() {
    const out = [];
    for (const [id, page] of this.tabs) {
      out.push({ id, url: page.url(), title: await page.title().catch(() => ''), active: id === this.activeId });
    }
    return out;
  }

  async state() {
    return {
      connected: this.connected,
      mode: this.mode(),
      headless: this.cfg.headless,
      browser_version: this.browser?.version() ?? null,
      tabs: this.connected ? await this.listTabs() : [],
      active_tab: this.activeId,
      disconnects: this.disconnects,
      dialogs: this.dialogs.slice(-10),
      downloads: this.downloads.slice(-10),
    };
  }

  async close() {
    const ctx = this.context;
    const browser = this.browser;
    this.reset();
    try {
      if (browser) await browser.close();
      else if (ctx) await ctx.close();
    } catch {
      // already gone
    }
  }
}

function classifyLaunchError(err) {
  const msg = err.message || String(err);
  if (/Executable doesn't exist|Failed to launch.*ENOENT/i.test(msg)) {
    return new CommanderError('BROWSER_MISSING', 'Chromium is not installed for this Playwright version.',
      'Run: npx playwright install chromium   (Linux CI also needs: npx playwright install-deps chromium)');
  }
  if (/XServer|Missing X server|\$DISPLAY/i.test(msg)) {
    return new CommanderError('NO_DISPLAY', 'Headed Chromium needs a display.', 'Use CC_HEADLESS=1 or xvfb-run -a.');
  }
  if (/ECONNREFUSED|connectOverCDP/i.test(msg)) {
    return new CommanderError('REMOTE_UNREACHABLE', `Could not reach the remote browser: ${msg.split('\n')[0]}`, 'Check CC_CDP_ENDPOINT.');
  }
  return new CommanderError('LAUNCH_FAILED', msg.split('\n')[0], 'Run: node src/cli.js doctor');
}
