// HALLMARK render check: loads a page in real Chromium at phone, tablet and desktop widths.
// Usage: node render_check.cjs <url> <out-dir>   (called by hallmark_check.py render)
// Prints one JSON line: {status: PASS|FAIL|BLOCKED, viewports: [...], problems: [...]}.
const fs = require("fs");
const path = require("path");

let chromium;
try {
  ({ chromium } = require("playwright"));
} catch (e) {
  console.log(JSON.stringify({ status: "BLOCKED", detail: "Node package 'playwright' not found" }));
  process.exit(0);
}

const VIEWPORTS = [
  { name: "phone", width: 390, height: 844 },
  { name: "tablet", width: 768, height: 1024 },
  { name: "desktop", width: 1440, height: 900 },
];
const MAX_TABS = 40;

(async () => {
  const [url, outDir] = process.argv.slice(2);
  fs.mkdirSync(outDir, { recursive: true });
  let browser;
  try {
    browser = await chromium.launch();
  } catch (e) {
    console.log(JSON.stringify({ status: "BLOCKED", detail: "Chromium failed to launch: " + e.message.split("\n")[0] }));
    return;
  }
  const problems = [];
  const viewports = [];
  for (const vp of VIEWPORTS) {
    const page = await browser.newPage({ viewport: { width: vp.width, height: vp.height } });
    const errors = [];
    page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(url, { waitUntil: "load", timeout: 30000 });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    const shot = path.join(outDir, `${vp.name}-${vp.width}.png`);
    await page.screenshot({ path: shot, fullPage: true });

    // Keyboard pass: Tab through the page; a focused control must look different from its unfocused self.
    // Fast path: an outline or box-shadow. Otherwise compare the control's pixels while focused with the
    // same page region on a freshly loaded page where nothing is focused (catches native widgets such as
    // the date picker button, whose ring is drawn inside the shadow DOM; a neighbour's ring can't leak in).
    const noRing = [];
    let reached = 0;
    const pending = []; // {label, clip, img} awaiting the unfocused baseline
    for (let i = 0; i < MAX_TABS; i++) {
      await page.keyboard.press("Tab");
      const r = await page.evaluate(() => {
        const el = document.activeElement;
        if (!el || el === document.body) return null;
        const s = getComputedStyle(el);
        const ring = (s.outlineStyle !== "none" && parseFloat(s.outlineWidth) > 0) || s.boxShadow !== "none";
        const b = el.getBoundingClientRect();
        const pad = 6;
        const clip = { x: Math.max(0, b.x + scrollX - pad), y: Math.max(0, b.y + scrollY - pad), width: b.width + 2 * pad, height: b.height + 2 * pad };
        const label = (el.getAttribute("aria-label") || el.textContent || el.tagName).trim().slice(0, 40);
        return { ring, clip, label: `${el.tagName.toLowerCase()} "${label}"` };
      });
      if (!r) break;
      reached++;
      if (!r.ring && r.clip.width > 0 && r.clip.height > 0) {
        pending.push({ label: r.label, clip: r.clip, img: await page.screenshot({ clip: r.clip, fullPage: true }) });
      }
    }
    if (pending.length) {
      await page.reload({ waitUntil: "load" });
      for (const p of pending) {
        const base = await page.screenshot({ clip: p.clip, fullPage: true });
        if (p.img.equals(base) && !noRing.includes(p.label)) noRing.push(p.label);
      }
    }
    viewports.push({ ...vp, overflow_px: overflow, console_errors: errors, focusable_reached: reached, screenshot: shot });
    if (overflow > 0) problems.push(`${vp.name}: page scrolls sideways by ${overflow}px`);
    for (const e of errors) problems.push(`${vp.name}: console error: ${e.slice(0, 160)}`);
    for (const l of noRing) problems.push(`${vp.name}: no visible focus indicator on ${l}`);
    await page.close();
  }
  await browser.close();
  console.log(JSON.stringify({ status: problems.length ? "FAIL" : "PASS", url, viewports, problems }));
})().catch((e) => console.log(JSON.stringify({ status: "BLOCKED", detail: String(e.message || e).split("\n")[0] })));
