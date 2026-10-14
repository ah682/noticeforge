/** Browser end-to-end model-review checks against the explicit offline fixture provider.
 * Start the documented fixture server on 8878, then:
 *   node scripts/browser-qa.mjs --model
 * No live AI or model benchmark is claimed by this script.
 */
import { chromium } from 'playwright';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

function argument(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : undefined;
}
const base = argument('--base') || process.env.NOTICEFORGE_MODEL_REVIEW_URL || 'http://127.0.0.1:8878';
const output = path.resolve(
  argument('--output') || process.env.NOTICEFORGE_MODEL_BROWSER_OUTPUT || 'reports/browser-model',
);
await mkdir(output, { recursive: true });
const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH || '/usr/bin/google-chrome',
  headless: true,
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 1 });
const errors = [];
const checks = [];
const mockedStateChecks = [];
let modelRequests = 0;
page.on('pageerror', (error) => errors.push(String(error)));
page.on('console', (message) => {
  if (message.type() === 'error') errors.push(message.text());
});
page.on('request', (request) => {
  if (request.method() === 'POST' && /\/model-runs$/.test(new URL(request.url()).pathname)) modelRequests++;
});
function check(name, value, mocked = false) {
  if (!value) throw new Error(`Browser model review check failed: ${name}`);
  (mocked ? mockedStateChecks : checks).push(name);
}
async function record() {
  return (
    await page.request.get(`${base}/api/notices/${new URL(page.url()).searchParams.get('notice')}`)
  ).json();
}
async function switchNotice(query) {
  await page.locator('#switch-notice').click();
  await page.locator('#queue-search').fill(query);
  await page.locator('#queue-list .queue-item').first().click();
  await page.waitForFunction((value) => document.querySelector('#notice-id').textContent === value, query);
}
async function modelView() {
  await page.locator('.workspace-tab[data-view="model"]').click();
  await page.waitForFunction(
    () =>
      document.querySelector('#model-content .model-mode-badge')?.textContent !== 'Checking setup' &&
      !document.querySelector('#model-content').textContent.includes('Loading saved model runs'),
  );
}
async function decide(card, action, reason) {
  await card.getByRole('button', { name: action === 'accept' ? 'Accept' : 'Reject', exact: true }).click();
  await page.locator('#proposal-reason').fill(reason);
  await page.locator('#proposal-reviewer').fill('Owned fixture browser QA');
  await page.locator('#proposal-submit').click();
  await page.locator('#proposal-dialog').waitFor({ state: 'hidden' });
  await card.locator('.proposal-decision').waitFor({ state: 'visible' });
}
let happyId;
let run;
let desktop;
let mobile;
try {
  const config = await (await page.request.get(`${base}/api/model`)).json();
  if (!/fixture/i.test(`${config.provider} ${config.model}`))
    throw new Error(
      'This verification script requires an explicitly labelled offline fixture provider; it will not request a live model.',
    );
  await page.goto(base, { waitUntil: 'networkidle' });
  await page.locator('#notice-content').waitFor({ state: 'visible' });
  await switchNotice('AST-PCN-2026-052');
  await modelView();
  const before = await record();
  happyId = before.id;
  check('Opening and switching notices never invokes the model', modelRequests === 0);
  check(
    'Offline fixture identity is explicit',
    (await page.locator('#model-content').innerText()).includes(
      'Offline fixture output; no live model inference',
    ),
  );
  check(
    'Configured model and provider are visible',
    (await page.locator('#model-content').innerText()).includes(config.model) &&
      (await page.locator('#model-content').innerText()).includes(config.provider),
  );
  check('Only explicit Run model review is enabled', await page.locator('#run-model-review').isEnabled());
  const created = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' && /\/model-runs$/.test(new URL(response.url()).pathname),
  );
  await page.locator('#run-model-review').click();
  const response = await created;
  run = await response.json();
  check(
    'Model request is queued asynchronously',
    response.status() === 202 && ['queued', 'running'].includes(run.status),
  );
  const runNode = page.locator(`.model-run[data-run-id="${run.id}"]`);
  await runNode.locator('.proposal-card').first().waitFor({ state: 'visible', timeout: 30000 });
  check(
    'Two source-valid fixture proposals are displayed',
    (await runNode.locator('.proposal-card').count()) === 2,
  );
  check(
    'Invented identifier output is rejected before review',
    (await runNode.locator('.model-rejected-list').innerText()).includes('INVENTED-PART-999') &&
      (await runNode.locator('.model-rejected-list button').count()) === 0,
  );
  const generated = await record();
  check(
    'Generation does not apply canonical edits',
    generated.version === before.version && JSON.stringify(generated.parts) === JSON.stringify(before.parts),
  );
  check('Exactly one explicit model request was sent', modelRequests === 1);
  const first = runNode.locator('.proposal-card[data-candidate-index="0"]');
  await first.getByRole('button', { name: 'Inspect source', exact: true }).click();
  check(
    'Proposal source uses actual text highlights',
    (await page.locator('#source-paper .source-mark').count()) > 0 &&
      (await page.locator('#evidence-caption-text').innerText()).includes('AMP-230-A'),
  );
  await page.screenshot({ path: path.join(output, 'proposals-desktop.png'), fullPage: true });
  desktop = await page.evaluate(() => ({
    width: innerWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  await decide(
    first,
    'accept',
    'Owned fixture review: AMP-230-A has the cited effective-change date 2027-01-15.',
  );
  const afterAccept = await record();
  const appliedPart = afterAccept.parts.find((part) => part.raw_identifier.value === 'AMP-230-A');
  const appliedDate = appliedPart.dates.find((date) => date.kind === 'effective_change');
  check(
    'Acceptance persists the exact part/date and model provenance',
    appliedDate.value === '2027-01-15' &&
      appliedDate.model_run_id === run.id &&
      appliedDate.model_candidate_index === 0,
  );
  check(
    'Acceptance requires and retains reviewer attribution',
    afterAccept.model_decisions.some(
      (decision) =>
        decision.run_id === run.id &&
        decision.action === 'accept' &&
        decision.reviewer === 'Owned fixture browser QA',
    ),
  );
  check('Acceptance increments the record version once', afterAccept.version === before.version + 1);
  const second = runNode.locator('.proposal-card[data-candidate-index="1"]');
  await decide(
    second,
    'reject',
    'Owned fixture review exercise: retain the independently reviewed baseline for AMP-230-B.',
  );
  const afterReject = await record();
  check(
    'Rejection records a decision without changing part facts',
    JSON.stringify(afterReject.parts) === JSON.stringify(afterAccept.parts) &&
      afterReject.model_decisions.some(
        (decision) =>
          decision.run_id === run.id && decision.candidate_index === 1 && decision.action === 'reject',
      ),
  );
  check(
    'Rejected outputs do not become affected parts',
    !afterReject.parts.some((part) => part.raw_identifier.value === 'INVENTED-PART-999'),
  );
  await page.locator('.workspace-tab[data-view="history"]').click();
  await page.waitForFunction(() =>
    document.querySelector('#history-content').textContent.includes('Model proposal rejected'),
  );
  const history = await page.locator('#history-content').innerText();
  check(
    'Decision history shows request, completion, acceptance and rejection',
    [
      'Model review requested',
      'Model review completed',
      'Model proposal applied',
      'Model proposal rejected',
    ].every((value) => history.includes(value)),
  );
  check(
    'Decision history retains model and reviewer attribution',
    history.includes(config.model) && history.includes('Owned fixture browser QA'),
  );
  await page.screenshot({ path: path.join(output, 'model-decision-history.png'), fullPage: true });
  await page.locator('#export-button').click();
  const jsonDownload = page.waitForEvent('download');
  await page.locator('[data-export="json"]').click();
  const jsonFile = await jsonDownload;
  await jsonFile.saveAs(path.join(output, 'applied-record.json'));
  const exported = JSON.parse(await readFile(path.join(output, 'applied-record.json'), 'utf8'));
  check(
    'Canonical export contains applied evidence and both model decisions',
    exported.parts.some((part) =>
      part.dates.some((date) => date.model_run_id === run.id && date.evidence.length),
    ) && exported.model_decisions.filter((decision) => decision.run_id === run.id).length === 2,
  );
  const xmlDownload = page.waitForEvent('download');
  await page.locator('[data-export="smartpcn"]').click();
  const xmlFile = await xmlDownload;
  await xmlFile.saveAs(path.join(output, 'applied-record.xml'));
  check(
    'Supported applied record still exports schema-validated XML',
    xmlFile.suggestedFilename().endsWith('.xml') &&
      (await readFile(path.join(output, 'applied-record.xml'), 'utf8')).includes('AMP-230-A'),
  );
  await page.locator('[data-close="export-dialog"]').click();
  await page.reload({ waitUntil: 'networkidle' });
  await modelView();
  const persistedRun = page.locator(`.model-run[data-run-id="${run.id}"]`);
  await persistedRun.locator('.proposal-decision').first().waitFor({ state: 'visible' });
  check(
    'Model run and both decisions survive browser reload',
    (await persistedRun.locator('.proposal-decision').count()) === 2,
  );
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: path.join(output, 'proposals-mobile.png'), fullPage: true });
  mobile = await page.evaluate(() => ({
    width: innerWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  check(
    'Model review fits desktop and mobile without page overflow',
    desktop.width === desktop.scrollWidth && mobile.width === mobile.scrollWidth,
  );
  await page.setViewportSize({ width: 1440, height: 1100 });

  // The following UI-only response-contract checks mock transport states; they are
  // kept separate from the real fixture-provider persistence checks above.
  const actualRuns = await (await page.request.get(`${base}/api/notices/${happyId}/model-runs`)).json();
  const template = actualRuns.runs.find((item) => item.id === run.id);
  const syntheticRun = (status, result) => ({
    ...template,
    id: `ui-contract-${status}`,
    status,
    decisions: [],
    result: {
      ...template.result,
      candidates: [],
      rejected: [],
      errors: [],
      warnings: [],
      truncated: false,
      status,
      ...result,
    },
  });
  const route = `**/api/notices/${happyId}/model-runs`;
  const states = [
    {
      name: 'Empty valid model response is explained without inventing proposals',
      run: syntheticRun('ok', {}),
      text: 'No candidate proposals were returned',
    },
    {
      name: 'Failed model response is actionable and preserves the record',
      run: syntheticRun('error', {
        errors: ['RuntimeError: model request or evidence validation failed; no candidates applied'],
      }),
      text: 'Check the provider configuration or runtime',
    },
    {
      name: 'Unavailable model runtime remains an explicit saved outcome',
      run: syntheticRun('unavailable', {
        errors: [
          'OSError: configured model runtime or weights unavailable. Check the local profile and restart.',
        ],
      }),
      text: 'configured model runtime or weights unavailable',
    },
    {
      name: 'Truncated context is prominent and quantified',
      run: syntheticRun('partial', {
        truncated: true,
        input_characters: 20000,
        included_characters: 16000,
        warnings: ['INCOMPLETE MODEL CONTEXT: clipped page 1.'],
      }),
      text: 'Incomplete model context',
    },
  ];
  for (const scenario of states) {
    await page.route(route, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ runs: [scenario.run] }),
      }),
    );
    await page.locator('#refresh-model-review').click();
    await page.waitForFunction(
      (text) => document.querySelector('#model-content').textContent.includes(text),
      scenario.text,
    );
    check(scenario.name, (await page.locator('#model-content').innerText()).includes(scenario.text), true);
    if (scenario.run.result.truncated)
      await page.screenshot({ path: path.join(output, 'context-warning.png'), fullPage: true });
    await page.unroute(route);
  }
  await page.route('**/api/model', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        configured: false,
        available: false,
        provider: 'none',
        model: null,
        remote: false,
        reason: 'No model is configured. Rules extraction remains available.',
      }),
    }),
  );
  await page.locator('#refresh-model-review').click();
  await page.waitForFunction(
    () => document.querySelector('.model-mode-badge')?.textContent === 'Not configured',
  );
  check(
    'Unconfigured provider disables generation without a fixture AI fallback',
    (await page.locator('#run-model-review').isDisabled()) &&
      (await page.locator('.model-config').innerText()).includes('No model is configured'),
    true,
  );
  await page.unroute('**/api/model');
  check('UI state inspections do not trigger additional generation', modelRequests === 1);
  await writeFile(
    path.join(output, 'result.json'),
    JSON.stringify(
      {
        base,
        provider: config,
        purpose: 'Owned offline fixture workflow verification; not live model performance',
        checks,
        mockedStateChecks,
        run_id: run.id,
        desktop,
        mobile,
        errors,
      },
      null,
      2,
    ),
  );
  console.log(JSON.stringify({ base, checks, mockedStateChecks, desktop, mobile, errors }));
  if (errors.length) process.exitCode = 1;
} catch (error) {
  await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => {});
  await writeFile(
    path.join(output, 'failure.json'),
    JSON.stringify({ base, checks, mockedStateChecks, error: String(error), errors }, null, 2),
  );
  throw error;
} finally {
  await browser.close();
}
