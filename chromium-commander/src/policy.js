// Action policy: every action is classified LOW, SENSITIVE or BLOCKED before it runs.
//
//   LOW        runs autonomously (reading, navigating, scrolling, filling ordinary fields).
//   SENSITIVE  needs a human: the action is parked as a pending approval and only runs through
//              confirm(approvalId). Ids are single-use, expire, are bound to the exact arguments and
//              to the page URL they were issued on. With approval "deny" sensitive actions are BLOCKED.
//   BLOCKED    never runs, even with approval: secret fields (passwords, OTP, card data), unsafe URL
//              schemes, hosts outside the allowlist, uploads outside the upload roots or of secret files.
//
// Element "facts" (tag, type, accessible name, form membership...) come from the page, so a page can
// try to look harmless. The rules therefore err towards SENSITIVE: a submit button is sensitive
// whatever its label says.
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

export const LOW = 'low';
export const SENSITIVE = 'sensitive';
export const BLOCKED = 'blocked';

// English plus common Indonesian equivalents (the owner's audience writes Bahasa Indonesia).
const SENSITIVE_WORDS = new RegExp(
  '\\b(' +
    [
      'buy', 'purchase', 'pay', 'payment', 'checkout', 'check out', 'place order', 'order now', 'donate',
      'send', 'submit', 'post', 'publish', 'tweet', 'reply', 'comment', 'share', 'upload',
      'delete', 'remove', 'destroy', 'erase', 'transfer', 'withdraw', 'deposit',
      'subscribe', 'unsubscribe', 'confirm', 'accept', 'agree', 'sign', 'sign up', 'register',
      'save', 'apply', 'update', 'change', 'deactivate', 'close account', 'cancel', 'book', 'reserve',
      'kirim', 'bayar', 'beli', 'hapus', 'simpan', 'unggah', 'setuju', 'konfirmasi', 'daftar', 'posting',
    ].map((w) => w.replace(/ /g, '\\s+')).join('|') +
    ')\\b',
  'i',
);

const SECRET_FIELD = /(pass(word|wd|code)?|pwd|otp|one[-_ ]?time|2fa|mfa|totp|cvv|cvc|csc|card[-_ ]?(number|no)|cc[-_]?(num|number)|security[-_ ]?code|\bpin\b|ssn|iban|routing)/i;
const SECRET_AUTOCOMPLETE = /(password|one-time-code|cc-)/i;
const SECRET_FILES = [
  /(^|\/)\.env(\..*)?$/i, /(^|\/)\.ssh\//, /(^|\/)id_(rsa|dsa|ecdsa|ed25519)(\.pub)?$/i, /\.(pem|key|p12|pfx|kdbx)$/i,
  /(^|\/)\.(aws|gnupg|kube|docker)\//, /(^|\/)(credentials|secrets?)(\.\w+)?$/i, /(^|\/)\.netrc$/, /(^|\/)\.git-credentials$/,
];
const SAFE_SCHEMES = new Set(['http:', 'https:', 'about:']);

const decision = (risk, reasons) => ({ risk, reasons });

export function hostAllowed(url, cfg) {
  let u;
  try {
    u = new URL(url);
  } catch {
    return { ok: false, reason: `not a valid absolute URL: ${url}` };
  }
  if (!SAFE_SCHEMES.has(u.protocol)) return { ok: false, reason: `URL scheme ${u.protocol} is not allowed` };
  if (u.protocol === 'about:' && u.href !== 'about:blank') return { ok: false, reason: 'only about:blank is allowed' };
  if (u.protocol === 'about:') return { ok: true };
  const host = u.hostname.toLowerCase();
  const match = (pattern) => {
    const p = pattern.toLowerCase();
    return p.startsWith('*.') ? host.endsWith(p.slice(1)) || host === p.slice(2) : host === p;
  };
  if ((cfg.blockedHosts || []).some(match)) return { ok: false, reason: `host ${host} is blocked by policy` };
  if ((cfg.allowedHosts || []).length && !cfg.allowedHosts.some(match)) {
    return { ok: false, reason: `host ${host} is not in allowedHosts` };
  }
  return { ok: true };
}

export function isSecretField(f) {
  if (!f) return false;
  if (f.type === 'password') return true;
  if (f.autocomplete && SECRET_AUTOCOMPLETE.test(f.autocomplete)) return true;
  return [f.nameAttr, f.id, f.label, f.name, f.placeholder].some((v) => v && SECRET_FIELD.test(v));
}

