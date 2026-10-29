// Loads config/browser.config.json, then applies CC_* environment overrides.
// Relative paths resolve against the chromium-commander folder, not the caller's cwd.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const list = (v) => v.split(',').map((s) => s.trim()).filter(Boolean);
const bool = (v) => !['0', 'false', 'no', 'off', ''].includes(String(v).toLowerCase());

export function loadConfig(overrides = {}, env = process.env) {
  const file = env.CC_CONFIG ? path.resolve(env.CC_CONFIG) : path.join(ROOT, 'config/browser.config.json');
  const cfg = JSON.parse(fs.readFileSync(file, 'utf8'));

  if (env.CC_HEADLESS !== undefined) cfg.headless = bool(env.CC_HEADLESS);
  if (env.CC_ALLOWED_HOSTS) cfg.allowedHosts = list(env.CC_ALLOWED_HOSTS);
  if (env.CC_BLOCKED_HOSTS) cfg.blockedHosts = list(env.CC_BLOCKED_HOSTS);
  if (env.CC_UPLOAD_ROOTS) cfg.uploadRoots = list(env.CC_UPLOAD_ROOTS);
  if (env.CC_APPROVAL) cfg.approval = env.CC_APPROVAL;
  if (env.CC_PROFILE_DIR) cfg.persistentProfileDir = env.CC_PROFILE_DIR;
  if (env.CC_CDP_ENDPOINT) cfg.cdpEndpoint = env.CC_CDP_ENDPOINT;
  if (env.CC_ARTIFACTS_DIR) cfg.artifactsDir = env.CC_ARTIFACTS_DIR;
  if (env.CC_DOWNLOADS_DIR) cfg.downloadsDir = env.CC_DOWNLOADS_DIR;

  Object.assign(cfg, overrides);
  cfg.timeouts = { action: 8000, navigation: 20000, download: 30000, ...cfg.timeouts };

  if (!['ask', 'deny'].includes(cfg.approval)) throw new Error(`approval must be "ask" or "deny", got ${cfg.approval}`);
  for (const key of ['artifactsDir', 'downloadsDir', 'persistentProfileDir']) {
    if (cfg[key]) cfg[key] = path.resolve(ROOT, cfg[key]);
  }
  cfg.uploadRoots = (cfg.uploadRoots || []).map((p) => path.resolve(ROOT, p));
  return cfg;
}
