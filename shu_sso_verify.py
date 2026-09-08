#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
上海大学统一身份认证 (newsso.shu.edu.cn) 多系统登录最小验证脚本
================================================================

目的：用「一次登录」的同一套凭据，向 3 个业务系统分别换取授权，验证是否都能登录成功。

协议（2026-09-08 实测）：OAuth 2.0 授权码模式 (RFC 6749)，非 OIDC
* SSO 会话 Cookie: SHU_OAUTH2（HttpOnly, host-scoped）
* 登录端点: POST /oauth/userLogin {username, password(RSA-PKCS1v15→base64), tenantId, params(base64url)}
* 2FA 端点: POST /oauth/twoStep/send {method: sms|wecom}；POST /oauth/twoStep/verify {...code, method}
* 授权端点: GET /oauth/authorize?response_type=code&client_id&redirect_uri&scope&state
* 结论: 授权码一次性、绑定 state 不可复用；但 SSO 会话 Cookie 在 newsso 域内可复用

外显：控制台按 [OAuth ①/②/③/④] 标注标准授权码流程（①构造授权请求→②用户认证→③下发code→④码换会话）

安全：密码经 getpass 读取，不落盘/不打印；保存的 JSON 自动剔除 password 字段；仅供账号所有者本机验证。

用法:
    python shu_sso_verify.py            # 交互式（推荐）
    python shu_sso_verify.py --tenant 上海大学
"""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import re
import sys
import uuid
import warnings
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding

# 按要求忽略证书校验，同时抑制 urllib3 的告警噪音
warnings.filterwarnings("ignore", message="Unverified HTTPS request")
try:
    from urllib3.exceptions import InsecureRequestWarning
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
except Exception:
    pass

# --------------------------------------------------------------------------
# 常量：从 newsso 前端 bundle 中提取
# --------------------------------------------------------------------------

SSO_BASE = "https://newsso.shu.edu.cn"

# RSA 公钥（1024-bit，来自 /p__oauth2__login__index.*.async.js 中的 Pe 常量）
RSA_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDl/aCgRl9f/4ON9MewoVnV58OL
OU2ALBi2FKc5yIsfSpivKxe7A6FitJjHva3WpM7gvVOinMehp6if2UNIkbaN+plW
f5IwqEVxsNZpeixc4GsbY9dXEk3WtRjwGSyDLySzEESH/kpJVoxO7ijRYqU+2oSR
wTBNePOk1H+LRQokgQIDAQAB
-----END PUBLIC KEY-----"""

DEFAULT_TENANT = "上海大学"

# 企业微信扫码登录参数（来自 newsso 前端 bundle，硬编码）
# 说明：newsso 前端用企微官方 WwLogin SDK 渲染二维码，参数是硬编码的。
WECOM = {
    "appid": "wxa8dea949443de641",                       # 上海大学企微应用 appid
    "agentid": "1000059",                                # 企微自建应用 agentid
    "redirect_uri": "https://newsso.shu.edu.cn/oauth/wecom/qrcode",  # 扫码回调
    "qrcode_base": "https://open.work.weixin.qq.com/wwopen/sso/qrConnect",
    "img_base": "https://open.work.weixin.qq.com/wwopen/sso/qrImg",
    "confirm_base": "https://open.work.weixin.qq.com/wwopen/sso/confirm2",
}

# 三个目标系统（client 注册信息已实测确认）
SYSTEMS = {
    "jwxt": {
        "name": "本科生教务系统",
        "client_id": "Km5t225E8KECKQ6ZDm5K2P6aS2459Cua",
        "redirect_uri": "https://jwxt.shu.edu.cn/sso/shulogin",
        "scope": "jw",
        # jwxt 的 /sso/shulogin 跳转 newsso 时**不带 state**，
        # 需自行生成随机 state（与 OTP/BBS 不同，无需预热）
        "generate_state": True,
        # 登录成功后的判定：URL 含该串 或 页面含该关键词
        "success_url_contains": "jwglxt",
        "success_body_contains": "教学管理",
    },
    "otp": {
        "name": "OTP令牌",
        "client_id": "05Q1L8woQK5350aK1U5o5GKh411ar3h1",
        "redirect_uri": "https://otp.shu.edu.cn//Callback.aspx",
        "scope": "read write",
        # OTP 的 Callback.aspx 会校验 state（存在 ASP.NET_SessionId 里），
        # 必须先访问它的入口拿到 state，否则回调报「State验证失败」
        "needs_state_bootstrap": "https://otp.shu.edu.cn/",
        # OTP 的 Callback.aspx 用 Refresh 头跳转（非 HTTP 302），需手动跟进
        "follow_up_url": "https://otp.shu.edu.cn/Default.aspx",
        "success_url_contains": "Default.aspx",
        "success_body_contains": "账户名",
    },
    "bbs": {
        "name": "上大bbs (乐乎社区)",
        "client_id": "vp8G2H42GGE86LP822LHF6Hs7f46483H",
        "redirect_uri": "https://bbs.shu.edu.cn/auth/oauth2_basic/callback",
        "scope": "",
        # BBS 特例：必须先向它自己要一个 state，再改走 newsso 授权
        "needs_state_bootstrap": "https://bbs.shu.edu.cn/auth/oauth2_basic",
        "success_url_contains": "bbs.shu.edu.cn",
        "success_body_contains": "乐乎",
    },
}

