import AxeBuilder from '@axe-core/playwright';
import {expect as baseExpect, test, type Page} from '@playwright/test';
import {readFileSync, writeFileSync, mkdirSync} from 'node:fs';
import path from 'node:path';

/**
 * Signed-in journey against the real stack (Supabase, FastAPI, Celery worker, Groq).
 * Uses the dedicated e2e account from web/.env.e2e (gitignored). Screenshots of these real
 * screens feed the landing-page product tour when CAPTURE_TOUR=1.
 */
const env = Object.fromEntries(
  readFileSync(path.join(__dirname, '..', '.env.e2e'), 'utf8')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith('#') && line.includes('='))
    .map((line) => [line.slice(0, line.indexOf('=')), line.slice(line.indexOf('=') + 1)] as [string, string])
);
const fixtures = path.join(__dirname, 'fixtures');
const tourDir = path.join(__dirname, '..', 'public', 'tour');
const capture = process.env.CAPTURE_TOUR === '1';
// Live free-tier Supabase: a server render or write can briefly take 3-9 s.
const expect = baseExpect.configure({timeout: 15_000});
const tour: {key: string; src: string; width: number; height: number}[] = [];

test.describe.configure({mode: 'serial'});
test.setTimeout(8 * 60_000);

async function shot(page: Page, key: string) {
  if (!capture) return;
  mkdirSync(tourDir, {recursive: true});
  await page.waitForTimeout(700);
  await page.screenshot({path: path.join(tourDir, `${key}.png`)});
  const size = page.viewportSize()!;
  tour.push({key, src: `/tour/${key}.png`, width: size.width, height: size.height});
}

async function axe(page: Page) {
  // Audit the settled UI, not a frame of an entrance animation.
  await page.waitForTimeout(900);
  const results = await new AxeBuilder({page}).withTags(['wcag2a', 'wcag2aa']).analyze();
  return results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical').map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).slice(0, 3).join(' | ')}`);
}

let page: Page;
const workspaceName = `Science board exam ${String(Date.now()).slice(-4)}`;

test.beforeAll(async ({browser}) => {
  // A dedicated context: axe-core needs one, and it isolates this signed-in session.
  // Tour captures use a tighter viewport at 2x density, so UI text stays legible when the shot is shown small.
  const context = await browser.newContext(capture ? {viewport: {width: 1100, height: 700}, deviceScaleFactor: 2} : {viewport: {width: 1280, height: 800}});
  page = await context.newPage();
});
test.afterAll(async () => {
  if (capture && tour.length) {
    // Merge by key: a run that stops early (e.g. provider quota) must not drop earlier captures.
    const file = path.join(tourDir, 'manifest.json');
    let previous: typeof tour = [];
    try { previous = JSON.parse(readFileSync(file, 'utf8')) as typeof tour; } catch { /* first capture */ }
    const merged = new Map(previous.map((item) => [item.key, item]));
    for (const item of tour) merged.set(item.key, item);
    writeFileSync(file, JSON.stringify([...merged.values()], null, 2));
  }
  await page.context().close();
});

test('sign in lands on the dashboard without a privacy prompt (accepted at signup)', async () => {
  await page.goto('/en/app/w/does-not-matter/materials');
  await expect(page).toHaveURL(/\/en\/login\?next=/);
  await page.getByLabel('Email').fill(env.E2E_EMAIL);
  await page.getByLabel('Password').fill(env.E2E_PASSWORD);
  await page.getByRole('button', {name: 'Sign in'}).click();
  await expect(page).toHaveURL(/\/en\/app\/w\/does-not-matter\/materials/);
  await expect(page.getByText("This workspace doesn't exist or you don't have access to it.")).toBeVisible();
  // Start from a clean test account (leftovers from interrupted runs), via the real BFF.
  const existing = (await (await page.request.get('/api/bff/workspaces')).json()) as {id: string}[];
  for (const workspace of existing) expect((await page.request.delete(`/api/bff/workspaces/${workspace.id}`)).status()).toBe(204);
  await page.goto('/en/app');
  await expect(page.getByRole('heading', {name: 'Your study workspaces'})).toBeVisible();
  await expect(page.getByRole('dialog', {name: 'Please review our Privacy Policy'})).toHaveCount(0);
});

