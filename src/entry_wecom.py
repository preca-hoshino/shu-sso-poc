"""企业微信扫码入口：出二维码 → 长轮询等 auth_code → 换 SSO 会话 → 批量登录。"""

from __future__ import annotations

from .client import ShuSSO
from .runner import login_all_systems, save_evidence, session_params, total_systems
from .ui import print_summary, print_wecom_qr
from .utils import log, save_json

_SCAN_STATUS_TEXT = {
    "QRCODE_SCAN_NEVER": "等待扫码",
    "QRCODE_SCAN_ING": "已扫码，请在手机上确认",
    "QRCODE_SCAN_SUCC": "已确认，正在换取会话",
    "QRCODE_SCAN_ERR": "二维码已过期",
}


def wecom_scan_flow(args) -> int:
    """返回退出码：0 全部成功，5 部分失败，6~8 扫码阶段失败。"""
    client = ShuSSO(tenant=args.tenant)

    # state 就是 paramsBase64（newsso 前端 WwLogin({state: paramsBase64})）
    state = session_params()

    log("\n[企微扫码] 请求 qrConnect，生成本次会话二维码 ...")
    info = client.wecom_qrcode_info(state=state)
    if not info.get("key"):
        log(f"  ✗ 未能解析出 key（HTTP {info.get('http_status')}）")
        save_json("script-00-wecom-scan-failed.json",
                  {"response": info, "trace": client.trace})
        return 6

    line = "─" * 62
    print()
    print(line)
    if print_wecom_qr(info["confirm_url"], args):
        print(" 请用企业微信扫描下方二维码，并在手机上点「确认登录」")
    else:
        print(" 请用企业微信扫码并在手机上点「确认登录」（二维码见下方 ①）")
    print(line)
    print()
    print(" ① 二维码图片 URL（浏览器打开即可扫码）")
    print(f"    {info['qr_img_url']}")
    print()
    print(" ② 二维码内容 = 扫码后企微打开的确认页")
    print(f"    {info['confirm_url']}")
    print()
    print(" ③ 包装后的 URI 跳转（在企微内直接打开该确认页）")
    print(f"    {info['wxwork_scheme']}")
    print(line)
    print(f" 等待扫码确认（最多 {args.scan_timeout} 秒，Ctrl+C 可中断）...")

    wait = client.wecom_wait_scan(
        info["key"], state=state, timeout=args.scan_timeout,
        poll_log=lambda status, _code: log(f"     {_SCAN_STATUS_TEXT.get(status, status)}"))

    if not wait.get("ok"):
        log(f"  ✗ 未取得 auth_code（{wait.get('reason') or wait.get('status')}）")
        save_json("script-00-wecom-scan-failed.json",
                  {"wait": wait, "wecom_qrcode": info, "trace": client.trace})
        return 7

    log("  ✓ 已取得 auth_code，换取 SSO 会话 ...")
    red = client.wecom_redeem(wait["auth_code"], state)
    if not red["ok"]:
        log(f"  ✗ 换取会话失败（HTTP {red['http_status']}）")
        save_json("script-00-wecom-redeem-failed.json",
                  {"redeem": red, "trace": client.trace})
        return 8

    log("  ✓ SSO 会话已建立（Cookie: SHU_OAUTH2）")
    log(f"     → {red['location'][:90]}")

    # ---------- 用同一会话依次登录全部系统（扫码模式拿不到学号，username 留空）----------
    results = login_all_systems(client)
    ok = print_summary(results)

    path = save_evidence("script-wecom-scan.json", client, results,
                         tenant=args.tenant, mode="wecom_scan", state=state,
                         wecom_qrcode=info, wait=wait, redeem=red)
    log(f"\n证据已保存: {path}")
    return 0 if ok == total_systems() else 5
