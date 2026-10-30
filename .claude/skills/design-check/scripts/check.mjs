#!/usr/bin/env node
// Render a page the way people will see it and measure what eyes miss.
//
//   node check.mjs <file.html | http(s)://url> [--out DIR] [--widths 390,1440] [--schemes light,dark] [--json]
//
// For each width × colour scheme: horizontal overflow, text contrast (WCAG AA), tap-target size,
// images without alt, console/page errors, failed loads, font fallbacks, clipped text, heading order,
// visible keyboard focus, line length, and whether the page follows the colour scheme. Screenshots go to
// --out (default ./design-check-out). Exit 1 when any ERROR is found, 0 otherwise; WARNs never fail.
import { createRequire } from "node:module";
import { execSync } from "node:child_process";
import { existsSync, mkdirSync } from "node:fs";
import { resolve, join } from "node:path";
import { pathToFileURL } from "node:url";

function loadPlaywright() {
  const tries = [process.cwd() + "/", import.meta.url];
  try { tries.push(execSync("npm root -g", { encoding: "utf8" }).trim() + "/"); } catch { /* no npm */ }
  for (const base of tries) {
    try { return createRequire(base.endsWith("/") ? base + "x.js" : base)("playwright"); } catch { /* next */ }
  }
  console.error("playwright not found. Install it: npm i -g playwright && npx playwright install chromium");
  process.exit(2);
}

function parseArgs(argv) {
  const o = { target: null, out: "design-check-out", widths: [390, 1440], schemes: ["light", "dark"], json: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--out") o.out = argv[++i];
    else if (a === "--widths") o.widths = argv[++i].split(",").map(Number).filter(Boolean);
    else if (a === "--schemes") o.schemes = argv[++i].split(",");
    else if (a === "--json") o.json = true;
    else if (!o.target) o.target = a;
  }
  if (!o.target) { console.error("usage: node check.mjs <file.html | url> [--out DIR] [--widths 390,1440] [--schemes light,dark] [--json]"); process.exit(2); }
  return o;
}

