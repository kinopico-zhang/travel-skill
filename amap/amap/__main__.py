#!/usr/bin/env python3
"""命令行入口:python -m amap <子命令>

默认走 Web 客户端(纯 HTTP,零模拟器依赖);--app 切到 Deep Link
页面代理(模拟器链路,后备)。

    amap route 22.9208 113.8903 松山湖 23.1066 113.3245 广州塔
    amap route ... --strategy cheap            # 路线偏好(App 同款策略名)
    amap route ... --depart "2026-10-22T08:00"   # 未来用时(v4/etd 预测)
    amap etd   22.9208 113.8903 23.1066 113.3245 "2026-10-22T08:00" \
        --interval 1800 --count 6                # 未来时刻表
    amap bus  22.9208 113.8903 松山湖 23.1066 113.3245 广州塔
    amap walk 22.9208 113.8903 松山湖 22.9250 113.8950 松山湖北
    amap geo 广州塔                                # 地名 → 坐标
    amap check
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import List, Optional


def cmd_route(args: argparse.Namespace) -> int:
    """路线查询:起终点坐标 + 名字(名字仅展示用)。"""
    depart = datetime.fromisoformat(args.depart) if args.depart else None
    if args.app:
        # Deep Link 模式:多方案一次返回(depart_at 走模拟器改时钟,后备)
        from .client import AmapClient  # pylint: disable=import-outside-toplevel
        r = AmapClient().nav_route(
            args.slat, args.slon, args.sname,
            args.dlat, args.dlon, args.dname, depart_at=depart)
    else:
        from .web import WebClient  # pylint: disable=import-outside-toplevel
        r = WebClient().nav_route(
            args.slat, args.slon, args.sname,
            args.dlat, args.dlon, args.dname,
            strategy=args.strategy, depart_at=depart)
    print(r.summary())
    best = r.best()
    if best:
        # 有名字的路段(高速/隧道/立交)从市政路段之后才开始,过滤空名;
        # v4/etd 的 steps 更碎(相邻多段同路名),相邻去重
        named: List[str] = []
        for s in best.steps:
            if s.road and (not named or named[-1] != s.road):
                named.append(s.road)
        named = named[:8]
        if named:
            roads = " → ".join(named)
            print(f"最快方案途经: {roads}{'…' if len(named) == 8 else ''}")
    return 0


def cmd_etd(args: argparse.Namespace) -> int:
    """未来用时时刻表(v4/etd):一次最多 48 个时间点的预估。"""
    from .web import WebClient  # pylint: disable=import-outside-toplevel
    etas = WebClient().etd_table(
        args.slat, args.slon, args.dlat, args.dlon,
        datetime.fromisoformat(args.first),
        interval_s=args.interval, count=args.count,
        strategy=args.strategy)
    if not etas:
        print("没有返回时刻预估")
        return 1
    print(f"{'出发时刻':<12}{'预估用时':<10}过路费")
    for e in etas:
        print(f"{datetime.fromtimestamp(e.depart_at):%m-%d %H:%M}"
              f"  {e.duration_min:>4}分钟"
              f"  ¥{e.toll_yuan:g}{'  ⚠限行' if e.restriction else ''}")
    return 0


def cmd_bus(args: argparse.Namespace) -> int:
    """公交查询:地铁/城际/公交方案(Web 客户端)。"""
    from .web import WebClient  # pylint: disable=import-outside-toplevel
    b = WebClient().bus_route(
        args.slat, args.slon, args.sname,
        args.dlat, args.dlon, args.dname,
        city=args.city, cityd=args.cityd)
    print(b.summary())
    return 0


def cmd_walk(args: argparse.Namespace) -> int:
    """步行查询(Web 客户端)。"""
    from .web import WebClient  # pylint: disable=import-outside-toplevel
    r = WebClient().walk_route(
        args.slat, args.slon, args.sname,
        args.dlat, args.dlon, args.dname)
    print(r.summary())
    return 0


def cmd_geo(args: argparse.Namespace) -> int:
    """地名 → 坐标(Web 客户端)。"""
    from .web import WebClient  # pylint: disable=import-outside-toplevel
    for g in WebClient().geocode(args.address, city=args.city):
        print(f"{g.lng:.6f},{g.lat:.6f}  {g.address}")
    return 0


def cmd_check(_args: argparse.Namespace) -> int:
    """链路体检:Web(必过)+ 模拟器 App 链路(可选)。"""
    from .web import WebClient  # pylint: disable=import-outside-toplevel
    w = WebClient()
    places = w.geocode("广州塔", city="广州")
    assert places, "geocode 竟然返回空"
    print(f"Web 客户端 OK(geocode: {places[0].address} "
          f"{places[0].lng:.4f},{places[0].lat:.4f})")
    from .client import AmapClient  # pylint: disable=import-outside-toplevel
    try:
        print(f"模拟器 App 链路 OK({AmapClient().check()})")
    except Exception as e:  # pylint: disable=broad-exception-caught  # 可选链路
        print(f"模拟器 App 链路不可用(未来用时需要它): {e}")
    return 0


def _add_points(p: argparse.ArgumentParser) -> None:
    """起终点参数:坐标 + 名字(名字仅展示用)。"""
    p.add_argument("slat", type=float, help="起点纬度 GCJ-02")
    p.add_argument("slon", type=float, help="起点经度 GCJ-02")
    p.add_argument("sname", help="起点名(展示用)")
    p.add_argument("dlat", type=float, help="终点纬度 GCJ-02")
    p.add_argument("dlon", type=float, help="终点经度 GCJ-02")
    p.add_argument("dname", help="终点名(展示用)")


def _add_strategy(p: argparse.ArgumentParser, help_tail: str) -> None:
    """--strategy:App「路线偏好」同款策略名(或 v3 数字)。"""
    from .web import APP_STRATEGIES, DRIVE_STRATEGIES  # pylint: disable=import-outside-toplevel
    names = sorted(APP_STRATEGIES)
    nums = [str(n) for n in sorted(DRIVE_STRATEGIES)]
    p.add_argument("--strategy", default="smart", metavar="STRATEGY",
                   choices=names + nums,
                   help=f"路线偏好: {'/'.join(names)}"
                        f"(默认 smart 高德AI推荐);或 v3 数字 {nums}。{help_tail}")


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="amap", description="高德导航 API 客户端")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("route", help="驾车路线(默认 Web 纯HTTP,--app 走模拟器)")
    _add_points(r)
    _add_strategy(r, "no_highway 返回 3 条备选方案")
    r.add_argument("--app", action="store_true",
                   help="强制走模拟器 Deep Link(多方案一次返回;"
                        "--depart 组合它时走模拟器改时钟,后备)")
    r.add_argument("--depart", metavar="TIME",
                   help="未来用时:出发时刻(ISO 如 2026-10-22T08:00)。"
                        "默认走 v4/etd 未来预测(纯 HTTP)")
    r.set_defaults(fn=cmd_route)
    e = sub.add_parser("etd", help="未来用时时刻表(v4/etd 一次多时刻)")
    e.add_argument("slat", type=float, help="起点纬度 GCJ-02")
    e.add_argument("slon", type=float, help="起点经度 GCJ-02")
    e.add_argument("dlat", type=float, help="终点纬度 GCJ-02")
    e.add_argument("dlon", type=float, help="终点经度 GCJ-02")
    e.add_argument("first", help="首时刻(ISO 如 2026-10-22T08:00)")
    e.add_argument("--interval", type=int, default=1800,
                   help="相邻时间点间隔秒数(默认 1800=半小时)")
    e.add_argument("--count", type=int, default=4,
                   help="时间点个数 1-48(默认 4)")
    _add_strategy(e, "v4/etd 仅避堵/免费两档,cheap 与 no_highway 走免费档")
    e.set_defaults(fn=cmd_etd)
    b = sub.add_parser("bus", help="公交(地铁/城际/公交)路线,Web 客户端")
    _add_points(b)
    b.add_argument("--city", default="",
                   help="起点城市(一般不用传,服务端按坐标识别)")
    b.add_argument("--cityd", default="",
                   help="终点城市(跨城兜底用,一般不用传)")
    b.set_defaults(fn=cmd_bus)
    w = sub.add_parser("walk", help="步行路线,Web 客户端")
    _add_points(w)
    w.set_defaults(fn=cmd_walk)
    g = sub.add_parser("geo", help="地名 → 坐标")
    g.add_argument("address", help="地名(如 广州塔)")
    g.add_argument("--city", default="", help="限定城市")
    g.set_defaults(fn=cmd_geo)
    c = sub.add_parser("check", help="链路体检(Web 必过,模拟器可选)")
    c.set_defaults(fn=cmd_check)
    args = p.parse_args(argv)
    try:
        return int(args.fn(args))
    except Exception as e:  # pylint: disable=broad-exception-caught  # CLI 兜底报错
        print(f"错误: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
