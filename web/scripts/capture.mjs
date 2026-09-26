import { chromium } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

// 격리된 실수집 서버만 촬영하며 경보나 소스 상태를 합성하지 않는다.
const url = process.argv[2];
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(url ?? '')) throw new Error('Local server URL required');
const output = resolve('dist/promo');
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
try {
  for (const [name, width, height] of [['desktop', 1440, 1120], ['mobile', 390, 844]]) {
    const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(url);
    await page.locator('body[data-running="true"]').waitFor();
    await page.locator('.source-row').first().waitFor();
    await page.evaluate(() => document.fonts.ready);
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw new Error('Horizontal overflow');
    if (errors.length) throw new Error(errors.join('\n'));
    await page.screenshot({ path: resolve(output, `kwa-${name}.png`), fullPage: true });
    await page.close();
  }
  const status = await (await fetch(`${url}/api/v1/status`)).json();
  await writeFile(resolve(output, 'capture.json'), JSON.stringify({ captured_at: new Date().toISOString(), synthetic: false, status }, null, 2));
  console.log('Real-data screenshots saved: dist/promo/kwa-desktop.png, kwa-mobile.png');
} finally {
  await browser.close();
}