// Runs inside the page. Returns raw findings for one viewport.
function audit({ mobile }) {
  const out = [];
  const add = (level, check, detail, where) => out.push({ level, check, detail, where });
  const vw = document.documentElement.clientWidth;

  const name = (el) => {
    let s = el.tagName.toLowerCase();
    if (el.id) return s + "#" + el.id;
    const cls = [...el.classList].slice(0, 2).join(".");
    if (cls) s += "." + cls;
    const t = (el.innerText || el.getAttribute("aria-label") || "").trim().replace(/\s+/g, " ").slice(0, 30);
    return t ? `${s} "${t}"` : s;
  };
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== "hidden" && cs.display !== "none" && Number(cs.opacity) > 0.05 && !el.closest("[aria-hidden=true],[inert]");
  };

  // colour maths
  const parse = (c) => {
    const m = c.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number);
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  const over = (fg, bg) => ({ r: fg.r * fg.a + bg.r * (1 - fg.a), g: fg.g * fg.a + bg.g * (1 - fg.a), b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1 });
  const lum = ({ r, g, b }) => {
    const f = (v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  // Effective background: composite every translucent layer up to the canvas. null = image/gradient (unknown).
  const bgOf = (el) => {
    const layers = [];
    for (let n = el; n; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if (cs.backgroundImage && cs.backgroundImage !== "none") return null;
      const c = parse(cs.backgroundColor);
      if (c && c.a > 0) { layers.push(c); if (c.a >= 1) break; }
    }
    let base = { r: 255, g: 255, b: 255, a: 1 }; // browsers paint a white canvas under a transparent page
    for (let i = layers.length - 1; i >= 0; i--) base = over(layers[i], base);
    return base;
  };

  // 1. horizontal overflow
  const sw = document.documentElement.scrollWidth;
  if (sw > vw + 1) {
    const culprits = [];
    for (const el of document.body.querySelectorAll("*")) {
      if (!visible(el)) continue;
      const r = el.getBoundingClientRect();
      if (r.right <= vw + 1) continue;
      let clipped = false;
      for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
        const ox = getComputedStyle(p).overflowX;
        if (ox !== "visible") { clipped = true; break; }
      }
      if (!clipped && getComputedStyle(el).position !== "fixed") culprits.push(el);
    }
    const leaf = culprits.filter((el) => !culprits.some((o) => o !== el && el.contains(o))).slice(0, 3);
    add("error", "overflow", `page is ${sw}px wide in a ${vw}px viewport`, leaf.map(name).join(", ") || "body");
  }

  // 2. contrast, 8. line length, font usage
  const seen = new Set();
  const families = new Map();
  for (const el of document.body.querySelectorAll("*")) {
    const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
    if (!own || !visible(el) || ["SCRIPT", "STYLE", "NOSCRIPT", "OPTION"].includes(el.tagName)) continue;
    const cs = getComputedStyle(el);
    const fam = cs.fontFamily.split(",")[0].trim().replace(/^["']|["']$/g, "");
    families.set(fam, (families.get(fam) || 0) + 1);
    const bg = bgOf(el);
    const fgRaw = parse(cs.color);
    if (bg && fgRaw) {
      const size = parseFloat(cs.fontSize), bold = Number(cs.fontWeight) >= 700;
      const large = size >= 24 || (bold && size >= 18.66);
      const need = large ? 3 : 4.5;
      const fg = over(fgRaw, bg);
      const r = ratio(fg, bg);
      const disabled = el.closest("[disabled],[aria-disabled=true]");
      if (r < need && !disabled) {
        const key = `${cs.color}|${bg.r},${bg.g},${bg.b}|${need}`;
        if (!seen.has(key)) { seen.add(key); add("error", "contrast", `${r.toFixed(2)}:1, needs ${need}:1 (${cs.color} on rgb(${Math.round(bg.r)}, ${Math.round(bg.g)}, ${Math.round(bg.b)}), ${size}px)`, name(el)); }
      }
    }
    if (el.tagName === "P" && el.innerText.length > 200) {
      const cpl = el.getBoundingClientRect().width / (parseFloat(cs.fontSize) * 0.5);
      if (cpl > 95) add("warn", "line-length", `about ${Math.round(cpl)} characters per line (aim for 45–80)`, name(el));
    }
  }

  // 6. font fallbacks: a named family the browser never loaded renders as something else.
  const generic = new Set(["serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "ui-sans-serif", "ui-serif", "ui-monospace", "ui-rounded", "-apple-system", "BlinkMacSystemFont", "math", "emoji"]);
  // Measure a sample in the family with two different fallbacks: identical widths to the bare fallbacks
  // mean the family itself never rendered (neither a loaded web font nor installed on this machine).
  const ctx2d = document.createElement("canvas").getContext("2d");
  const width = (font) => { ctx2d.font = font; return ctx2d.measureText("mmmmmmmmmlli1WQ@ 0123").width; };
  const renders = (fam) => ["monospace", "serif"].some((fb) => width(`32px "${fam}", ${fb}`) !== width(`32px ${fb}`));
  for (const [fam, count] of families) {
    if (generic.has(fam) || renders(fam)) continue;
    add("warn", "font", `"${fam}" never renders (not loaded, not installed); ${count} text elements use the fallback`, "font-family");
  }

  // 3. tap targets, 4. alt text
  for (const el of document.querySelectorAll("a[href],button,input:not([type=hidden]),select,textarea,[role=button],[role=link],[role=tab],[role=switch],[role=checkbox],[role=radio]")) {
    if (!visible(el)) continue;
    const r = el.getBoundingClientRect();
    const inline = el.tagName === "A" && getComputedStyle(el).display === "inline" && el.closest("p,li");
    if (!mobile || inline) continue;
    if (r.width < 24 || r.height < 24) add("error", "tap-target", `${Math.round(r.width)}×${Math.round(r.height)}px (min 24×24, aim 44×44)`, name(el));
    else if (r.width < 44 && r.height < 44) add("warn", "tap-target", `${Math.round(r.width)}×${Math.round(r.height)}px (aim for 44×44 on phones)`, name(el));
  }
  for (const img of document.querySelectorAll("img")) if (!img.hasAttribute("alt")) add("error", "alt", "image has no alt attribute (use alt=\"\" if decorative)", img.getAttribute("src")?.slice(0, 60) || "img");

  // 7. clipped text without an ellipsis
  for (const el of document.body.querySelectorAll("*")) {
    if (!visible(el) || !el.innerText?.trim()) continue;
    const cs = getComputedStyle(el);
    if (!["hidden", "clip"].includes(cs.overflowX) || cs.textOverflow === "ellipsis") continue;
    if (el.clientWidth <= 1 || cs.clip === "rect(0px, 0px, 0px, 0px)") continue; // screen-reader-only text
    if (el.scrollWidth > el.clientWidth + 2 && el.children.length === 0) add("warn", "clipped", `text cut off (${el.scrollWidth}px in ${el.clientWidth}px)`, name(el));
  }

  // 9. headings
  const hs = [...document.querySelectorAll("h1,h2,h3,h4,h5,h6")].filter(visible).map((h) => Number(h.tagName[1]));
  if (hs.length && !hs.includes(1)) add("warn", "headings", "no visible h1", "document");
  for (let i = 1; i < hs.length; i++) if (hs[i] > hs[i - 1] + 1) { add("warn", "headings", `jumps from h${hs[i - 1]} to h${hs[i]}`, "document"); break; }

  return { findings: out, bodyBg: getComputedStyle(document.body).backgroundColor, rootBg: getComputedStyle(document.documentElement).backgroundColor, hasTitle: !!document.title.trim() };
}

// Tab through the first focusable elements and check each one looks different when focused.
async function focusCheck(page) {
  const results = [];
  for (let i = 0; i < 8; i++) {
    await page.keyboard.press("Tab");
    const r = await page.evaluate(() => {
      const el = document.activeElement;
      if (!el || el === document.body) return null;
      const snap = () => { const cs = getComputedStyle(el); return [cs.outlineStyle + cs.outlineWidth, cs.boxShadow, cs.borderColor, cs.backgroundColor].join("|"); };
      const focused = snap();
      el.blur();
      const plain = snap();
      el.focus({ focusVisible: true });
      const label = (el.innerText || el.getAttribute("aria-label") || el.tagName).trim().slice(0, 30);
      return { label, same: focused === plain };
    });
    if (!r) break;
    if (r.same) results.push(r.label);
  }
  return [...new Set(results)];
}

const opts = parseArgs(process.argv.slice(2));
const url = /^https?:\/\//.test(opts.target) ? opts.target : pathToFileURL(resolve(opts.target)).href;
if (!url.startsWith("http") && !existsSync(resolve(opts.target))) { console.error(`not found: ${opts.target}`); process.exit(2); }
mkdirSync(opts.out, { recursive: true });

const { chromium } = loadPlaywright();
const browser = await chromium.launch();
const findings = [];
const bgs = {};
try {
  for (const width of opts.widths) {
    for (const scheme of opts.schemes) {
      const ctx = await browser.newContext({ viewport: { width, height: width < 600 ? 844 : 900 }, colorScheme: scheme, deviceScaleFactor: 1 });
      const page = await ctx.newPage();
      const where = `${width}px ${scheme}`;
      page.on("pageerror", (e) => findings.push({ level: "error", check: "js-error", detail: e.message.split("\n")[0], where }));
      page.on("console", (m) => { if (m.type() === "error") findings.push({ level: "error", check: "console", detail: m.text().slice(0, 160), where }); });
      page.on("requestfailed", (r) => findings.push({ level: "error", check: "load-failed", detail: `${r.url().slice(0, 100)} (${r.failure()?.errorText})`, where }));
      await page.goto(url, { waitUntil: "networkidle", timeout: 30000 }).catch((e) => findings.push({ level: "error", check: "load", detail: e.message.split("\n")[0], where }));
      await page.evaluate(() => document.fonts.ready).catch(() => {});
      await page.waitForTimeout(300);
      const r = await page.evaluate(audit, { mobile: width < 600 });
      for (const f of r.findings) findings.push({ ...f, where: `${where} · ${f.where}` });
      bgs[`${width}-${scheme}`] = r.bodyBg + r.rootBg;
      if (!r.hasTitle && width === opts.widths[0] && scheme === opts.schemes[0]) findings.push({ level: "warn", check: "title", detail: "page has no <title>", where: "document" });
      if (scheme === opts.schemes[0] && width === opts.widths[opts.widths.length - 1]) {
        for (const label of await focusCheck(page)) findings.push({ level: "warn", check: "focus", detail: "no visible change when focused by keyboard", where: `${where} · "${label}"` });
      }
      await page.screenshot({ path: join(opts.out, `${width}-${scheme}.png`), fullPage: true });
      await ctx.close();
    }
  }
} finally {
  await browser.close();
}

if (opts.schemes.includes("light") && opts.schemes.includes("dark")) {
  const w = opts.widths[0];
  if (bgs[`${w}-light`] === bgs[`${w}-dark`]) findings.push({ level: "info", check: "theme", detail: "page looks the same in light and dark; fine only if one look is deliberate", where: "document" });
}

// One line per distinct finding; collapse the same issue seen at several viewports.
const merged = new Map();
for (const f of findings) {
  const [vp, ...rest] = f.where.split(" · ");
  const key = `${f.level}|${f.check}|${f.detail}|${rest.join(" · ")}`;
  const m = merged.get(key) || { ...f, where: rest.join(" · ") || vp, viewports: [] };
  if (!m.viewports.includes(vp)) m.viewports.push(vp);
  merged.set(key, m);
}
const list = [...merged.values()].sort((a, b) => ["error", "warn", "info"].indexOf(a.level) - ["error", "warn", "info"].indexOf(b.level));
const errors = list.filter((f) => f.level === "error").length;
const warns = list.filter((f) => f.level === "warn").length;

if (opts.json) {
  console.log(JSON.stringify({ errors, warnings: warns, findings: list, screenshots: resolve(opts.out) }, null, 2));
} else {
  for (const f of list) console.log(`${f.level.toUpperCase().padEnd(5)} ${f.check.padEnd(11)} ${f.detail}  ← ${f.where}  [${f.viewports.join(", ")}]`);
  console.log(`\n${errors} error(s), ${warns} warning(s). Screenshots: ${resolve(opts.out)}`);
}
process.exit(errors ? 1 : 0);
