"""上海大学 SSO 多系统登录验证 — 核心逻辑包。

子模块：
- config : 协议常量（端点、RSA 公钥、企微参数、目标系统注册信息）
- utils  : 工具函数（RSA 加密、base64url、脱敏、日志）
- client : ShuSSO HTTP 客户端
- flows  : 高层登录流程（密码 / 企微扫码、批量登录、汇总）
"""

from . import config, utils, client, flows

__all__ = ["config", "utils", "client", "flows"]
