"""账号密码入口：凭据 → 2FA → 建立 SSO 会话 → 批量登录业务系统。"""

from __future__ import annotations

import getpass

from .client import ShuSSO
from .runner import login_all_systems, save_evidence, session_params, total_systems
from .ui import print_error_hint, print_summary, print_wecom_qr
from .utils import log, rsa_encrypt_password, save_json


def password_flow(args) -> int:
    """返回退出码：0 全部成功，5 部分失败，1~4 认证阶段失败。"""
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
    login_params = session_params()      # params 必填（缺了直接返回 badRequestParams）

    # ---------- 第 1 步：登录 ----------
    log("\n[OAuth ②｜用户认证] POST /oauth/userLogin (RSA 加密密码)")
    login_data = client.login(username, password, login_params)
    msg = login_data.get("message")
    if msg != "success":
        log(f"  ✗ 登录失败：{msg}")
        save_json("script-01-login-failed.json",
                  {"username": username, "response": login_data, "trace": client.trace})
        print_error_hint(msg)
        return 2
    log("  ✓ 认证成功")

    # ---------- 第 2 步：两步验证 ----------
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
        verify_resp = client.verify_2fa_code({
            "username": username,
            "password": rsa_encrypt_password(password),
            "tenantId": args.tenant,
            "params": login_params,
        }, code, method)
        if verify_resp.get("message") != "success":
            log(f"  ✗ 验证失败：{verify_resp.get('message')}")
            save_json("script-03-verify-failed.json",
                      {"method": method, "response": verify_resp, "trace": client.trace})
            print_error_hint(verify_resp.get("message"))
            return 4
        log("  ✓ 验证通过，SSO 会话已建立")
    else:
        log("  ✓ 登录成功（无需两步验证），SSO 会话已建立")

    log("  ✓ 已建立 SSO 会话 Cookie: SHU_OAUTH2（newsso 域可跨系统复用）")

    # ---------- 企微确认页（纯展示，失败不影响后续系统登录） ----------
    wecom: dict = {}
    if method == "wecom":
        try:
            wecom = client.wecom_qrcode_info(state=login_params)
        except Exception as exc:                      # noqa: BLE001 - 展示环节，不致命
            log(f"\n[企微扫码] 获取二维码信息失败（{type(exc).__name__}: {exc}），跳过展示")
            wecom = {}
        if wecom.get("key"):
            log("\n[企微扫码] 本次会话的二维码与唤起链接：")
            print_wecom_qr(wecom["confirm_url"], args)
            log(f"     二维码图片 : {wecom['qr_img_url']}")
            log(f"     确认页地址 : {wecom['confirm_url']}")
            log(f"     URI 跳转   : {wecom['wxwork_scheme']}")
        elif wecom:
            log(f"\n[企微扫码] 未能解析出 key（HTTP {wecom.get('http_status')}）")

    # ---------- 第 3 步：逐个系统换授权 ----------
    results = login_all_systems(client, username=username)
    ok = print_summary(results)

    log("")
    log("  结论：授权码一次性、绑定 state，不可复用；")
    log("        SHU_OAUTH2 会话 Cookie 在 newsso 域内可被多系统复用（OAuth 2.0，非 OIDC）。")

    path = save_evidence("script-result.json", client, results,
                         username=username, tenant=args.tenant,
                         two_factor_method=method, wecom_qrcode=wecom)
    log(f"\n证据已保存: {path}（密码与授权码已脱敏）")

    return 0 if ok == total_systems() else 5
