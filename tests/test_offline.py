"""离线测试：不打任何真实网络，用假会话（FakeSession）覆盖全链路。

运行方式（二选一）：
    python tests/test_offline.py       # 直接跑，只用标准库
    pytest tests/                      # 若装了 pytest

被测对象是**真实代码**（registry / runner / client / systems 下的实现），
只有 `ShuSSO.authorize()` 与 requests.Session 被替换成预设值。
"""

from __future__ import annotations

import base64
import json
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import config, registry  # noqa: E402
from src.client import ShuSSO  # noqa: E402
from src.runner import login_all_systems  # noqa: E402
from src.utils import b64_params, redact  # noqa: E402


# --------------------------------------------------------------------------
# 测试替身
# --------------------------------------------------------------------------
class FakeResponse:
    def __init__(self, url: str = "", status_code: int = 200, payload=None,
                 text: str | None = None, location: str = ""):
        self.url = url
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else ""
        self.headers = {"Location": location} if location else {}

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class Boom(Exception):
    pass


class FakeSession:
    """按 URL 子串路由的假会话；路由值可以是响应、异常实例或可调用对象。"""

    def __init__(self, routes: dict, cookies=None):
        self.routes = routes
        self.cookies = cookies or []
        self.headers: dict = {}

    def _do(self, url: str, **kw):
        for frag, resp in self.routes.items():
            if frag in url:
                if isinstance(resp, BaseException):
                    raise resp
                return resp(url, kw) if callable(resp) else resp
        raise Boom(f"FakeSession 未配置路由: {url}")

    def get(self, url, **kw):
        return self._do(url, **kw)

    def post(self, url, **kw):
        return self._do(url, **kw)


class Cookie:
    def __init__(self, name):
        self.name = name


class StubClient(ShuSSO):
    """真 ShuSSO + 假网络；authorize 单独预设（否则会真的打到 newsso）。"""

    def __init__(self, routes: dict, authorize_results: list[dict], cookies=None):
        super().__init__()
        self.sess = FakeSession(routes, cookies)
        self._results = list(authorize_results)
        self.authorize_calls: list[dict] = []

    def authorize(self, client_id, redirect_uri, scope="", state="", extra_params=None):
        self.authorize_calls.append({"client_id": client_id, "redirect_uri": redirect_uri,
                                    "scope": scope, "state": state, "extra": extra_params})
        auth = self._results.pop(0) if self._results else {
            "needs_login": False, "location": "", "code": None, "http_status": 302}
        self.record("authorize", auth)
        return auth


def ok_auth(location: str, code: str = "TESTCODE") -> dict:
    return {"needs_login": False, "location": location, "code": code, "http_status": 302}


@contextmanager
def patched_systems(mapping: dict):
    """临时替换 config.SYSTEMS，退出时还原。"""
    old = dict(config.SYSTEMS)
    config.SYSTEMS.clear()
    config.SYSTEMS.update(mapping)
    try:
        yield
    finally:
        config.SYSTEMS.clear()
        config.SYSTEMS.update(old)


# --------------------------------------------------------------------------
# 注册表与配置
# --------------------------------------------------------------------------
def test_registry_loads_all_systems():
    assert list(config.SYSTEMS) == ["bbs", "ds", "jwxt", "otp", "webvpn"], list(config.SYSTEMS)
    for key, cfg in config.SYSTEMS.items():
        for field in ("name", "client_id", "redirect_uri", "scope"):
            assert field in cfg, f"{key} 缺字段 {field}"


def test_only_spa_systems_have_impl():
    for key in ("bbs", "jwxt", "otp"):
        assert registry.redeem_impl(key) is None, f"{key} 不该有专属实现"
    for key in ("ds", "webvpn"):
        assert callable(registry.redeem_impl(key)), f"{key} 应提供 redeem(ctx)"


def test_system_dirs_mapping():
    dirs = registry.systems_dirs()
    assert dirs["ds"].name == "ds.shu.edu.cn"
    assert dirs["webvpn"].name == "webvpn.shu.edu.cn"


