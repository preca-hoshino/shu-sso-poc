"""超星（学习通）图书馆座位换会话实现：跨域 302 链 + 座位首页 userLoginInfo 校验。

换会话链（2026-10-05 浏览器实测，无头重放同通过）：

    newsso /oauth/authorize（持 SHU_OAUTH2 直接 302 带 code）
      → zhstsg-jx.5read.com/oauthlogin/loginByCodeSchoolid?code=&schoolid=2434&type=xxt
      → passport2-api.chaoxing.com/api/v2/login6?schoolid=35480&name=…&enc=…
      → 落地 chaoxing.com 域，login6 的 Set-Cookie 写全域会话（p_auth_token 约 30 天）

参数与实测约束见同目录 README.md、config.py。

判定（detection: api）：URL / 正文关键词没有可靠特征，只认 office 座位首页
（/front/third/apps/seat/index?fidEnc=…）内嵌的 `userLoginInfo` 能否解析出 uid ——
未登录时首页同样返回 HTTP 200，只是没有这段数据。
"""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from src.config import SSO_BASE
from src.system_api import RedeemContext, fail
from src.utils import log, mask

_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_AUTHORIZE_PATH = "/oauth/authorize"
# 页面内嵌 `var userLoginInfo = {...} || {};`（与浏览器实测逐字一致）
_USER_INFO_RE = re.compile(r"userLoginInfo\s*=\s*(\{.*?\})\s*\|\|\s*\{\}", re.S)
# 导航型请求：剥掉 SSO 会话的 Origin / Referer（跨站跳转浏览器不会带这些头）
_NAV_HEADERS = {"Origin": None, "Referer": None,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}


def _parse_user_info(html: str) -> dict:
    """从座位首页 HTML 解析 userLoginInfo；返回 {uid, uname, sno}。"""
    match = _USER_INFO_RE.search(html or "")
    if not match:
        raise ValueError("页面未包含 userLoginInfo（未登录或结构变化）")
    try:
        payload = json.loads(match.group(1))
    except ValueError as exc:
        raise ValueError("userLoginInfo 不是合法 JSON") from exc
    user = payload.get("userInfo") if isinstance(payload, dict) else None
    if not isinstance(user, dict):
        raise ValueError("userLoginInfo 缺少 userInfo 对象")
    uid = str(user.get("uid") or "").strip()
    if not uid:
        raise ValueError("userInfo 缺少 uid")
    return {"uid": uid, "uname": str(user.get("uname") or "").strip(),
            "sno": str(user.get("sno") or "").strip()}


def _is_cx_host(host: str) -> bool:
    return host == "chaoxing.com" or host.endswith(".chaoxing.com")


def _authorize(client, cfg: dict) -> dict:
    """授权取码；scope / state 显式送空串（对齐浏览器抓包，通用 authorize 会省略空值）。"""
    response = client.sess.get(SSO_BASE + _AUTHORIZE_PATH, params={
        "client_id": cfg["client_id"], "response_type": "code", "scope": "",
        "redirect_uri": cfg["redirect_uri"], "state": "",
    }, allow_redirects=False, timeout=client.timeout)
    location = response.headers.get("Location", "")
    result = {
        "http_status": response.status_code,
        "location": location,
        # 被踢回登录页 = SSO 会话没复用上（与其他系统同一判据）
        "needs_login": "/oauth2/login/" in location,
        "code": parse_qs(urlsplit(location).query).get("code", [None])[0],
    }
    client.record("chaoxing/authorize", {"client_id": mask(cfg["client_id"]), **result})
    return result


def redeem(ctx: RedeemContext) -> dict:
    """newsso 授权 → 逐跳跟随 302 链 → office 座位首页 userLoginInfo 校验。"""
    client, cfg = ctx.client, ctx.cfg

    log("     [OAuth ①] 授权请求显式带空 scope / state（对齐浏览器抓包）")
    auth = _authorize(client, cfg)
    if auth["needs_login"]:
        log("     ✗ 需要重新登录（会话未复用）")
        return fail("session_not_reused", authorize=auth)
    if not auth["location"]:
        log("     ✗ 未取得重定向地址")
        return fail("no_redirect", authorize=auth)
    if not auth["code"]:
        log("     ✗ 未取到授权码")
        return fail("no_code", authorize=auth)
    log(f"     [OAuth ③] HTTP {auth['http_status']} → 取到 code: {mask(auth['code'], 8)}")

    # [OAuth ④] 5read → passport2-api login6 → 落地；每跳显式跟随，结构变化立即暴露
    log("     [OAuth ④] 逐跳跟随 5read → login6 → chaoxing 域 ...")
    current, final, hops = auth["location"], None, 0
    while True:
        final = client.sess.get(current, headers=_NAV_HEADERS, allow_redirects=False,
                                timeout=client.timeout)
        next_location = (final.headers.get("Location") or "").strip()
        if final.status_code not in _REDIRECT_STATUSES or not next_location:
            break
        hops += 1
        if hops > cfg["max_redirect_hops"]:
            log("     ✗ 重定向次数超过限制")
            client.record("chaoxing/chain", {"ok": False, "hops": hops})
            return fail("too_many_redirects", http_status=final.status_code)
        current = urljoin(final.url or current, next_location)

    host = (urlsplit(final.url or current).hostname or "").lower()
    chain_ok = _is_cx_host(host)
    client.record("chaoxing/chain", {"ok": chain_ok, "hops": hops,
                                     "http_status": final.status_code})
    if not chain_ok:
        log(f"     ✗ 换会话链未落到 chaoxing 域（{host or '未知主机'}）")
        return fail("chain_failed", http_status=final.status_code, final_host=host)

    # [验证] office 座位首页：userLoginInfo 必须解析成功（唯一成功判据）
    log("     [验证] office 座位首页 userLoginInfo ...")
    page = client.sess.get(cfg["landing_url"], headers=_NAV_HEADERS,
                           allow_redirects=True, timeout=client.timeout)
    page_host = (urlsplit(page.url or "").hostname or "").lower()
    if not _is_cx_host(page_host):
        log(f"     ✗ 座位首页被重定向到站外（{page_host or '未知主机'}），会话未建立")
        return fail("invalid_session", http_status=page.status_code, final_host=page_host)
    try:
        user = _parse_user_info(page.text)
    except ValueError as exc:
        log(f"     ✗ {exc}")
        return fail("invalid_session", http_status=page.status_code)

    result = {
        "system": ctx.key,
        "detection": cfg.get("detection", "api"),
        "final_url": cfg["landing_url"],
        "http_status": page.status_code,
        "chain_hops": hops,
        "user_id": user["uid"],
        "username": user["sno"],
        "real_name": user["uname"],
        "body_match": None,
        "url_match": None,
        "logged_in": True,
        "body_preview": (f"userLoginInfo: uid={user['uid']} sno={user['sno']} "
                         f"uname={user['uname']}（链 {hops} 跳）"),
    }
    client.record(f"redeem/{ctx.key}", result)
    log(f"     [OAuth ④] ✓ 已解析座位首页 userLoginInfo（uid={user['uid']}）")
    return result
