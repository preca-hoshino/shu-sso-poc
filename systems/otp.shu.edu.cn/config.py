"""OTP 令牌 — otp.shu.edu.cn

本文件导出 SYSTEM 字典，字段说明见 ../README.md。
"""

SYSTEM = {
    "name": "OTP令牌",
    "client_id": "05Q1L8woQK5350aK1U5o5GKh411ar3h1",
    "redirect_uri": "https://otp.shu.edu.cn//Callback.aspx",
    "scope": "read write",
    # Callback.aspx 会校验存在 ASP.NET_SessionId 里的 state，必须先访问入口预热，
    # 否则回调报「State验证失败」
    "needs_state_bootstrap": "https://otp.shu.edu.cn/",
    # 回调页用 Refresh 头跳转（非 302），requests 不会自动跟随，需手动补一次
    "follow_up_url": "https://otp.shu.edu.cn/Default.aspx",
    "success_url_contains": "Default.aspx",
    "success_body_contains": "账户名",
}
