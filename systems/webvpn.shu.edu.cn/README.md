# WebVPN 访问控制系统

校外访问校内站点的反向代理门户（把 `xxx.shu.edu.cn` 映射成
`https-xxx-shu-edu-cn-443.webvpn.shu.edu.cn`）。

## OAuth 参数

| 项 | 值 |
| :--- | :--- |
| `client_id` | `nn7sbb22j2tKE100T024tEp42777p755` |
| `redirect_uri` | `https://webvpn.shu.edu.cn/callback/oauth2` |
| `scope` | 空（授权请求不带 `scope`） |
| `state` | 结构化固定值：**标准 base64（带填充）** 的 `{"externalId": <认证方式ID>}` |
| 额外参数 | `access_type=offline`（对齐前端发起的 `login_url`） |
| 换会话 | 私有接口两步握手：`auth/start` → 授权 → `auth/finish` |
| 成功判定 | `auth/finish` 返回 `code==0` 且 `user/info` 的 `userId` 非 0（**不看 URL/正文**） |

## 特殊设计

```text
① GET  /api/access/authentication/list?type=0   → 取 authType==5 那项的 externalId
② POST /api/access/auth/start                   → 登记本次认证，返回 login_url（授权地址）
③ GET  newsso /oauth/authorize?...              → 直连新闻 SSO 取 code
④ POST /api/access/auth/finish                  → 交 code，服务端去 newsso 换 token 建会话
⑤ GET  /api/access/user/info                    → userId 非 0 即已登录
```

- **`state` 不是随机值** —— 它是 `base64({"externalId": ...})`，且用的是**标准 base64
  （`+/` 字符集、保留 `=` 填充）**，与 `utils.b64_params()` 的 base64url 去填充**不可混用**。
- **`externalId` 是「认证方式」的固定 ID** —— 由 `auth_list` 下发，抓取失败时回退到
  `external_id_fallback`；该值变了说明服务端认证方式被重建，需重新抓。
- **`auth/start` 返回的 `login_url` 用反代主机** —— 形如
  `https-newsso-shu-edu-cn-443.webvpn.shu.edu.cn`。POC 的 `SHU_OAUTH2` 是直连
  `newsso.shu.edu.cn` 建立的，**必须还原成真实主机才能复用会话**，
  因此 `client.unproxy_url()` 做还原，且**仅当结果以 `.shu.edu.cn` 结尾时才改写**，
  避免把带 Cookie 的请求发往意外主机。
- **`deviceId` 必填** —— 缺失时 `auth/finish` 返回 `20001 DeviceId未找到`。
  前端取 FingerprintJS 的 `visitorId`（同一浏览器恒定）；POC 用
  `md5("shu-sso-poc::" + 账号名)` 造一个**稳定**伪指纹（同目录 `client.py` 的 `device_id_for`），
  否则每次运行都会被当成新设备。
- **只能用接口判定成功** —— 该站任意路径（含 `/callback/oauth2`、`/site-nav/`）
  返回的 `index.html` 字节完全相同，且模板本身就是 `WebVPN` 字样，
  用 URL/正文关键词判定只会假阳性，故 `detection: "api"`。
- **登录后可能有附加动作** —— `user/info` 会带 `needTriggerTFA` / `needChangePwd` /
  `needToBindLocalAccount`，POC 记入结果的 `pending_actions`，不阻断流程。

> 配置：同目录 `config.py`　换会话实现：同目录 `client.py`　逆向材料：`_analysis_bundle/webvpn/`（已 gitignore）
