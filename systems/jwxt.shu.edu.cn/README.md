# 本科生教务系统

选课、课表、成绩查询等本科生教学事务的入口站。

## OAuth 参数

| 项 | 值 |
| :--- | :--- |
| `client_id` | `Km5t225E8KECKQ6ZDm5K2P6aS2459Cua` |
| `redirect_uri` | `https://jwxt.shu.edu.cn/sso/shulogin` |
| `scope` | `jw` |
| `state` | **不传**，由 POC 生成随机 UUID |
| 额外参数 | 无 |
| 换会话 | 跟随 `302` 跳转（最普通的路径） |
| 成功判定 | 落地 URL 含 `jwglxt`，或正文含 `教学管理` |

## 特殊设计

- **授权请求不带 `state`** —— 该站跳 newsso 时就不传 `state`，POC 用 `generate_state: True`
  自行生成一个随机 UUID 补上（newsso 原样回传，仅作防 CSRF，服务端不校验其来源）。
- **换会话是标准路径** —— 跟随 `Location` 跳转即完成，落地 URL 形如 `/jwglxt/...`，
  无需任何私有接口，因此它是全流程的「对照组」。
- **判定读正文关键词** —— 正文含「教学管理」是教务系统首页模板的特征；上游改版时
  同步改 `success_body_contains` 即可，不必动代码。

> 配置：同目录 `config.py`（换会话走通用路径，故无 `client.py`）