"""WebVPN 换会话实现：私有接口两步握手。

    auth/start  登记本次认证，返回 newsso 授权地址（可直连复用 SSO 会话）
    auth/finish 交 code 给 WebVPN，由服务端去 newsso 换 token 建会话
    user/info   校验登录态（userId 非 0 即已登录）

参数与实测约束见同目录 README.md、config.py。
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from urllib.parse import urlparse

from src.system_api import RedeemContext, fail, json_or_error, same_origin_headers
from src.utils import log, mask

# WebVPN 会把被代理站点映射成
#   <scheme>-<主机名中的 . 换成 ->-<端口>.webvpn.shu.edu.cn
# 而本 POC 的 SHU_OAUTH2 是直连 newsso.shu.edu.cn 建立的，要复用会话
# 就必须把反代主机还原回真实主机。
_PROXY_HOST_RE = re.compile(
    r"^(?:https?)-(?P<host>[a-z0-9]+(?:-[a-z0-9]+)*)-(?P<port>\d+)\.webvpn\.shu\.edu\.cn$",
    re.IGNORECASE,
)


def unproxy_url(url: str, allowed_suffix: str = ".shu.edu.cn") -> str:
    """把 WebVPN 反代 URL 还原成真实主机 URL；非反代 URL 原样返回。

    仅当还原出的主机以 allowed_suffix 结尾时才改写，避免把带 Cookie 的请求
    发往意料之外的主机。
    """
    if not url:
        return url
    p = urlparse(url)
    m = _PROXY_HOST_RE.match(p.hostname or "")
    if not m:
        return url
    host = m.group("host").replace("-", ".")
    if not host.endswith(allowed_suffix):
        return url
    port = m.group("port")
    netloc = host if port in ("80", "443") else f"{host}:{port}"
    return p._replace(netloc=netloc).geturl()


def device_id_for(username: str) -> str:
    """生成 WebVPN 用的 deviceId（32 位 hex）。

    前端取的是 FingerprintJS 的 visitorId（同一浏览器恒定），POC 没有浏览器指纹，
    故用「固定盐 + 账号名」的 md5 造一个**稳定**伪指纹，避免每次运行都被当成新设备。
    """
    return hashlib.md5(f"shu-sso-poc::{username.lower()}".encode("utf-8")).hexdigest()


def _state(external_id: str) -> str:
    """state = **标准 base64（带填充）** 的 {"externalId": ...}（前端 btoa 的结果）。

    与 utils.b64_params()（base64url 去填充）不同，两者不可混用。
    """
    raw = json.dumps({"externalId": external_id}, separators=(",", ":"))
    return base64.b64encode(raw.encode("utf-8")).decode()


def _external_id(client, cfg: dict) -> dict:
    """取 OAuth2 认证方式的 externalId —— 它是固定值，state 的内容就是它。"""
    r = client.sess.get(cfg["base"] + cfg["auth_list"], params={"type": 0},
                        headers=same_origin_headers(cfg["base"]), timeout=client.timeout)
    body = json_or_error(r)
    found = None
    for item in (body.get("data") or {}).get("list") or []:
        if item.get("authType") == cfg["auth_type_oauth2"]:
            found = item.get("externalId")
            break

    result = {
        "http_status": r.status_code,
        "external_id": found or cfg["external_id_fallback"],
        "source": "api" if found else "fallback",
        "auth_method_name": next((i.get("name") for i in
                                  ((body.get("data") or {}).get("list") or [])), None),
    }
    client.record("webvpn/auth_list", result)
    return result


def _auth_start(client, cfg: dict, external_id: str, state: str) -> dict:
    r = client.sess.post(
        cfg["base"] + cfg["auth_start"],
        json={"externalId": external_id,
              "data": json.dumps({"callbackUrl": cfg["callback_url"], "state": state})},
        headers=same_origin_headers(cfg["base"], json_body=True), timeout=client.timeout)
    body = json_or_error(r)
    login_url = ((body.get("data") or {}).get("action") or {}).get("login_url")

    result = {
        "http_status": r.status_code,
        "api_code": body.get("code"),
        "api_message": body.get("message"),
        "login_url": login_url,
        # 服务端返回的是反代主机，还原成真实主机才复用得上直连建立的 SSO 会话
        "login_url_direct": unproxy_url(login_url) if login_url else None,
    }
    client.record("webvpn/auth_start", result)
    return result


def _auth_finish(client, cfg: dict, external_id: str, state: str, code: str,
                 device_id: str) -> dict:
    r = client.sess.post(
        cfg["base"] + cfg["auth_finish"],
        json={"externalId": external_id,
              "data": json.dumps({"callbackUrl": cfg["callback_url"], "code": code,
                                  "deviceId": device_id, "state": state})},
        headers=same_origin_headers(cfg["base"], "/callback/oauth2", json_body=True),
        timeout=client.timeout)
    body = json_or_error(r)

    result = {
        "http_status": r.status_code,
        "api_code": body.get("code"),          # 0 = 成功（20000 = 认证失败）
        "api_message": body.get("message"),
        "cookies": [c.name for c in client.sess.cookies],
    }
    client.record("webvpn/auth_finish", result)
    return result


def _user_info(client, cfg: dict) -> dict:
    r = client.sess.get(cfg["base"] + cfg["user_info"],
                        headers=same_origin_headers(cfg["base"]), timeout=client.timeout)
    body = json_or_error(r)
    user = body.get("data") or {}

    result = {
        "http_status": r.status_code,
        "api_code": body.get("code"),          # 未授权时 401
        "user_id": user.get("userId"),
        "username": user.get("username"),
        # WebVPN 侧的后续要求：需二次验证 / 需改密 / 需绑定本地账号
        "need_trigger_tfa": user.get("needTriggerTFA"),
        "need_change_pwd": user.get("needChangePwd"),
        "need_to_bind_local_account": user.get("needToBindLocalAccount"),
        "logged_in": bool(user.get("userId")),
    }
    client.record("webvpn/user_info", result)
    return result


def redeem(ctx: RedeemContext) -> dict:
    """走 auth/start + auth/finish 完成 WebVPN 会话。"""
    client, cfg = ctx.client, ctx.cfg

    # [OAuth ①] 取认证方式的固定 ID，它决定本次 state 的内容
    ext = _external_id(client, cfg)
    if not ext.get("external_id"):
        log("     ✗ 未能取得认证方式 externalId")
        return fail("no_external_id", auth_list=ext)
    external_id = ext["external_id"]
    log(f"     [OAuth ①] 认证方式 externalId: {external_id}（来源 {ext['source']}）")

    state = _state(external_id)
    log(f"     [OAuth ①] 私有握手 POST /api/access/auth/start（state={state}）")
    start = _auth_start(client, cfg, external_id, state)
    if start.get("api_code") != 0:
        # 这一步失败只是「未登记」，直连 newsso 授权仍可继续，故只告警不中断
        log(f"     ! auth/start 返回 {start.get('api_code')}：{start.get('api_message')}")
    elif start.get("login_url_direct"):
        log(f"        服务端给出的授权地址 → {start['login_url_direct'][:100]}")

    # [OAuth ③] 直连 newsso 授权（参数对齐服务端给出的地址）
    auth = client.authorize(cfg["client_id"], cfg["redirect_uri"], cfg.get("scope", ""),
                            state, extra_params=cfg.get("authorize_extra"))
    if auth["needs_login"]:
        log("     ✗ 需要重新登录（会话未复用）")
        return fail("session_not_reused", authorize=auth)
    if not auth["code"]:
        log("     ✗ 未取到授权码")
        return fail("no_code", authorize=auth)
    log(f"     [OAuth ③] HTTP {auth['http_status']} → 取到 code: {mask(auth['code'], 8)}")

    # [OAuth ④] 把 code 交给 WebVPN 换会话，再用 user/info 校验
    log("     [OAuth ④] POST /api/access/auth/finish + GET /api/access/user/info")
    finish = _auth_finish(client, cfg, external_id, state, auth["code"],
                          device_id_for(ctx.username))
    info = _user_info(client, cfg)

    # SPA 无可靠的 URL/正文特征，只能认接口：finish 返回 0 且 user/info 拿到 userId
    logged_in = finish.get("api_code") == 0 and info.get("logged_in", False)
    pending = []
    for flag, text in (("need_trigger_tfa", "needTriggerTFA(需二次验证)"),
                       ("need_change_pwd", "needChangePwd(需改密)"),
                       ("need_to_bind_local_account", "needToBindLocalAccount(需绑定本地账号)")):
        if info.get(flag):
            pending.append(text)

    result = {
        "system": ctx.key,
        "detection": cfg.get("detection", "api"),
        "final_url": cfg["landing_url"],
        "http_status": finish.get("http_status"),
        "finish_api_code": finish.get("api_code"),
        "finish_api_message": finish.get("api_message"),
        "user_id": info.get("user_id"),
        "username": info.get("username"),
        "pending_actions": pending,
        "body_match": None,
        "url_match": None,
        "logged_in": bool(logged_in),
        "body_preview": (f"auth/finish code={finish.get('api_code')} "
                         f"({finish.get('api_message')}); "
                         f"user/info code={info.get('api_code')} "
                         f"userId={info.get('user_id')}"
                         + (f"; 待处理: {'、'.join(pending)}" if pending else "")),
    }
    client.record(f"redeem/{ctx.key}", result)
    return result
