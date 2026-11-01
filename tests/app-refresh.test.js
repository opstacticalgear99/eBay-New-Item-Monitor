'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const code=fs.readFileSync('public/app.js','utf8');
function client(fetcher){
  const nodes=new Map(),documentEvents=new Map(),windowEvents=new Map(),intervals=[];
  function element(){return {value:'',textContent:'',children:[],get childNodes(){return this.children;},classList:{toggle(){},remove(){},add(){}},append(...items){this.children.push(...items);},replaceChildren(){this.children=[];},addEventListener(){}};}
  const document={hidden:false,getElementById(id){if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);},createElement:element,addEventListener:(name,fn)=>documentEvents.set(name,fn)};
  const context=vm.createContext({document,window:{addEventListener:(name,fn)=>windowEvents.set(name,fn)},navigator:{userAgent:'test'},fetch:fetcher,AbortController,setTimeout:()=>1,clearTimeout(){},setInterval(fn,ms){intervals.push({fn,ms});},Date,Promise,Error});
  vm.runInContext(code,context);return {nodes,document,context,intervals,documentEvents,windowEvents};
}
const tick=()=>new Promise(setImmediate);
function response(url,items=[]){return {ok:true,json:async()=>url==='/api/health'?{ok:true}:url==='/api/config'?{pushConfigured:false}:{items}};}
test('visible page refreshes every minute and on return without changing the local filter',async()=>{
  let calls=0;const c=client(async url=>{calls++;return response(url);});await tick();
  assert.equal(calls,3);assert.equal(c.intervals[0].ms,60000);
  c.nodes.get('filter').value='opscore';c.document.hidden=true;c.intervals[0].fn();await tick();assert.equal(calls,3);
  c.document.hidden=false;c.documentEvents.get('visibilitychange')();await tick();assert.equal(calls,6);
  assert.equal(c.nodes.get('filter').value,'opscore');
  c.intervals[0].fn();await tick();assert.equal(calls,9);
  assert.match(c.nodes.get('refreshInfo').textContent,/列表每分钟刷新/);
});
test('overlapping focus/timer/manual refreshes share the in-flight request',async()=>{
  let calls=0;const resolve=[];const c=client(url=>{calls++;return new Promise(r=>resolve.push(()=>r(response(url))));});
  c.intervals[0].fn();c.windowEvents.get('focus')();await vm.runInContext('load()',c.context);assert.equal(calls,3);
  resolve.forEach(r=>r());await tick();assert.match(c.nodes.get('refreshInfo').textContent,/列表每分钟刷新/);
});
test('temporary refresh failure keeps the existing feed for the next retry',async()=>{
  let offline=false;const c=client(async url=>{if(offline)throw Error('offline');return response(url,[{itemId:'test',title:'Existing listing',url:'https://www.ebay.com/itm/123456789012'}]);});await tick();
  const children=c.nodes.get('items').children;assert.equal(children.length,1);
  offline=true;c.intervals[0].fn();await tick();assert.equal(c.nodes.get('items').children,children);
  assert.match(c.nodes.get('refreshInfo').textContent,/刷新失败/);
  offline=false;c.intervals[0].fn();await tick();assert.match(c.nodes.get('refreshInfo').textContent,/列表每分钟刷新/);
});
