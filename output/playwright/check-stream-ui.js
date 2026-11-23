async (page) => {
  await page.evaluate(() => {
    const originalFetch = window.fetch.bind(window);
    window.__streamSamples = [];
    window.__testAnswer = '## A readable response\n\nThe answer arrives progressively, rather than appearing as one large block. **Formatting stays intact.**\n\n' + 'This is another sentence with enough text to test a burst. '.repeat(12);
    window.fetch = async (url, options) => {
      if (!String(url).endsWith('/api/chat')) return originalFetch(url, options);
      await new Promise(resolve => setTimeout(resolve, 250));
      const answer = window.__testAnswer;
      const encoder = new TextEncoder();
      return new Response(new ReadableStream({
        async start(controller) {
          const send = event => controller.enqueue(encoder.encode('data: ' + JSON.stringify(event) + '\n\n'));
          const pause = () => new Promise(resolve => setTimeout(resolve, 400));
          send({type:'stage',stage:'route',status:'active'}); await pause();
          send({type:'stage',stage:'route',status:'done'});
          send({type:'stage',stage:'retrieve',status:'active'}); await pause();
          send({type:'stage',stage:'retrieve',status:'done'});
          send({type:'stage',stage:'answer',status:'active'}); await pause();
          send({type:'token',text:answer});
          send({type:'done',answer,cited:[],provenance:'general',timings_ms:{},models:{generation:'test-fixture',router:'test-fixture'}});
          controller.close();
        }
      }), {headers:{'Content-Type':'text/event-stream'}});
    };
    window.__sampleTimer = setInterval(() => {
      const article = document.querySelector('main article');
      window.__streamSamples.push({status: article?.querySelector('[role=status]')?.textContent.trim() || null, text: article?.textContent || '', running: !!document.querySelector('button[aria-label="Stop generating"]')});
    }, 30);
  });
  await page.getByRole('textbox', {name:'Question about LM317'}).fill('UI streaming test');
  await page.getByRole('button', {name:'Send',exact:true}).click();
  await page.getByRole('button', {name:'Stop generating'}).waitFor();
  await page.getByRole('button', {name:'Send',exact:true}).waitFor({timeout:15000});
  const result = await page.evaluate(() => {
    clearInterval(window.__sampleTimer);
    const samples = window.__streamSamples;
    return {statuses:[...new Set(samples.map(s=>s.status).filter(Boolean))],distinctLengths:[...new Set(samples.filter(s=>s.text.includes('A readable response')).map(s=>s.text.length))],finalText:document.querySelector('main article')?.textContent,hasChecklist:!!document.querySelector('main article ol[aria-label]')};
  });
  if (result.statuses.join('|') !== 'Thinking|Understanding user query|Retrieving') throw new Error(JSON.stringify(result));
  if (result.distinctLengths.length < 5) throw new Error('Output was not progressive: '+JSON.stringify(result));
  console.log(JSON.stringify(result));
  await page.screenshot({path:'output/playwright/smooth-stream-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:'output/playwright/smooth-stream-mobile.png',fullPage:true});
  console.log('Horizontal overflow:', await page.evaluate(()=>document.documentElement.scrollWidth > window.innerWidth));
}
