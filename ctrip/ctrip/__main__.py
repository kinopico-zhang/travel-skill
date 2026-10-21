#!/usr/bin/env python3
"""命令行入口:python -m ctrip <子命令>

    ctrip cookies          查看浏览器里携程 cookie 的过期时间(登录态体检)
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import List, Optional

from .models import CookieEntry


def cmd_cookies(_args: argparse.Namespace) -> int:
    """CDP Network.getCookies —— cticket 是 HttpOnly, 页面 JS 看不到, 只能走 CDP."""
    # 函数内导入:测试时可整体 monkeypatch ctrip.client.CDPProxy
    from .client import CDPProxy  # pylint: disable=import-outside-toplevel
    p = CDPProxy()
    try:
        r = p.call("Network.getCookies",
                   {"urls": ["https://m.ctrip.com/", "https://ctrip.com/"]})
    # 首次查询可能要求先开 Network 域,失败就补一次
    except Exception:  # pylint: disable=broad-exception-caught
        p.call("Network.enable", {})
        r = p.call("Network.getCookies", {"urls": ["https://m.ctrip.com/"]})
    now = time.time()
    cookies: List[CookieEntry] = sorted(
        (CookieEntry.model_validate(c) for c in r.get("cookies", [])),
        key=lambda c: c.expires if c.expires > 0 else 9e9)
    print(f"{'name':<20} {'过期(本地)':<17} 剩余")
    for c in cookies:
        if c.expires <= 0:
            exps, left = "-", "会话级"
        else:
            exps = time.strftime("%Y-%m-%d %H:%M", time.localtime(c.expires))
            left = f"{(c.expires - now) / 86400:.0f}天"
        print(f"{c.name:<20} {exps:<17} {left}")
    ticket = next((c for c in cookies if c.name == "cticket"), None)
    if ticket and ticket.expires > now:
        days = (ticket.expires - now) / 86400
        print(f"\n登录态(cticket)剩余 {days:.0f} 天;过期后用 ctrip/scripts/ctrip_login.py 重登一次即可")
    elif ticket:
        print("\ncticket 已过期, 需要重登(机票查询本身不依赖登录, 仅会员功能受影响)")
    else:
        print("\n未发现 cticket(未登录或浏览器 cookie 被清);机票查询不受影响")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="ctrip", description="携程 H5 API 客户端")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cookies", help="查看 cookie 过期时间(登录态体检)")
    c.set_defaults(fn=cmd_cookies)
    args = p.parse_args(argv)
    try:
        return int(args.fn(args))
    except Exception as e:  # pylint: disable=broad-exception-caught  # CLI 兜底报错
        print(f"错误: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
