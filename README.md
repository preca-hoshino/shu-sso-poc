# shu-sso-poc

上海大学（SHU）统一身份认证 SSO 登录 POC —— 一次登录，向 3 个业务系统分别换取授权并验证登录。

## 协议

OAuth 2.0 授权码模式（RFC 6749），**非 OIDC**。

- SSO 会话 Cookie：`SHU_OAUTH2`（newsso 域，可跨系统复用）
- 登录（密码）：`POST /oauth/userLogin`（密码 RSA-PKCS1v15 加密 → base64）
- 2FA：`POST /oauth/twoStep/send` + `POST /oauth/twoStep/verify`
- 登录（企微扫码）：企微 `qrConnect` 取 key → 长轮询 `/wwopen/sso/l/qrConnect` 拿 `auth_code` → `GET /oauth/wecom/qrcode`
- 授权：`GET /oauth/authorize`

关键结论：**授权码一次性、绑定 state 不可复用**；但 SSO 会话 Cookie 在 newsso 域内可被多系统复用。

## 使用

```bash
pip install requests cryptography
python shu_sso_verify.py                          # 交互式选择登录方式
python shu_sso_verify.py --login password         # 账号密码登录
python shu_sso_verify.py --login wecom_scan       # 企业微信扫码登录
python shu_sso_verify.py --method sms             # 账号密码登录时指定 2FA 方式
python shu_sso_verify.py --scan-timeout 300       # 扫码等待秒数（默认 180）
```

启动后先选择登录方式：

| 选项 | 模式 | 说明 |
| --- | --- | --- |
| `[1]` | `password` | 学号/工号 + 密码 + 两步验证（企业微信/短信），登录后自动跑通 3 个业务系统 |
| `[2]` | `wecom_scan` | 企业微信扫码，扫码确认后自动建立会话并登录 3 个业务系统 |

**账号密码模式**交互流程：输入学号 → 输入密码（不回显）→ 选择 2FA（1 企业微信 / 2 短信）→ 输入验证码 → 自动登录 3 个系统并输出结果。

**企微扫码模式**：脚本生成二维码 → 用企业微信扫码并确认 → 脚本长轮询拿到 `auth_code` → 换取 `SHU_OAUTH2` 会话 → 自动登录 3 个系统。输出示例：

```text
① 二维码图片 URL            https://open.work.weixin.qq.com/wwopen/sso/qrImg?key=<key>
② 二维码内容（确认页）      https://open.work.weixin.qq.com/wwopen/sso/confirm2?k=<key>&notretry=yes
③ 包装后的 URI 跳转         wxwork://sso/jump?url=<urlencode(②)>

等待扫码确认（最多 180 秒，Ctrl+C 可中断）...
     等待扫码
     已扫码，请在手机上确认
     已确认，正在换取会话
  ✓ 已取得 auth_code，换取 SSO 会话 ...
  ✓ SSO 会话已建立（Cookie: SHU_OAUTH2）
```

## 目标系统

| key | 系统 | 备注 |
|---|---|---|
| `jwxt` | 本科生教务系统 | 自行生成 state |
| `otp` | OTP 令牌 | 先向其要 state |
| `bbs` | 上大 bbs（乐乎）| 先向其要 state，再改走 newsso 授权 |

每个系统 state 策略不同：`jwxt` 自生成随机 state；`otp`、`bbs` 需先访问自身入口预取 state（OTP 回调还依赖 `Refresh` 头跳转）。

## 企业微信扫码登录

### 1. 拿到二维码 key

`qrConnect` 页面直接返回 HTML，其中内嵌 `qrImg?key=<hex>`（key 为企微扫码会话标识）：

```text
① 二维码图片 URL   https://open.work.weixin.qq.com/wwopen/sso/qrImg?key=<key>
② 二维码内容       https://open.work.weixin.qq.com/wwopen/sso/confirm2?k=<key>&notretry=yes
```

脚本用 `wecom_qrcode_info()` 请求 `qrConnect` 解析出 `key`，再解码二维码 PNG 可验证内容与 ② 一致。

