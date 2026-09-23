# 千学百科（DeepSeek）

面向师生的 AI 问答 / 知识助手站点。

## OAuth 参数

| 项 | 值 |
| :--- | :--- |
| `client_id` | `re0owG1g776ng2eix7x3o8sa20W6OdA2` |
| `redirect_uri` | `https://ds.shu.edu.cn/login` |
| `scope` | 空（前端拼 URL 时完全不写 `scope`） |
| `state` | **不传**（前端拼 URL 时也不写 `state`） |
| 额外参数 | 无 |
| 换会话 | 后端接口：`GET /dsssologin/getSsoUser` |
| 成功判定 | 响应 `isSussess == true`（**不看 URL/正文**） |

## 特殊设计

```text
① GET newsso /oauth/authorize?response_type=code&client_id=<ds>&redirect_uri=<origin>/login
   （前端字符串直接拼接：无 state、无 scope）
② newsso 302 → https://ds.shu.edu.cn/login?code=...
③ GET https://ds.shu.edu.cn/dsssologin/getSsoUser?code=<code>&url=<redirect_uri>
   ← {"isSussess": true, "datas": "<用户信息 JSON 字符串>"}
```

- **响应字段真拼作 `isSussess`** —— 少一个 s 的拼写是上游原样，代码里按原样比对，
  **不要"纠正"**，否则解析必然失败。
- **`datas` 是 JSON 字符串而非对象** —— 前端写的是 `JSON.parse(u.datas)`，
  所以 POC 也要二次 `json.loads`。
- **`url` 必须与授权时的 `redirect_uri` 完全一致** —— 用无效 `code` 探测时返回
  `{"isSussess":false,"errMsg":"获取token失败：{...invalid_grant...}"}`，说明后端走的是
  标准码换 token，`url` 对不上就会被判 `invalid_grant`。
- **会话不在 Cookie 里** —— 前端把 `datas.userid` 写进 `localStorage` 当 Bearer token，
  因此「跟随跳转 + URL/正文关键词」判定完全无效，只能以 `isSussess` 为准
  （`detection: "api"`）；该站与 webvpn 一样，对任何路径都返回同一份 `index.html`。
- **改版本要重扫前端** —— 授权 URL 的拼接写在前端入口 chunk 里，
  改版后 `client_id` / `redirect_uri` 是否变化需重新抓包确认。

> 配置：同目录 `config.py`　换会话实现：同目录 `client.py`　逆向材料：`_analysis_bundle/ds/`（已 gitignore）
