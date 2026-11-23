async (page) => {
  await page.setViewportSize({width:1280,height:900});
  await page.getByRole('button', {name:'New session',exact:true}).click();
  await page.evaluate(() => {
    window.fetch = async () => {
      const answer = 'A long answer that should still be draining when stopped. '.repeat(100);
      const events = [
        {type:'stage',stage:'route',status:'active'},
        {type:'stage',stage:'route',status:'done'},
        {type:'stage',stage:'answer',status:'active'},
        {type:'token',text:answer},
        {type:'done',answer,cited:[],provenance:'general',timings_ms:{},models:{generation:'test',router:'test'}}
      ];
      return new Response(events.map(event=>'data: '+JSON.stringify(event)+'\n\n').join(''), {headers:{'Content-Type':'text/event-stream'}});
    };
  });
  await page.getByRole('textbox',{name:'Question about LM317'}).fill('Stop test');
  await page.getByRole('button',{name:'Send',exact:true}).click();
  await page.getByRole('button',{name:'Stop generating'}).click();
  await page.getByText('Stopped. Any text shown is an unfinished answer.',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Send',exact:true}).waitFor();
  await page.getByRole('button',{name:'New session',exact:true}).click();
  await page.emulateMedia({reducedMotion:'reduce'});
  await page.getByRole('textbox',{name:'Question about LM317'}).fill('Reduced motion test');
  await page.getByRole('button',{name:'Send',exact:true}).click();
  await page.getByText('General knowledge',{exact:true}).waitFor({timeout:5000});
  const result = {stoppedCleanly:true,reducedMotionCompleted:true,remainingStatus:await page.locator('main article [role=status]').count()};
  await page.reload();
  return result;
}
