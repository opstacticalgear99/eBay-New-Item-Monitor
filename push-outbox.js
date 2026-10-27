'use strict';
const fs=require('node:fs'),crypto=require('node:crypto');

// Persist separately from the product feed: accepting an item must not lose a
// notification just because Apple/another Push service is temporarily down.
module.exports=function createPushOutbox({file,send,subscriptions,expire,now=Date.now}){
  let queue=[];
  try{queue=JSON.parse(fs.readFileSync(file,'utf8'));if(!Array.isArray(queue))throw Error('Invalid Push outbox');}
  catch(e){if(e.code!=='ENOENT')throw e;}
  let draining=null;
  function save(){fs.writeFileSync(file+'.tmp',JSON.stringify(queue),{mode:0o600});fs.renameSync(file+'.tmp',file);}
  function enqueue(items){
    if(!items.length)return;
    const targets=subscriptions().map(s=>s.endpoint);
    if(!targets.length)return;
    const id=crypto.createHash('sha256').update(JSON.stringify(items.map(i=>i.itemId).sort())).digest('hex').slice(0,24);
    if(queue.some(e=>e.id===id))return;
    const payload=JSON.stringify({title:items.length===1?'FieldWatch · 新品/补货':`FieldWatch · 发现 ${items.length} 件商品更新`,body:items.length===1?items[0].title+(items[0].price?' · '+items[0].price:''):items.slice(0,3).map(i=>i.title).join('；'),url:'/',tag:'fieldwatch-'+id});
    queue.push({id,payload,targets,createdAt:now()});save();
  }
  async function run(){
    let pushSent=0,pushFailed=0;
    for(const entry of [...queue]){
      for(const endpoint of [...entry.targets]){
        const subscription=subscriptions().find(s=>s.endpoint===endpoint);
        if(!subscription){entry.targets=entry.targets.filter(v=>v!==endpoint);save();continue;}
        try{
          await send(subscription,entry.payload,{TTL:86400,urgency:'high',timeout:10000});
          pushSent++;entry.targets=entry.targets.filter(v=>v!==endpoint);save();
        }catch(e){
          pushFailed++;
          if(e.statusCode===404||e.statusCode===410){expire(endpoint);entry.targets=entry.targets.filter(v=>v!==endpoint);save();}
          else console.error('Push delivery queued for retry:',e.statusCode||'network');
        }
      }
      if(!entry.targets.length){queue=queue.filter(e=>e!==entry);save();}
    }
    return {pushSent,pushFailed};
  }
  return {enqueue,drain(){if(!draining)draining=run().finally(()=>{draining=null;});return draining;},get pending(){return queue.length;}};
};
