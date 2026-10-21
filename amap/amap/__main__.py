#!/usr/bin/env python3
"""命令行入口:python -m amap <子命令>

    amap route 22.9208 113.8903 松山湖 23.1066 113.3245 广州塔
    amap route ... --depart "2026-10-22T08:00"   # 未来用时(改模拟器时间)
    amap bus  22.9208 113.8903 松山湖 23.1066 113.3245 广州塔
    amap check
"""
from __future__ import annotations

import argparse
import sys
from typing import List, Optional


def cmd_route(args: argparse.Namespace) -> int:
    """路线查询:起终点坐标 + 名字(名字仅展示用)。"""
    from .client import AmapClient  # pylint: disable=import-outside-toplevel
    depart = None
    if args.depart:
        from datetime import datetime  # pylint: disable=import-outside-toplevel
        depart = datetime.fromisoformat(args.depart)
    r = AmapClient().nav_route(
        args.slat, args.slon, args.sname,
        args.dlat, args.dlon, args.dname, depart_at=depart)
    print(r.summary())
    best = r.best()
    if best:
        # 有名字的路段(高速/隧道/立交)从市政路段之后才开始,过滤空名
        named = [s.road for s in best.steps if s.road][:8]
        if named:
            roads = " → ".join(named)
            print(f"最快方案途经: {roads}{'…' if len(named) == 8 else ''}")
    return 0


def cmd_bus(args: argparse.Namespace) -> int:
    """公交查询:地铁/城际/公交聚合方案。"""
    from .client import AmapClient  # pylint: disable=import-outside-toplevel
    b = AmapClient().bus_route(
        args.slat, args.slon, args.sname,
        args.dlat, args.dlon, args.dname)
    print(b.summary())
    return 0


def cmd_check(_args: argparse.Namespace) -> int:
    """链路体检:adb/模拟器/高德/flows。"""
    from .client import AmapClient  # pylint: disable=import-outside-toplevel
    print(AmapClient().check())
    return 0


def _add_points(p: argparse.ArgumentParser) -> None:
    """起终点参数:坐标 + 名字(名字仅展示用)。"""
    p.add_argument("slat", type=float, help="起点纬度 GCJ-02")
    p.add_argument("slon", type=float, help="起点经度 GCJ-02")
    p.add_argument("sname", help="起点名(展示用)")
    p.add_argument("dlat", type=float, help="终点纬度 GCJ-02")
    p.add_argument("dlon", type=float, help="终点经度 GCJ-02")
    p.add_argument("dname", help="终点名(展示用)")


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="amap", description="高德导航 API 客户端")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("route", help="驾车路线查询(Deep Link 页面代理)")
    _add_points(r)
    r.add_argument("--depart", metavar="TIME",
                   help="未来用时:出发时刻(如 2026-10-22T08:00,ISO 格式)。"
                        "实现为改模拟器系统时间,偶发使用,勿高频")
    r.set_defaults(fn=cmd_route)
    b = sub.add_parser("bus", help="公交(地铁/城际/公交)路线查询")
    _add_points(b)
    b.set_defaults(fn=cmd_bus)
    c = sub.add_parser("check", help="链路体检")
    c.set_defaults(fn=cmd_check)
    args = p.parse_args(argv)
    try:
        return int(args.fn(args))
    except Exception as e:  # pylint: disable=broad-exception-caught  # CLI 兜底报错
        print(f"错误: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
