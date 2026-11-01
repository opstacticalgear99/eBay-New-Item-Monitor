'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const express=require('express'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const register=require('../monitor-settings');
async function service(t,credentials){
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'settings-auth-'));
  const app=express();app.use(express.json());register(app,{dir,...credentials});
  const server=await new Promise(r=>{const s=app.listen(0,'127.0.0.1',()=>r(s));});
  t.after(async()=>{await new Promise(r=>server.close(r));fs.rmSync(dir,{recursive:true,force:true});});
  return async(route,token,method='GET',body)=>fetch('http://127.0.0.1:'+server.address().port+route,{method,headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});
}
test('independent admin password protects writes while the monitor token still reads both settings APIs',async t=>{
  const req=await service(t,{token:'synthetic-sync-token',adminPassword:'synthetic-admin-password'});
  for(const route of ['/api/monitor/settings','/api/monitor/websites']){
    const read=await req(route,'synthetic-sync-token');assert.equal(read.status,200);const data=await read.json();
    assert.equal((await req(route,'synthetic-admin-password')).status,200);
    assert.equal((await req(route,'wrong')).status,401);
    assert.equal((await req(route,'synthetic-sync-token','POST',data)).status,401);
    assert.equal((await req(route,'synthetic-admin-password','POST',data)).status,200);
    assert.equal(JSON.stringify(data).includes('synthetic-admin-password'),false);
  }
  assert.equal((await req('/api/monitor/settings','synthetic-sync-token','PUT',{})).status,401);
});
test('password settings work without a machine token and legacy token fallback remains supported',async t=>{
  const passwordOnly=await service(t,{token:'',adminPassword:'synthetic-admin-password'});
  assert.equal((await passwordOnly('/api/monitor/settings','synthetic-admin-password')).status,200);
  const legacy=await service(t,{token:'synthetic-sync-token'});
  const data=await (await legacy('/api/monitor/settings','synthetic-sync-token')).json();
  assert.equal((await legacy('/api/monitor/settings','synthetic-sync-token','POST',data)).status,200);
  const missing=await service(t,{token:''});assert.equal((await missing('/api/monitor/settings','anything')).status,503);
});
