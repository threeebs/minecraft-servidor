// Chamado pelo teste HTTP com RUN_BROWSER_TESTS=1 e playwright disponível.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.CHROMIUM_EXECUTABLE_PATH || undefined,
    args: ['--no-sandbox']});
  try {
    const page = await browser.newPage({viewport: {width: 1280, height: 720}});
    page.setDefaultTimeout(10000);
    const errors = [];
    const postPaths = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => {
      if (request.method() === 'POST' && request.postData()?.includes('format=json')) {
        postPaths.push(new URL(request.url()).pathname);
      }
    });
    await page.goto(process.env.TEST_PANEL_URL);
    await page.locator('[name=password]').fill('test-panel-password-1234');
    await page.getByRole('button', {name: 'Entrar', exact: true}).click();
    const input = page.locator('#command');
    await input.fill('list');
    await input.press('Enter');
    await page.waitForFunction(() => document.querySelector('#console-state').textContent === 'Pronto para o próximo comando');
    assert.match(await page.locator('.console-response').last().innerText(), /players online/);
    await page.getByRole('button', {name: 'Dia', exact: true}).click();
    await page.waitForFunction(() => document.querySelector('#console-output').textContent.includes('Executado: time set day'));
    await input.press('ArrowUp');
    assert.equal(await input.inputValue(), 'time set day');
    page.on('dialog', dialog => dialog.accept());
    const button = page.locator('#update-form button');
    await page.waitForFunction(() => !document.querySelector('#update-form button').disabled);
    await button.click();
    await page.waitForFunction(() => document.querySelector('#update-message').textContent === 'Atualização na fila.');
    assert.equal(await button.isDisabled(), true);
    const jobs = process.env.TEST_JOBS_DIRECTORY;
    const job = JSON.parse(fs.readFileSync(path.join(jobs, 'update.job')));
    assert.deepEqual(Object.keys(job).sort(), ['id', 'requested_at']);
    fs.renameSync(path.join(jobs, 'update.job'), path.join(jobs, 'update.working'));
    fs.writeFileSync(path.join(jobs, 'update-status.json'), JSON.stringify({state: 'running',
      message: 'Preparando as novas imagens…', current: 'a'.repeat(40),
      events: [{time: '01:40', message: '<img src=x onerror="alert(1)">'}]}));
    await page.waitForFunction(() => document.querySelector('#update-message').textContent === 'Preparando as novas imagens…');
    assert.equal(await page.locator('#update-log img').count(), 0);
    assert.match(await page.locator('#update-log').innerText(), /<img/);
    let abortOnce = true;
    await page.route('**/?update_status=1', route => {
      if (abortOnce) {abortOnce = false; return route.abort();}
      return route.continue();
    });
    await page.waitForFunction(() => document.querySelector('#update-message').textContent.includes('Aguardando o painel responder'));
    fs.unlinkSync(path.join(jobs, 'update.working'));
    fs.writeFileSync(path.join(jobs, 'update-status.json'), JSON.stringify({state: 'success',
      message: 'Atualização concluída.', current: 'b'.repeat(40), events: []}));
    await page.waitForFunction(() => document.querySelector('#update-message').textContent === 'Atualização concluída.');
    assert.equal(await button.isDisabled(), false);
    assert.match(await page.locator('#update-revision').innerText(), /bbbbbbbbbbbb/);
    await page.reload();
    assert.match(await page.locator('#update-message').innerText(), /Atualização concluída/);
    assert.deepEqual(postPaths, ['/', '/', '/']);
    assert.deepEqual(errors, []);
    for (const [width, height] of [[1280, 720], [1920, 1080], [390, 844], [1080, 1920]]) {
      await page.setViewportSize({width, height});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      if (process.env.TEST_SCREENSHOT_DIRECTORY && [1280, 390].includes(width)) {
        await page.locator('#update-title').scrollIntoViewIfNeeded();
        await page.screenshot({path: path.join(process.env.TEST_SCREENSHOT_DIRECTORY, 'update-' + width + '.png')});
      }
    }
    console.log('PASS: terminal e atualizador no Chromium, fila fixa, progresso, reconexão, XSS, reload e quatro resoluções.');
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exit(1);});
