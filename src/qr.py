"""终端二维码渲染。

企微二维码的内容就是 confirm_url（已用 pyzbar 解码官方 qrImg 的 PNG 逐字核对），
故本地用 `qrcode` 重新生成同样内容的二维码即可，扫码后打开的还是同一确认页。
未安装 `qrcode` 时 `render_qr_terminal()` 返回 False，由调用方回退到打印图片 URL。
"""

from __future__ import annotations

import shutil

from .utils import log

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
    qr = qrcode.QRCode(error_correction=levels[_QR_EC_LEVEL], box_size=1, border=_QR_BORDER)
    qr.add_data(text)
    qr.make(fit=True)
    return qr.get_matrix()


def qr_half_block_lines(matrix: list[list[int]]) -> list[str]:
    """默认样式：带 ANSI 颜色的半块字符。

    `▀`（U+2580）用前景色画字符格上半、背景色画下半，一个字符格承载上下两个模块，
    正好抵消终端字符约 2:1 的高宽比；前景/背景都显式给纯黑/纯白，
    因此深浅色主题下二维码都是「白底黑块」。
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
    """保底样式：黑模块两个整块字符、白模块两个空格（宽度翻倍，不依赖颜色）。"""
    return ["".join("██" if v else "  " for v in row) for row in matrix]


_STYLES = {"block": qr_half_block_lines, "ascii": qr_ascii_lines}
_STYLE_COLS = {"block": 1, "ascii": 2}      # 每个模块占用的列数


def render_qr_terminal(text: str, style: str = "block") -> bool:
    """把 text 渲染成可扫描的二维码打印到终端。

    style: `block`（默认，紧凑）或 `ascii`（无颜色，兼容性最好）。
    """
    matrix = qr_matrix(text)
    if matrix is None:
        return False

    style = style if style in _STYLES else "block"
    width = len(matrix[0]) * _STYLE_COLS[style]
    columns = shutil.get_terminal_size((80, 24)).columns
    if width > columns:
        log(f"  ! 终端每行只有 {columns} 列，放不下 {width} 列的二维码，"
            f"建议拉宽窗口；也可用下方的图片 URL 扫码")

    print("\n".join(_STYLES[style](matrix)), flush=True)
    return True
