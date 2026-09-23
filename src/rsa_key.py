"""newsso 登录密码所用的 RSA 公钥：抓取 / 缓存 / 回退。

来源：登录 chunk `/p__oauth2__login__index.<hash>.async.js` 的 `Pe` 常量，
经 `v.setPublicKey(Pe)` 交给 JSEncrypt。chunk 名带 hash，前端重新打包就会变，
故首次使用时按「入口页 → 清单(preload_helper|umi) → 登录 chunk → 正则取 PEM」
从线上抓取，成功后缓存到项目根目录 `.rsa_public_key.pem`。
"""

from __future__ import annotations

import re
import warnings
from functools import lru_cache
from pathlib import Path

import requests

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

SSO_BASE = "https://newsso.shu.edu.cn"

# 内置回退值（联网抓取失败时使用）
FALLBACK_PEM = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDl/aCgRl9f/4ON9MewoVnV58OL
OU2ALBi2FKc5yIsfSpivKxe7A6FitJjHva3WpM7gvVOinMehp6if2UNIkbaN+plW
f5IwqEVxsNZpeixc4GsbY9dXEk3WtRjwGSyDLySzEESH/kpJVoxO7ijRYqU+2oSR
wTBNePOk1H+LRQokgQIDAQAB
-----END PUBLIC KEY-----"""

_CAPTURE_PEM_RE = re.compile(r"-----BEGIN PUBLIC KEY-----[\s\S]*?-----END PUBLIC KEY-----")
_JS_URL_RE = re.compile(r'["\']((?:/[A-Za-z0-9_\-./]+)+\.js)["\']')
_LOGIN_CHUNK_RE = re.compile(r'["\'](/?(?:p__oauth2__login__index)\.[0-9a-f]+\.async\.js)["\']')
# 含 chunk 映射的加载清单脚本
_MANIFEST_RE = re.compile(r'["\'](/(?:preload_helper|umi)\.[0-9a-f]+\.js)["\']')

CACHE_PATH = Path(__file__).resolve().parent.parent / ".rsa_public_key.pem"


def _fetch_text(url: str, session: requests.Session, timeout: int) -> str:
    """GET 并返回文本；任何异常返回空串。"""
    try:
        r = session.get(url, timeout=timeout)
        if r.status_code < 400:
            return r.text or ""
    except Exception:
        pass
    return ""


def fetch_rsa_public_key_pem(timeout: int = 30) -> str | None:
    """从线上 bundle 抓取最新 RSA 公钥 PEM；失败返回 None。"""
    session = requests.Session()
    session.verify = False
    session.headers.update({
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": SSO_BASE + "/",
    })

    html = _fetch_text(f"{SSO_BASE}/oauth2/login/", session, timeout)
    if not html:
        return None

    # 清单脚本里含 chunk 映射：先用页面明确引用的，找不到再退到通用正则
    manifest_urls = [m.group(1) for m in _MANIFEST_RE.finditer(html)]
    if not manifest_urls:
        manifest_urls = [u for u in (m.group(1) for m in _JS_URL_RE.finditer(html))
                         if "preload_helper" in u or "/umi" in u]

    chunk_name = None
    for base in manifest_urls:
        m = _LOGIN_CHUNK_RE.search(_fetch_text(SSO_BASE + base, session, timeout))
        if m:
            chunk_name = m.group(1)
            break
    if not chunk_name:
        return None

    # chunk_name 可能带或不带前导 /
    chunk_url = chunk_name if chunk_name.startswith("/") else "/" + chunk_name
    m = _CAPTURE_PEM_RE.search(_fetch_text(SSO_BASE + chunk_url, session, timeout))
    return m.group(0) if m else None


def _normalize_pem(pem: str) -> str:
    """把 chunk 里内嵌的（带空格/换行的）PEM 规范化为标准 PEM。"""
    body = re.sub(r"[\s]+", "", pem.replace("-----BEGIN PUBLIC KEY-----", "")
                  .replace("-----END PUBLIC KEY-----", ""))
    lines = [body[i:i + 64] for i in range(0, len(body), 64)]
    return "-----BEGIN PUBLIC KEY-----\n" + "\n".join(lines) + "\n-----END PUBLIC KEY-----"


@lru_cache(maxsize=1)
def public_key_pem() -> str:
    """取生效的公钥：本地缓存 → 线上抓取（成功后写缓存）→ 内置回退。

    只在首次调用时取（之后走 lru_cache），因此导入本模块不会联网。
    """
    if CACHE_PATH.exists():
        try:
            cached = CACHE_PATH.read_text(encoding="utf-8").strip()
            if "-----BEGIN PUBLIC KEY-----" in cached:
                return cached
        except Exception:
            pass

    pem = fetch_rsa_public_key_pem()
    if pem:
        normalized = _normalize_pem(pem)
        try:
            CACHE_PATH.write_text(normalized, encoding="utf-8")
        except Exception:
            pass
        return normalized

    return FALLBACK_PEM