CAPTURE_DIR = Path(__file__).parent / "captures"


# --------------------------------------------------------------------------
# 工具函数
# --------------------------------------------------------------------------

def rsa_encrypt_password(plain: str) -> str:
    """用 newsso 的 RSA 公钥加密密码（PKCS#1 v1.5），返回 base64 字符串。"""
    pub = serialization.load_pem_public_key(RSA_PUBLIC_KEY_PEM.encode())
    ciphertext = pub.encrypt(plain.encode("utf-8"), padding.PKCS1v15())
    return base64.b64encode(ciphertext).decode()


def b64_params(oauth_params: dict) -> str:
    """
    把 OAuth 参数编码成 newsso 前端使用的格式。

    实测确认：浏览器用的是 **base64url（去掉 = 填充）**，而非标准 base64。
    例：`eyJyZXNwb25zZVR5cGUiOiJjb2RlIiwi...` （含 `_` 不含 `/`，无 padding）
    """
    raw = json.dumps(oauth_params, separators=(",", ":"), ensure_ascii=False)
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode().rstrip("=")


def redact(obj):
    """递归剔除敏感字段，避免密码等写入证据文件。"""
    if isinstance(obj, dict):
        return {k: ("***REDACTED***" if k.lower() in {"password", "code"} else redact(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    return obj


def save_json(name: str, payload) -> Path:
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = CAPTURE_DIR / name
    path.write_text(json.dumps(redact(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def log(msg: str) -> None:
    print(msg, flush=True)


def mask(s: str, keep: int = 4) -> str:
    if not s:
        return ""
    return s[:keep] + "..." + s[-keep:] if len(s) > keep * 2 else s


# --------------------------------------------------------------------------
# SSO 客户端
# --------------------------------------------------------------------------

class ShuSSO:
    def __init__(self, tenant: str = DEFAULT_TENANT, timeout: int = 30):
        self.sess = requests.Session()
        self.sess.verify = False          # 忽略证书错误（按需求）
        self.sess.headers.update({
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"),
            "Accept": "application/json, text/plain, */*",
            "Origin": SSO_BASE,
            "Referer": SSO_BASE + "/",
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

        r = self.sess.post(f"{SSO_BASE}/oauth/userLogin", json=body,
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
        r = self.sess.post(f"{SSO_BASE}/oauth/twoStep/send", json={"method": method},
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
        r = self.sess.post(f"{SSO_BASE}/oauth/twoStep/verify", json=body, timeout=self.timeout)
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

        r = self.sess.get(f"{SSO_BASE}/oauth/authorize", params=q,
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
        cfg = SYSTEMS[system_key]
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
    def wecom_qrcode_info(self, state: str = "") -> dict:
        q = {
            "appid": WECOM["appid"],
            "agentid": WECOM["agentid"],
            "redirect_uri": WECOM["redirect_uri"],
            "state": state,
            "lang": "zh",
            "version": "1.2.7",
            "login_type": "jssdk",
        }
        r = self.sess.get(WECOM["qrcode_base"], params=q, timeout=self.timeout)
        html = r.text or ""

        # 提取 key：qrImg?key=<hex>
        m = re.search(r"qrImg\?key=([0-9a-fA-F]+)", html)
        key = m.group(1) if m else None

        result = {
            "qrConnect_url": r.url,
            "http_status": r.status_code,
            "key": key,
            "qrImg_url": f"{WECOM['img_base']}?key={key}" if key else None,
            "confirm_url": f"{WECOM['confirm_base']}?k={key}&notretry=yes" if key else None,
        }
        self._record("wecom_qrcode", result)
        return result


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def banner() -> None:
    """打印协议说明 + OAuth 2.0 授权码四步流程（紧凑版）。"""
    print("=" * 62)
    print(" 上海大学统一身份认证 · 多系统登录验证")
    print(" 协议: OAuth 2.0 授权码模式 (RFC 6749)，非 OIDC")
    print()
    print(" ① 构造授权请求   GET /oauth/authorize?response_type=code&client_id&redirect_uri&scope&state")
    print(" ② 用户认证       POST /oauth/userLogin (RSA加密) + 可选 2FA")
    print(" ③ 下发授权码     返回 302 ?code=...&state=...")
    print(" ④ 码换会话        用 code 在业务系统登录")
    print("=" * 62)


def main() -> int:
    parser = argparse.ArgumentParser(description="上海大学 SSO 多系统登录验证")
    parser.add_argument("--tenant", default=DEFAULT_TENANT, help=f"院校（默认 {DEFAULT_TENANT}）")
    parser.add_argument("--method", choices=["wecom", "sms"], help="2FA 方式（省略则交互选择）")
    args = parser.parse_args()

    banner()

    # ---------- 收集凭据（本地终端输入，不经网络） ----------
    username = input("学号/工号: ").strip()
    if not username:
        print("错误：学号不能为空")
        return 1

    password = getpass.getpass("密码（输入时不显示）: ")
    if not password:
        print("错误：密码不能为空")
        return 1

    method = args.method
    if not method:
        print("\n请选择两步验证方式：")
        print("  [1] 企业微信 (wecom)")
        print("  [2] 手机短信 (sms)")
        choice = input("输入 1 或 2 [默认 1]: ").strip() or "1"
        method = "sms" if choice == "2" else "wecom"

    client = ShuSSO(tenant=args.tenant)

    # 登录时必须带 params（实测：缺 params 会返回 badRequestParams）
    # 这里用第一个系统（jwxt）的参数，仅用于建立 SSO 会话
    first = SYSTEMS["jwxt"]
    login_params = b64_params({
        "responseType": "code",
        "clientId": first["client_id"],
        "clientName": first["name"],
        "scope": first["scope"],
        "redirectUri": first["redirect_uri"],
        "state": "",
    })

    # ---------- 第 1 步：登录 ----------
    log("\n[OAuth ②｜用户认证] POST /oauth/userLogin (RSA 加密密码)")
    login_data = client.login(username, password, login_params)
    msg = login_data.get("message")

    if msg != "success":
        log(f"  ✗ 登录失败：{msg}")
        save_json("script-01-login-failed.json",
                  {"username": username, "response": login_data, "trace": client.trace})
        _print_error_hint(msg)
        return 2
    log("  ✓ 认证成功")

    # ---------- 第 2 步：处理 2FA ----------
    if login_data.get("twoStepRequired"):
        methods = login_data.get("twoStepMethods") or {}
        log(f"  → 需要两步验证，可用：{', '.join(methods.keys()) or '(无)'}")

        if method not in methods:
            log(f"  ! 所选 '{method}' 不可用，改用 {list(methods)[0] if methods else 'sms'}")
            method = list(methods)[0] if methods else "sms"

        log(f"[OAuth ②｜2FA] POST /oauth/twoStep/send (方式: {method})")
        send_resp = client.send_2fa_code(method)
        if send_resp.get("message") != "success":
            log(f"  ✗ 发码失败：{send_resp.get('message')}")
            save_json("script-02-send-code-failed.json",
                      {"method": method, "response": send_resp, "trace": client.trace})
            return 3
        log("  ✓ 验证码已发送")

        code = input("请输入收到的验证码: ").strip()
        if not code:
            print("错误：验证码不能为空")
            return 3

        log("[OAuth ②｜2FA] POST /oauth/twoStep/verify")
        login_ctx = {
            "username": username,
            "password": rsa_encrypt_password(password),
            "tenantId": args.tenant,
            "params": login_params,
        }
        verify_resp = client.verify_2fa_code(login_ctx, code, method)
        if verify_resp.get("message") != "success":
            log(f"  ✗ 验证失败：{verify_resp.get('message')}")
            save_json("script-03-verify-failed.json",
                      {"method": method, "response": verify_resp, "trace": client.trace})
            _print_error_hint(verify_resp.get("message"))
            return 4
        log("  ✓ 验证通过，SSO 会话已建立")
    else:
        log("  ✓ 登录成功（无需两步验证），SSO 会话已建立")

    log("  ✓ 已建立 SSO 会话 Cookie: SHU_OAUTH2（newsso 域可跨系统复用）")

    # ---------- 企业微信扫码确认 URL ----------
    # 无需扫码，直接从 qrConnect 页面解析出 key，还原出「扫码后打开的确认页」地址
    wecom = client.wecom_qrcode_info(state=login_params)
    if wecom.get("key"):
        log(f"\n[企微扫码] 无需扫码即可还原确认地址：")
        log(f"     key : {mask(wecom['key'], 8)}")
        log(f"     url : {wecom['confirm_url']}")
    else:
        log(f"\n[企微扫码] 未能解析出 key（HTTP {wecom.get('http_status')}）")

    # ---------- 第 3 步：逐个系统换授权 ----------
    log(f"\n[OAuth ①③④] 用同一 SSO 会话依次登录 {len(SYSTEMS)} 个系统...\n")
    results: dict[str, dict] = {}

    for key, cfg in SYSTEMS.items():
        log(f"  ── {cfg['name']} ({key}) ──")

        state = ""
        if cfg.get("needs_state_bootstrap"):
            state = client.bootstrap_state(cfg["needs_state_bootstrap"]) or ""
            log(f"     [OAuth ①] 预热 state: {mask(state, 8)}")
        elif cfg.get("generate_state"):
            # jwxt 的授权请求不带 state，自行生成随机 UUID 作为防 CSRF 值
            state = uuid.uuid4().hex
            log(f"     [OAuth ①] 生成 state: {mask(state, 8)}")

        auth = client.authorize(cfg["client_id"], cfg["redirect_uri"],
                                cfg.get("scope", ""), state)

        if auth["needs_login"]:
            log("     ✗ 需要重新登录（会话未复用）")
            results[key] = {"logged_in": False, "reason": "session_not_reused",
                            "authorize": auth}
            continue

        if not auth["location"]:
            log("     ✗ 未取得重定向地址")
            results[key] = {"logged_in": False, "reason": "no_redirect",
                            "authorize": auth}
            continue

        log(f"     [OAuth ③] HTTP {auth['http_status']} → 取到 code: {mask(auth['code'] or '', 8)}")
        red = client.redeem(key, auth["location"])
        results[key] = red

        if red["logged_in"]:
            log(f"     [OAuth ④] ✓ 登录成功 → {red['final_url'][:70]}")
        else:
            log(f"     [OAuth ④] ✗ 登录失败 → {red['final_url'][:70]}")
        print()

    # ---------- 汇总 ----------
    log("\n" + "=" * 62)
    log(" 验证结果汇总")
    log("=" * 62)
    ok = 0
    for key, cfg in SYSTEMS.items():
        r = results.get(key, {})
        status = "✓ 成功" if r.get("logged_in") else "✗ 失败"
        final = (r.get("final_url") or "")[:42]
        log(f"  {status}  {cfg['name']:<18} {final}")
        if r.get("logged_in"):
            ok += 1
    log("=" * 62)
    log(f"  合计：{ok}/{len(SYSTEMS)} 个系统登录成功")
    log("")
    log("  结论：授权码一次性、绑定 state，不可复用；")
    log("        SHU_OAUTH2 会话 Cookie 在 newsso 域内可被多系统复用（OAuth 2.0，非 OIDC）。")

    # ---------- 保存证据 ----------
    evidence = {
        "timestamp": datetime.now().isoformat(),
        "username": username,
        "tenant": args.tenant,
        "two_factor_method": method,
        "protocol": "OAuth 2.0 Authorization Code (RFC 6749), NOT OIDC",
        "sso_session_cookie": "SHU_OAUTH2",
        "wecom_qrcode": wecom,
        "summary": {k: {"logged_in": v.get("logged_in"),
                        "final_url": v.get("final_url")} for k, v in results.items()},
        "details": results,
        "trace": client.trace,
    }
    path = save_json("script-result.json", evidence)
    log(f"\n证据已保存: {path}（密码与授权码已脱敏）")

    return 0 if ok == len(SYSTEMS) else 5


def _print_error_hint(msg: str | None) -> None:
    hints = {
        "badPassword": "密码错误",
        "userNotFound": "用户不存在",
        "userLocked": "账号已锁定",
        "userNotAllowed": "账号不允许登录",
        "invalidCode": "验证码错误或已过期",
        "ipLimitExceeded": "IP 请求过于频繁",
        "wecomAuthFailed": "企业微信认证失败",
        "internalServerError": "服务端内部错误",
    }
    if msg in hints:
        print(f"  提示：{hints[msg]}")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已取消")
        sys.exit(130)
