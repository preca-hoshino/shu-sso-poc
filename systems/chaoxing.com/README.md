# 超星（学习通）图书馆座位

上海大学图书馆的座位预约系统（超星 / 学习通供应商），业务站点 `office.chaoxing.com`，
用户入口在企业微信工作台 / 学习通 App；本目录实现网页端换会话，座位业务本身不在本仓库。

> 注意：全校学习通（泛雅，机构 209）走另一条 CAS 桥 `shu.fysso.chaoxing.com`，
> 与本文这条 **35480（图书馆）链平行且不通用**，本实现只覆盖后者。

## OAuth 参数

| 项 | 值 |
| :--- | :--- |
| `client_id` | `mK5y895566T96v8Z52z5M3J85K8Miv38` |
| `redirect_uri` | `https://zhstsg-jx.5read.com/oauthlogin/loginByCodeSchoolid?schoolid=2434&type=xxt` |
| `scope` / `state` | 空串，且**显式发送**（浏览器抓包逐字对齐；见下） |
| 额外参数 | 无 |
| 换会话 | 跨域 302 链：`5read` → `passport2-api.chaoxing.com/api/v2/login6` → 落地 chaoxing 域 |
| 成功判定 | `GET /front/third/apps/seat/index?fidEnc=…` 内嵌 `userLoginInfo` 可解析出 uid（`detection: api`） |

## 特殊设计

```text
① GET newsso /oauth/authorize?client_id=<chaoxing>&response_type=code&scope=&state=
       &redirect_uri=https://zhstsg-jx.5read.com/oauthlogin/loginByCodeSchoolid?schoolid=2434&type=xxt
   （scope / state 是空串 —— 浏览器拼 URL 的原文，非缺省省略）
② 持 SHU_OAUTH2 时直接 302：Location = zhstsg-jx.5read.com/oauthlogin/loginByCodeSchoolid?code=...
③ 302 → passport2-api.chaoxing.com/api/v2/login6?schoolid=35480&name=…&enc=…
   ← Set-Cookie 写 chaoxing.com 全域（p_auth_token 为 JWT，约 30 天）
④ 302 → 落地 chaoxing 域
⑤ GET office.chaoxing.com/front/third/apps/seat/index?fidEnc=00bae7f2bdea485a
   ← 页面内嵌 userLoginInfo（uid / uname / sno），这是唯一成功判据
```

- **为什么自带授权请求** —— 抓包中 `scope` / `state` 为「空串但显式携带」；通用
  `client.authorize()` 会省略空值，故本实现直接经 `ctx.client.sess` 发送，逐字对齐。
- **为什么逐跳手动跟随** —— 链跨越 `5read` / `passport2-api` 两个第三方域，通用路径
  「跟到底」无法在结构变化时定位断点；本实现每跳 `allow_redirects=False`，跳数超限
  （`max_redirect_hops`）或最终 host 非 `*.chaoxing.com` 时显式失败。
- **URL / 正文判定为什么无效** —— 未登录时座位首页同样返回 HTTP 200，只是没有
  `userLoginInfo`；这段数据才是会话建立的凭据（`detection: "api"`）。
- **`login6` 的 `enc` 无需计算** —— 实测两次登录的 `enc` 完全相同，随 302 跟随即可。
- **Cookie 留在共享会话** —— 链上的 Set-Cookie 全部写入 `ctx.client.sess` 的 CookieJar
  （chaoxing.com 全域），下游工具（如座位预约自动化）可直接从同一 Jar 取会话凭据。
- **桌面 Chrome UA 全程可用** —— 安卓企微 UA、企微 `X-Requested-With` 实测无差异，
  自动化不需要伪装成企微客户端。

> 配置：同目录 `config.py`　换会话实现：同目录 `client.py`。
> 完整实测记录（含 13 个座位业务 API、提交签名与 A/B 对照）见座位预约 POC 项目的
> `docs/chaoxing.md`，不在本仓库。
