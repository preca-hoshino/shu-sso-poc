"""空间预约管理系统 — there.shu.edu.cn

本文件导出 SYSTEM 字典，字段说明见 ../README.md。
"""

SYSTEM = {
    "name": "空间预约管理系统",
    "client_id": "eDrd-M0i0WoSWRxk7ShDC1n-fbS7jRvi",
    "redirect_uri": "https://there.shu.edu.cn/login-oauth2",
    # 授权请求固定带 scope=1（数字型 scope，非空）
    "scope": "1",
    # 先访问它预置 SPHYS_SESSION 会话（对齐浏览器流程）。
    # 它 302 出的授权 URL 带 state，但实测服务端并不校验 state ——
    # 真实成功回调是 /login-oauth2?code=...（完全无 state），故此处作用只是预置会话
    "needs_state_bootstrap": "https://there.shu.edu.cn/login?from=web",
    # 成功：302 到 /web?authJump=<64 位 token>（SPA 再自行路由到 /web/home）；
    # 失败：200 + 空正文，停在 /login-oauth2
    "success_url_contains": "there.shu.edu.cn/web",
    "success_body_contains": "空间预约",
}
