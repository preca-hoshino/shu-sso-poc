"""系统换会话实现的公共接口。

`systems/<域名>/client.py` 约定导出：

    def redeem(ctx: RedeemContext) -> dict: ...

返回值需与通用路径同形（`logged_in` / `final_url` / `body_preview` 等），
完整字段表见 systems/README.md。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RedeemContext:
    """一次换会话所需的全部输入。

    `client` 即 `client.ShuSSO`（鸭子类型即可），系统实现可直接使用它的
    `sess` / `timeout` / `authorize()` / `record()`。
    """

    client: Any
    key: str                # 系统 key，如 "webvpn"
    cfg: dict               # 该系统的 SYSTEM 配置
    username: str = ""      # 登录账号（WebVPN 用它派生稳定 deviceId）


def fail(reason: str, **extra) -> dict:
    """统一的「流程早期中止」结果。

    reason 取值见 README 的说明表（no_code / session_not_reused / ...）。
    """
    return {"logged_in": False, "reason": reason, "final_url": "", **extra}


def same_origin_headers(base: str, referer_path: str = "/", json_body: bool = False) -> dict:
    """构造同源 Origin/Referer 头（不少业务系统的接口会校验来源）。"""
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Origin": base,
        "Referer": f"{base}{referer_path}",
    }
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def json_or_error(r, note: str = "non-json") -> dict:
    """把响应解析成 dict；非 JSON 时返回带说明的占位 dict（不抛异常）。"""
    try:
        body = r.json()
        return body if isinstance(body, dict) else {"data": body}
    except Exception:
        return {"message": f"{note} (HTTP {r.status_code})", "raw": (r.text or "")[:300]}
