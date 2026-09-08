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

## 安全

- 密码经 `getpass` 读取，**不落盘、不打印、不写日志**
- 保存的证据 JSON 自动剔除 `password` / `code` 字段
- 证书校验按要求关闭（`verify=False`）
- 仅供参考学习，请勿用于未授权用途；验证请使用本人自己的账号

## 许可证

[AGPL-3.0](LICENSE)
