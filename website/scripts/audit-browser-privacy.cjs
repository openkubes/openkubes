#!/usr/bin/env node
// Manual privacy evidence audit using Playwright Chromium.
// Captures ONLY domains, request types, resource counts and browser storage
// metadata. Never logs question text, cookie values, request URLs, or HAR bodies.
const { chromium } = require('playwright');
const fs = require('node:fs');
const { URL } = require('node:url');

const origins = [
  'https://openkubes.org/',
  'https://preview.openkubes.org/',
];
const routes = ['/', '/ai/'];
const BLOCKED = [
  'googletagmanager.com', 'google-analytics.com', 'doubleclick.net',
  'googleadservices.com', 'googlesyndication.com',
  'snap.licdn.com', 'px.ads.linkedin.com',
  'fonts.googleapis.com', 'fonts.gstatic.com',
  'i.ytimg.com', 'img.youtube.com',
];
const safeHost = (url) => { try { return new URL(url).hostname.toLowerCase(); } catch { return ''; } };
const forbidden = (host) => BLOCKED.some(d => host === d || host.endsWith('.' + d));
const timeout = 25000;
async function snapshot(page) {
  // No values or key names are copied from cookies or browser storage.
  const state = await page.evaluate(() => ({
    cookieCount: document.cookie ? document.cookie.split(';').filter(Boolean).length : 0,
    localStorageCount: localStorage.length,
    sessionStorageCount: sessionStorage.length,
    indexedDBSupported: Boolean(window.indexedDB),
  }));
  const cookies = await page.context().cookies();
  const serviceWorkers = page.context().serviceWorkers().length;
  return { ...state, contextCookieCount: cookies.length, serviceWorkerCount: serviceWorkers };
}
async function inspect(browser, origin, route) {
  const context = await browser.newContext({ locale: 'en-US', serviceWorkers: 'block' });
  const page = await context.newPage();
  const events = [];
  const pageErrors = [];
  page.on('request', req => events.push({ host: safeHost(req.url()), type: req.resourceType(), phase: 'load' }));
  page.on('pageerror', err => pageErrors.push(err.name || 'Error'));
  const target = new URL(route, origin).toString();
  let status = null, error = null;
  try {
    const response = await page.goto(target, { waitUntil: 'networkidle', timeout });
    status = response?.status() ?? null;
    await page.waitForTimeout(800);
    const before = await snapshot(page);
    let interaction = null;
    if (route === '/') {
      const opener = page.getByRole('button', { name: /Open curated OK AI Lite|Ask OK AI/i }).first();
      if (await opener.count()) {
        const preClick = events.length;
        await opener.click();
        const field = page.locator('#okai-floating-input');
        if (await field.count()) {
          // Fixed synthetic question only; text is never recorded in the report.
          await field.fill('What is OpenKubes Local?');
          await page.locator('.okai-input-form button[type="submit"]').click();
          await page.waitForTimeout(1000);
          interaction = {
            widgetFound: true,
            requestCountFromInteraction: events.length - preClick,
            remoteHostsFromInteraction: [...new Set(events.slice(preClick).map(e => e.host)
              .filter(h => h && h !== new URL(origin).hostname))].sort(),
          };
        } else {
          interaction = { widgetFound: false, reason: 'Input missing after opening widget' };
        }
      } else {
        interaction = { widgetFound: false, reason: 'Lite launcher not detected' };
      }
    }
    const after = await snapshot(page);
    const hosts = [...new Set(events.map(e => e.host).filter(Boolean))].sort();
    return {
      origin, route, status,
      requests: events.length,
      hosts,
      forbiddenHosts: hosts.filter(forbidden),
      requestsByType: events.reduce((obj, e) => { obj[e.type] = (obj[e.type] || 0) + 1; return obj; }, {}),
      before, after, interaction, pageErrorTypes: pageErrors,
    };
  } catch (e) {
    error = e.name || 'BrowserAuditError';
    return { origin, route, status, error };
  } finally {
    await context.close();
  }
}
(async () => {
  const browser = await chromium.launch({ headless: true });
  const results = [];
  try {
    for (const origin of origins) for (const route of routes) {
      results.push(await inspect(browser, origin, route));
    }
  } finally {
    await browser.close();
  }
  const report = {
    schema: 'openkubes-browser-privacy-audit-v1',
    auditedAt: new Date().toISOString(),
    caveat: 'Point-in-time automated Chromium evidence; does not establish legal compliance or server-log retention',
    results,
  };
  fs.writeFileSync('openkubes-browser-privacy-audit.json', JSON.stringify(report, null, 2) + '\n');
  const blockers = results.flatMap(r => {
    const errors = [];
    if (r.error) errors.push(r.origin + r.route + ': browser error ' + r.error);
    if (!r.status || r.status >= 400) errors.push(r.origin + r.route + ': HTTP status ' + r.status);
    if (r.forbiddenHosts?.length) errors.push(r.origin + r.route + ': blocked third-party hosts ' + r.forbiddenHosts.join(', '));
    if (r.interaction && !r.interaction.widgetFound) errors.push(r.origin + r.route + ': Lite missing');
    if (r.interaction?.remoteHostsFromInteraction?.length) errors.push(r.origin + r.route + ': Lite interaction contacted ' + r.interaction.remoteHostsFromInteraction.join(', '));
    return errors;
  });
  for (const issue of blockers) console.error('PRIVACY AUDIT:', issue);
  console.log('Browser privacy audit wrote sanitized evidence for ' + results.length + ' routes.');
  process.exitCode = blockers.length ? 1 : 0;
})().catch(e => { console.error('Audit harness failed:', e.name || 'Error'); process.exitCode = 1; });
