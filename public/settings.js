'use strict';
const el = id => document.getElementById(id);
let token = '', current = null;
function message(text, error=false) {
  el('settingsMessage').textContent=text;
  el('settingsMessage').classList.toggle('error',error);
}
async function request(method, body, endpoint="/api/monitor/settings") {
  const response=await fetch(endpoint, {
    method, cache:'no-store', credentials:'omit', redirect:'error',
    headers:{Authorization:'Bearer '+token, 'Content-Type':'application/json'},
    ...(body ? {body:JSON.stringify(body)} : {})
  });
  const type=response.headers.get('content-type') || '';
  const text=await response.text();
  let data;
  try {
    if (!type.includes('application/json')) throw Error('non-json');
    data=JSON.parse(text);
  } catch (_) {
    throw Error('服务返回异常响应（HTTP '+response.status+'）。可能正在部署或暂时不可用，编辑内容已保留，请稍后重试。');
  }
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
  current=null; websiteCurrent=null; el('websiteFields').disabled=true; el('settingsFields').disabled=true; el('unlockSettings').disabled=true;
  message('正在读取…');
  try {
    show(await request('GET')); el('settingsFields').disabled=false; message('已读取当前配置，可以编辑。');
    try { showWebsites(await request('GET',null,'/api/monitor/websites')); el('websiteFields').disabled=false; websiteMessage('已读取网站列表，可以编辑。'); }
    catch(error) { websiteMessage(error.message || '网站读取失败，请重新读取设置。',true); }
  }
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
  try { show(await request('POST',body)); message('已保存。下一次定时检查会读取新配置；新增项先建立基线，不批量通知已有商品。'); }
  catch(error) { message(error.message || '保存失败，内容仍保留，请重试。',true); }
  finally { el('settingsFields').disabled=false; el('unlockSettings').disabled=false; }
});

let websiteCurrent=null;
function websiteMessage(text,error=false){el('websiteMessage').textContent=text;el('websiteMessage').classList.toggle('error',error);}
function websiteStatus(row){
  const status=row.querySelector('.website-status');
  let supported=false;
  try{const u=new URL(row.querySelector('.website-url').value);supported=u.protocol==='https:'&&['ronintactics.com','www.ronintactics.com','forwardobservations.com','www.forwardobservations.com'].includes(u.hostname)&&u.pathname==='/';}catch(_){}
  const enabled=row.querySelector('.website-enabled').checked;
  const alerts=row.querySelector('.website-new').checked||row.querySelector('.website-restock').checked;
  status.textContent=!supported?'待适配，尚未运行':!enabled?'已停用':!alerts?'提醒已关闭':'已支持 · '+(row.querySelector('.website-name').value||'网站监控');
  status.classList.toggle('pending',!supported);
}
function addWebsite(site={name:'',url:'',enabled:true,new_products:true,restocks:true}){
  const row=el('websiteTemplate').content.firstElementChild.cloneNode(true);
  row.querySelector('.website-name').value=site.name;
  row.querySelector('.website-url').value=site.url;
  row.querySelector('.website-enabled').checked=site.enabled;
  row.querySelector('.website-new').checked=site.new_products;
  row.querySelector('.website-restock').checked=site.restocks;
  row.querySelector('.remove-website').addEventListener('click',()=>{row.remove();websiteMessage('已从编辑列表移除，点击保存后生效。');});
  row.addEventListener('input',()=>websiteStatus(row));
  el('websiteRows').append(row);websiteStatus(row);
}
function showWebsites(data){websiteCurrent=data;el('websiteRows').replaceChildren();data.sites.forEach(addWebsite);}
el('addWebsite').addEventListener('click',()=>{if(el('websiteRows').children.length>=12)return websiteMessage('最多可保存 12 个网站。',true);addWebsite();websiteMessage('填写网站名称和 HTTPS 首页网址，再保存。');});
el('websitesForm').addEventListener('submit',async event=>{
  event.preventDefault();if(!websiteCurrent)return;
  const sites=Array.from(el('websiteRows').children).map(row=>({name:row.querySelector('.website-name').value.trim(),url:row.querySelector('.website-url').value.trim(),enabled:row.querySelector('.website-enabled').checked,new_products:row.querySelector('.website-new').checked,restocks:row.querySelector('.website-restock').checked}));
  el('websiteFields').disabled=true;el('unlockSettings').disabled=true;websiteMessage('正在保存网站列表…');
  try{showWebsites(await request('POST',{revision:websiteCurrent.revision,sites},'/api/monitor/websites'));websiteMessage('网站设置已保存，下次检查读取。待适配的网站不会自动运行。');}
  catch(error){websiteMessage(error.message||'保存失败，编辑内容仍保留。',true);}
  finally{el('websiteFields').disabled=false;el('unlockSettings').disabled=false;}
});
