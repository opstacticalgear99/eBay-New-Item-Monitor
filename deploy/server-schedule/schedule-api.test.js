const {test}=require('node:test'),assert=require('node:assert/strict'),mount=require('./schedule-api');
function app(controller,options={}){const routes={};mount({get:(p,f)=>routes.GET=f,post:(p,f)=>routes.POST=f},{adminPassword:'admin-test',token:'machine-test',controller,...options});return routes;}
function response(){return {code:200,set(){},status(n){this.code=n;return this;},json(v){this.body=v;return this;}};}
function request(auth,body={enabled:false,expectedEnabled:true}){return{get:()=>auth,body};}
test('unauthenticated/wrong/machine token cannot change schedule with admin password configured',async()=>{
 let calls=0;const r=app(async()=>{calls++;});
 for(const auth of ['', 'Bearer wrong','Bearer machine-test']){const res=response();await r.POST(request(auth),res);assert.equal(res.code,401);}assert.equal(calls,0);
});
test('valid admin gets actual controller result; malicious arguments rejected',async()=>{
 const calls=[];const r=app(async(...args)=>{calls.push(args);return{code:200,data:{enabled:false,active:false}};});
 const res=response();await r.POST(request('Bearer admin-test'),res);assert.equal(res.body.enabled,false);assert.deepEqual(calls,[['POST',{enabled:false,expectedEnabled:true}]]);
 const bad=response();await r.POST(request('Bearer admin-test',{enabled:false,expectedEnabled:true,unit:'sshd'}),bad);assert.equal(bad.code,400);assert.equal(calls.length,1);
});
test('controller errors never claim a successful toggle or expose internals',async()=>{
 const r=app(async()=>{throw Error('secret internal path');});const res=response();await r.POST(request('Bearer admin-test'),res);assert.equal(res.code,503);assert.ok(!JSON.stringify(res.body).includes('secret'));
});
test('overlapping toggles rejected and stale state conflicts propagated',async()=>{
 let resolve;const r=app(()=>new Promise(r=>resolve=r));const one=response(),two=response();const first=r.POST(request('Bearer admin-test'),one);await r.POST(request('Bearer admin-test'),two);assert.equal(two.code,409);resolve({code:409,data:{error:'internal'}});await first;assert.equal(one.code,409);
});
test('legacy fallback preserved, but missing all secrets refuses changes',async()=>{
 const r=app(async()=>({code:200,data:{enabled:false}}),{adminPassword:''});const a=response();await r.POST(request('Bearer machine-test'),a);assert.equal(a.code,200);
 const none=app(async()=>{throw Error('must not call');},{adminPassword:'',token:''});const b=response();await none.POST(request(''),b);assert.equal(b.code,503);
});