export function checkUploadPath(file, cfg) {
  const real = (() => {
    try {
      return fs.realpathSync(file);
    } catch {
      return null;
    }
  })();
  if (!real) return { ok: false, reason: `file does not exist: ${file}` };
  if (!fs.statSync(real).isFile()) return { ok: false, reason: `not a regular file: ${file}` };
  if (SECRET_FILES.some((re) => re.test(real))) return { ok: false, reason: `refusing to upload a secret-looking file: ${path.basename(real)}` };
  const roots = (cfg.uploadRoots || []).map((r) => {
    try {
      return fs.realpathSync(r);
    } catch {
      return null;
    }
  }).filter(Boolean);
  if (!roots.length) return { ok: false, reason: 'uploads are disabled: no uploadRoots configured (CC_UPLOAD_ROOTS)' };
  if (!roots.some((r) => real === r || real.startsWith(r + path.sep))) {
    return { ok: false, reason: `file is outside the configured uploadRoots: ${real}` };
  }
  return { ok: true, real };
}

// facts: element facts for the action's target (see targets.elementFacts), or null.
export function classify(action, args, facts, cfg) {
  const reasons = [];
  const label = facts ? [facts.name, facts.text, facts.value, facts.title].filter(Boolean).join(' ') : '';

  switch (action) {
    case 'open_url':
    case 'open_tab': {
      if (action === 'open_tab' && !args.url) return decision(LOW, []);
      const h = hostAllowed(args.url, cfg);
      return h.ok ? decision(LOW, []) : decision(BLOCKED, [h.reason]);
    }
    case 'fill_input':
      if (isSecretField(facts)) {
        return decision(BLOCKED, ['secret field (password, one-time code or payment data): the user must type this themselves in a visible browser']);
      }
      return decision(LOW, []);
    case 'click_element':
    case 'download_file':
      if (facts?.isSubmit) reasons.push('submits a form');
      if (label && SENSITIVE_WORDS.test(label)) reasons.push(`control is labelled "${label.slice(0, 60)}"`);
      if (facts?.href && /^(mailto|tel|sms):/i.test(facts.href)) reasons.push('opens an external messaging link');
      if (facts?.href && /^javascript:/i.test(facts.href)) reasons.push('runs a javascript: link');
      if (facts?.href && !/^(javascript|mailto|tel|sms):/i.test(facts.href) && /^[a-z][a-z0-9+.-]*:/i.test(facts.href)) {
        const h = hostAllowed(facts.href, cfg);
        if (!h.ok) return decision(BLOCKED, [h.reason]);
      }
      return decision(reasons.length ? SENSITIVE : LOW, reasons);
    case 'press_key':
      if (/^(enter|numpadenter)$/i.test(args.key) && facts?.inForm) return decision(SENSITIVE, ['Enter inside a form can submit it']);
      return decision(LOW, []);
    case 'check_checkbox':
    case 'select_option':
      if (label && /\b(agree|accept|terms|consent|authori[sz]e|setuju)\b/i.test(label)) return decision(SENSITIVE, ['accepts an agreement or consent']);
      return decision(LOW, []);
    case 'upload_file': {
      for (const p of args.paths) {
        const c = checkUploadPath(p, cfg);
        if (!c.ok) return decision(BLOCKED, [c.reason]);
      }
      return decision(SENSITIVE, ['uploads files from this machine to the website']);
    }
    case 'handle_dialogs':
      return args.mode === 'accept' ? decision(SENSITIVE, ['accepting a page dialog can confirm an irreversible action']) : decision(LOW, []);
    default:
      return decision(LOW, []);
  }
}

export class ApprovalBook {
  constructor(ttlSeconds = 300, now = () => Date.now()) {
    this.ttl = ttlSeconds * 1000;
    this.now = now;
    this.pending = new Map();
  }

  request(action, args, url, reasons) {
    const id = `apv_${crypto.randomBytes(6).toString('hex')}`;
    this.pending.set(id, { action, args, url, reasons, expires: this.now() + this.ttl });
    return id;
  }

  // Consumes the id. The caller runs entry.action with entry.args (the stored, approved arguments),
  // never arguments supplied with the confirmation. Returns { ok, entry } or { ok: false, reason }.
  take(id, currentUrl) {
    const entry = this.pending.get(id);
    if (!entry) return { ok: false, reason: 'unknown or already used approval id' };
    this.pending.delete(id);
    if (this.now() > entry.expires) return { ok: false, reason: 'approval expired; request the action again' };
    if (currentUrl !== entry.url) return { ok: false, reason: `page changed since approval was requested (was ${entry.url}, now ${currentUrl})` };
    return { ok: true, entry };
  }

  list() {
    return [...this.pending.entries()].map(([id, e]) => ({ approval_id: id, action: e.action, args: e.args, url: e.url, reasons: e.reasons }));
  }
}
