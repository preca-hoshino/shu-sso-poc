"""SSO 客户端：封装对 newsso (newsso.shu.edu.cn) 的全部 HTTP 访问。

提供一次登录后复用 SHU_OAUTH2 会话 Cookie，向多个业务系统分别换取授权的能力。
"""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime
from urllib.parse import parse_qs, quote, urlparse

import requests
import warnings

# 按要求忽略证书校验，同时抑制 urllib3 的告警噪音
warnings.filterwarnings("ignore", message="Unverified HTTPS request")
try:
    from urllib3.exceptions import InsecureRequestWarning
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
except Exception:
    pass

from . import config
from .utils import mask, rsa_encrypt_password


class ShuSSO:
    """上海大学统一身份认证客户端。

    一次登录后，凭借 newsso 域内的 SHU_OAUTH2 会话 Cookie，
    可向多个业务系统分别换取授权并完成登录。
    """

    def __init__(self, tenant: str = config.DEFAULT_TENANT, timeout: int = 30):
        self.sess = requests.Session()
        self.sess.verify = False          # 忽略证书错误（按需求）
        self.sess.headers.update({
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"),
            "Accept": "application/json, text/plain, */*",
            "Origin": config.SSO_BASE,
            "Referer": config.SSO_BASE + "/",
        })
        self.tenant = tenant
        self.timeout = timeout
        self.trace: list[dict] = []

    # ---- 记录每一步 ------------------------------------------------
    def _record(self, step: str, detail: dict) -> None:
        self.trace.append({"step": step, "time": datetime.now().isoformat(), **detail})

    # ---- 1. 登录 --------------------------------------------------
    def login(self, username: str, password: str, params_b64: str | None = None) -> dict:
        body = {
            "username": username,
            "password": rsa_encrypt_password(password),
            "tenantId": self.tenant,
        }
        if params_b64:
            body["params"] = params_b64

        r = self.sess.post(f"{config.SSO_BASE}/oauth/userLogin", json=body,
                           headers={"Request-Id": str(uuid.uuid4())},
                           timeout=self.timeout)
        try:
            data = r.json()
        except Exception:
            data = {"message": f"non-json response (HTTP {r.status_code})",
                    "body": r.text[:500]}

        self._record("userLogin", {"http_status": r.status_code, "response": data})
        return data

    # ---- 2. 两步验证：发码 ----------------------------------------
    def send_2fa_code(self, method: str) -> dict:
        r = self.sess.post(f"{config.SSO_BASE}/oauth/twoStep/send", json={"method": method},
                           timeout=self.timeout)
        try:
            data = r.json()
        except Exception:
            data = {"message": f"non-json (HTTP {r.status_code})", "body": r.text[:300]}
        self._record("twoStep/send", {"method": method, "http_status": r.status_code,
                                      "response": data})
        return data

    # ---- 3. 两步验证：校验 ----------------------------------------
    def verify_2fa_code(self, login_ctx: dict, code: str, method: str) -> dict:
        body = dict(login_ctx)
        body["code"] = code
        body["method"] = method
        r = self.sess.post(f"{config.SSO_BASE}/oauth/twoStep/verify", json=body, timeout=self.timeout)
        try:
            data = r.json()
        except Exception:
            data = {"message": f"non-json (HTTP {r.status_code})", "body": r.text[:300]}
        self._record("twoStep/verify", {"method": method, "http_status": r.status_code,
                                        "response": data})
        return data

    # ---- 4. 授权：拿 code ----------------------------------------
    def authorize(self, client_id: str, redirect_uri: str, scope: str = "",
                  state: str = "") -> dict:
        q = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri}
        if scope:
            q["scope"] = scope
        if state:
            q["state"] = state

        r = self.sess.get(f"{config.SSO_BASE}/oauth/authorize", params=q,
                          allow_redirects=False, timeout=self.timeout)
        location = r.headers.get("Location", "")
        needs_login = "/oauth2/login/" in location
        code = None
        if "code=" in location:
            code = parse_qs(urlparse(location).query).get("code", [None])[0]

        result = {
            "authorize_url": r.url,
            "sent_params": {
                "response_type": "code",
                "client_id": mask(client_id),
                "redirect_uri": redirect_uri,
                "scope": scope,
                "state": mask(state, 8),
            },
            "http_status": r.status_code,
            "location": location,
            "needs_login": needs_login,
            "code": code,
        }
        self._record("authorize", {"client_id": mask(client_id), **result})
        return result

    # ---- 5. 消费 code：完成业务系统登录 ---------------------------
    def redeem(self, system_key: str, location: str) -> dict:
        cfg = config.SYSTEMS[system_key]
        r = self.sess.get(location, allow_redirects=True, timeout=self.timeout)
        body = r.text or ""

        # 某些系统（如 OTP）的回调页用 Refresh 头跳转而非 302，
        # requests 不会自动跟随，这里手动跟进一次。
        follow = cfg.get("follow_up_url")
        if follow and cfg["success_url_contains"] not in r.url:
            r2 = self.sess.get(follow, allow_redirects=True, timeout=self.timeout)
            if cfg["success_url_contains"] in r2.url or cfg["success_body_contains"] in (r2.text or ""):
                r, body = r2, (r2.text or "")

        ok_url = cfg["success_url_contains"] in r.url
        ok_body = cfg["success_body_contains"] in body
        result = {
            "system": system_key,
            "final_url": r.url,
            "http_status": r.status_code,
            "url_match": ok_url,
            "body_match": ok_body,
            "logged_in": bool(ok_url or ok_body),
            "body_preview": body[:400],
        }
        self._record(f"redeem/{system_key}", result)
        return result

    # ---- 6. BBS 专用：先取 state ---------------------------------
    def bootstrap_state(self, url: str) -> str | None:
        r = self.sess.get(url, allow_redirects=False, timeout=self.timeout)
        loc = r.headers.get("Location", "")
        state = parse_qs(urlparse(loc).query).get("state", [None])[0]
        self._record("bootstrap_state", {"url": url, "location": loc, "state": state})
        return state

    # ---- 7. 企业微信：拿到「扫码后打开的确认 URL」 -----------------
    # 原理：newsso 前端用企微官方 WwLogin SDK 渲染二维码。
    #       qrConnect 页面直接返回 HTML，其中内嵌 `qrImg?key=<hex>`；
    #       解码该二维码，其内容就是 `confirm2?k=<同一个key>&notretry=yes`。
    #       因此无需扫码，仅凭 HTTP 请求即可还原出扫码后 URL。
    #
    #       进一步：企微官方 confirm2 页面自身就是靠 scheme 唤起客户端的，
    #       其内联脚本原文为：
    #         launchWWByScheme("wxwork://sso/jump?url=" + encodeURIComponent(confirm2_url))
    #       所以把 confirm2 URL 包进 `wxwork://sso/jump?url=` 即得到
    #       「一键在企业微信内部打开确认页」的链接。
    def wecom_qrcode_info(self, state: str = "") -> dict:
        q = {
            "appid": config.WECOM["appid"],
            "agentid": config.WECOM["agentid"],
            "redirect_uri": config.WECOM["redirect_uri"],
            "state": state,
            "lang": "zh",
            "version": "1.2.7",
            "login_type": "jssdk",
        }
        r = self.sess.get(config.WECOM["qrcode_base"], params=q, timeout=self.timeout)
        html = r.text or ""

        # 提取 key：qrImg?key=<hex>
        m = re.search(r"qrImg\?key=([0-9a-fA-F]+)", html)
        key = m.group(1) if m else None

        confirm_url = f"{config.WECOM['confirm_base']}?k={key}&notretry=yes" if key else None
        result = {
            "qrConnect_url": r.url,
            "http_status": r.status_code,
            "key": key,
            "qr_img_url": f"{config.WECOM['img_base']}?key={key}" if key else None,
            "confirm_url": confirm_url,
            # 企业微信客户端内直接打开的 scheme（外部浏览器/短信里点击可拉起企微）
            "wxwork_scheme": (config.WECOM["scheme_jump_base"]
                              + quote(confirm_url, safe="")) if confirm_url else None,
        }
        self._record("wecom_qrcode", result)
        return result

    # ---- 8. 企业微信扫码登录：长轮询等 auth_code --------------------
    # 原理（用 Chrome DevTools 抓包 + 读 qrConnect 页面 window.settings 确认）：
    #   qrConnect 页面暴露 longPollGetUrl = /wwopen/sso/l/qrConnect，
    #   浏览器对它发起 GET 长轮询，返回 JSONP：
    #     jsonpCallback({"status":"QRCODE_SCAN_NEVER","auth_code":""})
    #   状态机（实测捕获）：
    #     QRCODE_SCAN_NEVER  未扫码
    #     QRCODE_SCAN_ING    已扫、待手机确认
    #     QRCODE_SCAN_SUCC   已确认 → auth_code 有值
    #     QRCODE_SCAN_ERR    二维码过期
    #   拿到 auth_code 后 GET /oauth/wecom/qrcode?code=<auth_code>&state=<paramsBase64>
    #   即可换取 SHU_OAUTH2 会话。
    def wecom_wait_scan(self, key: str, state: str = "", timeout: int = 180,
                        poll_log=None) -> dict:
        deadline = time.time() + timeout
        last_status = None
        # 长轮询属于 open.work.weixin.qq.com，需用该域的 Referer/Origin，
        # 否则可能被拒（ShuSSO 会话默认头指向 newsso）。
        hdrs = {
            "Referer": config.WECOM["qrcode_base"],
            "Origin": "https://open.work.weixin.qq.com",
            "x-requested-with": "XMLHttpRequest",
            "Accept": "text/javascript, application/javascript, application/ecmascript, */*; q=0.01",
        }
        while time.time() < deadline:
            try:
                r = self.sess.get(config.WECOM["longpoll"], params={
                    "callback": "jsonpCallback",
                    "key": key,
                    "redirect_uri": config.WECOM["redirect_uri"],
                    "appid": config.WECOM["appid"],
                    "_": int(time.time() * 1000),
                }, headers=hdrs, timeout=40)
            except requests.exceptions.Timeout:
                continue
            except Exception:
                time.sleep(1)
                continue

            m = re.search(r"jsonpCallback\((\{.*?\})\)", r.text or "", re.S)
            if not m:
                continue
            try:
                data = json.loads(m.group(1))
            except Exception:
                continue

            status = data.get("status")
            if status != last_status:
                if poll_log:
                    poll_log(status, data.get("auth_code") or "")
                last_status = status

            if status == "QRCODE_SCAN_SUCC" and data.get("auth_code"):
                out = {"ok": True, "status": status,
                       "auth_code": data["auth_code"]}
                self._record("wecom_wait_scan", out)
                return out
            if status in ("QRCODE_SCAN_ERR", "QRCODE_SCAN_OVERDUE",
                          "QRCODE_SCAN_CANCEL"):
                out = {"ok": False, "status": status, "reason": "qrcode_expired_or_cancelled"}
                self._record("wecom_wait_scan", out)
                return out
            if status == "QRCODE_SCAN_ING":
                time.sleep(0.5)

        out = {"ok": False, "status": last_status, "reason": "timeout"}
        self._record("wecom_wait_scan", out)
        return out

    # ---- 9. 企业微信扫码登录：用 auth_code 换 SSO 会话 -------------
    # 注意：回调除 code/state 外还**必须带 appid**（DevTools 抓浏览器实际请求确认），
    #       缺 appid 会返回 {"message":"badRequestParams"}。
    def wecom_redeem(self, auth_code: str, state: str) -> dict:
        r = self.sess.get(config.WECOM["redirect_uri"],
                          params={"code": auth_code, "state": state,
                                  "appid": config.WECOM["appid"]},
                          allow_redirects=False, timeout=self.timeout)
        loc = r.headers.get("Location", "") or ""
        ok = "message=wecomAuthFailed" not in loc and "badRequestParams" not in (r.text or "")
        result = {
            "ok": ok,
            "http_status": r.status_code,
            "location": loc,
            "cookies": [c.name for c in self.sess.cookies],
            "body": (r.text or "")[:300],
        }
        self._record("wecom_redeem", result)
        return result
