/** Automated WCAG A/AA checks plus keyboard interaction checks.
 * npm ci installs the pinned axe-core 4.14.0 scanner.
 * node scripts/browser-qa.mjs --a11y --base http://127.0.0.1:8879 --model-base http://127.0.0.1:8878
 * These checks are not a human assistive-technology or usability study.
 */
import { chromium } from 'playwright';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';

const require = createRequire(import.meta.url);
function argument(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : undefined;
}
const base = argument('--base') || process.env.NOTICEFORGE_URL || 'http://127.0.0.1:8879';
const modelBase =
  argument('--model-base') || process.env.NOTICEFORGE_MODEL_REVIEW_URL || 'http://127.0.0.1:8878';
const output = path.resolve(argument('--output') || 'reports/accessibility');
let axePath = process.env.NOTICEFORGE_AXE_PATH;
if (!axePath) {
  try {
    axePath = require.resolve('axe-core/axe.min.js');
  } catch {
    axePath = '/tmp/noticeforge-ui-a11y/node_modules/axe-core/axe.min.js';
  }
}
const axeSource = await readFile(axePath, 'utf8');
const axePackage = JSON.parse(await readFile(path.join(path.dirname(axePath), 'package.json'), 'utf8'));
if (axePackage.version !== '4.14.0')
  throw new Error('This reproducible accessibility pass is pinned to axe-core 4.14.0.');
