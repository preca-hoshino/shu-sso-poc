# shu-sso-poc

上海大学（SHU）统一身份认证 SSO 登录 POC —— 一次登录，向 3 个业务系统分别换取授权并验证登录。

## 协议

OAuth 2.0 授权码模式（RFC 6749），**非 OIDC**。

- SSO 会话 Cookie：`SHU_OAUTH2`（newsso 域，可跨系统复用）
- 登录：`POST /oauth/userLogin`（密码 RSA-PKCS1v15 加密 → base64）
- 2FA：`POST /oauth/twoStep/send` + `POST /oauth/twoStep/verify`
- 授权：`GET /oauth/authorize`

关键结论：**授权码一次性、绑定 state 不可复用**；但 SSO 会话 Cookie 在 newsso 域内可被多系统复用。

## 使用

```bash
pip install requests cryptography
python shu_sso_verify.py               # 交互式
python shu_sso_verify.py --method wecom   # 指定 2FA 方式
```

交互流程：输入学号 → 输入密码（不回显）→ 选择 2FA（1 企业微信 / 2 短信）→ 输入验证码 → 自动登录 3 个系统并输出结果。

## 目标系统

| key | 系统 | 备注 |
|---|---|---|
| `jwxt` | 本科生教务系统 | 自行生成 state |
| `otp` | OTP 令牌 | 先向其要 state |
| `bbs` | 上大 bbs（乐乎）| 先向其要 state，再改走 newsso 授权 |

每个系统 state 策略不同：`jwxt` 自生成随机 state；`otp`、`bbs` 需先访问自身入口预取 state（OTP 回调还依赖 `Refresh` 头跳转）。

## 企业微信扫码确认 URL

脚本登录成功后，会通过纯 HTTP 请求（无需扫码）还原出「企业微信扫码后打开的确认页地址」：

```text
https://open.work.weixin.qq.com/wwopen/sso/confirm2?k=<key>&notretry=yes
```

原理：

1. newsso 前端用企微官方 `WwLogin` SDK 在 `#ww_login_container` 里渲染一个 iframe，src 指向企微 `qrConnect` 页面。
2. `qrConnect` 页面直接返回 HTML，其中内嵌 `qrImg?key=<hex>`（key 为企微扫码会话标识）。
3. 解码该二维码 PNG，其内容就是 `confirm2?k=<同一个key>&notretry=yes`。

因此脚本通过 `wecom_qrcode_info()` 请求 `qrConnect` 并解析出 `key`，即可拼出扫码后确认 URL，完全避开扫码步骤。

企微参数（`appid` / `agentid` / `redirect_uri`）硬编码在脚本的 `WECOM` 常量中，来自 newsso 前端 bundle。

### 一键在企业微信内打开（scheme）

上面那个 `confirm2` 地址是**网页**，在电脑浏览器里打开只会显示「正在跳转到企业微信…」。要真正触发确认，需要让它在**企业微信客户端内置浏览器**里打开。

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
