import {test, expect} from '@playwright/test';

test('real API status, reference UI and mobile layout', async ({page}) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.locator('h1')).toHaveText('한국 전쟁 경보기');
  await expect(page.locator('#level')).toHaveText('INFO');
  await expect(page.locator('#connection')).toContainText('Core 응답 지연');
  await expect(page.locator('#incidents')).toContainText('관측된 활성 사건 없음');
  await expect(page.locator('#coverage')).toContainText('CRITICAL·사이렌 조건 충족 불가');
  await page.setViewportSize({width: 390, height: 844});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});

test('API outage is visible', async ({page}) => {
  await page.route('**/api/**', route => route.abort());
  await page.goto('/');
  await expect(page.locator('#connection')).toContainText(/연결 끊김|재시도/);
});
