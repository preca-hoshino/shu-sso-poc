"""超星（学习通）图书馆座位 — chaoxing.com

本文件只放数据，导出 SYSTEM 字典（字段说明见 ../README.md）。
换会话实现见同目录 client.py。
"""

SYSTEM = {
    "name": "超星（学习通）图书馆座位",
    "client_id": "mK5y895566T96v8Z52z5M3J85K8Miv38",
    "redirect_uri": ("https://zhstsg-jx.5read.com/oauthlogin/"
                     "loginByCodeSchoolid?schoolid=2434&type=xxt"),
    # 浏览器抓包逐字对齐：scope / state 为空串且**显式发送**。
    # 通用 client.authorize() 会省略空值，故本系统在 client.py 里自带授权请求。
    "scope": "",
    # 换会话是跨域 302 链（5read → passport2-api），落地 chaoxing 域；
    # 目标站是座位 SPA，URL / 正文关键词无可靠特征，只认座位首页内嵌 userLoginInfo
    "detection": "api",

    # ---- 以下仅 chaoxing 使用（client.py 的 redeem）----
    # 机构：上海大学图书馆 fid=35480，deptIdEnc=fidEnc=00bae7f2bdea485a
    "landing_url": ("https://office.chaoxing.com/front/third/apps/seat/index"
                    "?fidEnc=00bae7f2bdea485a"),
    "max_redirect_hops": 10,       # 换会话链逐跳上限（实测 5read→login6→落地共 3~4 跳）
}
