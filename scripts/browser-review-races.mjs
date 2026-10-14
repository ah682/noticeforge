import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';

function argument(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : undefined;
}
const base = argument('--base') || process.env.NOTICEFORGE_URL || 'http://127.0.0.1:8877';
const output = path.resolve(argument('--output') || 'reports/browser-races');
await mkdir(output, { recursive: true });
const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH || '/usr/bin/google-chrome',
  headless: true,
});
const results = [];
const firstNotice = 'AST-PDN-2026-041';
const secondNotice = 'BRS-PDN-2026-018';

async function switchNotice(page, notice) {
  await page.locator('#switch-notice').click();
  await page.locator('#queue-search').fill(notice);
  const response = page.waitForResponse(
    (res) => /\/api\/notices\/[^/]+$/.test(new URL(res.url()).pathname) && res.request().method() === 'GET',
  );
  await page.locator('#queue-list .queue-item').first().click();
  await response;
  await page.waitForFunction((value) => document.querySelector('#notice-id').textContent === value, notice);
  await page.locator('#queue-dialog').waitFor({ state: 'hidden' });
}

function delayNext(page, pattern, error = false) {
  let started, release, completed;
  const requested = new Promise((resolve) => {
    started = resolve;
  });
  const released = new Promise((resolve) => {
    release = resolve;
  });
  const done = new Promise((resolve) => {
    completed = resolve;
  });
  const registered = page.route(
    pattern,
    async (route) => {
      const response = error ? null : await route.fetch();
      started();
      await released;
      const delivered = page.waitForResponse(
        (result) => result.url() === route.request().url() && result.request().method() === 'POST',
      );
      if (error)
        await route.fulfill({
          status: 409,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Deliberately delayed stale request error' }),
        });
      else await route.fulfill({ response });
      await (await delivered).finished();
      await page.evaluate(
        () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))),
      );
      completed();
    },
    { times: 1 },
  );
  return { registered, requested, release, done };
}

async function run(name, test) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  const errors = [];
  page.on('pageerror', (error) => errors.push(String(error)));
  try {
    await page.goto(base, { waitUntil: 'networkidle' });
    await page.locator('#notice-content').waitFor({ state: 'visible' });
    if ((await page.locator('#notice-id').innerText()) !== firstNotice) await switchNotice(page, firstNotice);
    await test(page);
    assert.deepEqual(errors, [], 'No uncaught application errors');
    results.push({ name, passed: true });
  } catch (error) {
    results.push({ name, passed: false, error: String(error), pageErrors: errors });
    await page.screenshot({ path: path.join(output, `${results.length}-failure.png`), fullPage: true });
  } finally {
    await page.close();
  }
}

async function startBOM(page) {
  await page.locator('.workspace-tab[data-view="bom"]').click();
  await page.locator('#bom-input').fill('part_number,manufacturer\n00128-Q1,Aster Semiconductor');
  await page.locator('#bom-form button[type="submit"]').click();
}

try {
  for (const error of [false, true]) {
    await run(`BOM late ${error ? 'error' : 'result'} stays with its original notice`, async (page) => {
      const delayed = delayNext(page, '**/api/notices/*/bom', error);
      await delayed.registered;
      await startBOM(page);
      await delayed.requested;
      await switchNotice(page, secondNotice);
      delayed.release();
      await delayed.done;
      await page.waitForFunction(() => !document.querySelector('#bom-form button[type="submit"]').disabled);
      assert.equal(await page.locator('#notice-id').innerText(), secondNotice);
      assert.equal(
        await page.locator('.bom-match').count(),
        0,
        'Old matches must not populate another notice',
      );
      assert.equal(
        await page.locator('#bom-error').isVisible(),
        false,
        'Old errors must not populate another notice',
      );
    });
  }
  await run('Reloading the same notice invalidates its earlier BOM request', async (page) => {
    const delayed = delayNext(page, '**/api/notices/*/bom');
    await delayed.registered;
    await startBOM(page);
    await delayed.requested;
    await switchNotice(page, firstNotice);
    delayed.release();
    await delayed.done;
    await page.waitForFunction(() => !document.querySelector('#bom-form button[type="submit"]').disabled);
    assert.equal(await page.locator('.bom-match').count(), 0);
    assert.equal(await page.locator('#bom-result-summary').innerText(), 'Awaiting input');
  });
  await run('A newer BOM submission keeps its results when an earlier request completes', async (page) => {
    const delayed = delayNext(page, '**/api/notices/*/bom');
    await delayed.registered;
    await startBOM(page);
    await delayed.requested;
    await page.locator('#bom-input').fill('part_number,manufacturer\nNEWER-UNMATCHED,Aster Semiconductor');
    await page.locator('#bom-form').evaluate((form) => form.requestSubmit());
    await page.waitForFunction(() =>
      document.querySelector('#bom-results').textContent.includes('NEWER-UNMATCHED'),
    );
    delayed.release();
    await delayed.done;
    await page.waitForFunction(() => !document.querySelector('#bom-form button[type="submit"]').disabled);
    assert.match(await page.locator('#bom-results').innerText(), /NEWER-UNMATCHED/);
    assert.doesNotMatch(await page.locator('#bom-results').innerText(), /00128-Q1/);
  });
  for (const error of [false, true]) {
    for (const close of ['escape', 'button', 'reload']) {
      await run(
        `Review late ${error ? 'error' : 'save'} after ${close} stays with its original notice`,
        async (page) => {
          const delayed = delayNext(page, '**/api/notices/*/reviews', error);
          await delayed.registered;
          await page.locator('[data-field="parts.0.raw_identifier"]').click();
          await page.locator('#selected-review').click();
          await page
            .locator('#review-reason')
            .fill('Owned browser race regression confirms the literal source identifier.');
          await page.locator('#reviewer-name').fill('Browser race QA');
          await page.locator('#review-submit').click();
          await delayed.requested;
          if (close !== 'button') await page.keyboard.press('Escape');
          else await page.locator('#review-dialog [data-close="review-dialog"]').first().click();
          await page.locator('#review-dialog').waitFor({ state: 'hidden' });
          const nextNotice = close === 'reload' ? firstNotice : secondNotice;
          await switchNotice(page, nextNotice);
          await page.locator('[data-field="parts.0.raw_identifier"]').click();
          await page.locator('#selected-review').click();
          const currentValue = await page.locator('#review-original-value').innerText();
          delayed.release();
          await delayed.done;
          await page.waitForFunction(() => !document.querySelector('#review-submit').disabled);
          assert.equal(await page.locator('#notice-id').innerText(), nextNotice);
          assert.equal(
            await page.locator('#review-dialog').isVisible(),
            true,
            'Old save must not close the new review',
          );
          assert.equal(await page.locator('#review-original-value').innerText(), currentValue);
          assert.equal(await page.locator('#review-error').isVisible(), false);
        },
      );
    }
  }
} finally {
  await browser.close();
  const report = {
    base,
    boundary:
      'Real API and rendered UI; selected response delivery deliberately delayed. Error responses explicitly mocked as 409.',
    results,
  };
  await writeFile(path.join(output, 'result.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  if (results.some((result) => !result.passed)) process.exitCode = 1;
}