企微参数（`appid` / `agentid` / `redirect_uri`）硬编码在 `WECOM` 常量中，来自 newsso 前端 bundle。

### 2. 长轮询等扫码结果

`qrConnect` 页面在 `window.settings` 里暴露了轮询地址（`longPollGetUrl = /wwopen/sso/l/qrConnect`），
浏览器对它发起 JSONP 长轮询。**用 Chrome DevTools 抓包确认**的请求与响应：

```text
GET https://open.work.weixin.qq.com/wwopen/sso/l/qrConnect
    ?callback=jsonpCallback&key=<key>
    &redirect_uri=<urlencode(回调)>&appid=<corpid>&_=<ts>
```

```json
jsonpCallback({"status":"QRCODE_SCAN_ING","auth_code":""})
```

状态机（逐个实测捕获）：

| status | 含义 |
| --- | --- |
| `QRCODE_SCAN_NEVER` | 未扫码 |
| `QRCODE_SCAN_ING` | 已扫码，等待手机确认 |
| `QRCODE_SCAN_SUCC` | 已确认，`auth_code` 有值 |
| `QRCODE_SCAN_ERR` | 二维码过期/失效 |

### 3. 用 auth_code 换 SSO 会话

```text
GET https://newsso.shu.edu.cn/oauth/wecom/qrcode
    ?code=<auth_code>&state=<paramsBase64>&appid=<corpid>
```

成功后响应 `302` 且下发 `SHU_OAUTH2` Cookie。

> ⚠️ 两个实测坑：
> - `state` 必须是 **base64url 无填充**（标准 base64 会返回 `{"message":"badRequestParams"}`）；
> - 回调**必须带 `appid`**（缺了同样报 `badRequestParams`）。

### 一键在企业微信内打开（scheme）

`confirm2` 地址是**网页**，在电脑浏览器里打开只会显示「正在跳转到企业微信…」。要真正触发确认，需要让它在**企业微信客户端内置浏览器**里打开。

企微官方 `confirm2` 页面本身就是这么做的——它的内联脚本里有：

```js
launchWWByScheme("wxwork://sso/jump?url=" + encodeURIComponent(
  "https://open.work.weixin.qq.com/wwopen/sso/confirm2?k=<key>"
), function (isOk) { WeixinJSBridge.invoke('closeWindow'); })
```

所以只需把 `confirm2` 地址包一层 `wxwork://sso/jump?url=`（URL 编码），脚本会直接输出这个链接：

```text
wxwork://sso/jump?url=https%3A%2F%2Fopen.work.weixin.qq.com%2Fwwopen%2Fsso%2Fconfirm2%3Fk%3D<key>%26notretry%3Dyes
```

在浏览器地址栏（或短信、聊天窗口里）点开它即可拉起企业微信并跳进内置浏览器完成确认。相关常量与字段：

| 位置 | 值 |
| --- | --- |
| `WECOM["scheme_jump_base"]` | `wxwork://sso/jump?url=` |
| 返回值 `wxwork_scheme` | 完整 scheme 链接 |

其他已知的 `wxwork://` 协议（备查，均非本流程所需）：

| 用途 | Scheme |
| --- | --- |
| 唤起企微（仅拉起 App） | `wxwork://` |
| 内置浏览器打开指定 URL | `wxwork://sso/jump?url=<urlencode(url)>` |
| webview 型模板内跳转（官方文档） | `wxwork://openurl?url=<urlencode(url)>` |
| 扫一扫 | `wxwork://platformId=wechat&wwact=qrcode` |
| 打开个人聊天窗口 | `wxwork://launch?launch_code=xxx` |

## 安全

- 密码经 `getpass` 读取，**不落盘、不打印、不写日志**
- 保存的证据 JSON 自动剔除 `password` / `code` 字段
- 证书校验按要求关闭（`verify=False`）
- 仅供参考学习，请勿用于未授权用途；验证请使用本人自己的账号

## 许可证

[AGPL-3.0](LICENSE)
