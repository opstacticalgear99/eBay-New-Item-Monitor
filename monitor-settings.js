'use strict';
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const defaults = require('./monitor-defaults.json');

module.exports = function registerSettings(app, {dir, token}) {
  const file = path.join(dir, 'monitor-settings.json');
  function read() {
    try { return validate(JSON.parse(fs.readFileSync(file, 'utf8'))); }
    catch (error) { if (error.code === 'ENOENT') return defaults; throw error; }
  }
  function validate(value) {
    if (!value || !Array.isArray(value.brands) || value.brands.length < 1 || value.brands.length > 50 ||
        !Array.isArray(value.sellers) || value.sellers.length < 1 || value.sellers.length > 20) {
      throw Error('请保留 1–50 个品牌关键词和 1–20 个卖家。');
    }
    const brands = value.brands.map(entry => {
      if (!entry || typeof entry.query !== 'string' || typeof entry.label !== 'string') throw Error('关键词格式无效。');
      const query = entry.query.trim(), label = entry.label.trim();
      if (!query || !label || query.length > 120 || label.length > 120 || /[\r\n]/.test(query + label)) throw Error('每个关键词需为 1–120 个字符，且只能占一行。');
      return {label, query};
    });
    const sellers = value.sellers.map(seller => {
      if (typeof seller !== 'string' || !/^[A-Za-z0-9_.*-]{1,64}$/.test(seller.trim())) throw Error('卖家请输入 eBay 用户名，不要填写网址。');
      return seller.trim();
    });
    if (new Set(brands.map(x=>x.query.toLowerCase())).size !== brands.length || new Set(sellers.map(x=>x.toLowerCase())).size !== sellers.length) throw Error('请删除重复的关键词或卖家。');
    return {brands, sellers};
  }
  function revision(data) { return crypto.createHash('sha256').update(JSON.stringify(data)).digest('hex'); }
  function authorized(req, res, next) {
    res.set('Cache-Control', 'no-store');
    if (!token) return res.status(503).json({error:'尚未配置管理密钥。'});
    const supplied = Buffer.from(req.get('authorization') || ''), expected = Buffer.from('Bearer ' + token);
    if (supplied.length !== expected.length || !crypto.timingSafeEqual(supplied, expected)) return res.status(401).json({error:'管理密钥不正确。'});
    next();
  }
  require('./website-settings')(app,{dir,authorized});
  app.get('/api/monitor/settings', authorized, (req,res)=>{
    try { const data=read(); res.json({...data, revision:revision(data)}); }
    catch (_) { res.status(503).json({error:'无法读取已保存的设置，请检查服务存储。'}); }
  });
  function saveSettings(req,res) {
    let current;
    try { current=read(); }
    catch (_) { return res.status(503).json({error:'无法读取已保存的设置，已停止覆盖。'}); }
    if (!req.body || req.body.revision !== revision(current)) return res.status(409).json({error:'设置已发生变化，请重新读取后编辑。'});
    let data;
    try { data=validate(req.body); }
    catch (error) { return res.status(400).json({error:error.message}); }
    try {
      fs.writeFileSync(file+'.tmp', JSON.stringify(data,null,2)+'\n', {mode:0o600});
      fs.renameSync(file+'.tmp', file);
      res.json({...data, revision:revision(data), ok:true});
    } catch (_) { res.status(503).json({error:'保存失败，请稍后重试。'}); }
  }
  app.post('/api/monitor/settings', authorized, saveSettings);
  app.put('/api/monitor/settings', authorized, saveSettings);
};
