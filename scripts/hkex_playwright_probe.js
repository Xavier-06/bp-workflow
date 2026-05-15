const { chromium } = require('playwright');

(async() => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ locale: 'zh-HK' });
  page.setDefaultTimeout(20000);
  try {
    await page.goto('https://www.hkexnews.hk/search/titlesearch.xhtml?lang=zh', { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3000);
    console.log('TITLE', await page.title());
    const inputs = await page.locator('input').evaluateAll(els => els.map(e => ({id:e.id,name:e.name,type:e.type,placeholder:e.placeholder||''})).slice(0,30));
    console.log('INPUTS', JSON.stringify(inputs, null, 2));
    const text = await page.locator('body').innerText();
    console.log('BODY_SNIP', text.slice(0, 2000));
  } catch (e) {
    console.error('ERR', String(e));
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