# --------------------------------------------------------------------------
# 两种 base64 形态不可混用
# --------------------------------------------------------------------------
def test_params_is_unpadded_base64url():
    s = b64_params({"responseType": "code", "clientId": "x", "state": ""})
    assert "=" not in s and "+" not in s and "/" not in s
    padded = s + "=" * (-len(s) % 4)
    assert json.loads(base64.urlsafe_b64decode(padded))["clientId"] == "x"


def test_webvpn_state_is_padded_standard_base64():
    state = registry.impl_module("webvpn")._state("YJrvSXWl")
    assert state.endswith("="), state                      # btoa 行为：带填充
    assert json.loads(base64.b64decode(state)) == {"externalId": "YJrvSXWl"}


def test_unproxy_url_only_rewrites_shu_hosts():
    unproxy = registry.impl_module("webvpn").unproxy_url
    proxy = "https-newsso-shu-edu-cn-443.webvpn.shu.edu.cn"
    assert unproxy(f"https://{proxy}/oauth/authorize?x=1") \
        == "https://newsso.shu.edu.cn/oauth/authorize?x=1"
    assert unproxy("https://evil.com/x") == "https://evil.com/x"
    assert unproxy("") == ""


# --------------------------------------------------------------------------
# 脱敏
# --------------------------------------------------------------------------
def test_redact_hides_password_and_code():
    out = redact({"password": "p", "code": "c",
                  "location": "https://x/cb?code=SECRET&state=s"})
    assert out["password"] == "***REDACTED***" and out["code"] == "***REDACTED***"
    assert "SECRET" not in out["location"] and "state=s" in out["location"]


# --------------------------------------------------------------------------
# 全链路：假网络跑真实代码
# --------------------------------------------------------------------------
GENERIC_OK = FakeResponse(url="https://g.shu.edu.cn/home", text="教学管理")
WEBVPN_ROUTES = {
    "/api/access/authentication/list": FakeResponse(payload={
        "code": 0, "data": {"list": [{"name": "OAuth2", "authType": 5,
                                      "externalId": "YJrvSXWl"}]}}),
    "/api/access/auth/start": FakeResponse(payload={
        "code": 0, "data": {"action": {"login_url": "https://x/oauth/authorize"}}}),
    "/api/access/auth/finish": FakeResponse(payload={"code": 0, "message": "ok"}),
    "/api/access/user/info": FakeResponse(payload={
        "code": 0, "data": {"userId": 1001, "username": "abc", "fullName": "张三"}}),
}
DS_ROUTES = {
    "/dsssologin/getSsoUser": FakeResponse(payload={
        "isSussess": True, "datas": json.dumps({"userid": "u-9", "username": "abc"})}),
}


def _systems_for_e2e(gen_keys=("gen_a", "gen_b")) -> dict:
    systems = {
        "webvpn": config.SYSTEMS["webvpn"],       # 真配置 → 真实现
        "ds": config.SYSTEMS["ds"],
    }
    for k in gen_keys:
        systems[k] = {
            "name": f"假系统 {k}", "client_id": f"cid-{k}",
            "redirect_uri": f"https://g.shu.edu.cn/{k}/cb", "scope": "",
            "generate_state": True,
            "success_url_contains": "g.shu.edu.cn", "success_body_contains": "教学管理",
        }
    return systems


