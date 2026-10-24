# eBay 全新商品邮件监控（GitHub Actions）

监控关键词：SureFire、S&S Precision、Vans DEFCON、Mystery Ranch。默认每小时运行一次，将新发现的 eBay 全新商品提醒发到指定 Gmail。

## 重要说明

- 这只是部署包，尚未在你的 GitHub 账号中部署。你需要创建仓库、eBay 开发者应用并添加 GitHub Secrets。
- GitHub 定时任务可能延迟，不保证每小时整点准时运行。
- 程序使用 eBay Browse API 的 condition ID 1000（New）筛选，并按商品 ID 去重。关键词搜索无法保证覆盖所有新品；请打开商品页面复核商品描述、卖家及配件。
- 首次成功运行只建立基线，不发送历史商品邮件。之后发现新商品才发送提醒。
- 默认搜索 eBay 美国站（EBAY_US）。

## 1. 创建 GitHub 仓库

1. 打开 https://github.com/ 注册并验证账号。
2. 登录后点右上角 `+` → `New repository`。
3. 仓库名填写 `ebay-new-item-monitor`，选择 **Private**，创建仓库。
4. 将本包中的 `monitor.py`、`requirements.txt`、`README_中文.md` 上传到仓库根目录。
5. 将 `.github/workflows/hourly-monitor.yml` 上传到仓库对应的 `.github/workflows/` 目录，保持目录结构。

## 2. 创建 eBay API 凭据

1. 打开 https://developer.ebay.com/ 并登录/注册。
2. 进入 Application Keys，创建 Production 应用密钥。
3. 保存 Production 的 **Client ID (App ID)** 和 **Client Secret (Cert ID)**。
4. 官方参考：https://developer.ebay.com/develop/api/buy

## 3. Gmail 发信授权

本方案用 `opstacticalgear99@gmail.com` 同时作为发件人和收件人。Google 账号需开启两步验证，并生成 **App password（应用专用密码）**。不要使用普通 Gmail 登录密码。

官方说明：https://support.google.com/accounts/answer/185833

如果没有应用专用密码选项，不要把普通密码填进去；请先选择其他邮件发送方案。

## 4. 添加 GitHub Secrets

进入仓库 `Settings` → `Secrets and variables` → `Actions` → `New repository secret`，分别添加：

| Name | Value |
|---|---|
| `EBAY_CLIENT_ID` | eBay Production Client ID / App ID |
| `EBAY_CLIENT_SECRET` | eBay Production Client Secret / Cert ID |
| `GMAIL_ADDRESS` | `opstacticalgear99@gmail.com` |
| `GMAIL_APP_PASSWORD` | Google 应用专用密码 |
| `ALERT_TO` | `opstacticalgear99@gmail.com` |

不要把密钥写进代码或发到聊天里。

## 5. 手动测试

1. 打开仓库 `Actions`。
2. 选择 `eBay hourly new-item monitor`。
3. 点击 `Run workflow`，确认运行。
4. 首次成功运行应建立 `seen_items.json` 基线，不发邮件。
5. 后续新出现的商品才触发邮件；没有新品时不发信。
6. 在 Actions 页面查看运行日志。

## 故障排查

- `Missing required environment variable`：检查 Secrets 名称。
- eBay 401 / `invalid_client`：核对 Production Client ID/Secret 是否正确。
- Gmail 登录失败：确认开启两步验证并使用应用专用密码。
- `git push` 被拒绝：在仓库 `Settings` → `Actions` → `General` → `Workflow permissions` 允许读写仓库内容。
- 监控只覆盖 API 返回的关键词结果，不是全站实时新品数据流。
