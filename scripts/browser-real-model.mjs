/** Actual local pretrained inference through the browser/API/persisted queue.
 * Start an isolated server with the optional ML interpreter and local model profile.
 * node scripts/browser-qa.mjs --real-model --base http://127.0.0.1:8876
 * This verifies integration, including honest model failure; it is not a quality benchmark.
 */
import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

function argument(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : undefined;
}
const base = argument('--base') || 'http://127.0.0.1:8876';
const output = path.resolve(argument('--output') || 'reports/browser-real-model');
await mkdir(output, { recursive: true });
const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH || '/usr/bin/google-chrome',
  headless: true,
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 1 });
const checks = [];
const errors = [];
let requests = 0;
page.on('pageerror', (error) => errors.push(String(error)));
page.on('request', (request) => {
  if (request.method() === 'POST' && /\/model-runs$/.test(new URL(request.url()).pathname)) requests++;
});
function check(name, passed) {
  if (!passed) throw new Error(name);
  checks.push(name);
}
async function get(relative) {
  const response = await page.request.get(base + relative);
  if (!response.ok()) throw new Error(`Read failed: ${relative} HTTP ${response.status()}`);
  return response.json();
}
try {
  const config = await get('/api/model');
  check(
    'Actual local Transformers provider is configured, available and nonremote',
    config.provider === 'local-transformers' && config.available && !config.remote,
  );
  const notices = await get('/api/notices');
  const selected = notices.notices.find((notice) => notice.notice_id === 'AST-PCN-2026-052');
  if (!selected) throw new Error('Run the isolated seeded demonstration before this integration check.');
  const noticePath = `/api/notices/${selected.id}`;
  const before = await get(noticePath);
  await page.goto(`${base}/?notice=${selected.id}`, { waitUntil: 'networkidle' });
  await page.locator('.workspace-tab[data-view="model"]').click();
  await page.waitForFunction(
    () =>
      document.querySelector('#run-model-review') && !document.querySelector('#run-model-review').disabled,
  );
  check('Opening the actual-model view does not invoke inference', requests === 0);
  const created = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' && /\/model-runs$/.test(new URL(response.url()).pathname),
  );
  await page.locator('#run-model-review').click();
  const response = await created;
  const queued = await response.json();
  check(
    'Explicit browser request creates an asynchronous model run',
    response.status() === 202 && ['queued', 'running'].includes(queued.status),
  );
  const started = Date.now();
  let run;
  do {
    run = (await get(noticePath + '/model-runs')).runs.find((item) => item.id === queued.id);
    if (run && !['queued', 'running'].includes(run.status)) break;
    if (Date.now() - started > 240000)
      throw new Error('Actual model integration did not complete within 240 seconds.');
    await new Promise((resolve) => setTimeout(resolve, 1000));
  } while (true);
  await writeFile(path.join(output, 'run.json'), JSON.stringify(run, null, 2));
  check(
    'Actual model generated tokens and retained its output hash',
    run.result?.usage?.output_tokens > 0 && run.result.output_sha256?.length === 64,
  );
  check(
    'Provider and pretrained revision provenance persist',
    run.provider === 'local-transformers' &&
      run.configuration.revision?.length === 40 &&
      run.configuration.configuration_sha256?.length === 64,
  );
  const after = await get(noticePath);
  check(
    'Actual inference leaves canonical facts and review version unchanged',
    JSON.stringify(after) === JSON.stringify(before),
  );
  check('Only one explicitly requested model inference occurred', requests === 1);
  await page.reload({ waitUntil: 'networkidle' });
  await page.locator('.workspace-tab[data-view="model"]').click();
  const runNode = page.locator(`.model-run[data-run-id="${run.id}"]`);
  await runNode.waitFor({ state: 'visible' });
  if (run.result.candidates.length) {
    check(
      'All usable proposals are presented for a human decision',
      (await runNode.locator('.proposal-card').count()) === run.result.candidates.length,
    );
  } else {
    check(
      'No usable output produces an explicit failure or empty explanation',
      (await runNode.locator('.form-error,.model-no-candidates').count()) > 0,
    );
  }
  check(
    'Actual model run is not labelled as an offline fixture',
    (await runNode.locator('.model-fixture-note').count()) === 0,
  );
  await page.screenshot({ path: path.join(output, 'actual-model-result.png'), fullPage: true });
  const exported = await get(noticePath + '/export');
  check(
    'Canonical JSON export remains intact after the model result',
    JSON.stringify(exported) === JSON.stringify(after),
  );
  const xml = await page.request.get(base + noticePath + '/export?format=smartpcn');
  check('The supported deterministic fixture remains exportable', xml.ok());
  await writeFile(path.join(output, 'record.json'), JSON.stringify(after, null, 2));
  await writeFile(path.join(output, 'record.xml'), await xml.body());
  const audit = await get(noticePath + '/audit');
  await writeFile(path.join(output, 'audit.json'), JSON.stringify(audit, null, 2));
  check(
    'Request and completion are recorded in history',
    ['model_requested', 'model_completed'].every((action) =>
      audit.events.some((event) => event.action === action),
    ),
  );
  check('No unexpected browser errors occurred', errors.length === 0);
  const report = {
    purpose:
      'Actual pretrained model browser/API/persistence integration on an owned development fixture; not extraction-quality evidence',
    base,
    config,
    checks,
    errors,
    run_id: run.id,
    model_status: run.status,
    validated_candidates: run.result.candidates.length,
    rejected_candidates: run.result.rejected.length,
    usage: run.result.usage,
    elapsed_seconds: (Date.now() - started) / 1000,
    canonical_unchanged: true,
    fixture_provider: false,
  };
  await writeFile(path.join(output, 'result.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report));
} finally {
  await browser.close();
}
