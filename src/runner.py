"""批量登录：用已建立的 SSO 会话依次向各业务系统换取授权。

系统实现不存在时走通用路径（授权取码 → 跟随 302 换会话）；
存在 `systems/<域名>/client.py` 的交给它（见 `registry.redeem_impl`）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from . import config, registry
from .client import ShuSSO
from .system_api import RedeemContext, fail
from .utils import b64_params, log, mask, save_json


def total_systems() -> int:
    return len(config.SYSTEMS)


def session_params(system: dict | None = None) -> str:
    """拼 `/oauth/userLogin` 的 `params`（base64url）。

    服务端只校验格式、不关心是哪个业务系统，故优先借 jwxt 的参数；
    jwxt 缺失时退到任一已注册系统 —— 避免单个系统的配置问题连登录都做不成。
    """
    s = system or config.SYSTEMS.get("jwxt") or next(iter(config.SYSTEMS.values()))
    return b64_params({
        "responseType": "code",
        "clientId": s["client_id"],
        "clientName": s["name"],
        "scope": s["scope"],
        "redirectUri": s["redirect_uri"],
        "state": "",
    })


def login_all_systems(client: ShuSSO, username: str = "") -> dict[str, dict]:
    """依次登录全部系统。

    **各系统彼此独立**：任一系统出错（网络异常、上游改版、接口报错等）只记为该
    系统失败，不中断其余系统；仅 Ctrl+C 会向上抛出。

    返回 {system_key: 换会话结果}。
    """
    log(f"\n[OAuth ①③④] 用同一 SSO 会话依次登录 {total_systems()} 个系统...\n")
    results: dict[str, dict] = {}

    for key, cfg in config.SYSTEMS.items():
        log(f"  ── {cfg['name']} ({key}) ──")
        ctx = RedeemContext(client=client, key=key, cfg=cfg, username=username)
        try:
            results[key] = login_one(ctx)
        except KeyboardInterrupt:
            # 用户主动中断要终止全局，故单独拦（它不属于 Exception 的子类分支）
            results[key] = {"logged_in": False, "reason": "interrupted", "final_url": ""}
            print()
            raise
        except Exception as exc:                      # noqa: BLE001 - 逐系统隔离
            reason = f"{type(exc).__name__}: {exc}"
            log(f"     ✗ 该系统中止（{reason}），继续下一个系统")
            results[key] = {"logged_in": False, "reason": "exception",
                            "error": reason, "final_url": ""}
        print()

    return results


def login_one(ctx: RedeemContext) -> dict:
    """登录单个业务系统：有专属实现就用它，否则走通用路径。

    各类失败都收敛为 {"logged_in": False, "reason": ...} 而不抛出，便于逐系统隔离。
    """
    impl = registry.redeem_impl(ctx.key)
    return impl(ctx) if impl else _login_generic(ctx)


def _login_generic(ctx: RedeemContext) -> dict:
    """通用路径：按需取 state → 授权取码 → 跟随 302（或 Refresh 头）换会话。"""
    client, cfg = ctx.client, ctx.cfg

    state = ""
    if cfg.get("needs_state_bootstrap"):
        state = client.bootstrap_state(cfg["needs_state_bootstrap"]) or ""
        log(f"     [OAuth ①] 预热 state: {mask(state, 8)}")
    elif cfg.get("generate_state"):
        # 授权请求本身不带 state，自行生成随机 UUID 作为防 CSRF 值
        state = uuid.uuid4().hex
        log(f"     [OAuth ①] 生成 state: {mask(state, 8)}")

    auth = client.authorize(cfg["client_id"], cfg["redirect_uri"], cfg.get("scope", ""),
                            state, extra_params=cfg.get("authorize_extra"))
    if auth["needs_login"]:
        log("     ✗ 需要重新登录（会话未复用）")
        return fail("session_not_reused", authorize=auth)
    if not auth["location"]:
        log("     ✗ 未取得重定向地址")
        return fail("no_redirect", authorize=auth)

    log(f"     [OAuth ③] HTTP {auth['http_status']} → 取到 code: {mask(auth['code'] or '', 8)}")
    red = client.redeem(ctx.key, cfg, auth["location"])
    if red["logged_in"]:
        log(f"     [OAuth ④] ✓ 登录成功 → {red['final_url'][:70]}")
    else:
        log(f"     [OAuth ④] ✗ 登录失败 → {red['final_url'][:70]}")
    return red


def save_evidence(name: str, client: ShuSSO, results: dict[str, dict], **fields) -> Path:
    """把本次运行的脱敏证据写到 captures/，返回文件路径。"""
    evidence = {
        "timestamp": datetime.now().isoformat(),
        "protocol": "OAuth 2.0 Authorization Code (RFC 6749), NOT OIDC",
        "sso_session_cookie": "SHU_OAUTH2",
        "summary": {k: {"logged_in": v.get("logged_in"), "final_url": v.get("final_url")}
                    for k, v in results.items()},
        "details": results,
        "trace": client.trace,
        **fields,
    }
    return save_json(name, evidence)
