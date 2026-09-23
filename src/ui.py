"""终端交互界面：横幅、菜单、二维码、结果汇总、错误提示。"""

from __future__ import annotations

import sys
import unicodedata

from . import config
from .qr import render_qr_terminal
from .utils import log

# 汇总表里对「流程早期就中止」的中文说明（来自各实现返回的 reason 字段）
REASON_TEXT = {
    "session_not_reused": "SSO 会话未复用，需重新登录",
    "no_redirect": "未取得重定向地址",
    "no_code": "未取到授权码",
    "no_external_id": "未取到认证方式 externalId",
    "interrupted": "用户中断",
    "exception": "异常中止",
}

# 常见错误码的中文提示
ERROR_HINTS = {
    "badPassword": "密码错误",
    "userNotFound": "用户不存在",
    "userLocked": "账号已锁定",
    "userNotAllowed": "账号不允许登录",
    "invalidCode": "验证码错误或已过期",
    "ipLimitExceeded": "IP 请求过于频繁",
    "wecomAuthFailed": "企业微信认证失败",
    "internalServerError": "服务端内部错误",
}


def banner() -> None:
    """打印协议说明 + OAuth 2.0 授权码四步流程。"""
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
    print("  [2] 企业微信扫码登录（扫码确认后自动登录全部系统）")
    choice = input("输入 1 或 2 [默认 1]: ").strip() or "1"
    return "wecom_scan" if choice == "2" else "password"


def pad(text: str, width: int) -> str:
    """按终端**显示宽度**右补空格对齐（中文等全角字符占 2 列）。"""
    w = sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)
    return text + " " * max(0, width - w)


def result_detail(r: dict) -> str:
    """为汇总行挑一段可读详情：成功看落地 URL，失败优先看原因/错误信息。"""
    if r.get("logged_in"):
        return r.get("final_url") or ""
    if r.get("reason") == "exception":
        return r.get("error") or REASON_TEXT["exception"]
    if r.get("reason"):
        return REASON_TEXT.get(r["reason"], r["reason"])
    # 未标注 reason：多用接口/页面信息说明，HTML 正文无参考价值故跳过
    preview = (r.get("body_preview") or "").strip()
    if preview.startswith("<"):
        preview = ""
    return preview or r.get("final_url") or ""


def print_summary(results: dict[str, dict]) -> int:
    """打印汇总，返回成功系统数。"""
    log("=" * 62)
    log(" 验证结果汇总")
    log("=" * 62)
    ok = 0
    for key, cfg in config.SYSTEMS.items():
        r = results.get(key, {})
        status = "✓ 成功" if r.get("logged_in") else "✗ 失败"
        detail = result_detail(r).replace("\n", " ")
        log(f"  {status}  {pad(cfg['name'], 20)} {detail[:42]}")
        if r.get("logged_in"):
            ok += 1
    log("=" * 62)
    log(f"  合计：{ok}/{len(config.SYSTEMS)} 个系统登录成功")
    return ok


def print_error_hint(msg: str | None) -> None:
    """针对常见错误码给出中文提示。"""
    if msg in ERROR_HINTS:
        print(f"  提示：{ERROR_HINTS[msg]}")


def print_wecom_qr(confirm_url: str, args) -> bool:
    """在终端渲染扫码二维码，返回是否渲染成功。

    三重保护：`--no-qr` 关闭 / 输出非 TTY 时跳过（ANSI 码会污染重定向的文件）/
    未装 qrcode 时返回 False（由调用方回退到打印图片 URL）。
    """
    if getattr(args, "no_qr", False):
        log("     （已按 --no-qr 关闭终端二维码）")
        return False
    if not sys.stdout.isatty():
        log("     （输出不是终端，跳过二维码渲染）")
        return False
    if render_qr_terminal(confirm_url, getattr(args, "qr_style", "block") or "block"):
        return True
    log("     （未安装 qrcode 库，无法渲染终端二维码：pip install qrcode）")
    return False
