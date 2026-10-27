'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const create=require('../push-outbox');

test('transient Push failure survives restart and does not repeat successful recipients',async t=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'push-outbox-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
  const file=path.join(dir,'queue.json'),subs=[{endpoint:'one'},{endpoint:'two'}];
  let fail=true,calls=[];
  const options={file,subscriptions:()=>subs,expire:()=>{},send:async(s,payload)=>{calls.push({endpoint:s.endpoint,payload:JSON.parse(payload)});if(s.endpoint==='two'&&fail)throw {statusCode:503};}};
  let out=create(options);out.enqueue([{itemId:'first',title:'First'}]);
  assert.deepEqual(await out.drain(),{pushSent:1,pushFailed:1});assert.equal(out.pending,1);
  out=create(options);fail=false;await out.drain();assert.equal(out.pending,0);
  assert.equal(calls.filter(c=>c.endpoint==='one').length,1);assert.equal(calls.filter(c=>c.endpoint==='two').length,2);
});

test('different batches have unique tags and report full batch count',async t=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'push-tags-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
  const payloads=[];const out=create({file:path.join(dir,'queue.json'),subscriptions:()=>[{endpoint:'one'}],expire:()=>{},send:async(s,p)=>payloads.push(JSON.parse(p))});
  out.enqueue(Array.from({length:25},(_,i)=>({itemId:String(i),title:'Item '+i})));await out.drain();
  out.enqueue([{itemId:'next',title:'Next'}]);await out.drain();
  assert.match(payloads[0].title,/25/);assert.notEqual(payloads[0].tag,payloads[1].tag);
});

test('expired subscriptions are removed and retries are serialized',async t=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'push-expiry-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));
  let expired=[],calls=0;const out=create({file:path.join(dir,'queue.json'),subscriptions:()=>[{endpoint:'gone'}],expire:s=>expired.push(s),send:async()=>{calls++;throw {statusCode:410};}});
  out.enqueue([{itemId:'one',title:'One'}]);await Promise.all([out.drain(),out.drain()]);
  assert.equal(calls,1);assert.deepEqual(expired,['gone']);assert.equal(out.pending,0);
});
