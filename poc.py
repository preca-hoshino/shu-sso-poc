#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上海大学统一身份认证（newsso.shu.edu.cn）多系统登录验证 — POC 入口。

用「一次登录」的同一套 SSO 会话，向多个业务系统分别换取授权并验证登录
（OAuth 2.0 授权码模式，非 OIDC）。流程说明见 README.md，
各业务系统的交换配置见 systems/<域名>/config.py。

安全：密码经 getpass 读取，不落盘/不打印；证据 JSON 自动剔除密码与授权码。

用法:
    python poc.py            # 交互式（推荐）
    python poc.py --tenant 上海大学
    python poc.py --login wecom_scan
"""

from __future__ import annotations

import argparse
import sys

from src import config
from src.entry_password import password_flow
from src.entry_wecom import wecom_scan_flow
from src.ui import banner, choose_login_mode


def main() -> int:
    parser = argparse.ArgumentParser(description="上海大学 SSO 多系统登录验证")
    parser.add_argument("--tenant", default=config.DEFAULT_TENANT,
                        help=f"院校（默认 {config.DEFAULT_TENANT}）")
    parser.add_argument("--login", choices=["password", "wecom_scan"],
                        help="登录方式（省略则交互选择）")
    parser.add_argument("--method", choices=["wecom", "sms"],
                        help="账号密码登录时的 2FA 方式（省略则交互选择）")
    parser.add_argument("--scan-timeout", type=int, default=180,
                        help="企微扫码等待秒数（默认 180）")
    parser.add_argument("--no-qr", action="store_true",
                        help="不在终端渲染二维码（默认渲染，可直接用手机扫）")
    parser.add_argument("--qr-style", choices=["block", "ascii"], default="block",
                        help="二维码样式：block=ANSI 半块（默认，紧凑）；"
                             "ascii=无颜色整块（终端不支持颜色时用）")
    args = parser.parse_args()

    banner()

    mode = choose_login_mode(args)
    if mode == "wecom_scan":
        return wecom_scan_flow(args)
    return password_flow(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已取消")
        sys.exit(130)
