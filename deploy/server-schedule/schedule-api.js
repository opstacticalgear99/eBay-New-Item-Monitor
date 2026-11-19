'use strict';
const http=require('http'),crypto=require('crypto');
function control(method,body){
  return new Promise((resolve,reject)=>{
    const raw=body?JSON.stringify(body):null;
    const req=http.request({socketPath:'/run/fieldwatch-schedule/control.sock',path:'/schedule',method,
      headers:raw?{'Content-Type':'application/json','Content-Length':Buffer.byteLength(raw)}:{}},res=>{
      let data='';res.on('data',chunk=>{data+=chunk;if(data.length>8192)req.destroy(Error('Oversized response'));});
      res.on('end',()=>{try{resolve({code:res.statusCode,data:JSON.parse(data)});}catch(_){reject(Error('Invalid controller response'));}});
    });
    req.setTimeout(10000,()=>req.destroy(Error('Schedule timeout')));req.on('error',reject);req.end(raw);
  });
}
module.exports=function(app,{adminPassword='',token='',controller=control}){
  let changing=false;
  app.get('/api/monitor/schedule',async(req,res)=>{
    res.set('Cache-Control','no-store');
    try{const result=await controller('GET');res.status(result.code).json(result.data);}
    catch(_){res.status(503).json({error:'无法读取 Schedule 状态，请稍后重试。'});}
  });
  app.post('/api/monitor/schedule',async(req,res)=>{
    res.set('Cache-Control','no-store');
    const secret=adminPassword||token;
    if(!secret)return res.status(503).json({error:'请先配置管理员口令。'});
    const expected=Buffer.from('Bearer '+secret),supplied=Buffer.from(req.get('authorization')||'');
    if(supplied.length!==expected.length||!crypto.timingSafeEqual(expected,supplied))return res.status(401).json({error:'管理员口令不正确或无操作权限。'});
    const body=req.body;
    if(!body||Object.keys(body).sort().join(',')!=='enabled,expectedEnabled'||typeof body.enabled!=='boolean'||typeof body.expectedEnabled!=='boolean')return res.status(400).json({error:'Schedule 参数无效。'});
    if(changing)return res.status(409).json({error:'正在修改 Schedule，请稍后刷新。'});
    changing=true;
    try{const result=await controller('POST',body);res.status(result.code).json(result.code===200?result.data:{error:result.code===409?'Schedule 已发生变化，请刷新后重试。':'操作未确认成功，请刷新检查实际状态。'});}
    catch(_){res.status(503).json({error:'操作未确认成功，请刷新检查实际状态。'});}
    finally{changing=false;}
  });
};
