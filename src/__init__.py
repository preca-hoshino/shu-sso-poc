"""上海大学 SSO 多系统登录验证 —— 核心逻辑包。

模块分工：
    config / registry       协议常量与 systems/ 装载
    rsa_key / utils         公钥抓取、加密、参数编码、脱敏
    client                  newsso 通用 HTTP 客户端
    system_api              系统实现的接口（RedeemContext 等）
    runner                  批量登录与证据落盘
    entry_password / entry_wecom / ui / qr
                            两条入口 + 终端呈现

这里不做 eager import，避免与 systems/ 下的实现形成导入环。
"""

__all__ = [
    "config", "registry", "rsa_key", "utils", "client", "system_api",
    "runner", "entry_password", "entry_wecom", "ui", "qr",
]
