"""WebVPN 访问控制系统 — webvpn.shu.edu.cn

本文件只放数据，导出 SYSTEM 字典（字段说明见 ../README.md）。
换会话实现见同目录 client.py，特殊设计见 README.md。
"""

SYSTEM = {
    "name": "WebVPN 访问控制系统",
    "client_id": "nn7sbb22j2tKE100T024tEp42777p755",
    "redirect_uri": "https://webvpn.shu.edu.cn/callback/oauth2",
    "scope": "",
    # 参数对齐前端发起的 login_url：授权请求额外带 access_type=offline
    "authorize_extra": {"access_type": "offline"},
    # SPA：任意路径都返回同一份 index.html（正文自带 "WebVPN" 字样），
    # URL / 正文关键词判定必然假阳性 → 只认接口返回码
    "detection": "api",

    # ---- 以下仅 webvpn 使用（client.py 的 webvpn_* / redeem_webvpn）----
    "base": "https://webvpn.shu.edu.cn",
    "callback_url": "https://webvpn.shu.edu.cn/callback/oauth2",
    "landing_url": "https://webvpn.shu.edu.cn/site-nav/",
    "auth_list": "/api/access/authentication/list",   # ?type=0，取 authType==5
    "auth_start": "/api/access/auth/start",
    "auth_finish": "/api/access/auth/finish",
    "user_info": "/api/access/user/info",
    "auth_type_oauth2": 5,
    # 认证方式 ID 由 auth_list 下发；这是抓取失败时的回退值（2026-09-14 实测）
    "external_id_fallback": "YJrvSXWl",
}
