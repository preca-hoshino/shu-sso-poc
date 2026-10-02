# 空间预约管理系统

上海大学空间预约管理系统（`there.shu.edu.cn`）：研讨间 / 工位 / 图书馆座位的预约与审批。
校内系统，仅校园网可达。

## OAuth 参数

| 项 | 值 |
| :--- | :--- |
| `client_id` | `eDrd-M0i0WoSWRxk7ShDC1n-fbS7jRvi` |
| `redirect_uri` | `https://there.shu.edu.cn/login-oauth2` |
| `scope` | `1`（数字型 scope，非空，必须原样带上） |
| `state` | 先访问 `https://there.shu.edu.cn/login?from=web` 取其 302 `Location` 里的值（**服务端并不校验**，见下） |
| 额外参数 | 无 |
| 换会话 | 跟随 `302` |
| 成功判定 | 落地 URL 含 `there.shu.edu.cn/web`，或正文含「空间预约」 |

授权 URL 由服务端拼好后 302 给出，POC 不需要自己拼：

```text
GET /login-oauth2
  └─ 302 https://oauth.shu.edu.cn/oauth/authorize
        ?scope=1&response_type=code
        &redirect_uri=https%3A%2F%2Fthere.shu.edu.cn%2Flogin-oauth2
        &client_id=eDrd-M0i0WoSWRxk7ShDC1n-fbS7jRvi
  └─ 302 <redirect_uri>?code=...&state=...
```

## 完整成功链路

实测（Chrome DevTools 抓真实企微扫码登录）换会话只有一跳，但落地形态与常见系统不同：

```text
POST open.work.weixin.qq.com/wwopen/sso/lp/qrConnect      企微扫码
  └─ GET newsso.shu.edu.cn/oauth/wecom/qrcode?code=...&state=...       [302]
      └─ GET newsso.shu.edu.cn/oauth/authorize?...&state=              [302]
          │    ← 注意这里的 state 已经空了
          └─ GET there.shu.edu.cn/login-oauth2?code=<48 位码>           [302]  ★ 无 state
              │    Set-Cookie: SPHYS_SESSION=...&utoken=<JWT>、authenticityToken=...
              └─ GET there.shu.edu.cn/web?authJump=<64 位 token>        [307→200]  ★ 落地
                  └─ SPA 自行路由到 /web/home（标题「欢迎使用空间预约系统」）
```

登录后的业务接口在 `/api/v2.0/*`（如 `my-meetings`、`settings`、`my-stats`）。

## 特殊设计

- **SSO 主机是 `oauth.shu.edu.cn`，不是 `newsso.shu.edu.cn`** —— 本站 302 指向
  `oauth.shu.edu.cn/oauth/authorize`，但两者是**同一套 SSO**：前端产物哈希逐字相同
  （`umi.7f1cbd8a.js`、`p__oauth2__login__index.c7119352.async.js`），`/oauth/token`
  的报错也一致。会话 cookie `SHU_OAUTH2` 是 host-scoped，POC 里仍在 `newsso` 取码，
  业务后端拿 code 去换 token，两边通用。
- **`state` 服务端不校验，别被它的两条入口误导** —— 站内有两条登录入口：
  - `/login-oauth2`（页头「登录」）→ 授权 URL **不带 `state`**；
  - `/login?from=web`（`/web/**` 未登录时 302 到这里）→ 授权 URL **带 16 位 `state`**。

  但实测成功回调是 `GET /login-oauth2?code=<码>`，**`state` 参数根本不存在**，
  且此前经企微链路时 `state` 已被清空（`...&state=`），后端依然换会话成功 ——
  说明 state 只是随流程透传，不做比对。配置里仍保留 `needs_state_bootstrap`，
  目的是**预置 `SPHYS_SESSION` 站点会话**（对齐浏览器行为），而非取 state 值。
- **落地页是 `/web?authJump=<64 位 token>`，不是 `/shu`** —— `/shu` 系列
  （`/shu`、`/shu/booking.html`、`/shu/rule.html`）是**未登录也能看的静态介绍页**，
  别拿它当成功标志。判定要用 `/web`。
- **回调失败是「静默」的** —— `/login-oauth2` 拿到坏 code 时返回 `200` + **空正文**
  （不跳转、不报错），成功才 302 到 `/web?authJump=...`。所以成功判定不能只看
  「URL 含 `there.shu.edu.cn`」（失败时停在该域的 `/login-oauth2` 上也含）。
- **站点会话 cookie 是 `SPHYS_SESSION`**（HTTPOnly，`Path=/`），值与 SSO 的
  `SHU_OAUTH2` 无关。成功后它被扩写为携带 `utoken=<HS512 JWT>`，
  另下发 `authenticityToken`（CSRF 用）—— POC 不解析它们，只认落地页。

> 配置：同目录 `config.py`（换会话走通用 302 路径，故无 `client.py`）
