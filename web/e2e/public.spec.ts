import AxeBuilder from '@axe-core/playwright';
import {expect, test, type Page} from '@playwright/test';

const locales = ['en', 'hi-IN', 'pa-IN', 'te-IN', 'deccani-Latn'];
const widths = [320, 768, 1440];
const shots = process.env.SHOT_DIR;

async function noHorizontalOverflow(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, 'horizontal overflow (px)').toBeLessThanOrEqual(0);
}

async function seriousViolations(page: Page) {
  const results = await new AxeBuilder({page}).withTags(['wcag2a', 'wcag2aa']).analyze();
  return results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).slice(0, 3).join(' | ')}`);
}

for (const locale of locales) {
  test(`landing renders in ${locale} without overflow @a11y`, async ({page}) => {
    for (const width of widths) {
      await page.setViewportSize({width, height: 900});
      await page.goto(`/${locale}`);
      await expect(page.locator('html')).toHaveAttribute('lang', locale === 'deccani-Latn' ? 'dcc-Latn' : locale);
      await expect(page.getByRole('heading', {level: 1})).toBeVisible();
      await noHorizontalOverflow(page);
      if (shots) await page.screenshot({path: `${shots}/landing-${locale}-${width}.png`, fullPage: width !== 320});
    }
    // Audit the settled page: reduced motion skips entrance animations (no mid-fade contrast).
    await page.emulateMedia({reducedMotion: 'reduce'});
    await page.reload();
    await page.waitForLoadState('networkidle');
    expect(await seriousViolations(page)).toEqual([]);
  });

  for (const path of ['login', 'privacy']) {
    test(`${path} in ${locale} is accessible @a11y`, async ({page}) => {
      await page.setViewportSize({width: 375, height: 800});
      await page.goto(`/${locale}/${path}`);
      await noHorizontalOverflow(page);
      expect(await seriousViolations(page)).toEqual([]);
      if (shots) await page.screenshot({path: `${shots}/${path}-${locale}.png`, fullPage: true});
    });
  }
}

test('locale selector switches language and keeps the page', async ({page}) => {
  await page.goto('/en/privacy');
  await page.getByRole('combobox', {name: 'Language'}).first().selectOption('te-IN');
  await expect(page).toHaveURL(/\/te-IN\/privacy$/);
  await expect(page.getByRole('heading', {level: 1})).toHaveText('గోప్యతా విధానం');
});

test('browser language is detected on first visit', async ({browser}) => {
  const context = await browser.newContext({locale: 'hi-IN'});
  const page = await context.newPage();
  await page.goto('/');
  await expect(page).toHaveURL(/\/hi-IN$/);
  await context.close();
});

test('student app requires sign-in', async ({page}) => {
  await page.goto('/pa-IN/app');
  await expect(page).toHaveURL(/\/pa-IN\/login\?next=%2Fpa-IN%2Fapp/);
});

test('sign-up cannot proceed without accepting the Privacy Policy', async ({page}) => {
  let authCalls = 0;
  page.on('request', (request) => { if (request.url().includes('/auth/v1/signup')) authCalls += 1; });
  await page.goto('/en/login?mode=signup');
  await page.getByLabel('Email').fill('nobody@example.com');
  await page.getByLabel('Password').fill('correct-horse-9');
  await page.getByRole('button', {name: 'Create account'}).click();
  // The required checkbox blocks submission natively; nothing reaches Supabase.
  expect(authCalls).toBe(0);
  await expect(page.getByRole('checkbox')).not.toBeChecked();
});

test('FAQ accordion and mobile menu work by keyboard', async ({page}) => {
  await page.setViewportSize({width: 375, height: 800});
  await page.goto('/en');
  await page.getByRole('button', {name: 'Menu'}).click();
  await expect(page.getByRole('navigation', {name: 'Mobile'})).toBeVisible();
  await page.getByRole('navigation', {name: 'Mobile'}).getByRole('link', {name: 'FAQ'}).click();
  const question = page.getByRole('button', {name: 'Which files can I upload?'});
  await question.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByText('including scanned PDFs')).toBeVisible();
});

test('BFF rejects unknown routes before reaching the API', async ({request}) => {
  const response = await request.get('/api/bff/admin/users');
  expect(response.status()).toBe(404);
  expect((await response.json()).error.code).toBe('NOT_FOUND');
});
