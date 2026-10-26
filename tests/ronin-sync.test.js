'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const net=require('node:net');
const {spawn}=require('node:child_process');
const {once}=require('node:events');

test('receiver accepts new/restock Ronin events, deduplicates retries and preserves eBay history',async t=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'ronin-sync-'));
  t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
  const probe=net.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));
  const port=probe.address().port;await new Promise(r=>probe.close(r));
  let child;
  t.after(async()=>{if(child && child.exitCode===null){child.kill();await once(child,'exit');}});
  async function start(){
    child=spawn(process.execPath,['server.js'],{env:{PATH:process.env.PATH,PORT:String(port),DATA_DIR:dir,APP_API_TOKEN:'synthetic-test-token'},stdio:'ignore'});
    for(let i=0;i<60;i++){
      if(child.exitCode!==null)throw Error('test server failed');
      try{const r=await fetch(`http://127.0.0.1:${port}/api/health`);if(r.ok)return;}catch(_){}
      await new Promise(r=>setTimeout(r,50));
    }
    throw Error('test server did not start');
  }
  async function sync(items){const res=await fetch(`http://127.0.0.1:${port}/api/monitor/sync`,{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer synthetic-test-token'},body:JSON.stringify({items})});assert.equal(res.status,200);return res.json();}
  const ebay={itemId:'existing-ebay',title:'eBay listing',url:'https://www.ebay.com/itm/123456789012'};
  const fresh={itemId:'ronin:339:new',title:'【新品】Carrier',source:'Ronin Tactics',url:'https://www.ronintactics.com/store/p339/Carrier.html',labels:['Ronin Tactics','新品']};
  await start();assert.equal((await sync([ebay,fresh])).added,2);
  assert.equal((await sync([fresh])).added,0);
  const fog={...fresh,itemId:'fog:123:new',source:'Forward Observations Group',url:'https://forwardobservations.com/products/roll-1'};
  assert.equal((await sync([fog])).added,1);
  assert.equal((await sync([{...fog,itemId:'invalid-fog',url:'https://forwardobservations.com.evil.com/products/a'}])).added,0);
  assert.equal((await sync([{...fresh,itemId:'ronin:339:restock:2',title:'【补货】Carrier'}])).added,1);
  for(const url of ['https://www.ronintactics.com.evil.com/store/p339/Carrier.html','https://www.ronintactics.com/checkout','http://www.ronintactics.com/store/p339/Carrier.html'])assert.equal((await sync([{...fresh,itemId:'invalid:'+url,url}])).added,0);
  child.kill();await once(child,'exit');await start();assert.equal((await sync([fresh,ebay])).added,0);
  const items=(await (await fetch(`http://127.0.0.1:${port}/api/items`)).json()).items;
  assert.equal(items.length,4);assert.equal(items.find(i=>i.itemId===fresh.itemId).source,'Ronin Tactics');
});