def test_e2e_all_paths_succeed():
    systems = _systems_for_e2e()
    routes = {**WEBVPN_ROUTES, **DS_ROUTES, "g.shu.edu.cn": GENERIC_OK}
    stub = StubClient(routes, [ok_auth("https://webvpn.shu.edu.cn/callback/oauth2?..."),
                               ok_auth("https://ds.shu.edu.cn/login?code=TESTCODE"),
                               ok_auth("https://g.shu.edu.cn/gen_a/cb?code=TESTCODE"),
                               ok_auth("https://g.shu.edu.cn/gen_b/cb?code=TESTCODE")],
                      cookies=[Cookie("SHU_OAUTH2")])

    with patched_systems(systems):
        results = login_all_systems(stub, username="20260001")

    assert all(r["logged_in"] for r in results.values()), results
    assert results["webvpn"]["user_id"] == 1001
    assert results["webvpn"]["detection"] == "api"
    assert results["ds"]["user_id"] == "u-9"

    # webvpn：state 是私有值，且授权请求带 access_type=offline
    wv = next(c for c in stub.authorize_calls if c["client_id"] == "nn7sbb22j2tKE100T024tEp42777p755")
    assert wv["state"] == registry.impl_module("webvpn")._state("YJrvSXWl")
    assert wv["extra"] == {"access_type": "offline"}

    # ds：不带 state / scope
    ds = next(c for c in stub.authorize_calls if c["redirect_uri"].startswith("https://ds."))
    assert ds["state"] == "" and ds["scope"] == ""

    # 通用系统：随机 state（32 位 hex）
    gen = next(c for c in stub.authorize_calls if c["redirect_uri"].endswith("gen_a/cb"))
    assert len(gen["state"]) == 32 and all(ch in "0123456789abcdef" for ch in gen["state"])

    # deviceId 由账号派生 → 稳定
    dev = registry.impl_module("webvpn").device_id_for("20260001")
    assert len(dev) == 32 and dev == registry.impl_module("webvpn").device_id_for("20260001")


def test_e2e_early_failures_are_reported():
    """会话未复用 / 未取到 code 都要转成 reason 而不是异常。"""
    stub = StubClient(WEBVPN_ROUTES, [{"needs_login": True, "location": "/oauth2/login/",
                                       "code": None, "http_status": 302},
                                      {"needs_login": False, "location": "", "code": None,
                                       "http_status": 200}])
    with patched_systems(_systems_for_e2e(gen_keys=())):
        results = login_all_systems(stub)

    assert results["webvpn"]["reason"] == "session_not_reused"
    assert results["ds"]["reason"] == "no_code"
    assert results["webvpn"]["logged_in"] is False


def test_one_system_failure_does_not_stop_others():
    """单个系统抛异常 / 接口报错，其余系统照常。"""
    systems = _systems_for_e2e(gen_keys=("gen_a",))
    routes = {
        # 更具体的路由要排在前面（FakeSession 按声明顺序做子串匹配）
        "g.shu.edu.cn/gen_a/cb": Boom("Connection reset by peer"),
        **WEBVPN_ROUTES,
        "g.shu.edu.cn": GENERIC_OK,
        "/dsssologin/getSsoUser": FakeResponse(payload={
            "isSussess": False, "errMsg": "获取token失败：invalid_grant"}),
    }
    stub = StubClient(routes, [ok_auth("https://webvpn.shu.edu.cn/callback/oauth2?..."),
                               ok_auth("https://ds.shu.edu.cn/login?code=TESTCODE"),
                               ok_auth("https://g.shu.edu.cn/gen_a/cb?code=TESTCODE")])

    with patched_systems(systems):
        results = login_all_systems(stub)

    assert results["gen_a"]["reason"] == "exception"
    assert "Connection reset by peer" in results["gen_a"]["error"]
    assert results["ds"]["logged_in"] is False and "invalid_grant" in results["ds"]["api_error"]
    assert results["webvpn"]["logged_in"] is True          # 前一个挂了不影响后面的


def test_keyboard_interrupt_still_aborts_everything():
    systems = _systems_for_e2e(gen_keys=())
    routes = {**WEBVPN_ROUTES, "/api/access/auth/finish": KeyboardInterrupt()}
    stub = StubClient(routes, [ok_auth("https://webvpn.shu.edu.cn/callback/oauth2?code=X"),
                               ok_auth("https://ds.shu.edu.cn/login?code=X")])
    with patched_systems(systems):
        try:
            login_all_systems(stub)
        except KeyboardInterrupt:
            return
    raise AssertionError("KeyboardInterrupt 被吞掉了")


# --------------------------------------------------------------------------
# 跑测试（不依赖 pytest）
# --------------------------------------------------------------------------
def main() -> int:
    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ✓ {name}")
        except Exception as exc:                      # noqa: BLE001
            failed += 1
            print(f"  ✗ {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} 通过" + ("" if not failed else " ❌"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
