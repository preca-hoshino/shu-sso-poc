"""协议常量配置：从 newsso 前端 bundle 中提取。

集中存放所有与上海大学（SHU）统一身份认证相关的常量，避免散落在各模块中。
"""

import re
import warnings
from pathlib import Path

import requests

# 按要求忽略证书校验，同时抑制 urllib3 的告警噪音
warnings.filterwarnings("ignore", message="Unverified HTTPS request")
try:
    from urllib3.exceptions import InsecureRequestWarning
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
except Exception:
    pass

SSO_BASE = "https://newsso.shu.edu.cn"

# --------------------------------------------------------------------------
# RSA 公钥自动获取（1024-bit）
# --------------------------------------------------------------------------
# 公钥最初来源：登录 chunk /p__oauth2__login__index.*.async.js 中的 Pe 常量，
# 经 `v.setPublicKey(Pe)` 传给 JSEncrypt 用于加密密码。
# 该 chunk 文件名带 hash（如 ac94fa6e），前端每次重新打包都会变化，
# 因此公钥会随部署更新，这里自动从线上抓取最新值。
#
# 抓取链路：
#   GET /oauth2/login/             -> 得到 JS 引用 /umi.*.js, /preload_helper.*.js
#   GET /preload_helper.*.js       -> 得到 chunk 映射，含 p__oauth2__login__index.<hash>.async.js
#   GET /p__oauth2__login__index.<hash>.async.js
#                                  -> 用正则提取 `-----BEGIN PUBLIC KEY----- ... -----END PUBLIC KEY-----`
# --------------------------------------------------------------------------

