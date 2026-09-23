"""本科生教务系统 — jwxt.shu.edu.cn

本文件导出 SYSTEM 字典，字段说明见 ../README.md。
"""

SYSTEM = {
    "name": "本科生教务系统",
    "client_id": "Km5t225E8KECKQ6ZDm5K2P6aS2459Cua",
    "redirect_uri": "https://jwxt.shu.edu.cn/sso/shulogin",
    "scope": "jw",
    # 授权请求本就不带 state，由 POC 自行生成随机 UUID
    "generate_state": True,
    # 成功判定：跳转 URL 含 jwglxt，或页面含「教学管理」
    "success_url_contains": "jwglxt",
    "success_body_contains": "教学管理",
}
