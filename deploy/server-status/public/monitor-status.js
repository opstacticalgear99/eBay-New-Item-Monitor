'use strict';
(function(){
  const host=document.getElementById('monitorDetails');if(!host)return;
  const names={ok:'正常',partial:'部分失败',failed:'失败',running:'扫描中',rate_limited:'受 eBay 限流',unknown:'尚未收到扫描报告'};
  function at(value){return value?new Date(value).toLocaleString(): '暂无记录';}
  function line(label,text){const p=document.createElement('p');p.className='muted';p.textContent=label+'：'+text;host.append(p);}
  async function load(){
    try{
      const r=await fetch('/api/monitor/status',{cache:'no-store'});if(!r.ok)throw Error('unavailable');const s=await r.json();host.replaceChildren();
      const stale=s.startedAt&&Date.now()-Date.parse(s.startedAt)>((s.intervalMinutes||15)+10)*60000;
      const heading=document.createElement('strong');heading.textContent=stale?'扫描报告已超时，请检查 Server 定时任务':names[s.state]||names.unknown;
      heading.style.color=stale||['partial','failed','rate_limited'].includes(s.state)?'#f1787c':'#d7bf8c';host.append(heading);
      line('扫描频率',s.intervalMinutes?'每 '+s.intervalMinutes+' 分钟一次':'等待 Server 确认');
      line('最近开始',at(s.startedAt));line('最近完成',at(s.finishedAt));line('最近全部成功',at(s.lastSuccessAt));
      for(const [key,label] of [['ebay','eBay'],['websites','Ronin / FOG']]){const v=s[key];if(v)line(label,(names[v.state]||'未知')+' · '+at(v.finishedAt)+(key==='ebay'?' · 本次请求 '+(v.requests??'未知')+' · 待通知 '+(v.pendingDeliveries??'未知'):'')+' · 警告 '+(v.warnings??0));}
      const q=s.quota||{};if(q.state==='available'&&q.rates?.length){for(const rate of q.rates)line('eBay 官方额度','剩余 '+rate.remaining+' / '+rate.limit+'（'+(rate.timeWindow===86400?'每日':rate.timeWindow+' 秒窗口')+'） · 重置 '+at(rate.reset));line('额度查询时间',at(q.checkedAt));}
      else{line('eBay 官方额度','暂时无法获取，剩余数量未知');if(q.lastKnown?.length)line('上次额度记录',at(q.lastKnownAt)+' · 剩余 '+q.lastKnown.map(r=>r.remaining+'/'+r.limit).join('，')+'（非当前值）');}
      if(s.ebay?.state==='rate_limited')line('提醒','eBay 已限制请求，本轮后续搜索已停止；下次定时扫描再尝试。已有去重记录保留。');
      if(s.ebay?.pendingDeliveries)line('通知提醒','有通知尚未完成，将继续重试。');
    }catch(_){host.replaceChildren();line('监控状态','暂时无法读取，请稍后重试。接收端在线不代表扫描成功。');}
  }
  load();setInterval(()=>{if(!document.hidden)load();},60000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)load();});
})();
