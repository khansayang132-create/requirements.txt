// Turns a target spec into one Playwright locator, preferring semantic locators:
//   { role, name, exact }  >  { label }  >  { placeholder }  >  { testId }  >  { text }  >  { css }  >  { xpath }
// Optional: nth (0-based, picks among several matches), within (css scope).
// A spec that matches several elements without nth is an error, not a guess.
import { CommanderError } from './browser.js';

export const TARGET_SCHEMA = {
  type: 'object',
  description: 'Element to act on. Prefer {role,name} as returned by inspect_page; then label, placeholder, testId, text, css, xpath.',
  properties: {
    role: { type: 'string' }, name: { type: 'string' }, exact: { type: 'boolean' },
    label: { type: 'string' }, placeholder: { type: 'string' }, testId: { type: 'string' },
    text: { type: 'string' }, css: { type: 'string' }, xpath: { type: 'string' },
    nth: { type: 'integer', minimum: 0 }, within: { type: 'string' },
  },
  additionalProperties: false,
};

export function describeTarget(t) {
  if (t.role) return `${t.role}${t.name !== undefined ? ` "${t.name}"` : ''}${t.nth !== undefined ? ` #${t.nth}` : ''}`;
  const key = ['label', 'placeholder', 'testId', 'text', 'css', 'xpath'].find((k) => t[k] !== undefined);
  return key ? `${key}=${JSON.stringify(t[key])}${t.nth !== undefined ? ` #${t.nth}` : ''}` : '(empty target)';
}

export function buildLocator(page, t) {
  const scope = t.within ? page.locator(t.within) : page;
  const exact = t.exact ?? true;
  if (t.role) return scope.getByRole(t.role, t.name !== undefined ? { name: t.name, exact } : {});
  if (t.label !== undefined) return scope.getByLabel(t.label, { exact });
  if (t.placeholder !== undefined) return scope.getByPlaceholder(t.placeholder, { exact });
  if (t.testId !== undefined) return scope.getByTestId(t.testId);
  if (t.text !== undefined) return scope.getByText(t.text, { exact: t.exact ?? false });
  if (t.css !== undefined) return scope.locator(t.css);
  if (t.xpath !== undefined) return scope.locator(`xpath=${t.xpath}`);
  throw new CommanderError('INVALID_ARGUMENTS', 'target has no locator field', 'give role+name, label, placeholder, testId, text, css or xpath');
}

// Waits (bounded) for the target to exist, then requires exactly one match.
export async function resolveTarget(page, t, timeout, { state = 'attached' } = {}) {
  const all = buildLocator(page, t);
  try {
    await all.first().waitFor({ state, timeout });
  } catch (err) {
    if (/Timeout/i.test(err.name + err.message)) {
      throw new CommanderError('TARGET_NOT_FOUND', `no element matches ${describeTarget(t)} on ${page.url()}`,
        'call inspect_page to see the current controls; the page may have changed');
    }
    throw err;
  }
  const count = await all.count();
  if (t.nth !== undefined) {
    if (t.nth >= count) throw new CommanderError('TARGET_NOT_FOUND', `${describeTarget(t)}: only ${count} match(es)`);
    return all.nth(t.nth);
  }
  if (count > 1) {
    throw new CommanderError('AMBIGUOUS_TARGET', `${describeTarget(t)} matches ${count} elements`,
      'add nth (0-based), a more specific name, or within (a css scope)');
  }
  return all;
}

// Facts the policy needs. Values from the page are untrusted; they only make an action MORE restricted.
export async function elementFacts(locator) {
  return locator.evaluate((el) => {
    const labelText = el.labels?.length ? [...el.labels].map((l) => l.innerText).join(' ') : '';
    const aria = el.getAttribute('aria-label') || '';
    const text = (el.innerText || el.textContent || '').trim().slice(0, 120);
    const form = el.form || el.closest('form');
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    const isSubmit = (tag === 'button' && (type === '' || type === 'submit') && !!form) || (tag === 'input' && (type === 'submit' || type === 'image'));
    return {
      tag, type, role: el.getAttribute('role') || '',
      name: (aria || labelText || '').trim().slice(0, 120),
      text, value: tag === 'input' && ['submit', 'button'].includes(type) ? el.value : '',
      title: el.getAttribute('title') || '',
      nameAttr: el.getAttribute('name') || '', id: el.id || '',
      label: labelText.trim().slice(0, 120), placeholder: el.getAttribute('placeholder') || '',
      autocomplete: el.getAttribute('autocomplete') || '',
      href: el.closest('a')?.getAttribute('href') || '',
      opensNewTab: !!el.closest('a') && !['', '_self', '_top', '_parent'].includes((el.closest('a').getAttribute('target') || '').toLowerCase()),
      inForm: !!form, isSubmit,
      contentEditable: el.isContentEditable,
    };
  });
}
