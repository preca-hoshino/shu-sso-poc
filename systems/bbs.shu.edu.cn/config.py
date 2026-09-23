"""上大 bbs（乐乎社区）— bbs.shu.edu.cn

本文件导出 SYSTEM 字典，字段说明见 ../README.md。
"""

SYSTEM = {
    "name": "上大bbs (乐乎社区)",
    "client_id": "vp8G2H42GGE86LP822LHF6Hs7f46483H",
    "redirect_uri": "https://bbs.shu.edu.cn/auth/oauth2_basic/callback",
    "scope": "",
    # state 由 BBS 自己生成：先访问入口向它索要，再拿这个 state 去 newsso 授权
    "needs_state_bootstrap": "https://bbs.shu.edu.cn/auth/oauth2_basic",
    "success_url_contains": "bbs.shu.edu.cn",
    "success_body_contains": "乐乎",
}
