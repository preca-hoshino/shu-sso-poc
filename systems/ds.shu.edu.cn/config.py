"""千学百科（DeepSeek）— ds.shu.edu.cn

本文件只放数据，导出 SYSTEM 字典（字段说明见 ../README.md）。
换会话实现见同目录 client.py。
"""

SYSTEM = {
    "name": "千学百科 (DeepSeek)",
    "client_id": "re0owG1g776ng2eix7x3o8sa20W6OdA2",
    "redirect_uri": "https://ds.shu.edu.cn/login",
    # 前端直接拼授权 URL，不带 scope 也不带 state（scope 为空即不发送）
    "scope": "",
    # SPA：URL / 正文判定无效，只看 getSsoUser 的 isSussess
    "detection": "api",

    # ---- 以下仅 ds 使用（client.py 的 redeem_ds）----
    "base": "https://ds.shu.edu.cn",
    "get_sso_user": "/dsssologin/getSsoUser",
    "landing_url": "https://ds.shu.edu.cn/",
}
