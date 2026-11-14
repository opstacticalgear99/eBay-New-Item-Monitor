'use strict';
const fs=require('fs'),path=require('path');
const states=new Set(['running','ok','partial','failed','rate_limited']);
function date(value){return typeof value==='string'&&Number.isFinite(Date.parse(value))?value:null;}
function integer(value){return Number.isSafeInteger(value)&&value>=0?value:null;}
function rates(value){return Array.isArray(value)?value.slice(0,10).map(r=>({limit:integer(r.limit),remaining:integer(r.remaining),timeWindow:integer(r.timeWindow),reset:date(r.reset)})):[];}
function sanitize(input){
  if(!input||!states.has(input.state)||input.intervalMinutes!==15||!date(input.startedAt))throw Error('Invalid status');
  const result={state:input.state,intervalMinutes:15,startedAt:date(input.startedAt),finishedAt:date(input.finishedAt),lastSuccessAt:date(input.lastSuccessAt)};
  for(const key of ['ebay','websites']){const s=input[key];if(s&&states.has(s.state))result[key]={state:s.state,startedAt:date(s.startedAt),finishedAt:date(s.finishedAt),warnings:integer(s.warnings),errors:integer(s.errors),requests:integer(s.requests),pendingDeliveries:integer(s.pendingDeliveries)};}
  const q=input.quota||{};result.quota={state:q.state==='available'?'available':'unavailable',checkedAt:date(q.checkedAt),rates:rates(q.rates),lastKnown:rates(q.lastKnown),lastKnownAt:date(q.lastKnownAt)};
  return result;
}
module.exports=function(app,{dir,token}){
  const file=path.join(dir,'monitor-status.json');
  app.get('/api/monitor/status',(req,res)=>{res.set('Cache-Control','no-store');try{res.json(JSON.parse(fs.readFileSync(file,'utf8')));}catch(e){if(e.code==='ENOENT')res.json({state:'unknown',intervalMinutes:null});else res.status(503).json({error:'Status unavailable'});}});
  app.post('/api/monitor/status',(req,res)=>{
    if(!token||req.get('authorization')!=='Bearer '+token)return res.status(401).json({error:'Unauthorized'});
    let status;try{status=sanitize(req.body);}catch(_){return res.status(400).json({error:'Invalid monitor status'});}
    try{fs.writeFileSync(file+'.tmp',JSON.stringify(status),{mode:0o600});fs.renameSync(file+'.tmp',file);res.json({ok:true});}catch(_){res.status(503).json({error:'Cannot save status'});}
  });
};
module.exports.sanitize=sanitize;