await mkdir(output, { recursive: true });
const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH || '/usr/bin/google-chrome',
  headless: true,
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 1 });
const keyboardChecks = [];
const scans = [];
const diagnosticChecks = [];
const errors = [];
page.on('pageerror', (error) => errors.push(String(error)));
await page.route('**/__noticeforge_axe.js', (route) =>
  route.fulfill({ status: 200, contentType: 'application/javascript', body: axeSource }),
);
function check(name, passed) {
  keyboardChecks.push({ name, passed: Boolean(passed) });
}
async function scan(name) {
  if (!(await page.evaluate(() => Boolean(window.axe))))
    await page.addScriptTag({ url: new URL('/__noticeforge_axe.js', page.url()).href });
  const result = await page.evaluate(async () => {
    const result = await window.axe.run(document, {
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'] },
    });
    return {
      testEngine: result.testEngine,
      testEnvironment: result.testEnvironment,
      timestamp: result.timestamp,
      url: result.url,
      violations: result.violations,
      incomplete: result.incomplete,
      pass_count: result.passes.length,
    };
  });
  scans.push({ name, ...result });
  await writeFile(path.join(output, `${name}.json`), JSON.stringify(result, null, 2));
  await page.screenshot({ path: path.join(output, `${name}.png`), fullPage: true });
}
async function openByKeyboard(trigger, dialog) {
  await page.locator(trigger).focus();
  await page.keyboard.press('Enter');
  await page.locator(dialog).waitFor({ state: 'visible' });
  check(
    `${dialog}: keyboard activation focuses the dialog`,
    await page.evaluate(
      (selector) => document.querySelector(selector).contains(document.activeElement),
      dialog,
    ),
  );
  let trapped = true;
  for (let index = 0; index < 15; index++) {
    await page.keyboard.press('Tab');
    trapped =
      trapped &&
      (await page.evaluate(
        (selector) => document.querySelector(selector).contains(document.activeElement),
        dialog,
      ));
  }
  for (let index = 0; index < 5; index++) {
    await page.keyboard.press('Shift+Tab');
    trapped =
      trapped &&
      (await page.evaluate(
        (selector) => document.querySelector(selector).contains(document.activeElement),
        dialog,
      ));
  }
  check(`${dialog}: Tab and Shift+Tab remain inside the modal`, trapped);
}
async function closeByEscape(trigger, dialog) {
  await page.keyboard.press('Escape');
  await page.locator(dialog).waitFor({ state: 'hidden' });
  check(
    `${dialog}: Escape restores focus to its trigger`,
    await page.locator(trigger).evaluate((element) => document.activeElement === element),
  );
}
try {
  const notices = await (await page.request.get(`${base}/api/notices`)).json();
  const primary = notices.notices.find((notice) => notice.notice_id === 'AST-PDN-2026-041');
  await page.goto(`${base}/?notice=${primary.id}`, { waitUntil: 'networkidle' });
  await page.locator('#notice-content').waitFor({ state: 'visible' });
  await page.screenshot({ path: path.join(output, 'default-workspace-desktop.png'), fullPage: true });
  await page.keyboard.press('Tab');
  check(
    'Skip link is the first keyboard stop',
    await page.locator('.skip-link').evaluate((element) => document.activeElement === element),
  );
  await page.keyboard.press('Enter');
  check(
    'Skip link transfers focus into main content',
    await page.evaluate(() => document.activeElement.id === 'main-content'),
  );
  await scan('default-review-desktop');
  const firstTab = '.workspace-tab[data-view="review"]';
  await page.locator(firstTab).focus();
  await page.keyboard.press('ArrowRight');
  check(
    'Right arrow changes the selected workspace tab',
    await page
      .locator('.workspace-tab[data-view="model"]')
      .evaluate(
        (element) => document.activeElement === element && element.getAttribute('aria-selected') === 'true',
      ),
  );
  await page.keyboard.press('End');
  check(
    'End moves to the last workspace tab',
    await page
      .locator('.workspace-tab[data-view="history"]')
      .evaluate((element) => document.activeElement === element),
  );
  await page.keyboard.press('Home');
  check(
    'Home returns to the first workspace tab',
    await page.locator(firstTab).evaluate((element) => document.activeElement === element),
  );
  await openByKeyboard('#switch-notice', '#queue-dialog');
  await scan('notice-queue-dialog');
  await closeByEscape('#switch-notice', '#queue-dialog');
  await openByKeyboard('#upload-button', '#upload-dialog');
  await scan('notice-upload-dialog');
  await closeByEscape('#upload-button', '#upload-dialog');
  await openByKeyboard('#export-button', '#export-dialog');
  await scan('notice-export-dialog');
  await closeByEscape('#export-button', '#export-dialog');
  const fieldTrigger = '.deadline-row .review-trigger';
  await page.locator(fieldTrigger).first().focus();
  await page.keyboard.press('Enter');
  await page.locator('#review-dialog').waitFor({ state: 'visible' });
  check(
    'Field review opens from the keyboard with focus inside',
    await page.evaluate(() => document.querySelector('#review-dialog').contains(document.activeElement)),
  );
  await scan('field-review-dialog');
  await page.keyboard.press('Escape');
  await page.locator('#review-dialog').waitFor({ state: 'hidden' });
  check(
    'Field review Escape restores its field trigger',
    await page
      .locator(fieldTrigger)
      .first()
      .evaluate((element) => document.activeElement === element),
  );
  await page.locator('.workspace-tab[data-view="model"]').click();
  await page.locator('#run-model-review').waitFor({ state: 'visible' });
  await scan('default-model-unconfigured');
  await page.locator(firstTab).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await scan('default-review-mobile');
  await page.setViewportSize({ width: 1440, height: 1100 });

  const config = await (await page.request.get(`${modelBase}/api/model`)).json();
  if (!/fixture/i.test(`${config.provider} ${config.model}`))
    throw new Error('The model accessibility workflow requires the owned offline fixture provider.');
  const modelNotices = await (await page.request.get(`${modelBase}/api/notices`)).json();
  const happy = modelNotices.notices.find((notice) => notice.notice_id === 'AST-PCN-2026-052');
  await page.goto(`${modelBase}/?notice=${happy.id}`, { waitUntil: 'networkidle' });
  await page.locator('.workspace-tab[data-view="model"]').click();
  await page.locator('#run-model-review').waitFor({ state: 'visible' });
  const created = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' && /\/model-runs$/.test(new URL(response.url()).pathname),
  );
  await page.locator('#run-model-review').click();
  const run = await (await created).json();
  const candidate = `.model-run[data-run-id="${run.id}"] .proposal-card[data-candidate-index="0"]`;
  await page.locator(candidate).waitFor({ state: 'visible', timeout: 30000 });
  await scan('fixture-model-proposals-desktop');
  const accept = `${candidate} .proposal-actions .button.primary`;
  await openByKeyboard(accept, '#proposal-dialog');
  await scan('model-proposal-dialog');
  diagnosticChecks.push(
    await page.locator('#proposal-review-context > .proposal-evidence').evaluate((element) => {
      const style = getComputedStyle(element);
      const rectangle = element.getBoundingClientRect();
      const luminance = (color) => {
        const components = color
          .match(/[\d.]+/g)
          .slice(0, 3)
          .map(Number)
          .map((value) => {
            const channel = value / 255;
            return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
          });
        return components[0] * 0.2126 + components[1] * 0.7152 + components[2] * 0.0722;
      };
      const fore = luminance(style.color);
      const back = luminance(style.backgroundColor);
      const samples = [0.2, 0.5, 0.8]
        .flatMap((x) =>
          [0.2, 0.5, 0.8].map((y) =>
            document.elementFromPoint(
              rectangle.left + rectangle.width * x,
              rectangle.top + rectangle.height * y,
            ),
          ),
        )
        .map((node) => element === node || element.contains(node));
      return {
        name: 'Proposal evidence contrast and visible bounds',
        reason:
          'axe reports this native-dialog text as partially overlapping other elements; retained as incomplete in the raw report.',
        foreground: style.color,
        background: style.backgroundColor,
        contrast_ratio: Number(((Math.max(fore, back) + 0.05) / (Math.min(fore, back) + 0.05)).toFixed(2)),
        sampled_points_unobscured: samples.every(Boolean),
        sample_count: samples.length,
        screenshot: 'model-proposal-dialog.png',
      };
    }),
  );
  await closeByEscape(accept, '#proposal-dialog');
  await page.setViewportSize({ width: 390, height: 844 });
  await scan('fixture-model-proposals-mobile');
  const summary = {
    axe_version: axePackage.version,
    official_api_reference: 'https://github.com/dequelabs/axe-core/blob/develop/doc/API.md',
    standards: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'],
    limitation:
      'Automated rule scanning and scripted keyboard checks only; not a human screen-reader or component-engineer usability study.',
    base,
    modelBase,
    keyboardChecks,
    diagnosticChecks,
    scans: scans.map(({ name, violations, incomplete, pass_count }) => ({
      name,
      violation_count: violations.length,
      violating_nodes: violations.reduce((sum, rule) => sum + rule.nodes.length, 0),
      violations: violations.map((rule) => ({ id: rule.id, impact: rule.impact, nodes: rule.nodes.length })),
      incomplete_count: incomplete.length,
      pass_count,
    })),
    errors,
  };
  await writeFile(path.join(output, 'result.json'), JSON.stringify(summary, null, 2));
  console.log(JSON.stringify(summary));
  if (
    errors.length ||
    keyboardChecks.some((item) => !item.passed) ||
    scans.some((item) => item.violations.length)
  )
    process.exitCode = 1;
} finally {
  await browser.close();
}
