'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('fs'),os=require('os'),path=require('path');
const mount=require('../monitor-status');
test('status only exposes allowed operational fields',()=>{
 const s=mount.sanitize({state:'partial',intervalMinutes:15,startedAt:'2026-11-13T12:00:00Z',secret:'private',ebay:{state:'rate_limited',error:'token',requests:1},quota:{state:'available',rates:[{remaining:0,limit:5000,timeWindow:86400}]}});
 assert.equal(s.quota.rates[0].remaining,0);assert.equal(s.ebay.state,'rate_limited');assert.ok(!JSON.stringify(s).includes('private'));assert.ok(!JSON.stringify(s).includes('token'));
});
test('status writes require token, reject malformed data, and survive remount',()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'fw-status-')),routes={};
 const app={get:(p,f)=>routes['GET']=f,post:(p,f)=>routes['POST']=f};
 const res={code:200,status(c){this.code=c;return this;},json(v){this.body=v;return this;},set(){}};
 try{mount(app,{dir,token:'test-secret'});
  routes.POST({get:()=>'',body:{}},res);assert.equal(res.code,401);
  routes.POST({get:()=>'Bearer test-secret',body:{}},res);assert.equal(res.code,400);
  res.code=200;routes.POST({get:()=>'Bearer test-secret',body:{state:'ok',startedAt:'2026-11-13T12:00:00Z',intervalMinutes:15}},res);assert.equal(res.code,200);
  mount(app,{dir,token:'test-secret'});routes.GET({},res);assert.equal(res.body.state,'ok');
 }finally{fs.rmSync(dir,{recursive:true});}
});
