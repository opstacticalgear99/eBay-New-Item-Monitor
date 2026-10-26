'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const source=fs.readFileSync('public/settings.js','utf8');
function client(response) {
  const nodes=new Map();
  const context=vm.createContext({document:{getElementById(id){if(!nodes.has(id)) nodes.set(id,{value:'retained draft',disabled:false,addEventListener(){},classList:{toggle(){}}});return nodes.get(id);}},fetch:async()=>response,JSON,Map,Error});
  vm.runInContext(source,context);return {context,nodes};
}
test('HTML gateway pages produce clear error and retain draft',async()=>{
  const {context,nodes}=client(new Response('<!DOCTYPE html><h1>Gateway failure</h1>',{status:502,headers:{'Content-Type':'text/html'}}));
  await assert.rejects(vm.runInContext("request('POST', {})",context),/HTTP 502.*编辑内容已保留/);
  assert.equal(nodes.get('brandQueries')?.value ?? 'retained draft','retained draft');
});
test('malformed JSON is handled without raw parsing errors',async()=>{
  const {context}=client(new Response('<!DOCTYPE html>',{status:200,headers:{'Content-Type':'application/json'}}));
  await assert.rejects(vm.runInContext("request('GET')",context),/服务返回异常响应/);
});
test('API validation errors and successful saves retain JSON semantics',async()=>{
  const failed=client(new Response(JSON.stringify({error:'请删除重复的关键词或卖家。'}),{status:400,headers:{'Content-Type':'application/json'}}));
  await assert.rejects(vm.runInContext("request('POST', {})",failed.context),/请删除重复/);
  const good=client(new Response('{"ok":true}',{headers:{'Content-Type':'application/json'}}));
  assert.equal((await vm.runInContext("request('POST', {})",good.context)).ok,true);
});
