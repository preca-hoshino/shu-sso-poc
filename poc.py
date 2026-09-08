#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
上海大学统一身份认证 (newsso.shu.edu.cn) 多系统登录验证 — POC 入口
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

结构：
    poc.py        CLI 入口（参数解析、模式选择、分发）
    src/config   协议常量
    src/utils    工具函数
    src/client   ShuSSO HTTP 客户端
    src/flows    高层登录流程

用法:
    python poc.py            # 交互式（推荐）
    python poc.py --tenant 上海大学
    python poc.py --login wecom_scan
"""

from __future__ import annotations

import argparse
import sys

from src import config
from src.flows import banner, choose_login_mode, password_flow, wecom_scan_flow


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
    args = parser.parse_args()

    banner()

    # ---------- 选择登录方式 ----------
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
