async (page) => {
  return await page.evaluate(() => ({
    statuses: window.__streamSamples.reduce((values, sample) => sample.status && values.at(-1) !== sample.status ? [...values, sample.status] : values, []),
    progressiveUpdates: new Set(window.__streamSamples.filter(s=>s.text.includes('A readable response')).map(s=>s.text.length)).size,
    overflow: document.documentElement.scrollWidth > innerWidth
  }));
}
