/** Bounded browser environment recovery. Never clicks or calls game code. */
export async function navigateWithRetry(page, url, diagnostics, { timeoutMs = 30000, attempts = 3 } = {}) {
  const deadline = performance.now() + timeoutMs;
  for (let attempt = 1; attempt <= attempts; attempt++) {
    const remaining = Math.floor(deadline - performance.now());
    if (remaining <= 0) throw new Error('Browser navigation deadline exhausted');
    try {
      const response = await page.goto(url, { waitUntil: 'load', timeout: remaining });
      diagnostics.push({ kind: 'navigation', attempt, status: response?.status(), url: page.url() });
      if (response && !response.ok()) throw new Error(`Browser entry HTTP ${response.status()}`);
      return response;
    } catch (error) {
      diagnostics.push({ kind: 'navigation_error', attempt, error: String(error.message || error).slice(0,1000) });
      if (!String(error.message || error).includes('ERR_CONNECTION_REFUSED') || attempt === attempts) throw error;
      const delay = Math.min(attempt * 250, deadline - performance.now());
      if (delay <= 0) throw error;
      await page.waitForTimeout(delay);
    }
  }
}

export async function ensureInputFocus(page, diagnostics, { attempts = 3 } = {}) {
  for (let attempt = 0; attempt <= attempts; attempt++) {
    if (await page.evaluate(() => document.hasFocus())) {
      if (attempt) diagnostics.push({ kind: 'focus_restored', attempt });
      return;
    }
    diagnostics.push({ kind: 'focus_missing', attempt, url: page.url() });
    if (attempt === attempts) throw new Error('Browser focus could not be restored after bounded retries');
    await page.bringToFront();
    await page.evaluate(() => window.focus());
    await page.waitForTimeout(100);
  }
}
