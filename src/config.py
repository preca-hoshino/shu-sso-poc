"""newsso（newsso.shu.edu.cn）协议常量与系统注册表。

本模块只做常量定义，导入它不会联网（RSA 公钥的抓取在 `rsa_key`，首次使用时才发生）。
各业务系统的交换配置见 systems/<域名>/config.py，由 `registry` 装载成 `SYSTEMS`。
"""

from pathlib import Path

from .registry import load_systems

SSO_BASE = "https://newsso.shu.edu.cn"
DEFAULT_TENANT = "上海大学"

# 企微扫码参数（newsso 前端用官方 WwLogin SDK 渲染二维码，参数硬编码在 bundle 里）
WECOM = {
    "appid": "wxa8dea949443de641",                       # 上海大学企微应用 appid
    "agentid": "1000059",                                # 企微自建应用 agentid
    "redirect_uri": "https://newsso.shu.edu.cn/oauth/wecom/qrcode",
    "qrcode_base": "https://open.work.weixin.qq.com/wwopen/sso/qrConnect",
    "img_base": "https://open.work.weixin.qq.com/wwopen/sso/qrImg",
    "confirm_base": "https://open.work.weixin.qq.com/wwopen/sso/confirm2",
    # 扫码状态长轮询；也见 qrConnect 页面的 window.settings.longPollGetUrl
    "longpoll": "https://open.work.weixin.qq.com/wwopen/sso/l/qrConnect",
    # 企微客户端协议，用于在企微内直接打开确认页（官方 confirm2 页内联脚本即此法）
    "scheme_jump_base": "wxwork://sso/jump?url=",
}

# 运行产物（脱敏证据）保存目录
CAPTURE_DIR = Path(__file__).resolve().parent.parent / "captures"

# 业务系统注册表：来自 systems/<域名>/config.py，键 = 域名首段
SYSTEMS: dict[str, dict] = load_systems()
