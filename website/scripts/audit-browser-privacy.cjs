#!/usr/bin/env node
// Manual privacy evidence audit using Playwright Chromium.
// Captures ONLY domains, request types, resource counts and browser storage
// metadata. Never logs cookie values, request URLs, or HAR bodies.
const { chromium } = require('playwright');
const fs = require('node:fs');
const { URL } = require('node:url');

const origin = 'https://openkubes.org/';
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
async function inspect(browser, route) {
  const context = await browser.newContext({ locale: 'en-US', serviceWorkers: 'block' });
  const page = await context.newPage();
  const events = [];
  const pageErrors = [];
  page.on('request', req => events.push({ host: safeHost(req.url()), type: req.resourceType() }));
  page.on('pageerror', err => pageErrors.push(err.name || 'Error'));
  const target = new URL(route, origin).toString();
  let status = null, error = null;
  try {
    const response = await page.goto(target, { waitUntil: 'networkidle', timeout });
    status = response?.status() ?? null;
    await page.waitForTimeout(800);
    const storage = await snapshot(page);
    const retiredWidgetFound = await page.locator('#okai-floating-demo, #okai-float-panel, #okai-floating-input').count() > 0;
    const hosts = [...new Set(events.map(e => e.host).filter(Boolean))].sort();
    return {
      origin, route, status,
      requests: events.length,
      hosts,
      forbiddenHosts: hosts.filter(forbidden),
      requestsByType: events.reduce((obj, e) => { obj[e.type] = (obj[e.type] || 0) + 1; return obj; }, {}),
      storage, retiredWidgetFound, pageErrorTypes: pageErrors,
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
    for (const route of routes) {
      results.push(await inspect(browser, route));
    }
  } finally {
    await browser.close();
  }
  const report = {
    schema: 'openkubes-browser-privacy-audit-v2',
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
    if (r.retiredWidgetFound) errors.push(r.origin + r.route + ': retired OK AI widget found');
    return errors;
  });
  for (const issue of blockers) console.error('PRIVACY AUDIT:', issue);
  console.log('Browser privacy audit wrote sanitized evidence for ' + results.length + ' routes.');
  process.exitCode = blockers.length ? 1 : 0;
})().catch(e => { console.error('Audit harness failed:', e.name || 'Error'); process.exitCode = 1; });
