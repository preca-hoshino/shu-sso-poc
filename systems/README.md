# systems/ — 各业务系统的交换配置

存放**可能变动**的系统级配置：client 注册信息、换会话方式、成功判定依据。
`src/` 里不写死任何业务系统，全部从这里读取（加载器：`src/registry.py`）。

## 目录约定

```text
systems/
  <系统域名>/          # 例如 ds.shu.edu.cn，与抓包/浏览器地址栏的 Host 一一对应
    config.py          # 必需，导出 SYSTEM 字典（纯数据，不做导入副作用）
    client.py          # 可选，导出 redeem(ctx) —— 换会话不走「跟随 302」时才需要
    README.md          # 建议，系统说明（干什么的 / OAuth 参数 / 特殊设计）
```

- 系统 key = 域名首段（`ds.shu.edu.cn` → `ds`），即代码里的 `config.SYSTEMS["ds"]`；
- 加载顺序按目录名排序；`_`、`.` 开头的目录会被跳过；
- `config.py` 只放数据、不做导入副作用（不联网、不打印）；
- `client.py` 有就会被自动识别（`registry.redeem_impl`），不需要任何配置开关；
  它可以直接 `from src.system_api import ...` / `from src.utils import log`。

## SYSTEM 字段

| 字段 | 必需 | 说明 |
| :--- | :---: | :--- |
| `name` | ✔ | 显示名（汇总表用） |
| `client_id` | ✔ | 业务系统在 newsso 注册的 `client_id` |
| `redirect_uri` | ✔ | 回调地址，授权与换码两处必须一致 |
| `scope` | | 空串 = 授权请求不带 `scope` |
| `generate_state` | | `true` = 该站授权本就不带 `state`，由 POC 生成随机 UUID |
| `needs_state_bootstrap` | | 先访问该 URL，从其 302 的 `Location` 里取 `state` |
| `follow_up_url` | | 回调用 `Refresh` 头跳转（非 302）时，手动补访问的 URL |
| `authorize_extra` | | 追加到授权请求的额外参数 |
| `success_url_contains` | | 通用换会话的成功判定：落地 URL 含该串 |
| `success_body_contains` | | 通用换会话的成功判定：页面正文含该串 |
| `detection` | | 判定来源标记：`api` = 只认接口返回；缺省 = URL/正文关键词 |
| 其余键 | | 系统专用常量，由该系统自己的实现读取（如 webvpn 的 `base` / `auth_start`） |

> 换会话不走「跟随 302」的系统**不要**在这里声明实现名 —— 在同目录放一个
> `client.py` 即可，见下节。

## 换会话实现（`client.py`）

只有换会话不是「跟随 `302`」的系统才有这个文件，约定导出：

```python
def redeem(ctx: RedeemContext) -> dict: ...
```

`ctx` 是 `src/system_api.RedeemContext`：

| 字段 | 说明 |
| :--- | :--- |
| `client` | `ShuSSO` 实例：`sess` / `timeout` / `authorize()` / `record()` / `bootstrap_state()` |
| `key` | 系统 key，如 `webvpn` |
| `cfg` | 该系统的 `SYSTEM` 字典 |
| `username` | 登录账号（WebVPN 用它派生稳定 `deviceId`；扫码登录时为空串） |

返回值需与通用路径同形：

| 键 | 必需 | 说明 |
| :--- | :---: | :--- |
| `logged_in` | ✔ | 是否登录成功 |
| `final_url` | ✔ | 落地页地址（汇总表在成功时显示它） |
| `system` / `detection` | | 系统 key 与判定来源标记 |
| `body_match` / `url_match` | | 接口判定时置 `None` |
| `body_preview` | | 失败原因摘要（汇总表在失败时显示它） |
| 其余键 | | 业务字段（`user_id` / `username` / `pending_actions` 等），原样写进证据 JSON |

早期中止（会话未复用 / 未取到 code 等）用 `src.system_api.fail("reason")` 返回；
`reason` 会由 `src/ui.REASON_TEXT` 翻成中文，想新增就在那里补一行。

## 新增一个系统

1. 建 `systems/<域名>/config.py`，导出 `SYSTEM`（`client_id` / `redirect_uri` 抓包即得）；
2. 若换会话不是「跟随 302」，再在同目录加 `client.py` 导出 `redeem(ctx)`
   （照 `systems/webvpn.shu.edu.cn/client.py` 与 `systems/ds.shu.edu.cn/client.py` 抄），
   并可用 `from src.system_api import same_origin_headers, json_or_error` 等辅助件；
3. 写同目录 `README.md`（介绍 / OAuth 参数 / 特殊设计）；
4. 在仓库根 `README.md` 的「③ 授权：逐系统换取 code」与「系统交换配置」两处补一行引用。
