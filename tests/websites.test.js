'use strict';
const {test}=require('node:test');const assert=require('node:assert/strict');
const express=require('express');const fs=require('node:fs');const os=require('node:os');const path=require('node:path');
const register=require('../monitor-settings');const defaults=require('../website-defaults.json');

test('website settings: defaults, auth, validation, persistence, conflicts and eBay isolation',async t=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'website-config-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
  const ebay=JSON.stringify({brands:[{label:'Custom','query':'Custom'}],sellers:['seller']});fs.writeFileSync(path.join(dir,'monitor-settings.json'),ebay);
  const app=express();app.use(express.json());register(app,{dir,token:'test-token'});let server=await new Promise(r=>{const s=app.listen(0,'127.0.0.1',()=>r(s));});t.after(()=>new Promise(r=>server.close(r)));
  const url='http://127.0.0.1:'+server.address().port+'/api/monitor/websites';
  const req=(method='GET',body,token='test-token')=>fetch(url,{method,headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});
  assert.equal((await req('GET',null,'bad')).status,401);
  let initial=await (await req()).json();assert.equal(initial.sites.length,2);assert.equal(initial.sites[0].status,'已支持');
  const sites=[{...defaults.sites[0],name:'My Ronin',enabled:false},{...defaults.sites[1],restocks:false},{...defaults.sites[1],name:'Next site',url:'https://example.com/'}];
  const saved=await req('POST',{revision:initial.revision,sites});assert.equal(saved.status,200);let data=await saved.json();
  assert.equal(data.sites[0].status,'已停用');assert.equal(data.sites[1].restocks,false);assert.equal(data.sites[2].supported,false);assert.match(data.sites[2].status,/待适配/);
  assert.equal(fs.readFileSync(path.join(dir,'monitor-settings.json'),'utf8'),ebay);assert.equal(fs.statSync(path.join(dir,'website-settings.json')).mode&0o777,0o600);
  assert.equal((await req('POST',{revision:initial.revision,sites})).status,409);
  for(const bad of ['http://example.com','https://localhost/','https://127.0.0.1/','https://user:password@example.com/','https://example.com/cart','https://example.com/?token=bad'])assert.equal((await req('POST',{revision:data.revision,sites:[{...sites[0],url:bad}]})).status,400);
  assert.equal((await req('POST',{revision:data.revision,sites:[defaults.sites[0],{...defaults.sites[0],url:'https://ronintactics.com/'}]})).status,400);
  assert.equal((await req('POST',{revision:data.revision,sites:[]})).status,200);assert.equal((await (await req()).json()).sites.length,0);
  // Re-registering the module after a restart reads the saved empty list.
  await new Promise(r=>server.close(r));const again=express();again.use(express.json());register(again,{dir,token:'test-token'});server=await new Promise(r=>{const s=again.listen(0,'127.0.0.1',()=>r(s));});
  const after=await fetch('http://127.0.0.1:'+server.address().port+'/api/monitor/websites',{headers:{Authorization:'Bearer test-token'}});assert.deepEqual((await after.json()).sites,[]);
  fs.writeFileSync(path.join(dir,'website-settings.json'),'{broken');
  const broken=await fetch('http://127.0.0.1:'+server.address().port+'/api/monitor/websites',{headers:{Authorization:'Bearer test-token'}});assert.equal(broken.status,503);
  assert.equal(fs.readFileSync(path.join(dir,'monitor-settings.json'),'utf8'),ebay);
});
