<div align="center">

# SHU SSO POC

上海大学统一身份认证（`newsso.shu.edu.cn`）OAuth 2.0 授权码流程验证工具 ——
**一次登录，向 jwxt / otp / bbs / webvpn / ds 五个业务系统分别换取授权并验证登录**

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Protocol](https://img.shields.io/badge/OAuth%202.0-RFC%206749-informational)](https://datatracker.ietf.org/doc/html/rfc6749)
[![License](https://img.shields.io/badge/License-AGPL--3.0-blue)](LICENSE)

</div>

---

## 流程解析

```mermaid
flowchart TD
    A["CLI · poc.py"] --> B{"登录方式"}
    B -->|账号密码| C["POST /oauth/userLogin<br/>密码 RSA-PKCS1v15 加密 → base64"]
    C --> D{"twoStepRequired?"}
    D -->|是| E["/oauth/twoStep/send<br/>/oauth/twoStep/verify"]
    D -->|否| F["建立 SHU_OAUTH2 会话"]
    E --> F
    B -->|企业微信扫码| G["qrConnect 取 key<br/>终端渲染二维码"]
    G --> H["长轮询 /wwopen/sso/l/qrConnect"]
    H --> I["GET /oauth/wecom/qrcode"]
    I --> F
    F --> J["遍历 config.SYSTEMS"]
    J --> K["GET /oauth/authorize"]
    K --> L{"该系统有 client.py？"}
    L -->|webvpn| M["POST /api/access/auth/finish<br/>GET /api/access/user/info"]
    L -->|ds| P["GET /dsssologin/getSsoUser<br/>看 isSussess 字段"]
    L -->|无| N["跟随 302 / Refresh 头换会话"]
    M --> O["汇总结果<br/>保存脱敏证据 JSON"]
    P --> O
    N --> O
```

整体流程：**认证 → 授权取码 → 换会话 → 汇总**。
其中认证有账号密码（①）与企业微信扫码（②）两条路径，任选其一、**全程只需一次**；
授权取码（③）与换会话（④）对每个业务系统独立执行。

### ① 认证：建立 SSO 会话

| 步骤 | 端点 | 请求体 |
| :--- | :--- | :--- |
| 登录 | `POST /oauth/userLogin` | `{username, password(RSA→base64), tenantId, params(base64url)}` |
| 发码 | `POST /oauth/twoStep/send` | `{method: sms \| wecom}` |
| 校验 | `POST /oauth/twoStep/verify` | `{username, password, tenantId, params, code, method}` |

- 密码以 RSA PKCS#1 v1.5 加密后 base64 提交，公钥来自 `rsa_key.public_key_pem()`（自动更新）；
- `params` **必填**，缺失直接返回 `badRequestParams`；
- 响应中 `twoStepRequired` 为真才进入两步验证；
- 成功后服务端下发 `SHU_OAUTH2`（HttpOnly，host-scoped 于 `newsso.shu.edu.cn`）。

### ② 认证（备选）：企业微信扫码

不输入密码，改由企微扫码确认身份，最终同样落到 `SHU_OAUTH2` 会话。

**取二维码 `key`** —— `GET /wwopen/sso/qrConnect` 直接返回 HTML，内嵌 `qrImg?key=<hex>`：

```text
① 二维码图片 URL   https://open.work.weixin.qq.com/wwopen/sso/qrImg?key=<key>
② 二维码内容       https://open.work.weixin.qq.com/wwopen/sso/confirm2?k=<key>&notretry=yes
```

企微参数（`appid` / `agentid` / `redirect_uri`）硬编码于 `config.WECOM`，来自 newsso 前端 bundle。

**长轮询等结果** —— 页面在 `window.settings.longPollGetUrl` 暴露轮询地址，以 JSONP 形式发起：

```text
GET https://open.work.weixin.qq.com/wwopen/sso/l/qrConnect
    ?callback=jsonpCallback&key=<key>
    &redirect_uri=<urlencode(回调)>&appid=<corpid>&_=<ts>
```

```json
jsonpCallback({"status":"QRCODE_SCAN_ING","auth_code":""})
```

| status | 含义 |
| :--- | :--- |
| `QRCODE_SCAN_NEVER` | 未扫码 |
| `QRCODE_SCAN_ING` | 已扫码，等待手机确认 |
| `QRCODE_SCAN_SUCC` | 已确认，`auth_code` 有值 |
| `QRCODE_SCAN_ERR` | 二维码过期 / 失效 |

**换 SSO 会话**

```text
GET https://newsso.shu.edu.cn/oauth/wecom/qrcode
    ?code=<auth_code>&state=<paramsBase64>&appid=<corpid>
```

成功后响应 `302` 并下发 `SHU_OAUTH2` Cookie。

> **⚠️ 两个必踩的坑**
>
> - `state` 必须是 **base64url 无填充**（标准 base64 会返回 `{"message":"badRequestParams"}`）；
> - 回调**必须携带 `appid`**，缺失同样报 `badRequestParams`。

**在企微内直接打开确认页** —— `confirm2` 是网页，桌面浏览器打开只会提示「正在跳转到企业微信…」。
官方页面用内联脚本 `launchWWByScheme("wxwork://sso/jump?url=" + encodeURIComponent(url))` 完成跳转，
本 POC 输出同样格式的链接：

```text
wxwork://sso/jump?url=https%3A%2F%2Fopen.work.weixin.qq.com%2Fwwopen%2Fsso%2Fconfirm2%3Fk%3D<key>%26notretry%3Dyes
```

在浏览器地址栏、短信或聊天窗口中打开即可唤起企微并跳入内置浏览器完成确认。

<details>
<summary><b>其他已知的 <code>wxwork://</code> 协议（备查，均非本流程所需）</b></summary>

| 用途 | Scheme |
| :--- | :--- |
| 唤起企微（仅拉起 App） | `wxwork://` |
| 内置浏览器打开指定 URL | `wxwork://sso/jump?url=<urlencode(url)>` |
| webview 型模板内跳转（官方文档） | `wxwork://openurl?url=<urlencode(url)>` |
| 扫一扫 | `wxwork://platformId=wechat&wwact=qrcode` |
| 打开个人聊天窗口 | `wxwork://launch?launch_code=xxx` |

</details>

### ③ 授权：逐系统换取 code

```text
GET /oauth/authorize?response_type=code&client_id=...&redirect_uri=...&scope=...&state=...
  └─ 302 Location: <redirect_uri>?code=...&state=...
```

| key | 系统 | `client_id` | 取到 code 后如何换会话 | 配置与说明 |
| :--- | :--- | :--- | :--- | :--- |
| `jwxt` | 本科生教务系统 | `Km5t225E8KECKQ6ZDm5K2P6aS2459Cua` | 跟随 `302` | [`systems/jwxt.shu.edu.cn/`](systems/jwxt.shu.edu.cn/README.md) |
| `otp` | OTP 令牌 | `05Q1L8woQK5350aK1U5o5GKh411ar3h1` | 跟随 `Refresh` 头跳转 | [`systems/otp.shu.edu.cn/`](systems/otp.shu.edu.cn/README.md) |
| `bbs` | 上大 bbs（乐乎社区） | `vp8G2H42GGE86LP822LHF6Hs7f46483H` | 跟随 `302` | [`systems/bbs.shu.edu.cn/`](systems/bbs.shu.edu.cn/README.md) |
| `webvpn` | WebVPN 访问控制系统 | `nn7sbb22j2tKE100T024tEp42777p755` | 私有接口两步握手（见 ④） | [`systems/webvpn.shu.edu.cn/`](systems/webvpn.shu.edu.cn/README.md) |
| `ds` | 千学百科（DeepSeek） | `re0owG1g776ng2eix7x3o8sa20W6OdA2` | 私有接口换 token（见 ④） | [`systems/ds.shu.edu.cn/`](systems/ds.shu.edu.cn/README.md) |

**`state` 策略各不相同**，是全流程最容易踩坑的一环：

| 系统 | 策略 |
| :--- | :--- |
| `jwxt` | 授权请求本就不带 `state`，由 POC 生成随机 UUID |
| `otp` | 需先访问 `https://otp.shu.edu.cn/` 预取 `state`（存于 `ASP.NET_SessionId`），否则回调报「State验证失败」 |
| `bbs` | 需先访问 `https://bbs.shu.edu.cn/auth/oauth2_basic` 向其索要 `state` |
| `webvpn` | `state` 为固定结构化值 `base64({"externalId": <认证方式ID>})`，非随机 |
| `ds` | 授权请求**完全不带 `state` / `scope`**（前端直接拼 URL） |

**Base64 有两种形态，不可混用**：

| 用途 | 编码 | 特点 |
| :--- | :--- | :--- |
| `params` 参数（`utils.b64_params`） | base64**url** | `-_` 字符集，**去除 `=` 填充** |
| WebVPN 的 `state` | 标准 base64 | `+/` 字符集，**保留 `=` 填充**（`btoa` 行为） |

新增业务系统**不用改 `src/`** —— 在 [`systems/`](systems/README.md) 下新建 `<系统域名>/config.py`
（导出 `SYSTEM` 字典），只有换会话不走「跟随 `302`」时才再加一个 `client.py`。
各系统的差异（`generate_state` / `needs_state_bootstrap` / `authorize_extra` /
`detection` 等）全部写在它自己的配置文件里，字段含义见 [`systems/README.md`](systems/README.md)。

### ④ 换会话：`code` → 系统会话

**通用路径**：跟随 `Location` 头跳转即完成（`otp` 例外，使用 `Refresh` 响应头而非标准 `302`）。

**WebVPN 例外**：目标站是纯前端 SPA，nginx 对**所有**路径都返回同一份 `index.html`，
因此不能靠跳转换会话，需调两个私有接口完成握手：

```text
① POST /api/access/auth/start
   {"externalId":"YJrvSXWl",
    "data":"{\"callbackUrl\":\"https://webvpn.shu.edu.cn/callback/oauth2\",
             \"state\":\"eyJleHRlcm5hbElkIjoiWUpydlNYV2wifQ==\"}"}
   ← {"code":0,"data":{"action":{"login_url":".../oauth/authorize?access_type=offline&..."}}}

② 浏览器跳转 login_url → newsso 302 回
   https://webvpn.shu.edu.cn/callback/oauth2?code=...&state=...

③ POST /api/access/auth/finish
   {"externalId":"YJrvSXWl",
    "data":"{\"callbackUrl\":\"...\",\"code\":\"<授权码>\",
             \"deviceId\":\"<32位hex>\",\"state\":\"...\"}"}
   ← {"code":0} 表示会话已建立（服务端持 code 向 newsso 换取 token）

④ GET /api/access/user/info
   ← {"code":0,"data":{"userId":...,"username":...}}   ← 判定登录成功的依据
```

客户端信息（从首页跳转的 `/oauth2/login/<paramsBase64>` 解出，经抓包核对）：

| 项 | 值 |
| :--- | :--- |
| `client_id` | `nn7sbb22j2tKE100T024tEp42777p755` |
| `redirect_uri` | `https://webvpn.shu.edu.cn/callback/oauth2` |
| `scope` | 空 |
| 额外授权参数 | `access_type=offline` |

实测约束：

- **`externalId` 是固定值而非随机值** —— 它是「认证方式」在服务端的 ID，由
  `GET /api/access/authentication/list?type=0` 下发（取 `authType == 5`，即 `Oauth2Type`）。
  实测值 `YJrvSXWl`，抓取失败时回退到该系统配置里的 `external_id_fallback`。
- **`deviceId` 必填** —— 缺失时 `auth/finish` 返回 `{"code":20001,"message":"DeviceId未找到"}`；
  提供任意非空值后即推进到 `20000 认证失败`（说明请求结构已正确）。
  前端取 FingerprintJS 的 `visitorId`（持久化于浏览器，故同一浏览器恒定）。
  POC 无浏览器指纹，使用 `md5("shu-sso-poc::" + 账号名)` 生成**稳定**伪指纹
  （`systems/webvpn.shu.edu.cn/client.py` 的 `device_id_for`），避免每次运行被服务端视为新设备。
- **WebVPN 会反代 newsso** —— `auth/start` 返回的 `login_url` 指向
  `https-newsso-shu-edu-cn-443.webvpn.shu.edu.cn`，规则为
  `<scheme>-<主机名中的 . 替换为 ->-<端口>.webvpn.shu.edu.cn`。
  而 POC 的 `SHU_OAUTH2` 由直连 `newsso.shu.edu.cn` 建立，**只有直连才能复用**，
  故 `client.unproxy_url()` 将反代主机还原为真实主机 —— 且**仅当还原结果以 `.shu.edu.cn`
  结尾时才改写**，避免携带 Cookie 的请求被送往意外主机。
- **该站无法用 URL / 正文关键词判定成功** —— `/callback/oauth2`、`/site-nav/`、`/auth/login`
  返回的字节完全相同，且页面模板本身含 `WebVPN` 字样，用作判定只会产生假阳性，
  因此本系统以 `detection: "api"` 标记，**只认接口返回码**。
- **登录后可能有附加动作** —— `user/info` 会带 `needTriggerTFA` / `needChangePwd` /
  `needToBindLocalAccount`，POC 将其列入结果的 `pending_actions` 字段。

> 该系统的完整参数与约束：[`systems/webvpn.shu.edu.cn/README.md`](systems/webvpn.shu.edu.cn/README.md)；
> 配置：[`systems/webvpn.shu.edu.cn/config.py`](systems/webvpn.shu.edu.cn/config.py)、
> 实现：[`systems/webvpn.shu.edu.cn/client.py`](systems/webvpn.shu.edu.cn/client.py)。
>
> 逆向材料：`_analysis_bundle/webvpn/`（已被 `.gitignore` 忽略），
> `auth-DY9U0HS6.js` 为接口封装，`Oauth2Callback-CV3Kw-qa.js` 为回调处理逻辑。

**千学百科例外**：同为纯前端 SPA，但换会话由 ds 自己的**后端**完成 ——
前端只需把 `code` 递过去，服务端持 `code` 去 newsso 换 token：

```text
① GET https://newsso.shu.edu.cn/oauth/authorize
        ?response_type=code&client_id=<ds 的 client_id>
        &redirect_uri=https://ds.shu.edu.cn/login        ← 无 state、无 scope
② newsso 302 → https://ds.shu.edu.cn/login?code=...
③ GET https://ds.shu.edu.cn/dsssologin/getSsoUser
        ?code=<授权码>&url=https://ds.shu.edu.cn/login
   ← {"isSussess": true, "datas": "{\"userid\": ...}"}    ← 判定依据（字段名确实拼作 isSussess）
```

| 项 | 值 |
| :--- | :--- |
| `client_id` | `re0owG1g776ng2eix7x3o8sa20W6OdA2` |
| `redirect_uri` | `https://ds.shu.edu.cn/login` |
| `scope` | 空 |
| `state` | 不传 |

实测约束：

- **换 token 失败会直说原因** —— 用无效 `code` 请求时返回
  `{"isSussess":false,"errMsg":"获取token失败：{...\"error\":\"invalid_grant\"...}"}`，
  即 ds 服务端走的是标准 OAuth 码换 token，且 `url` 必须与授权时的 `redirect_uri` 一致；
- **`datas` 是「JSON 字符串」而非对象** —— 前端写的是 `JSON.parse(u.datas)`，
  故 POC 也做二次解析（`client.redeem_ds`）；
- **ds 的会话不在 Cookie 里** —— 前端把 `datas.userid` 存 `localStorage` 当 Bearer token，
  因此无法靠「跟随跳转 + URL/正文关键词」判定，只能以 `getSsoUser` 的 `isSussess` 为准
  （`detection: "api"`）；该站同样对任何路径都返回同一份 `index.html`。

> 该系统的完整参数与约束：[`systems/ds.shu.edu.cn/README.md`](systems/ds.shu.edu.cn/README.md)；
> 配置：[`systems/ds.shu.edu.cn/config.py`](systems/ds.shu.edu.cn/config.py)、
> 实现：[`systems/ds.shu.edu.cn/client.py`](systems/ds.shu.edu.cn/client.py)。
>
> 逆向材料：`_analysis_bundle/ds/`（已被 `.gitignore` 忽略），
> `entry-index-*.js` 内含路由守卫与 `getSsoUser` 调用，`login-chunk-*.js` 内含授权 URL 拼接。

### 关键结论

1. **授权码一次性、绑定 `state`，不可复用**；
2. **SSO 会话 Cookie 可复用** —— `SHU_OAUTH2` host-scoped 于 `newsso.shu.edu.cn`，
   只要后续授权请求仍发往 newsso，即可免登录直接取得新的授权码；
3. 各业务系统仅负责「用 `code` 换自己的会话」，彼此独立、互不影响 ——
   任一系统失败（网络异常、上游改版、接口报错等）**只记为该项失败，不会中断其余系统**，
   汇总表会逐项列出失败原因（详见 `src/runner.py` 的 `login_all_systems()`）。

```text
                          ┌──────────────────────────────┐
    一次登录  ───────────▶ │  newsso.shu.edu.cn           │
                          │  SHU_OAUTH2（host-scoped）    │
                          └───────────────┬──────────────┘
                                          │ 复用同一会话
        ┌─────────────┬───────────────────┼───────────────┬─────────────┬─────────────┐
        ▼             ▼                   ▼               ▼             ▼             ▼
      jwxt          otp                 bbs            webvpn          ds       （可扩展）
```

## 快速开始

### 环境要求

| 项 | 要求 |
| :--- | :--- |
| Python | 3.10 或更高（实测 3.12） |
| 依赖 | `requests`、`cryptography`；`qrcode` 可选（终端二维码） |
| 网络 | 可访问 `newsso.shu.edu.cn` 及目标业务系统 |

### 安装

```bash
git clone <repo-url> && cd shu-sso-poc

# Windows
python -m venv .venv && .venv\Scripts\activate
# macOS / Linux
python -m venv .venv && source .venv/bin/activate

pip install requests cryptography qrcode
```

> 未安装 `qrcode` 亦不影响运行，仅终端二维码渲染会降级为输出图片 URL。

## 使用

```bash
python poc.py                          # 交互式选择登录方式（推荐）
python poc.py --login password         # 账号密码登录
python poc.py --login wecom_scan       # 企业微信扫码登录
python poc.py --method sms             # 账号密码登录时指定 2FA 方式
python poc.py --scan-timeout 300       # 扫码等待秒数（默认 180）
python poc.py --no-qr                  # 不在终端渲染二维码
python poc.py --qr-style ascii         # 二维码改用无颜色整块样式
```

### 登录模式

| 选项 | 模式 | 说明 |
| :---: | :--- | :--- |
| `[1]` | `password` | 学号/工号 + 密码 + 两步验证（企业微信 / 短信），登录后自动跑通全部业务系统 |
| `[2]` | `wecom_scan` | 企业微信扫码，扫码确认后自动建立会话并登录全部业务系统 |

- **账号密码模式**：输入学号 → 输入密码（`getpass`，不回显）→ 选择 2FA → 输入验证码 → 自动登录全部系统
- **企微扫码模式**：终端直接画出二维码 → 企业微信扫码确认 → 长轮询取得 `auth_code`
  → 换取 `SHU_OAUTH2` 会话 → 自动登录全部系统

### 命令行参数

| 参数 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `--tenant` | `上海大学` | 院校标识（`tenantId`） |
| `--login {password,wecom_scan}` | 交互选择 | 登录方式 |
| `--method {wecom,sms}` | 交互选择 | 账号密码模式下的 2FA 方式 |
| `--scan-timeout` | `180` | 企微扫码等待秒数 |
| `--no-qr` | 关闭 | 不在终端渲染二维码 |
| `--qr-style {block,ascii}` | `block` | 二维码渲染样式 |

### 输出示例

```text
──────────────────────────────────────────────────────────────
▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀          ← 直接可扫的二维码
▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀             （终端里是白底黑块）
 请用企业微信扫描下方二维码，并在手机上点「确认登录」
──────────────────────────────────────────────────────────────
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

## 终端二维码渲染

企微二维码的**内容就是扫码后打开的确认页地址**（`confirm_url`）——
已用 `pyzbar` 解码官方 `qrImg?key=<key>` 返回的 PNG 并逐字核对。
因此可以在本地用 `qrcode` 重新生成同样内容的二维码，扫码后打开的是同一个确认页，
无需再打开浏览器点击图片链接。

### 渲染方案

`utils.render_qr_terminal()` 采用**半块字符压缩**：

1. `▀`（U+2580）以**前景色绘制字符格上半、背景色绘制下半**，一个字符格承载上下两个模块；
   终端字符高宽比约为 2:1，压缩后行列比例恰好接近二维码的方块比例；
2. 前景/背景均显式指定纯黑/纯白 —— 无论终端是深色还是浅色主题，二维码始终为「白底黑块」，
   不受主题影响；
3. 仅在颜色发生变化时输出 ANSI 控制码，减小输出体积。

### 样式选择

| 样式 | 字符 | 宽度 | 适用场景 |
| :--- | :--- | :--- | :--- |
| `block`（默认） | `▀` + ANSI 颜色 | 41 列 | 紧凑，需终端支持颜色 |
| `ascii` | `██` / 空格 | 82 列 | 不依赖颜色，兼容性最佳 |

### 降级与开关

| 条件 | 行为 |
| :--- | :--- |
| 未安装 `qrcode` | 回退打印图片 URL，并提示 `pip install qrcode` |
| 输出被重定向（非 TTY） | 跳过渲染，避免 ANSI 控制码污染文件 |
| 终端过窄 | 提示当前列数并建议拉宽窗口，仍会渲染 |
| `--no-qr` | 强制关闭终端二维码 |

> **验证方法**：将渲染出的 ANSI 文本反向解析回模块矩阵，与原始矩阵逐格比对一致；
> 再栅格化后交由 `pyzbar` 解码，可完整还原 `confirm_url`，确认确实可扫。

## 工程说明

### 项目结构

```text
poc.py                  CLI 入口（参数解析、模式选择、分发）
src/
  config.py             newsso 协议常量（端点 / 企微参数）+ 装载系统注册表
  registry.py           系统注册表：扫描 systems/ 装载配置与换会话实现
  rsa_key.py            RSA 公钥抓取 / 缓存 / 回退
  utils.py              工具函数（RSA 加密、base64url、脱敏、日志）
  system_api.py         系统实现的接口（RedeemContext / fail / 辅助函数）
  client.py             ShuSSO HTTP 客户端（只放所有系统共用的能力）
  runner.py             批量登录（逐系统隔离）与证据落盘
  entry_password.py     账号密码入口
  entry_wecom.py        企微扫码入口
  ui.py                 横幅 / 菜单 / 汇总表 / 错误提示
  qr.py                 终端二维码渲染
systems/                ★ 可能变动的系统配置与实现，按域名分目录
  README.md             目录约定与 SYSTEM 字段说明
  <域名>/config.py      该系统的 client 信息 / 换会话方式 / 成功判定
  <域名>/client.py      可选：换会话实现（只有不走「跟随 302」的系统才有）
  <域名>/README.md      该系统的介绍 / OAuth 参数 / 特殊设计
tests/
  test_offline.py       离线测试（假会话跑真实代码，不打真实网络）
```

`poc.py` 只做命令行入口，`src/` 放与具体系统无关的机制，业务系统的差异**全部**外置在 `systems/`。

### 系统交换配置（`systems/`）

每个系统一个目录，目录名就是它的域名，键取域名首段（`ds.shu.edu.cn` → `ds`）：

| 系统 | 配置与说明 | 换会话 | 判定依据 |
| :--- | :--- | :--- | :--- |
| `jwxt` | [`systems/jwxt.shu.edu.cn/`](systems/jwxt.shu.edu.cn/README.md) | 跟随 `302` | URL / 正文关键词 |
| `otp` | [`systems/otp.shu.edu.cn/`](systems/otp.shu.edu.cn/README.md) | 跟随 `Refresh` 头 | URL / 正文关键词 |
| `bbs` | [`systems/bbs.shu.edu.cn/`](systems/bbs.shu.edu.cn/README.md) | 跟随 `302` | URL / 正文关键词 |
| `webvpn` | [`systems/webvpn.shu.edu.cn/`](systems/webvpn.shu.edu.cn/README.md) | 私有接口握手 | 接口返回码（`detection: api`） |
| `ds` | [`systems/ds.shu.edu.cn/`](systems/ds.shu.edu.cn/README.md) | 后端接口换 token | 接口返回码（`detection: api`） |

- 目录约定、`SYSTEM` 全部字段、新增系统的步骤：见 [`systems/README.md`](systems/README.md)；
- 各系统的 README 都按「一句话介绍 → OAuth 参数表格 → 特殊设计」写，
  改上游相关问题先看对应那一篇；
- 加载顺序按目录名排序，`_` / `.` 开头的目录会被跳过。

**换会话实现的发现规则**：系统目录里若有 `client.py` 且导出 `redeem(ctx)`，
`runner.login_one()` 就用它；没有就走通用路径（授权取码 → 跟随 `302`）。
实现拿到的是 `system_api.RedeemContext`（`client` / `key` / `cfg` / `username`），
可直接用 `ctx.client.sess` 发请求、`ctx.client.authorize()` 取码、`ctx.client.record()` 记 trace。

### 模块 API

| 模块 | 主要符号 | 说明 |
| :--- | :--- | :--- |
| `config` | `SSO_BASE` `WECOM` `SYSTEMS` `CAPTURE_DIR` | newsso 协议常量与系统注册表（`SYSTEMS` 由 `registry` 装载） |
| `rsa_key` | `fetch_rsa_public_key_pem()` / `public_key_pem()` | 公钥抓取与缓存（导入不联网，首次使用时才取） |
| `registry` | `load_systems()` / `redeem_impl()` / `impl_module()` | 装载系统配置与换会话实现 |
| `system_api` | `RedeemContext` / `fail()` / `json_or_error()` | 系统实现的接口与辅助函数 |
| `utils` | `rsa_encrypt_password()` `b64_params()` | 密码加密与参数编码 |
| `utils` | `mask()` `redact()` `save_json()` | 脱敏与证据落盘 |
| `client` | `ShuSSO.login` / `send_2fa_code` / `verify_2fa_code` | 认证与两步验证 |
| `client` | `ShuSSO.authorize` / `redeem` / `bootstrap_state` | 通用授权与换会话 |
| `client` | `ShuSSO.wecom_qrcode_info` / `wecom_wait_scan` / `wecom_redeem` | 企微扫码链路 |
| `runner` | `login_all_systems()` / `login_one()` / `save_evidence()` | 批量登录（逐系统隔离）与落盘 |
| `ui` | `banner()` `choose_login_mode()` `print_summary()` | 终端呈现 |
| `qr` | `render_qr_terminal()` | 终端二维码渲染 |
| `entry_password` / `entry_wecom` | `password_flow()` / `wecom_scan_flow()` | 两种登录入口 |
| `systems/<域名>/client.py` | `redeem(ctx)` | 该系统专属换会话实现（webvpn / ds） |

### RSA 公钥自动更新

登录密码使用 newsso 前端 bundle 中的 RSA 公钥加密，该公钥位于登录 chunk
`/p__oauth2__login__index.<hash>.async.js` 内（经 `setPublicKey(Pe)` 传给 JSEncrypt）。
每次前端重新打包 hash 都会变化，公钥亦可能随部署更新，
因此 `rsa_key.public_key_pem()` 在**首次使用时**取一次（`lru_cache`，导入不联网）：

| 优先级 | 来源 | 说明 |
| :---: | :--- | :--- |
| 1 | **本地缓存** | `.rsa_public_key.pem` 存在且合法就直接用 |
| 2 | **线上抓取** | `GET /oauth2/login/` → 解析 `preload_helper \| umi` 清单 → 定位登录 chunk → 正则提取 PEM，成功后写缓存 |
| 3 | **内置回退** | 联网失败时使用 `rsa_key.FALLBACK_PEM` |

也可手动调用：

```python
from src.rsa_key import fetch_rsa_public_key_pem
pem = fetch_rsa_public_key_pem()   # 成功返回最新 PEM，失败返回 None
```

### 离线测试

`tests/test_offline.py` 用**假会话**替换 `requests.Session`、预设 `authorize()` 的返回，
其余全走真实代码（注册表装载、实现分派、批量登录、通用换会话）：

```bash
python tests/test_offline.py     # 只用标准库
pytest tests/                    # 若装了 pytest
```

| 用例 | 覆盖点 |
| :--- | :--- |
| 注册表 | 5 个系统全部装载；`ds` / `webvpn` 有专属实现，其余走通用路径 |
| 编码 | `params` 是 base64url 去填充；webvpn 的 `state` 是标准 base64 带填充 |
| 反代还原 | 仅 `.shu.edu.cn` 结尾的主机才改写（避免带 Cookie 的请求发往意外主机） |
| 脱敏 | 按键名剔除 + URL 查询串里的 `?code=` |
| 全链路 | webvpn / ds / 通用系统三条路径都能换到会话，且授权参数各自正确 |
| 早期失败 | 未复用会话 / 未取到 code → 转成 `reason` 而非异常 |
| 失败隔离 | 单个系统抛异常不影响其余；接口报错如实记录 |
| 中断语义 | `Ctrl+C`（`KeyboardInterrupt`）仍会终止全局 |

### 退出码

| 码 | 含义 |
| :---: | :--- |
| `0` | 全部目标系统登录成功 |
| `1` | 学号或密码为空 |
| `2` | 登录失败（`/oauth/userLogin` 未返回 `success`） |
| `3` | 2FA 发码失败，或验证码为空 |
| `4` | 2FA 校验失败 |
| `5` | 部分业务系统登录失败 |
| `6` | 未能解析出企微二维码 `key` |
| `7` | 扫码超时或失败（未取得 `auth_code`） |
| `8` | 用 `auth_code` 换取 SSO 会话失败 |
| `130` | 用户中断（`Ctrl+C`） |

### 运行产物

脱敏后的证据 JSON 写入 `captures/`（已被 `.gitignore` 忽略）：

| 文件 | 产生时机 |
| :--- | :--- |
| `script-result.json` | 账号密码模式正常完成 |
| `script-wecom-scan.json` | 企微扫码模式正常完成 |
| `script-00-wecom-scan-failed.json` | 二维码 `key` 解析失败 / 扫码超时 |
| `script-00-wecom-redeem-failed.json` | 企微换会话失败 |
| `script-01-login-failed.json` | 登录失败 |
| `script-02-send-code-failed.json` | 2FA 发码失败 |
| `script-03-verify-failed.json` | 2FA 校验失败 |

## 常见问题

<details>
<summary><b>提示 <code>badRequestParams</code>？</b></summary>

三种常见原因：

1. `/oauth/userLogin` 缺少 `params` 字段（必填）；
2. 企微回调的 `state` 使用了标准 base64，而非 base64url 无填充；
3. 企微回调缺少 `appid` 参数。

</details>

<details>
<summary><b>OTP 回调提示「State验证失败」？</b></summary>

`otp.shu.edu.cn` 会校验存于 `ASP.NET_SessionId` 中的 `state`。
必须先访问其入口页预取 `state`（见
[`systems/otp.shu.edu.cn/config.py`](systems/otp.shu.edu.cn/config.py) 的 `needs_state_bootstrap`）
后再发起授权。

</details>

<details>
<summary><b>WebVPN 返回 <code>20001 DeviceId未找到</code>？</b></summary>

`auth/finish` 的 `deviceId` 为必填项。POC 默认由 `systems/webvpn.shu.edu.cn/client.py`
的 `device_id_for(账号名)` 生成稳定伪指纹，请检查传入的用户名是否为空（扫码登录时为 `""`，仍是稳定值）。

</details>

<details>
<summary><b>终端二维码显示不出来或扫不出？</b></summary>

- 确认已安装 `qrcode`：`pip install qrcode`；
- 终端不支持 ANSI 颜色时，改用 `--qr-style ascii`；
- 终端过窄会提示列数不足，请拉宽窗口后重跑；
- 输出被重定向到文件时不会渲染（避免 ANSI 控制码污染），可改用输出的图片 URL。

</details>

<details>
<summary><b>系统实际登录成功，却被判定为失败？</b></summary>

除 `webvpn`、`ds` 外，其余系统通过 URL / 正文关键词判定成功。
若上游页面改版，请同步更新该系统配置里的
`success_url_contains` / `success_body_contains` —— 见 [`systems/`](systems/README.md)
下对应目录的 `config.py` 与 `README.md`。

</details>

<details>
<summary><b>想加一个新系统要改哪些地方？</b></summary>

通常**不用改 `src/`**：在 [`systems/`](systems/README.md) 下新建 `<系统域名>/config.py`，
填好 `name` / `client_id` / `redirect_uri` / `scope` 与判定字段即可接入。
只有当换会话不是「跟随 302」时，才需要在同目录再加一个 `client.py`，导出
`redeem(ctx)`（照 `webvpn` / `ds` 抄）—— 有它就会被自动识别，无需任何开关。
最后补一篇同目录 `README.md`：一句话介绍、OAuth 参数表格、特殊设计。

</details>

<details>
<summary><b>某个系统挂了，会不会导致其它系统也跑不了？</b></summary>

不会。每个系统独立执行、独立记录结果：任一系统抛异常（连接超时、接口 5xx、上游改版等）
只把该系统标为失败并在汇总里给出原因，随后继续登录下一个系统。
仅 `Ctrl+C` 会中断整个流程。失败详情也会完整写进 `captures/` 的证据 JSON 供排查。

</details>

<details>
<summary><b>证书校验为什么是关闭的？</b></summary>

`requests.Session.verify = False` 为按需求显式关闭，同时抑制了 urllib3 的告警噪音。
请仅在受控网络环境下使用；如需严格校验，可自行改为 `True` 并提供 CA 证书。

</details>

## 许可证

[AGPL-3.0](LICENSE)