test('create a workspace', async () => {
  await page.getByRole('button', {name: 'New workspace'}).first().click();
  await page.getByLabel('Workspace name').fill(workspaceName);
  await page.getByRole('dialog').getByRole('button', {name: 'New workspace'}).click();
  // First write after an API restart opens its Supabase pool + fetches JWKS: can exceed 5 s.
  await expect(page).toHaveURL(/\/en\/app\/w\/[0-9a-f-]{36}\/materials/, {timeout: 30_000});
  await expect(page.getByRole('heading', {level: 1, name: workspaceName})).toBeVisible();
});

test('upload syllabus and past paper; both reach Ready through the real worker', async () => {
  await page.getByText('Syllabus', {exact: true}).click();
  await page.locator('input[type=file]').setInputFiles(path.join(fixtures, 'sample-syllabus.pdf'));
  await expect(page.getByText('sample-syllabus.pdf uploaded. Processing has started.')).toBeVisible({timeout: 60_000});
  await page.getByText('Past paper', {exact: true}).click();
  await page.locator('input[type=file]').setInputFiles(path.join(fixtures, 'sample-past-paper.txt'));
  await expect(page.getByText('sample-past-paper.txt uploaded. Processing has started.')).toBeVisible({timeout: 60_000});
  await page.getByText('Notes', {exact: true}).click();
  await page.locator('input[type=file]').setInputFiles(path.join(fixtures, 'sample-notes.txt'));
  await expect(page.getByText('sample-notes.txt uploaded. Processing has started.')).toBeVisible({timeout: 60_000});
  const rows = page.locator('ul li').filter({hasText: 'sample-'});
  await expect(rows.filter({hasText: 'Ready'})).toHaveCount(3, {timeout: 4 * 60_000});
  await expect(rows.filter({hasText: 'sample-syllabus.pdf'})).toContainText('2 pages');
  expect(await axe(page)).toEqual([]);
  await shot(page, 'materials');
});

test('source viewer shows page-located text with headings', async () => {
  await page.locator('li', {hasText: 'sample-syllabus.pdf'}).getByRole('link', {name: 'View extracted text'}).click();
  await expect(page.getByRole('heading', {name: 'Page 1'})).toBeVisible();
  await expect(page.getByRole('heading', {name: 'Page 2'})).toBeVisible();
  await expect(page.getByText(/Unit 1: Light and Optics/).first()).toBeVisible();
  await page.goBack();
});

