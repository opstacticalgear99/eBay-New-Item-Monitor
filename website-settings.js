'use strict';
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),net=require('node:net');
const defaults=require('./website-defaults.json');
const supported=new Map([['ronintactics.com',['ronin','https://www.ronintactics.com/']],['www.ronintactics.com',['ronin','https://www.ronintactics.com/']],['forwardobservations.com',['fog','https://forwardobservations.com/']],['www.forwardobservations.com',['fog','https://forwardobservations.com/']]]);
function validate(value){
  if(!value||!Array.isArray(value.sites)||value.sites.length>12)throw Error('最多可保存 12 个网站。');
  const seen=new Set();
  const sites=value.sites.map(site=>{
    if(!site||typeof site.name!=='string'||!site.name.trim()||site.name.length>80||typeof site.url!=='string'||site.url.length>500)throw Error('请填写网站名称（最多 80 个字符）和 HTTPS 首页网址。');
    let u;try{u=new URL(site.url.trim());}catch(_){throw Error('网站网址格式不正确。');}
    if(u.protocol!=='https:'||u.username||u.password||u.port||net.isIP(u.hostname)||!u.hostname.includes('.')||/(^|\.)(localhost|local|internal)$/.test(u.hostname)||u.pathname!=='/'||u.search||u.hash)throw Error('请输入公开网站的 HTTPS 首页地址，不要填写账号密码、商品路径或查询参数。');
    const match=supported.get(u.hostname);const url=match?match[1]:u.origin+'/';
    const id=match?match[0]:'site-'+crypto.createHash('sha256').update(url).digest('hex').slice(0,16);
    if(seen.has(id))throw Error('同一网站只能添加一次。');seen.add(id);
    for(const key of ['enabled','new_products','restocks'])if(typeof site[key]!=='boolean')throw Error('网站开关格式不正确。');
    return {id,name:site.name.trim(),url,enabled:site.enabled,new_products:site.new_products,restocks:site.restocks};
  });return {sites};
}
function decorate(data){return {...data,sites:data.sites.map(site=>({...site,supported:site.id==='ronin'||site.id==='fog',status:!['ronin','fog'].includes(site.id)?'待适配，尚未运行':!site.enabled?'已停用':!site.new_products&&!site.restocks?'提醒已关闭':'已支持'}))};}
module.exports=function(app,{dir,authorized}){
  const file=path.join(dir,'website-settings.json');
  const revision=data=>crypto.createHash('sha256').update(JSON.stringify(data)).digest('hex');
  function read(){try{return validate(JSON.parse(fs.readFileSync(file,'utf8')));}catch(e){if(e.code==='ENOENT')return validate(defaults);throw e;}}
  app.get('/api/monitor/websites',authorized,(req,res)=>{try{const data=read();res.json({...decorate(data),revision:revision(data)});}catch(_){res.status(503).json({error:'无法读取网站设置，已保留原数据。'});}});
  app.post('/api/monitor/websites',authorized,(req,res)=>{
    let current;try{current=read();}catch(_){return res.status(503).json({error:'网站配置存储异常，已停止覆盖。'});}
    if(!req.body||req.body.revision!==revision(current))return res.status(409).json({error:'网站列表已更新，请重新读取后编辑。'});
    let data;try{data=validate(req.body);}catch(e){return res.status(400).json({error:e.message});}
    try{fs.writeFileSync(file+'.tmp',JSON.stringify(data,null,2)+'\n',{mode:0o600});fs.renameSync(file+'.tmp',file);res.json({...decorate(data),revision:revision(data),ok:true});}
    catch(_){res.status(503).json({error:'保存网站列表失败，编辑内容已保留。'});}
  });
};
module.exports.validate=validate;
