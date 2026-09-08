"""高层登录流程：密码 / 企微扫码两种入口，及批量登录、汇总。

这些函数是 CLI 入口（poc.py）背后的实际业务编排，不直接接触网络细节
（网络细节在 client.ShuSSO 中）。
"""

from __future__ import annotations

import getpass
import uuid
from datetime import datetime

from . import config
from .client import ShuSSO
from .utils import b64_params, log, mask, rsa_encrypt_password, save_json


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


def choose_login_mode(args) -> str:
    """选择登录方式：password（账号密码+2FA）或 wecom_scan（企微扫码）。"""
    if args.login:
        return args.login
    print("\n请选择登录方式：")
    print("  [1] 账号密码登录（学号/工号 + 密码 + 两步验证）")
    print("  [2] 企业微信扫码登录（扫码确认后自动登录 3 个系统）")
    choice = input("输入 1 或 2 [默认 1]: ").strip() or "1"
    return "wecom_scan" if choice == "2" else "password"


def login_all_systems(client: ShuSSO) -> dict[str, dict]:
    """用已建立的 SSO 会话，依次向 3 个业务系统换取授权并登录。

    返回 {system_key: redeem 结果}。
    """
    log(f"\n[OAuth ①③④] 用同一 SSO 会话依次登录 {len(config.SYSTEMS)} 个系统...\n")
    results: dict[str, dict] = {}

    for key, cfg in config.SYSTEMS.items():
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

    return results


def print_summary(results: dict[str, dict]) -> int:
    """打印汇总，返回成功系统数。"""
    log("=" * 62)
    log(" 验证结果汇总")
    log("=" * 62)
    ok = 0
    for key, cfg in config.SYSTEMS.items():
        r = results.get(key, {})
        status = "✓ 成功" if r.get("logged_in") else "✗ 失败"
        log(f"  {status}  {cfg['name']:<18} {(r.get('final_url') or '')[:42]}")
        if r.get("logged_in"):
            ok += 1
    log("=" * 62)
    log(f"  合计：{ok}/{len(config.SYSTEMS)} 个系统登录成功")
    return ok


def password_flow(args) -> int:
    """账号密码登录流程：输入凭据 → 可选 2FA → 自动登录 3 个系统。

    返回退出码（0 全部成功，其余为失败）。
    """
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
    first = config.SYSTEMS["jwxt"]
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

    # ---------- 企业微信扫码确认 URL（仅 2FA 走企微时展示） ----------
    # 无需扫码，直接从 qrConnect 页面解析出 key，还原出「扫码后打开的确认页」地址
    wecom: dict = {}
    if method == "wecom":
        wecom = client.wecom_qrcode_info(state=login_params)
        if wecom.get("key"):
            log("\n[企微扫码] 本次会话的二维码与唤起链接：")
            log(f"     二维码图片 : {wecom['qr_img_url']}")
            log(f"     确认页地址 : {wecom['confirm_url']}")
            log(f"     URI 跳转   : {wecom['wxwork_scheme']}")
        else:
            log(f"\n[企微扫码] 未能解析出 key（HTTP {wecom.get('http_status')}）")

    # ---------- 第 3 步：逐个系统换授权 ----------
    results = login_all_systems(client)
    ok = print_summary(results)

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

    return 0 if ok == len(config.SYSTEMS) else 5


def wecom_scan_flow(args) -> int:
    """企业微信扫码登录：生成二维码 → 长轮询等 auth_code → 换 SSO 会话 → 登录 3 个系统。

    机制（用 Chrome DevTools 抓包确认）：
      1. qrConnect 页面内嵌 qrImg?key=<key>，key 即本次扫码会话标识；
      2. 页面同时对 /wwopen/sso/l/qrConnect 发起 JSONP 长轮询，
         返回 {"status":"QRCODE_SCAN_XXX","auth_code":"..."}；
      3. 状态到 QRCODE_SCAN_SUCC 时 auth_code 有值；
      4. GET /oauth/wecom/qrcode?code=<auth_code>&state=<paramsBase64> 换 SSO 会话。
    """
    client = ShuSSO(tenant=args.tenant)

    # state = paramsBase64（newsso 前端 WwLogin({state:n})，n 即 paramsBase64）
    first = config.SYSTEMS["jwxt"]
    state = b64_params({
        "responseType": "code",
        "clientId": first["client_id"],
        "clientName": first["name"],
        "scope": first["scope"],
        "redirectUri": first["redirect_uri"],
        "state": "",
    })

    log("\n[企微扫码] 请求 qrConnect，生成本次会话二维码 ...")
    info = client.wecom_qrcode_info(state=state)

    if not info.get("key"):
        log(f"  ✗ 未能解析出 key（HTTP {info.get('http_status')}）")
        save_json("script-00-wecom-scan-failed.json",
                  {"response": info, "trace": client.trace})
        return 6

    line = "─" * 62
    print()
    print(line)
    print(" 请用企业微信扫描下面的二维码并在手机上点「确认登录」")
    print()
    print(" ① 二维码图片 URL（浏览器打开即可扫码）")
    print(f"    {info['qr_img_url']}")
    print()
    print(" ② 二维码内容 = 扫码后企微打开的确认页")
    print(f"    {info['confirm_url']}")
    print()
    print(" ③ 包装后的 URI 跳转（在企微内直接打开该确认页）")
    print(f"    {info['wxwork_scheme']}")
    print(line)
    print(f" 等待扫码确认（最多 {args.scan_timeout} 秒，Ctrl+C 可中断）...")

    def _on_status(status, auth_code):
        shown = {
            "QRCODE_SCAN_NEVER": "等待扫码",
            "QRCODE_SCAN_ING": "已扫码，请在手机上确认",
            "QRCODE_SCAN_SUCC": "已确认，正在换取会话",
            "QRCODE_SCAN_ERR": "二维码已过期",
        }.get(status, status)
        log(f"     {shown}")

    wait = client.wecom_wait_scan(info["key"], state=state,
                                  timeout=args.scan_timeout, poll_log=_on_status)

    if not wait.get("ok"):
        log(f"  ✗ 未取得 auth_code（{wait.get('reason') or wait.get('status')}）")
        save_json("script-00-wecom-scan-failed.json",
                  {"wait": wait, "wecom_qrcode": info, "trace": client.trace})
        return 7

    log("  ✓ 已取得 auth_code，换取 SSO 会话 ...")
    red = client.wecom_redeem(wait["auth_code"], state)
    if not red["ok"]:
        log(f"  ✗ 换取会话失败（HTTP {red['http_status']}）")
        save_json("script-00-wecom-redeem-failed.json",
                  {"redeem": red, "trace": client.trace})
        return 8

    log(f"  ✓ SSO 会话已建立（Cookie: SHU_OAUTH2）")
    log(f"     → {red['location'][:90]}")

    # ---------- 用同一会话依次登录 3 个系统 ----------
    results = login_all_systems(client)
    ok = print_summary(results)

    path = save_json("script-wecom-scan.json", {
        "timestamp": datetime.now().isoformat(),
        "tenant": args.tenant,
        "mode": "wecom_scan",
        "state": state,
        "wecom_qrcode": info,
        "wait": wait,
        "redeem": red,
        "summary": {k: {"logged_in": v.get("logged_in"),
                        "final_url": v.get("final_url")} for k, v in results.items()},
        "details": results,
        "trace": client.trace,
    })
    log(f"\n证据已保存: {path}")
    return 0 if ok == len(config.SYSTEMS) else 5


def _print_error_hint(msg: str | None) -> None:
    """针对常见错误码给出中文提示。"""
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