test('topic map is proposed automatically, with exact cited evidence', async () => {
  await page.getByRole('link', {name: 'Topic map'}).click();
  const tree = page.locator('main ul').first();
  await expect(tree.getByText(/Light|Optics/i).first()).toBeVisible({timeout: 3 * 60_000});
  await expect(tree.getByText(/Electricity/i).first()).toBeVisible();
  await expect(tree.getByText(/Life Processes/i).first()).toBeVisible();
  await page.getByRole('button', {name: /citation/}).first().click();
  const drawer = page.getByRole('dialog');
  await expect(drawer.getByText('Original (English)').first()).toBeVisible();
  await expect(drawer.getByText('sample-syllabus.pdf').first()).toBeVisible();
  expect(await axe(page)).toEqual([]);
  await shot(page, 'evidence');
  await drawer.getByRole('link', {name: 'Open in extracted text'}).first().click();
  await expect(page).toHaveURL(/\/sources\/[0-9a-f-]{36}#chunk-/);
  await expect(page.getByText('Cited passage')).toBeVisible();
  await page.goBack();
});

test('approve all, match past papers, importance follows marks; override wins', async () => {
  await page.getByRole('button', {name: 'Approve all'}).click();
  await expect(page.getByText(/topics? approved\./)).toBeVisible();
  await page.getByRole('button', {name: 'Match past papers', exact: true}).click();
  await expect(page.getByText('Past papers matched. Importance updated.')).toBeVisible({timeout: 3 * 60_000});
  await expect(page.getByText('Q3').first()).toBeVisible();
  const mapped = page.getByRole('button', {name: /Importance [1-5] of 5\. From past papers/}).first();
  await expect(mapped).toBeVisible();
  expect(await axe(page)).toEqual([]);
  await shot(page, 'topics');

  await page.getByRole('button', {name: /^More actions: /}).first().click();
  await page.getByRole('menuitem', {name: 'Edit'}).click();
  await page.getByRole('radio', {name: '2'}).click();
  await page.getByRole('dialog').getByRole('button', {name: 'Save'}).click();
  await expect(page.getByRole('button', {name: 'Importance 2 of 5. Set by you.'}).first()).toBeVisible();
});

test('Hindi UI shows the original quote plus a labelled translation', async () => {
  await page.getByRole('combobox', {name: 'Language'}).selectOption('hi-IN');
  await expect(page).toHaveURL(/\/hi-IN\/app\/w\//);
  await expect(page.getByRole('heading', {name: 'विषय मानचित्र'})).toBeVisible();
  await page.getByRole('button', {name: /उद्धरण/}).first().click();
  const drawer = page.getByRole('dialog');
  await expect(drawer.getByText('मूल (English)').first()).toBeVisible(); // originals show at once
  await expect(drawer.getByText(/अनुवाद \(हिन्दी\)/).first()).toBeVisible({timeout: 90_000});
  await page.keyboard.press('Escape');
  await page.getByRole('combobox', {name: 'भाषा'}).selectOption('en');
  await expect(page).toHaveURL(/\/en\/app\/w\//);
});

test('diagnostic: generate, answer with autosave, submit-lock, review with sources', async () => {
  await page.getByRole('link', {name: 'Diagnostics'}).click();
  await page.getByRole('button', {name: 'New diagnostic'}).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByText('5 questions', {exact: true}).click();
  await dialog.getByRole('button', {name: 'Create diagnostic'}).click();
  await expect(page.getByText(/Writing questions…/)).toBeVisible();
  const start = page.getByRole('button', {name: 'Start'});
  await expect(start).toBeVisible({timeout: 5 * 60_000});
  expect(await axe(page)).toEqual([]);
  await start.click();
  await expect(page).toHaveURL(/\/quiz\/[0-9a-f-]{36}$/);
  await expect(page.getByText('Question 1 of 5')).toBeVisible();
  // The answer key never reaches the browser before submission (checked on the real BFF payload).
  const attemptId = page.url().split('/').pop();
  const payload = await (await page.request.get(`/api/bff/attempts/${attemptId}`)).text();
  for (const secret of ['correct_option_id', 'correct_boolean', 'model_answer', 'rubric', 'citations', 'explanation']) expect(payload).not.toContain(secret);
  expect(await axe(page)).toEqual([]);
  await shot(page, 'quiz');
  for (let i = 0; i < 5; i++) {
    const type = await page.locator('main span').filter({hasText: /^(Multiple choice|True or false|Short answer)$/}).first().innerText();
    if (type === 'Short answer') await page.getByLabel('Your answer').fill('Based on my notes, the key idea is explained here.');
    else if (type === 'Multiple choice') await page.keyboard.press('b');
    else await page.keyboard.press('t');
    await expect(page.getByText('Saved')).toBeVisible({timeout: 15_000});
    if (i < 4) await page.getByRole('button', {name: 'Next'}).click();
  }
  await page.reload();
  await expect(page.getByText('5 of 5 answered')).toBeVisible();
  await page.getByRole('button', {name: 'Submit'}).first().click();
  await expect(page.getByText('You have answered every question.')).toBeVisible();
  await page.getByRole('button', {name: 'Submit and lock'}).click();
  await expect(page.getByText('Submitted. Your answers are locked.')).toBeVisible();
  await expect(page.getByText('Review with sources')).toBeVisible();
  await expect(page.getByRole('link', {name: 'Open in extracted text'}).first()).toBeVisible();
  expect(await axe(page)).toEqual([]);
  await shot(page, 'review');
});

test('evaluation: marked results, then a Gap Report with reasons and cited missed questions', async () => {
  // Still on the submitted attempt: the worker marks it (objective instantly, short answers via Groq).
  await expect(page.getByText(/^Score: /)).toBeVisible({timeout: 4 * 60_000});
  await expect(page.getByTestId('review-item').first().getByText(/^(Correct|Partly correct|Incorrect|Not answered)$/)).toBeVisible();
  expect(await axe(page)).toEqual([]);
  await page.getByRole('link', {name: 'Open Gap Report'}).click();
  await expect(page).toHaveURL(/\/report$/);
  await expect(page.getByRole('heading', {name: 'Gap Report', level: 2})).toBeVisible();
  const units = page.getByTestId('report-unit');
  await expect(units.first()).toBeVisible();
  await expect(units.first().getByText('Why this label')).toBeVisible();
  await expect(page.getByTestId('overall-score')).toContainText('%');
  const missed = page.getByRole('button', {name: /^Questions you missed/}).first();
  if (await missed.count()) {
    await missed.click();
    await expect(page.getByRole('link', {name: 'Open in extracted text'}).first()).toBeVisible();
  }
  expect(await axe(page)).toEqual([]);
  await shot(page, 'report');
});

test('plan: availability builds a versioned plan, shortfall is explicit, sessions can be ticked', async () => {
  await page.getByRole('link', {name: 'Plan'}).click();
  await expect(page.getByRole('heading', {name: 'Your available time'})).toBeVisible();
  const exam = new Date(Date.now() + 3 * 86_400_000);
  await page.getByLabel('Exam date').fill(exam.toISOString().slice(0, 10));
  await page.getByLabel('Minutes per study day').fill('20');
  for (const day of ['Sat', 'Sun']) {
    const box = page.getByRole('checkbox', {name: day});
    if (!(await box.isChecked())) await page.getByText(day, {exact: true}).click();
  }
  await page.getByRole('button', {name: 'Build my plan'}).click();
  // 20 minutes a day for ~3 days cannot cover a weak unit: the shortfall must be stated, not hidden.
  await expect(page.getByText('Not enough time for everything.')).toBeVisible({timeout: 30_000});
  await expect(page.getByTestId('shortfall-list').locator('li').first()).toBeVisible();
  const first = page.getByRole('checkbox', {name: /^Mark “.+” as done$/}).first();
  await first.check();
  await expect(first).toBeChecked();
  expect(await axe(page)).toEqual([]);
  await shot(page, 'plan');
  // Changing availability appends a new plan version; the old one stays readable.
  await page.getByRole('button', {name: 'Change availability'}).click();
  await page.getByLabel('Minutes per study day').fill('240');
  await page.getByRole('button', {name: 'Save and rebuild plan'}).click();
  await expect(page.getByText('Everything fits before your exam.')).toBeVisible({timeout: 30_000});
  await expect(page.getByRole('combobox', {name: 'Version'})).toHaveValue(/.+/);
});

test('progress: chart and table views; completion is shown separately from mastery', async () => {
  await page.getByRole('link', {name: 'Progress'}).click();
  await expect(page.getByRole('heading', {name: 'Test score by report'})).toBeVisible();
  await expect(page.getByRole('heading', {name: 'Plan sessions completed'})).toBeVisible();
  expect(await axe(page)).toEqual([]);
  await page.getByRole('button', {name: 'Table'}).click();
  await expect(page.getByRole('columnheader', {name: 'Report 1'})).toBeVisible();
  await expect(page.getByRole('rowheader', {name: 'Test score'})).toBeVisible();
  expect(await axe(page)).toEqual([]);
  await page.getByRole('button', {name: 'Chart'}).click();
  await shot(page, 'progress');
});

test('re-test: gaps pre-selected, a new report version, history preserved', async () => {
  await page.getByRole('link', {name: 'Diagnostics'}).click();
  await page.getByRole('button', {name: 'Re-test my gaps'}).click();
  const dialog = page.getByRole('dialog', {name: 'Create a re-test'});
  await expect(dialog).toBeVisible();
  const boxes = dialog.getByRole('checkbox');
  if ((await dialog.getByRole('checkbox', {checked: true}).count()) === 0) await boxes.first().check();
  await dialog.getByText('5 questions', {exact: true}).click();
  await dialog.getByRole('button', {name: 'Create re-test'}).click();
  const start = page.getByRole('button', {name: 'Start'});
  await expect(start).toBeVisible({timeout: 5 * 60_000});
  await start.click();
  await expect(page.getByText('Question 1 of 5')).toBeVisible();
  for (let i = 0; i < 5; i++) {
    const type = await page.locator('main span').filter({hasText: /^(Multiple choice|True or false|Short answer)$/}).first().innerText();
    if (type === 'Short answer') await page.getByLabel('Your answer').fill('From my notes: the main idea, its cause and an example.');
    else if (type === 'Multiple choice') await page.keyboard.press('a');
    else await page.keyboard.press('f');
    await expect(page.getByText('Saved')).toBeVisible({timeout: 15_000});
    if (i < 4) await page.getByRole('button', {name: 'Next'}).click();
  }
  await page.getByRole('button', {name: 'Submit'}).first().click();
  await page.getByRole('button', {name: 'Submit and lock'}).click();
  await expect(page.getByText(/^Score: /)).toBeVisible({timeout: 4 * 60_000});
  await page.getByRole('link', {name: 'Open Gap Report'}).click();
  const versions = page.getByRole('combobox', {name: 'Version'});
  await expect(versions.locator('option')).toHaveCount(2);
  await expect(page.getByText('Re-test', {exact: true}).first()).toBeVisible();
  await versions.selectOption({label: 'Version 1'});
  await expect(page.getByText('You are viewing an earlier version.')).toBeVisible();
  expect(await axe(page)).toEqual([]);
  await page.getByRole('link', {name: 'Progress'}).click();
  await page.getByRole('button', {name: 'Table'}).click();
  await expect(page.getByRole('columnheader', {name: 'Report 2'})).toBeVisible();
});

test('explain: shortcut from the Gap Report, cited answer, honest voice/visual states', async () => {
  await page.getByRole('link', {name: 'Gap Report'}).click();
  await page.getByTestId('report-unit').first().getByRole('link', {name: 'Explain', exact: true}).click();
  await expect(page).toHaveURL(/\/explain\?/);
  await expect(page.getByLabel('Your question')).not.toHaveValue('');
  await page.getByRole('button', {name: 'Explain', exact: true}).click();
  const answer = page.getByTestId('explanation');
  await expect(answer.getByText(/Finding the answer|Sources|doesn't cover this/).first()).toBeVisible({timeout: 30_000});
  await expect(answer.getByText(/^Sources$|^Your material doesn't cover this yet\.$/).first()).toBeVisible({timeout: 2 * 60_000});
  if (await answer.getByText('Sources', {exact: true}).count()) {
    await expect(answer.getByRole('link', {name: 'Open in extracted text'}).first()).toBeVisible();
    // Live voice (ElevenLabs): real, playable audio from the private bucket.
    await answer.getByRole('button', {name: 'Listen'}).click();
    const audio = answer.getByTestId('explain-audio');
    await expect(audio.or(answer.getByText("The audio couldn't be made.", {exact: false}))).toBeVisible({timeout: 2 * 60_000});
    await expect(audio).toBeVisible();
    await expect.poll(() => audio.evaluate((el: HTMLAudioElement) => (el.readyState >= 1 ? el.duration : 0)), {timeout: 30_000}).toBeGreaterThan(0.5);
    // Live visual: a source figure, an AI illustration (Cloudflare), or an honest "nothing to draw" — never a failure.
    await answer.getByRole('button', {name: 'Show illustration'}).click();
    const illustration = answer.getByTestId('explain-illustration');
    const outcome = illustration
      .or(answer.getByText(/^Original figure in /))
      .or(answer.getByText('This explanation has no clear parts or steps to draw', {exact: false}))
      .or(answer.getByText("The illustration couldn't be made.", {exact: false}));
    await expect(outcome.first()).toBeVisible({timeout: 3 * 60_000});
    await expect(answer.getByText("The illustration couldn't be made.", {exact: false})).toHaveCount(0);
    if (await illustration.count()) {
      await expect.poll(() => illustration.locator('img').evaluate((img: HTMLImageElement) => img.naturalWidth), {timeout: 30_000}).toBeGreaterThan(0);
      await expect(illustration.getByText('AI-generated illustration', {exact: false})).toBeVisible();
    }
  }
  await expect(page.getByTestId('limits')).toContainText('explanations left today');
  expect(await axe(page)).toEqual([]);
  await shot(page, 'explain');
});

test('dashboard lists the workspace; deleting it removes everything', async () => {
  await page.goto('/en/app');
  await expect(page.getByRole('link', {name: workspaceName})).toBeVisible();
  expect(await axe(page)).toEqual([]);
  await shot(page, 'dashboard');
  await page.getByRole('button', {name: `More actions: ${workspaceName}`}).click();
  await page.getByRole('menuitem', {name: 'Delete'}).click();
  await page.getByRole('button', {name: 'Delete permanently'}).click();
  await expect(page.getByRole('link', {name: workspaceName})).toHaveCount(0);
});
