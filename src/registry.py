"""系统注册表：装载 `systems/<域名>/` 下的系统配置与换会话实现。

约定（详见 systems/README.md）：
- 子目录名 = 系统域名，键取域名首段（ds.shu.edu.cn → ds）；
- `config.py` 必需，导出 `SYSTEM` 字典（纯数据，不做导入副作用）；
- `client.py` 可选，导出 `def redeem(ctx) -> dict`（只有换会话不走「跟随 302」
  的系统才需要，如 webvpn / ds）。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
SYSTEMS_DIR = ROOT / "systems"


def _ensure_root_on_path() -> None:
    """让 systems 下的实现能用 `from src.xxx import ...`（它们不是包）。"""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


def _load_module(name: str, path: Path):
    """按文件路径加载模块 —— 目录名带点（ds.shu.edu.cn）无法当包路径导入。"""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def systems_dirs() -> dict[str, Path]:
    """{系统 key: 目录}，按目录名排序；`_` / `.` 开头的目录跳过。"""
    if not SYSTEMS_DIR.is_dir():
        return {}
    out: dict[str, Path] = {}
    for folder in sorted(SYSTEMS_DIR.iterdir()):
        if folder.is_dir() and not folder.name.startswith((".", "_")):
            out[folder.name.split(".")[0]] = folder
    return out


def load_systems() -> dict[str, dict]:
    """扫描并加载全部系统配置；无目录时返回空表。"""
    systems: dict[str, dict] = {}
    for key, folder in systems_dirs().items():
        cfg_path = folder / "config.py"
        if not cfg_path.is_file():
            continue
        cfg = getattr(_load_module(f"shu_sso_system_{key}", cfg_path), "SYSTEM", None)
        if isinstance(cfg, dict):
            systems[key] = cfg
    return systems


_module_cache: dict[str, Any] = {}


def impl_module(key: str):
    """取该系统的实现模块（`systems/<域名>/client.py`）；没有则返回 None。

    按需加载并缓存 —— 只有配了实现的系统才会引入额外依赖。
    """
    if key not in _module_cache:
        folder = systems_dirs().get(key)
        impl_path = folder / "client.py" if folder else None
        if impl_path and impl_path.is_file():
            _ensure_root_on_path()
            _module_cache[key] = _load_module(f"shu_sso_impl_{key}", impl_path)
        else:
            _module_cache[key] = None
    return _module_cache[key]


def redeem_impl(key: str) -> Callable[[Any], dict] | None:
    """取该系统的 `redeem(ctx)` 函数；没有实现则返回 None（走通用路径）。"""
    module = impl_module(key)
    return getattr(module, "redeem", None) if module else None
