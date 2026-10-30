// node --test .claude/skills/design-check/scripts/check.test.mjs
// Pins what check.mjs catches (fixtures/bad.html) and what it must not flag (fixtures/good.html).
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const run = (fixture) => {
  const out = mkdtempSync(join(tmpdir(), "design-check-"));
  const r = spawnSync(process.execPath, [join(here, "check.mjs"), join(here, "fixtures", fixture), "--out", out, "--json"], { encoding: "utf8", timeout: 120000 });
  assert.notEqual(r.status, 2, r.stderr);
  return { code: r.status, report: JSON.parse(r.stdout) };
};

test("a clean, themed, responsive page passes with no findings", () => {
  const { code, report } = run("good.html");
  assert.equal(code, 0);
  assert.deepEqual(report.findings.filter((f) => f.level !== "info"), []);
});

test("a broken page fails and names every planted problem", () => {
  const { code, report } = run("bad.html");
  assert.equal(code, 1);
  const has = (level, check, text = "") => report.findings.some((f) => f.level === level && f.check === check && (f.detail + f.where).includes(text));
  assert.ok(has("error", "overflow", "div.wide"), "overflow");
  assert.ok(has("error", "contrast", "p.faint"), "contrast");
  assert.ok(has("error", "tap-target", "button.tiny"), "tap target");
  assert.ok(has("error", "alt"), "alt");
  assert.ok(has("error", "js-error", "boom from fixture"), "js error");
  assert.ok(has("warn", "font", "Imaginary Grotesk"), "font fallback");
  assert.ok(!has("warn", "font", "Arial"), "installed fonts are not flagged");
  assert.ok(has("warn", "headings", "no visible h1"), "h1");
  assert.ok(has("warn", "title"), "title");
  assert.ok(has("warn", "focus"), "focus");
  // Overflow and tap targets are phone problems; they must not be reported at desktop width.
  assert.ok(report.findings.filter((f) => f.check === "tap-target").every((f) => f.viewports.every((v) => v.startsWith("390"))));
});
