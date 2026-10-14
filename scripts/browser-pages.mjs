import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import path from 'node:path';
import { chromium } from 'playwright';
import axe from 'axe-core';

function argument(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] : undefined;
}

let base = argument('--base');
let server;
if (!base) {
  const assets = new Map([
    ['', ['index.html', 'text/html']],
    ['index.html', ['index.html', 'text/html']],
    ['style.css', ['style.css', 'text/css']],
    ['favicon.svg', ['favicon.svg', 'image/svg+xml']],
    ['assets/review.png', ['assets/review.png', 'image/png']],
  ]);
  server = createServer(async (request, response) => {
    const pathname = new URL(request.url, 'http://localhost').pathname;
    const asset = pathname.startsWith('/noticeforge/') && assets.get(pathname.slice('/noticeforge/'.length));
    if (!asset) return response.writeHead(404).end();
    try {
      const content = await readFile(path.resolve('site', asset[0]));
      response.writeHead(200, { 'Content-Type': asset[1] }).end(content);
    } catch {
      response.writeHead(500).end();
    }
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  base = `http://127.0.0.1:${server.address().port}/noticeforge/`;
}
const output = path.resolve(argument('--output') || 'reports/pages');
await mkdir(output, { recursive: true });
let browser;
const errors = [];
const viewports = [];
try {
  browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH || '/usr/bin/google-chrome',
    headless: true,
  });
  const page = await browser.newPage();
  page.on('pageerror', (error) => errors.push(String(error)));
  page.on('requestfailed', (request) => errors.push(`${request.url()}: ${request.failure()?.errorText}`));
  page.on('response', (response) => {
    if (response.status() >= 400) errors.push(`${response.status()}: ${response.url()}`);
  });
  await page.goto(base, { waitUntil: 'networkidle' });
  assert.match(await page.title(), /NoticeForge/);
  assert.match(await page.locator('.scope').innerText(), /project overview/);
  for (const width of [1440, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 1000 });
    const layout = await page.evaluate(() => ({
      width: innerWidth,
      scrollWidth: document.documentElement.scrollWidth,
      imagesLoaded: [...document.images].every((image) => image.complete && image.naturalWidth > 0),
      overflowingElements: [...document.querySelectorAll('body *')]
        .filter((element) => element.getBoundingClientRect().right > innerWidth + 1)
        .map((element) => `${element.tagName}.${element.className}`),
    }));
    assert.equal(layout.scrollWidth, width, `Page overflows at ${width}px: ${layout.overflowingElements}`);
    assert.ok(layout.imagesLoaded, 'Workspace screenshot loads');
    await page.addScriptTag({ content: axe.source });
    const accessibility = await page.evaluate(async () => {
      const result = await axe.run(document, { runOnly: ['wcag2a', 'wcag2aa', 'wcag21aa'] });
      return { violations: result.violations, incomplete: result.incomplete };
    });
    assert.equal(accessibility.violations.length, 0, JSON.stringify(accessibility.violations));
    viewports.push({ ...layout, accessibility });
    if (width === 1440 || width === 390) {
      await page.screenshot({ path: path.join(output, `${width}.png`), fullPage: true });
    }
  }
  await page.getByRole('link', { name: 'Run it locally' }).click();
  assert.equal(new URL(page.url()).hash, '#start');
  assert.ok(await page.getByRole('heading', { name: 'A working demo. On your machine.' }).isVisible());
  assert.deepEqual(errors, []);
  await writeFile(path.join(output, 'result.json'), JSON.stringify({ base, viewports, errors }, null, 2));
  console.log(JSON.stringify({ base, widths: viewports.map((view) => view.width), errors }));
} finally {
  await browser?.close();
  if (server) await new Promise((resolve) => server.close(resolve));
}