# 内置回退值（2026-09-08 实测抓取；当联网抓取失败时使用）
RSA_PUBLIC_KEY_PEM_FALLBACK = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDl/aCgRl9f/4ON9MewoVnV58OL
OU2ALBi2FKc5yIsfSpivKxe7A6FitJjHva3WpM7gvVOinMehp6if2UNIkbaN+plW
f5IwqEVxsNZpeixc4GsbY9dXEk3WtRjwGSyDLySzEESH/kpJVoxO7ijRYqU+2oSR
wTBNePOk1H+LRQokgQIDAQAB
-----END PUBLIC KEY-----"""

_CAPTURE_PEM_RE = re.compile(r"-----BEGIN PUBLIC KEY-----[\s\S]*?-----END PUBLIC KEY-----")
_JS_URL_RE = re.compile(r'["\']((?:/[A-Za-z0-9_\-./]+)+\.js)["\']')
_LOGIN_CHUNK_RE = re.compile(r'["\'](/?(?:p__oauth2__login__index)\.[0-9a-f]+\.async\.js)["\']')
# 加载清单脚本：preload_helper.*.js 或 umi.*.js（含 chunk 映射）
_MANIFEST_RE = re.compile(r'["\'](/(?:preload_helper|umi)\.[0-9a-f]+\.js)["\']')


def _fetch_text(url: str, session: requests.Session, timeout: int = 30) -> str:
    """GET 并返回文本，任何异常返回空串。"""
    try:
        r = session.get(url, timeout=timeout)
        if r.status_code < 400:
            return r.text or ""
    except Exception:
        pass
    return ""


def fetch_rsa_public_key_pem(timeout: int = 30) -> str | None:
    """从线上 newsso 前端 bundle 抓取最新的 RSA 公钥 PEM。

    返回：找到的 PEM 字符串；失败返回 None（调用方可回退到内置值）。
    """
    session = requests.Session()
    session.verify = False
    session.headers.update({
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": SSO_BASE + "/",
    })

    # 1) 登录入口页，找 JS 引用
    html = _fetch_text(f"{SSO_BASE}/oauth2/login/", session, timeout)
    if not html:
        return None

    # 2) 加载清单（preload_helper 或 umi 主 bundle）中含 chunk 映射。
    #    优先用页面里明确引用的清单脚本；找不到就回退到通用清单正则。
    manifest_urls = [m.group(1) for m in _MANIFEST_RE.finditer(html)]
    if not manifest_urls:
        # 从所有 JS 引用里挑 manifest 类（preload_helper / umi）
        manifest_urls = [u for u in (m.group(1) for m in _JS_URL_RE.finditer(html))
                         if "preload_helper" in u or "/umi" in u]

    chunk_name = None
    for base in manifest_urls:
        text = _fetch_text(SSO_BASE + base, session, timeout)
        m = _LOGIN_CHUNK_RE.search(text)
        if m:
            chunk_name = m.group(1)
            break

    if not chunk_name:
        return None

    # 3) 登录 chunk 内提取公钥（chunk_name 可能带或不带前导 /，统一拼接）
    chunk_url = chunk_name if chunk_name.startswith("/") else "/" + chunk_name
    chunk_text = _fetch_text(SSO_BASE + chunk_url, session, timeout)
    m = _CAPTURE_PEM_RE.search(chunk_text)
    return m.group(0) if m else None


def _normalize_pem(pem: str) -> str:
    """把 chunk 里内嵌的带空格/换行的 PEM 规范化为标准 PEM。"""
    # 去掉 BEGIN/END 行以外的所有空白，再重排成每 64 字符一行的标准 PEM
    body = re.sub(r"[\s]+", "", pem.replace("-----BEGIN PUBLIC KEY-----", "")
                  .replace("-----END PUBLIC KEY-----", ""))
    lines = [body[i:i + 64] for i in range(0, len(body), 64)]
    return "-----BEGIN PUBLIC KEY-----\n" + "\n".join(lines) + "\n-----END PUBLIC KEY-----"


def _load_rsa_public_key_pem() -> str:
    """返回当前生效的 RSA 公钥 PEM。

    优先线上抓取（失败回退内置）；抓取到的值会缓存到项目目录的
    .rsa_public_key.pem，下次不再联网请求。
    """
    cache = Path(__file__).resolve().parent.parent / ".rsa_public_key.pem"

    # 有缓存且内容合法则直接用
    if cache.exists():
        try:
            cached = cache.read_text(encoding="utf-8").strip()
            if "-----BEGIN PUBLIC KEY-----" in cached:
                return cached
        except Exception:
            pass

    # 联网抓取
    pem = fetch_rsa_public_key_pem()
    if pem:
        normalized = _normalize_pem(pem)
        try:
            cache.write_text(normalized, encoding="utf-8")
        except Exception:
            pass
        return normalized

    # 回退内置
    return RSA_PUBLIC_KEY_PEM_FALLBACK


# 最终导出的公钥常量：模块导入时自动解析（联网抓取 -> 缓存 -> 内置回退）
RSA_PUBLIC_KEY_PEM = _load_rsa_public_key_pem()

DEFAULT_TENANT = "上海大学"

# 企业微信扫码登录参数（来自 newsso 前端 bundle，硬编码）
# 说明：newsso 前端用企微官方 WwLogin SDK 渲染二维码，参数是硬编码的。
WECOM = {
    "appid": "wxa8dea949443de641",                       # 上海大学企微应用 appid
    "agentid": "1000059",                                # 企微自建应用 agentid
    "redirect_uri": "https://newsso.shu.edu.cn/oauth/wecom/qrcode",  # 扫码回调
    "qrcode_base": "https://open.work.weixin.qq.com/wwopen/sso/qrConnect",
    "img_base": "https://open.work.weixin.qq.com/wwopen/sso/qrImg",
    "confirm_base": "https://open.work.weixin.qq.com/wwopen/sso/confirm2",
    # 扫码状态长轮询（Chrome DevTools 抓包确认；也见 qrConnect 页面的
    # window.settings.longPollGetUrl，值为 /wwopen/sso/l/qrConnect）
    "longpoll": "https://open.work.weixin.qq.com/wwopen/sso/l/qrConnect",
    # 企微客户端协议：在企微内拉起内置浏览器打开指定 URL。
    # 来源：企微官方 confirm2 页面内联脚本 launchWWByScheme()，原文为
    #   launchWWByScheme("wxwork://sso/jump?url=" + encodeURIComponent(confirm2_url))
    # 即：<scheme_jump_base><urlencode(目标URL)>
    "scheme_jump_base": "wxwork://sso/jump?url=",
}

# --------------------------------------------------------------------------
# WebVPN 访问控制系统（webvpn.shu.edu.cn）
# --------------------------------------------------------------------------
# 与其它系统不同，WebVPN 是纯前端 SPA，拿到 code 后**不是**直接 302 换会话，
# 而是由前端调两个私有接口完成握手（Chrome DevTools 抓包 + 读 bundle 还原）：
#
#   ① POST /api/access/auth/start
#        body {"externalId": <认证方式ID>,
#              "data": "{\"callbackUrl\":<回调>,\"state\":<base64({'externalId':...})>}"}
#        -> data.action.login_url 即 newsso 的 /oauth/authorize 地址
#   ② 浏览器跳到 login_url，newsso 302 回
#        https://webvpn.shu.edu.cn/callback/oauth2?code=...&state=...
#   ③ POST /api/access/auth/finish
#        body {"externalId": ..., "data": "{\"callbackUrl\":...,\"code\":...,\"deviceId\":...,\"state\":...}"}
#        -> {"code":0} 表示换会话成功（服务端拿 code 去 newsso 换 token）
#   ④ GET /api/access/user/info -> data.userId 非 0 即已登录
#
# 注意：`externalId` 不是随机值，而是「认证方式」在服务端的固定 ID，可由
# /api/access/authentication/list 查到（authType 5 = Oauth2Type）。
WEBVPN = {
    "base": "https://webvpn.shu.edu.cn",
    "callback_url": "https://webvpn.shu.edu.cn/callback/oauth2",
    "landing_url": "https://webvpn.shu.edu.cn/site-nav/",   # 登录后落地页
    "auth_list": "/api/access/authentication/list",          # ?type=0
    "auth_start": "/api/access/auth/start",
    "auth_finish": "/api/access/auth/finish",
    "user_info": "/api/access/user/info",
    "auth_type_oauth2": 5,                 # 枚举值：Oauth2Type
    "external_id_fallback": "YJrvSXWl",    # 2026-09-14 实测；抓取失败时的回退值
}

# 目标系统（client 注册信息已实测确认）
SYSTEMS = {
    "jwxt": {
        "name": "本科生教务系统",
        "client_id": "Km5t225E8KECKQ6ZDm5K2P6aS2459Cua",
        "redirect_uri": "https://jwxt.shu.edu.cn/sso/shulogin",
        "scope": "jw",
        # jwxt 的 /sso/shulogin 跳转 newsso 时**不带 state**，
        # 需自行生成随机 state（与 OTP/BBS 不同，无需预热）
        "generate_state": True,
        # 登录成功后的判定：URL 含该串 或 页面含该关键词
        "success_url_contains": "jwglxt",
        "success_body_contains": "教学管理",
    },
    "otp": {
        "name": "OTP令牌",
        "client_id": "05Q1L8woQK5350aK1U5o5GKh411ar3h1",
        "redirect_uri": "https://otp.shu.edu.cn//Callback.aspx",
        "scope": "read write",
        # OTP 的 Callback.aspx 会校验 state（存在 ASP.NET_SessionId 里），
        # 必须先访问它的入口拿到 state，否则回调报「State验证失败」
        "needs_state_bootstrap": "https://otp.shu.edu.cn/",
        # OTP 的 Callback.aspx 用 Refresh 头跳转（非 HTTP 302），需手动跟进
        "follow_up_url": "https://otp.shu.edu.cn/Default.aspx",
        "success_url_contains": "Default.aspx",
        "success_body_contains": "账户名",
    },
    "bbs": {
        "name": "上大bbs (乐乎社区)",
        "client_id": "vp8G2H42GGE86LP822LHF6Hs7f46483H",
        "redirect_uri": "https://bbs.shu.edu.cn/auth/oauth2_basic/callback",
        "scope": "",
        # BBS 特例：必须先向它自己要一个 state，再改走 newsso 授权
        "needs_state_bootstrap": "https://bbs.shu.edu.cn/auth/oauth2_basic",
        "success_url_contains": "bbs.shu.edu.cn",
        "success_body_contains": "乐乎",
    },
    "webvpn": {
        "name": "WebVPN 访问控制系统",
        "client_id": "nn7sbb22j2tKE100T024tEp42777p755",
        "redirect_uri": "https://webvpn.shu.edu.cn/callback/oauth2",
        "scope": "",
        # 授权请求的额外参数（对齐前端发起的 login_url）
        "authorize_extra": {"access_type": "offline"},
        # state 不是随机值：state = base64({"externalId": <认证方式ID>})
        "state_kind": "webvpn",
        # 换取会话的方式：走 auth/start + auth/finish 两步私有握手
        "redeem_kind": "webvpn",
        # 该站是 SPA，任何路径都返回同一份 index.html（含 "WebVPN" 字样），
        # 因此 URL / 正文关键词判定全部无效，只能靠接口返回码判定成功。
    },
}

# 运行产物（脱敏证据）保存目录：项目根目录下的 captures/
CAPTURE_DIR = Path(__file__).resolve().parent.parent / "captures"
