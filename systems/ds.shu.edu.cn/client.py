"""千学百科换会话实现：把 code 交给 ds 后端换 token。

前端只做一件事 ——

    GET /dsssologin/getSsoUser?code=<code>&url=<redirect_uri>

由 ds 服务端持 code 去 newsso 换 token 并返回用户信息。
参数与实测约束见同目录 README.md、config.py。
"""

from __future__ import annotations

import json

from src.system_api import RedeemContext, fail, json_or_error
from src.utils import log, mask


def _get_sso_user(client, cfg: dict, code: str, redirect_uri: str) -> dict:
    r = client.sess.get(
        cfg["base"] + cfg["get_sso_user"],
        params={"code": code, "url": redirect_uri},
        headers={"Accept": "application/json, text/plain, */*",
                 "Origin": cfg["base"],
                 "Referer": redirect_uri},
        timeout=client.timeout)

    body = json_or_error(r, "getSsoUser non-json")
    if body.get("message") and "isSussess" not in body:
        body = {"isSussess": False, "errMsg": body["message"]}

    user: dict = {}
    if body.get("datas"):
        # datas 是「JSON 字符串」，需二次解析（前端同样写的是 JSON.parse(u.datas)）
        try:
            user = json.loads(body["datas"])
        except Exception:
            user = {}
    return {"body": body, "user": user, "http_status": r.status_code}


def redeem(ctx: RedeemContext) -> dict:
    """授权请求不带 state / scope，拿到 code 后交给 ds 后端。"""
    client, cfg = ctx.client, ctx.cfg

    log("     [OAuth ①] ds 授权请求不带 state / scope（对齐前端拼接的 URL）")
    auth = client.authorize(cfg["client_id"], cfg["redirect_uri"], cfg.get("scope", ""), "")
    if auth["needs_login"]:
        log("     ✗ 需要重新登录（会话未复用）")
        return fail("session_not_reused", authorize=auth)
    if not auth["code"]:
        log("     ✗ 未取到授权码")
        return fail("no_code", authorize=auth)
    log(f"     [OAuth ③] HTTP {auth['http_status']} → 取到 code: {mask(auth['code'], 8)}")

    # [OAuth ④] 交给 ds 后端换 token（前端 getSsoUser 的实际调用）
    log("     [OAuth ④] GET /dsssologin/getSsoUser?code=...&url=...")
    got = _get_sso_user(client, cfg, auth["code"], cfg["redirect_uri"])
    body, user = got["body"], got["user"]
    # 字段名确系上游原样拼写，勿「纠正」
    ok = body.get("isSussess") is True

    result = {
        "system": ctx.key,
        "detection": cfg.get("detection", "api"),
        "final_url": cfg["landing_url"],
        "http_status": got["http_status"],
        "api_ok": ok,
        "api_error": body.get("errMsg"),
        "user_id": user.get("userid"),
        "username": user.get("username") or user.get("account") or user.get("loginname"),
        "body_match": None,
        "url_match": None,
        "logged_in": bool(ok),
        "body_preview": (f"getSsoUser isSussess={body.get('isSussess')} "
                         f"userid={user.get('userid')}"
                         + (f"; errMsg={body.get('errMsg')}" if body.get("errMsg") else "")),
    }
    client.record(f"redeem/{ctx.key}", result)
    return result
