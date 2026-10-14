import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

if (process.argv.includes('--pages')) {
  await import('./browser-pages.mjs');
  process.exit(process.exitCode || 0);
}

if (process.argv.includes('--races')) {
  await import('./browser-review-races.mjs');
  process.exit(process.exitCode || 0);
}

if (process.argv.includes('--model')) {
  await import('./browser-model-review.mjs');
  process.exit(process.exitCode || 0);
}
if (process.argv.includes('--a11y')) {
  await import('./browser-accessibility.mjs');
  process.exit(process.exitCode || 0);
}
if (process.argv.includes('--real-model')) {
  await import('./browser-real-model.mjs');
  process.exit(process.exitCode || 0);
}

function argument(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : undefined;
}
const base = argument('--base') || process.env.NOTICEFORGE_URL || 'http://127.0.0.1:8877';
const output = path.resolve(
  argument('--output') || process.env.NOTICEFORGE_BROWSER_OUTPUT || 'reports/browser',
);
await mkdir(output, { recursive: true });
const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH || '/usr/bin/google-chrome',
  headless: true,
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 1 });
const errors = [];
const expectedHttpFailures = [];
const checks = [];
page.on('pageerror', (error) => errors.push(String(error)));
page.on('console', (message) => {
  if (message.type() !== 'error') return;
  if (/Failed to load resource.*(?:400|422)/.test(message.text())) expectedHttpFailures.push(message.text());
  else errors.push(message.text());
});
function check(name, okay) {
  if (!okay) throw new Error(`Browser check failed: ${name}`);
  checks.push(name);
}
async function switchNotice(query) {
  await page.locator('#switch-notice').click();
  await page.locator('#queue-search').fill(query);
  await page.locator('#queue-list .queue-item').first().click();
  await page.waitForFunction(
    (value) => document.querySelector('#notice-id').textContent.includes(value),
    query,
  );
}
try {
  await page.goto(base, { waitUntil: 'networkidle' });
  await page.locator('#notice-content').waitFor({ state: 'visible' });
  await page
    .locator('.incoming-revision,.revision-note,.revision-context')
    .first()
    .waitFor({ state: 'visible', timeout: 2000 })
    .catch(() => {});
  check(
    'Primary fixture has six exact parts',
    (await page.locator('#notice-part-count').innerText()) === '6 parts',
  );
  check(
    'Only one relevant primary review item',
    (await page.locator('#notice-review-count').innerText()) === '1 to review',
  );
  check(
    'Subset revision visible',
    (await page.locator('#records-content').innerText()).includes('5 original part records'),
  );
  await page.locator('[data-field="parts.3.dates.2"]').click();
  check(
    'Evidence selection follows exact part',
    (await page.locator('#evidence-caption-text').innerText()).includes('NX-4100-B'),
  );
  check('PDF evidence region drawn', (await page.locator('.pdf-highlight').count()) > 0);
  await page.locator('#zoom-in').click();
  check('PDF zoom works', (await page.locator('#zoom-fit').innerText()) === '125%');
  check(
    'Zoom remains inside pane',
    await page.evaluate(() => document.documentElement.scrollWidth === innerWidth),
  );
  await page.locator('#zoom-fit').click();
  await page.screenshot({ path: path.join(output, 'desktop.png'), fullPage: true });
  const desktop = await page.evaluate(() => ({
    title: document.title,
    width: innerWidth,
    scrollWidth: document.documentElement.scrollWidth,
    body: document.body.innerText,
  }));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: path.join(output, 'mobile.png'), fullPage: true });
  const mobile = await page.evaluate(() => ({
    width: innerWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.locator('.workspace-tab[data-view="model"]').click();
  await page.waitForFunction(
    () =>
      document.querySelector('#run-model-review') &&
      !document.querySelector('#model-content').textContent.includes('Checking the provider'),
  );
  const providerConfiguration = await (await page.request.get(`${base}/api/model`)).json();
  if (!providerConfiguration.configured) {
    check(
      'Default model review is explicitly unconfigured',
      (await page.locator('#model-content').innerText()).toLowerCase().includes('not configured'),
    );
    check(
      'Default model run is unavailable without setup',
      await page.locator('#run-model-review').isDisabled(),
    );
  }
  await page.locator('.workspace-tab[data-view="bom"]').click();
  await page
    .locator('#bom-input')
    .fill('part_number,manufacturer\n00128-Q1,Aster Semiconductor\n128-Q1,Aster Semiconductor\n00128-Q1,');
  await page.locator('#bom-form button[type="submit"]').click();
  await page.waitForFunction(() => document.querySelectorAll('.bom-match').length === 3);
  const bom = await page.locator('#bom-results').innerText();
  check(
    'BOM shows literal, ambiguous and unmatched results',
    ['Literal match', 'Ambiguous', 'Unmatched'].every((text) => bom.includes(text)),
  );
  await page.screenshot({ path: path.join(output, 'bom.png'), fullPage: true });
  await page.locator('.workspace-tab[data-view="review"]').click();
  await switchNotice('BRS-PDN-2026-018');
  await page.locator('[data-field="parts.0.dates.0"]').click();
  await page.locator('#selected-review').click();
  await page.locator('#review-reason').fill('Browser test checks an unresolved date cannot be accepted.');
  await page.locator('#reviewer-name').fill('Browser QA');
  await page.locator('#review-submit').click();
  await page.locator('#review-error').waitFor({ state: 'visible' });
  check(
    'Ambiguous date acceptance blocked with explanation',
    (await page.locator('#review-error').innerText()).includes('missing value'),
  );
  await page.locator('input[name="action"][value="correct"]').check();
  await page.locator('#corrected-value').fill('2027-04-03');
  await page
    .locator('#review-reason')
    .fill('Owned browser fixture: explicitly interpret source as day/month/year.');
  await page.locator('#review-submit').click();
  await page.locator('#review-dialog').waitFor({ state: 'hidden' });
  check(
    'Correction visible',
    (await page.locator('[data-field="parts.0.dates.0"]').innerText()).includes('3 Apr 2027'),
  );
  await page.locator('.workspace-tab[data-view="history"]').click();
  await page.waitForFunction(() =>
    document.querySelector('#history-content').textContent.includes('Field corrected'),
  );
  check(
    'Decision history preserves original',
    (await page.locator('#history-content').innerText()).includes('03/04/2027'),
  );
  await page.screenshot({ path: path.join(output, 'review-history.png'), fullPage: true });
  await page.locator('.workspace-tab[data-view="review"]').click();
  await switchNotice('AST-PCN-2026-052');
  await page.locator('#export-button').click();
  const download = page.waitForEvent('download');
  await page.locator('[data-export="smartpcn"]').click();
  const file = await download;
  await file.saveAs(path.join(output, 'browser-export.xml'));
  check('Valid smartPCN downloads', file.suggestedFilename().endsWith('.xml'));
  await page.locator('[data-close="export-dialog"]').click();
  await switchNotice('CRS-PDN-2026-009');
  check(
    'Incomplete coverage is prominent',
    (await page.locator('#records-content').innerText()).includes('Source coverage is incomplete'),
  );
  await page.locator('#export-button').click();
  await page.locator('[data-export="smartpcn"]').click();
  await page.locator('#export-error').waitFor({ state: 'visible' });
  check(
    'Incomplete XML export refused',
    (await page.locator('#export-error').innerText()).includes('incomplete'),
  );
  await page.locator('[data-close="export-dialog"]').click();
  await page.screenshot({ path: path.join(output, 'incomplete.png'), fullPage: true });
  await page.locator('#upload-button').click();
  await page
    .locator('#file-input')
    .setInputFiles({ name: 'invalid.pdf', mimeType: 'application/pdf', buffer: Buffer.from('not a PDF') });
  await page.locator('#upload-submit').click();
  await page.locator('#upload-error').waitFor({ state: 'visible' });
  check(
    'Malformed upload shows a useful error',
    (await page.locator('#upload-error').innerText()).includes('not a PDF'),
  );
  await page.locator('[data-close="upload-dialog"]').first().click();
  await page.locator('#upload-button').click();
  await page.locator('#file-input').setInputFiles({
    name: 'owned-browser-notice.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from(
      'Notice ID: QA-PDN-77\nSupplier: Owned Browser Fixture\nNotice type: PDN\nTitle: Browser import test\nIssue date: 2026-10-01\nPart number | Last buy\n000-QA-R | 2027-01-01\n<img src=x onerror=alert(1)>\nPage 1 of 1\n',
    ),
  });
  await page.locator('#upload-submit').click();
  await page.waitForFunction(() => document.querySelector('#notice-id').textContent === 'QA-PDN-77');
  check(
    'Valid notice upload renders extracted record',
    (await page.locator('#records-content').innerText()).includes('000-QA-R'),
  );
  check(
    'Uploaded markup is rendered as text',
    (await page.locator('#source-paper').innerText()).includes('<img src=x onerror=alert(1)>') &&
      (await page.locator('#source-paper img').count()) === 0,
  );
  await page.route('**/api/notices', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 800));
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{"notices":[]}' });
  });
  await page.goto(base, { waitUntil: 'domcontentloaded' });
  check('Loading state visible during pending request', await page.locator('#loading-state').isVisible());
  await page.locator('#empty-upload').waitFor({ state: 'visible' });
  check('Empty workspace is actionable', await page.locator('#empty-upload').isVisible());
  await page.unroute('**/api/notices');
  await page.route('**/api/notices', (route) => route.abort());
  await page.goto(base, { waitUntil: 'networkidle' });
  check(
    'Unavailable service shows retry',
    (await page.locator('#global-error').innerText()).includes('Try again'),
  );
  // Network abort is intentional and separately recorded; no app exception may occur.
  const unexpectedErrors = errors.filter((error) => !error.includes('net::ERR_FAILED'));
  await writeFile(
    path.join(output, 'result.json'),
    JSON.stringify(
      { base, desktop, mobile, checks, errors: unexpectedErrors, expectedHttpFailures },
      null,
      2,
    ),
  );
  console.log(
    JSON.stringify({
      base,
      checks,
      desktop: { title: desktop.title, width: desktop.width, scrollWidth: desktop.scrollWidth },
      mobile,
      errors: unexpectedErrors,
    }),
  );
  if (unexpectedErrors.length || desktop.scrollWidth > desktop.width || mobile.scrollWidth > mobile.width)
    process.exitCode = 1;
} finally {
  await browser.close();
}
