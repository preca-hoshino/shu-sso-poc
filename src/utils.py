"""工具函数：RSA 加密、base64url 编码、脱敏、日志。

这些函数不依赖具体业务，仅供其它模块复用。
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding

from . import config


def rsa_encrypt_password(plain: str) -> str:
    """用 newsso 的 RSA 公钥加密密码（PKCS#1 v1.5），返回 base64 字符串。"""
    pub = serialization.load_pem_public_key(config.RSA_PUBLIC_KEY_PEM.encode())
    ciphertext = pub.encrypt(plain.encode("utf-8"), padding.PKCS1v15())
    return base64.b64encode(ciphertext).decode()


def device_id_for(username: str) -> str:
    """生成 WebVPN 用的 deviceId（32 位 hex）。

    WebVPN 前端的 deviceId 取自 FingerprintJS 的 visitorId —— 存在浏览器里，
    因此同一个浏览器永远是同一个值。POC 没有浏览器指纹可用，这里用
    「固定盐 + 账号名」的 md5 造一个**稳定**的伪指纹：同一账号每次运行得到
    同一个 deviceId，不会被服务端反复当成新设备。
    """
    return hashlib.md5(f"shu-sso-poc::{username.lower()}".encode("utf-8")).hexdigest()


# URL 查询串里的一次性授权码：?code=xxx / &auth_code=xxx
_CODE_IN_URL_RE = re.compile(
    r"([?&](?:code|auth_?code|authorization_?code)=)[^&\s\"'>]+", re.IGNORECASE)


def b64_params(oauth_params: dict) -> str:
    """
    把 OAuth 参数编码成 newsso 前端使用的格式。

    实测确认：浏览器用的是 **base64url（去掉 = 填充）**，而非标准 base64。
    例：`eyJyZXNwb25zZVR5cGUiOiJjb2RlIiwi...` （含 `_` 不含 `/`，无 padding）
    """
    raw = json.dumps(oauth_params, separators=(",", ":"), ensure_ascii=False)
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode().rstrip("=")


def redact(obj):
    """递归剔除敏感字段，避免密码等写入证据文件。

    除按键名剔除 password/code 外，还会处理「授权码藏在 URL 查询串里」的情况
    （如 `?code=xxx&state=yyy`），否则 location / authorize_url 这类字段会把
    一次性授权码原样写进证据文件。
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
    """把脱敏后的 payload 写入 captures/ 目录，返回文件路径。"""
    config.CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    path = config.CAPTURE_DIR / name
    path.write_text(json.dumps(redact(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def log(msg: str) -> None:
    """带刷新地打印（便于实时看到进度）。"""
    print(msg, flush=True)


def mask(s: str, keep: int = 4) -> str:
    """对字符串脱敏显示：保留首尾各 keep 个字符，中间用 ... 代替。"""
    if not s:
        return ""
    return s[:keep] + "..." + s[-keep:] if len(s) > keep * 2 else s


# --------------------------------------------------------------------------
# 终端二维码渲染（直接给手机扫）
# --------------------------------------------------------------------------
# 企微 qrConnect 的二维码内容就是 confirm_url —— 已用 pyzbar 解码官方
# qrImg?key=<key> 返回的 PNG 核对，内容与 confirm_url 逐字一致。
# 因此本地用 qrcode 重新生成同样内容的二维码，扫码后打开的还是同一个确认页，
# 不必再开浏览器点图片链接。
_QR_BORDER = 2          # 静默区（模块数），留白保证识别率
_QR_EC_LEVEL = "M"      # 纠错等级

_FG_BLACK = "\x1b[30m"
_FG_WHITE = "\x1b[37m"
_BG_BLACK = "\x1b[40m"
_BG_WHITE = "\x1b[47m"
_SGR_RESET = "\x1b[0m"


def qr_matrix(text: str) -> list[list[int]] | None:
    """生成二维码模块矩阵（含静默区，1 = 黑模块）。未装 qrcode 时返回 None。"""
    try:
        import qrcode
        from qrcode import constants
    except ImportError:
        return None

    levels = {"L": constants.ERROR_CORRECT_L, "M": constants.ERROR_CORRECT_M,
              "Q": constants.ERROR_CORRECT_Q, "H": constants.ERROR_CORRECT_H}
    qr = qrcode.QRCode(error_correction=levels[_QR_EC_LEVEL], box_size=1,
                       border=_QR_BORDER)
    qr.add_data(text)
    qr.make(fit=True)
    return qr.get_matrix()


def qr_half_block_lines(matrix: list[list[int]]) -> list[str]:
    """把模块矩阵压成带 ANSI 颜色的半块字符行。

    原理：`▀`（U+2580）用**前景色画字符格的上半、背景色画下半**，
    于是「一个字符格承载上下两个模块」——行列比例正好接近二维码的方块比例
    （终端字符高约为宽的 2 倍）。前景/背景都显式指定为纯黑/纯白，
    因此不论终端是深色还是浅色主题，二维码都是「白底黑块」，不影响识别。
    """
    height = len(matrix)
    width = len(matrix[0])
    lines: list[str] = []

    for y in range(0, height, 2):
        top_row = matrix[y]
        bottom_row = matrix[y + 1] if y + 1 < height else [0] * width
        parts: list[str] = []
        fg: bool | None = None      # 仅在颜色变化时才输出 ANSI 码，减少体积
        bg: bool | None = None
        for x in range(width):
            top, bottom = bool(top_row[x]), bool(bottom_row[x])
            if top != fg:
                fg = top
                parts.append(_FG_BLACK if top else _FG_WHITE)
            if bottom != bg:
                bg = bottom
                parts.append(_BG_BLACK if bottom else _BG_WHITE)
            parts.append("▀")
        parts.append(_SGR_RESET)
        lines.append("".join(parts))

    return lines


def qr_ascii_lines(matrix: list[list[int]]) -> list[str]:
    """无颜色的保底样式：黑模块用两个整块字符、白模块用两个空格。

    不依赖任何 ANSI 颜色，任何终端都能正确显示；代价是宽度翻倍
    （每个模块占 2 列，与终端字符约 2:1 的高宽比相抵消，比例依然正确）。
    """
    return ["".join("██" if v else "  " for v in row) for row in matrix]


_QR_STYLES = {"block": qr_half_block_lines, "ascii": qr_ascii_lines}
_QR_STYLE_COLS = {"block": 1, "ascii": 2}      # 每个模块占用的列数


def render_qr_terminal(text: str, style: str = "block") -> bool:
    """把 text 渲染成可扫描的二维码打印到终端。成功返回 True。

    style: `block`（默认，ANSI 半块，紧凑）或 `ascii`（无颜色，兼容性最好）。
    失败（未安装 qrcode）返回 False，由调用方回退到打印图片 URL。
    """
    matrix = qr_matrix(text)
    if matrix is None:
        return False

    style = style if style in _QR_STYLES else "block"
    width = len(matrix[0]) * _QR_STYLE_COLS[style]
    columns = shutil.get_terminal_size((80, 24)).columns
    if width > columns:
        log(f"  ! 终端每行只有 {columns} 列，放不下 {width} 列的二维码，"
            f"建议拉宽窗口；也可用下方的图片 URL 扫码")

    print("\n".join(_QR_STYLES[style](matrix)), flush=True)
    return True
