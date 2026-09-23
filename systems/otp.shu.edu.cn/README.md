# OTP 令牌

动态口令（OTP）令牌服务站点，登录后进入 `Default.aspx` 展示账户信息。

## OAuth 参数

| 项 | 值 |
| :--- | :--- |
| `client_id` | `05Q1L8woQK5350aK1U5o5GKh411ar3h1` |
| `redirect_uri` | `https://otp.shu.edu.cn//Callback.aspx` |
| `scope` | `read write`（空格分隔，newsso 原样接收） |
| `state` | 先访问 `https://otp.shu.edu.cn/` 预热取得 |
| 额外参数 | 无 |
| 换会话 | `Refresh` 响应头跳转 → 手动补访 `Default.aspx` |
| 成功判定 | 落地 URL 含 `Default.aspx`，或正文含 `账户名` |

## 特殊设计

- **`state` 存在服务端会话里** —— `Callback.aspx` 会拿收到的 `state` 与
  `ASP.NET_SessionId` 中保存的值比对，不匹配直接报「State验证失败」。
  故必须先 `GET https://otp.shu.edu.cn/` 预热（`needs_state_bootstrap`），
  让服务端先落下 `state` 并返回 `ASP.NET_SessionId`，再带同一个 Cookie 去 newsso 授权。
- **回调用 `Refresh` 头而非 302** —— 响应形如 `Refresh: 0;url=Default.aspx`，
  `requests` 的 `allow_redirects` 不认它，所以 `client.redeem()` 在读不到目标 URL 时
  会按 `follow_up_url` 手动补一次。
- **`redirect_uri` 里的双斜杠是有意的** —— `//Callback.aspx` 是服务端注册的值，
  看着别扭但**不要"顺手"改成单斜杠**，改了会与注册值不符。

> 配置：同目录 `config.py`（换会话走通用路径，故无 `client.py`）
