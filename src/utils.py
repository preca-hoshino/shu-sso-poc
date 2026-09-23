"""工具函数：RSA 加密、参数编码、脱敏、日志。"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding

from . import config, rsa_key


def rsa_encrypt_password(plain: str) -> str:
    """用 newsso 的 RSA 公钥加密密码（PKCS#1 v1.5），返回 base64 字符串。"""
    pub = serialization.load_pem_public_key(rsa_key.public_key_pem().encode())
    ciphertext = pub.encrypt(plain.encode("utf-8"), padding.PKCS1v15())
    return base64.b64encode(ciphertext).decode()


def b64_params(oauth_params: dict) -> str:
    """把 OAuth 参数编码成 newsso 前端使用的 **base64url（去掉 = 填充）**。

    例：`eyJyZXNwb25zZVR5cGUiOiJjb2RlIiwi...`（含 `_` 不含 `/`，无 padding）。
    注意与 WebVPN 的 state 不同 —— 那个是标准 base64（带填充）。
    """
    raw = json.dumps(oauth_params, separators=(",", ":"), ensure_ascii=False)
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode().rstrip("=")


# URL 查询串里的一次性授权码：?code=xxx / &auth_code=xxx
_CODE_IN_URL_RE = re.compile(
    r"([?&](?:code|auth_?code|authorization_?code)=)[^&\s\"'>]+", re.IGNORECASE)


def redact(obj):
    """递归剔除敏感字段，避免密码/授权码写入证据文件。

    URL 查询串里的 `?code=xxx` 也要处理，否则 location / authorize_url
    这类字段会把一次性授权码原样写进证据文件。
    """
    if isinstance(obj, dict):
        return {k: ("***REDACTED***" if k.lower() in {"password", "code"} else redact(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    if isinstance(obj, str):
        return _CODE_IN_URL_RE.sub(r"\1***REDACTED***", obj)
    return obj


def save_json(name: str, payload) -> Path:
    """把脱敏后的 payload 写入 captures/，返回文件路径。"""
    config.CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = config.CAPTURE_DIR / name
    path.write_text(json.dumps(redact(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def log(msg: str) -> None:
    """带 flush 的打印（便于实时看到进度）。"""
    print(msg, flush=True)


def mask(s: str, keep: int = 4) -> str:
    """脱敏显示：保留首尾各 keep 个字符，中间用 ... 代替。"""
    if not s:
        return ""
    return s[:keep] + "..." + s[-keep:] if len(s) > keep * 2 else s
