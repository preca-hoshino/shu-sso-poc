# 上大 bbs（乐乎社区）

校内论坛，帖文浏览与讨论。

## OAuth 参数

| 项 | 值 |
| :--- | :--- |
| `client_id` | `vp8G2H42GGE86LP822LHF6Hs7f46483H` |
| `redirect_uri` | `https://bbs.shu.edu.cn/auth/oauth2_basic/callback` |
| `scope` | 空（授权请求不带 `scope`） |
| `state` | 先访问 `https://bbs.shu.edu.cn/auth/oauth2_basic`，向 BBS 索要 |
| 额外参数 | 无 |
| 换会话 | 跟随 `302` |
| 成功判定 | 落地 URL 含 `bbs.shu.edu.cn`，或正文含 `乐乎` |

## 特殊设计

- **`state` 由 BBS 自己生成** —— 访问入口 `/auth/oauth2_basic` 时，它的 302
  `Location` 里就带着 `state=`，POC 把这个值原样拿去 newsso 授权；
  自己编一个随机值会导致回调时 state 校验不通过。
- **判定关键词以正文为准** —— `success_url_contains` 取的是 `bbs.shu.edu.cn`，
  而回调本身就在该域，此项近乎恒真；真正起作用的是正文里的「乐乎」。
  上游改版时优先更新 `success_body_contains`。

> 配置：同目录 `config.py`（换会话走通用路径，故无 `client.py`）
