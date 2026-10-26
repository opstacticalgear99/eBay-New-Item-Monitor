'use strict';
const el = id => document.getElementById(id);
let token = '', current = null;
function message(text, error=false) {
  el('settingsMessage').textContent=text;
  el('settingsMessage').classList.toggle('error',error);
}
async function request(method, body) {
  const response=await fetch('/api/monitor/settings', {
    method, cache:'no-store', credentials:'omit', redirect:'error',
    headers:{Authorization:'Bearer '+token, 'Content-Type':'application/json'},
    ...(body ? {body:JSON.stringify(body)} : {})
  });
  const data=await response.json();
  if (!response.ok) throw Error(data.error || '请求失败，请重试。');
  return data;
}
function lines(id) { return el(id).value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean); }
function show(data) {
  current=data;
  el('brandQueries').value=data.brands.map(x=>x.query).join('\n');
  el('sellerNames').value=data.sellers.join('\n');
}
el('unlockForm').addEventListener('submit',async event=>{
  event.preventDefault();
  token=el('settingsToken').value.trim(); el('settingsToken').value='';
  current=null; el('settingsFields').disabled=true; el('unlockSettings').disabled=true;
  message('正在读取…');
  try { show(await request('GET')); el('settingsFields').disabled=false; message('已读取当前配置，可以编辑。'); }
  catch(error) { token=''; message(error.message || '读取失败，请重新输入密钥。',true); }
  finally { el('unlockSettings').disabled=false; }
});
el('settingsForm').addEventListener('submit',async event=>{
  event.preventDefault(); if (!current) return;
  const queries=lines('brandQueries'), sellers=lines('sellerNames');
  if (!queries.length || queries.length>50 || !sellers.length || sellers.length>20) return message('请填写 1–50 个关键词、1–20 个卖家。',true);
  const labels=new Map(current.brands.map(x=>[x.query,x.label]));
  const body={revision:current.revision, brands:queries.map(query=>({query,label:labels.get(query)||query})), sellers};
  el('settingsFields').disabled=true; el('unlockSettings').disabled=true; message('正在保存…');
  try { show(await request('PUT',body)); message('已保存。下一次定时检查会读取新配置；新增项先建立基线，不批量通知已有商品。'); }
  catch(error) { message(error.message || '保存失败，内容仍保留，请重试。',true); }
  finally { el('settingsFields').disabled=false; el('unlockSettings').disabled=false; }
});
