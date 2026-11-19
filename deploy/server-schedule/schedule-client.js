'use strict';
(function(){
  const box=document.getElementById('schedulePanel');if(!box)return;
  const status=document.getElementById('scheduleState'),help=document.getElementById('scheduleHelp'),button=document.getElementById('scheduleToggle'),refresh=document.getElementById('scheduleRefresh');
  let current=null,busy=false,reading=false;
  function draw(){button.disabled=busy||!current||!token||document.getElementById('settingsFields').disabled;refresh.disabled=busy||reading;button.textContent=busy?'正在更新…':current?.enabled?'暂停 Schedule':'启用 Schedule';}
  function show(data){
    if(typeof data.enabled!=='boolean'||typeof data.active!=='boolean')throw Error('Schedule 状态无效。');
    current=data;
    status.textContent=data.enabled&&data.active?'已启用 · 每 15 分钟检查':!data.enabled&&!data.active?'已暂停 · 不再定时检查':'配置与运行状态不一致，请重新启停或检查 Server';
    status.classList.toggle('error',data.enabled!==data.active);
    help.textContent=(data.scanRunning?'当前扫描仍在进行，会正常完成。':'当前没有扫描运行。')+(data.enabled&&data.active&&data.nextRun?'下次计划：'+data.nextRun:'')+' 暂停后历史记录保留；恢复时可能补执行一次错过的扫描。';
    draw();
  }
  async function load(){
    if(busy||reading)return;reading=true;draw();
    try{show(await request('GET',null,'/api/monitor/schedule'));}
    catch(e){current=null;status.textContent=e.message||'无法读取 Schedule 状态。';status.classList.add('error');help.textContent='状态未确认，启停按钮暂不可用。';}
    finally{reading=false;draw();}
  }
  button.addEventListener('click',async()=>{
    if(busy||!current||!token)return;
    const desired=!current.enabled,previous=current.enabled;busy=true;draw();status.textContent=desired?'正在启用 Schedule…':'正在暂停 Schedule…';
    try{show(await request('POST',{enabled:desired,expectedEnabled:previous},'/api/monitor/schedule'));}
    catch(e){current=null;status.textContent=e.message||'操作未确认成功，请刷新检查。';status.classList.add('error');help.textContent='请刷新 Schedule 状态后再操作。';}
    finally{busy=false;draw();}
  });
  refresh.addEventListener('click',load);
  // The existing password remains only in the settings page's memory.
  document.getElementById('unlockForm').addEventListener('submit',()=>{current=null;draw();setTimeout(load,0);});
  setInterval(()=>{if(!document.hidden){if(current)draw();load();}},30000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)load();});
  new MutationObserver(draw).observe(document.getElementById('settingsFields'),{attributes:true,attributeFilter:['disabled']});
  load();
})();
