"""命令行入口:python -m airchina <子命令>

    airchina award   CAN PEK 2026-10-21 [--return-date 2026-10-24] [--cabin X]
    airchina calendar CAN PEK 2026-10-21
    airchina account
    airchina session  [--from-flows /tmp/airchina.flows] [--save ~/.airchina/session.json]
    airchina keepalive [--interval 900] [--once] [--deep]
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from typing import Optional

from pydantic import BaseModel

from .client import AirChinaClient
from .errors import AirChinaError, CookieExpiredError
from .models import MileageSummary
from .session import DEFAULT_FLOWS, DEFAULT_SESSION_FILE


class Heartbeat(BaseModel):
    """keepalive 心跳文件(~/.airchina/keepalive.json)的内容。"""

    ok: bool
    ts: float
    err: str = ""


def cmd_award(args: argparse.Namespace, ac: AirChinaClient) -> int:
    r = ac.award_search(args.org, args.dst, args.date,
                        return_date=args.return_date, cabin=args.cabin,
                        adults=args.adults, children=args.children,
                        flag=args.flag, check_token=args.check_token)
    if not r:
        print(f"{args.org}->{args.dst} {args.date}:无可兑换航班"
              + (f"({r.message})" if r.message else ""))
        return 0
    print(f"{args.org}->{args.dst} {args.date} 奖励客票 去程 {len(r.flights)} 班"
          + (f" / 回程 {len(r.return_flights)} 班" if r.return_flights else ""))
    for f in r.flights:
        print("  " + str(f))
    for f in r.return_flights:
        print("  (回) " + str(f))
    return 0


def cmd_calendar(args: argparse.Namespace, ac: AirChinaClient) -> int:
    cal = ac.low_price_calendar(args.org, args.dst, args.date)
    print(f"{args.org}->{args.dst} 现金低价日历(自 {args.date} 前后):")
    for p in cal:
        print(f"  {p.date}  ¥{p.price}")
    return 0


def cmd_account(_args: argparse.Namespace, ac: AirChinaClient) -> int:
    resp = ac.mileage_summary()
    print(f"  code: {resp.code}")
    print(f"  msg: {resp.msg}")
    for k, v in sorted(resp.model_dump(exclude={"code", "msg"}).items()):
        if isinstance(v, (str, int, float, bool)) or v is None:
            print(f"  {k}: {v}")
        else:
            print(f"  {k}: <{type(v).__name__}>")
    return 0


def _log(msg: str) -> None:
    print(time.strftime("[%Y-%m-%d %H:%M:%S] ") + msg, flush=True)


def cmd_keepalive(args: argparse.Namespace, ac: AirChinaClient) -> int:
    """会话保活守护: 每 --interval 秒 ping 一次查询接口续期滑动会话。

    会话失效(CookieExpiredError)时写心跳标记并退出 1 —— 需要人工重登
    (短信验证码), 这是设计行为, 不要配置自动重启。
    """
    while True:
        try:
            resp = ac.keepalive_ping(deep=args.deep)
            if isinstance(resp, MileageSummary):
                fields = resp.model_dump(exclude={"code", "msg"})
                miles = next((v for v in fields.values()
                              if isinstance(v, (int, float)) and 1000 < v < 10**7), "?")
                log_msg = f"OK(账户) 里程≈{miles}"
            else:
                log_msg = f"OK(日历) 返回{len(resp)}天票价"
            _log(log_msg)
            _write_hb(args.heartbeat, Heartbeat(ok=True, ts=time.time()))
        except CookieExpiredError as e:
            _log(f"会话已失效, 需重登: {e}")
            _write_hb(args.heartbeat, Heartbeat(ok=False, ts=time.time(), err=str(e)))
            return 1
        except (AirChinaError, OSError, TimeoutError) as e:
            _log(f"瞬时错误: {e}")
            _write_hb(args.heartbeat, Heartbeat(ok=False, ts=time.time(), err=str(e)))
            if args.once:
                return 1
            _log(f"退避 {args.backoff}s")
            time.sleep(args.backoff)
            continue
        if args.once:
            return 0
        # 抖动 ±10%, 避免整点节律
        time.sleep(args.interval * (1 + random.uniform(-0.1, 0.1)))


def _write_hb(path: str, hb: Heartbeat) -> None:
    real = os.path.expanduser(path)
    directory = os.path.dirname(real)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(real, "w", encoding="utf-8") as f:
        json.dump(hb.model_dump(), f)


def cmd_session(args: argparse.Namespace, _ac: Optional[AirChinaClient] = None) -> int:
    ac = AirChinaClient.from_flows(args.from_flows, save_to=None)
    print("cookies:", ac.session.cookies[:80], "...")
    print("identity:", json.dumps(ac.session.identity.model_dump(), ensure_ascii=False))
    if args.save:
        ac.session.save(args.save)
        print("saved ->", args.save)
    return 0


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(prog="airchina",
                                description="国航 H5 API 客户端(奖励客票/日历/账户)")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("award", help="里程奖励客票查询")
    a.add_argument("org")
    a.add_argument("dst")
    a.add_argument("date")
    a.add_argument("--return-date", help="回程日期(往返查询)")
    a.add_argument("--cabin", default="X", help="X=经济舱奖励票(默认), 0=不限")
    a.add_argument("--adults", type=int, default=1)
    a.add_argument("--children", type=int, default=0)
    a.add_argument("--flag", default="D", help="D 国内(默认) / I 国际")
    a.add_argument("--check-token", default="", help="过滑块后的 checkToken(通常不需要)")
    a.set_defaults(fn=cmd_award)

    c = sub.add_parser("calendar", help="现金票低价日历")
    c.add_argument("org")
    c.add_argument("dst")
    c.add_argument("date")
    c.set_defaults(fn=cmd_calendar)

    m = sub.add_parser("account", help="里程/账户概要")
    m.set_defaults(fn=cmd_account)

    s = sub.add_parser("session", help="从抓包提取/保存会话")
    s.add_argument("--from-flows", default=DEFAULT_FLOWS)
    s.add_argument("--save", default=DEFAULT_SESSION_FILE)
    s.set_defaults(fn=cmd_session)

    k = sub.add_parser("keepalive", help="会话保活守护(默认每 15 分钟轻量 ping 续期)")
    k.add_argument("--interval", type=int, default=900,
                   help="ping 间隔秒(默认 900, 须小于 ~25 分钟闲置超时)")
    k.add_argument("--backoff", type=int, default=1800,
                   help="瞬时错误退避秒(默认 1800)")
    k.add_argument("--once", action="store_true", help="只 ping 一次即退出")
    k.add_argument("--deep", action="store_true",
                   help="用账户接口深检(能看里程, 但端点较敏感)")
    k.add_argument("--heartbeat", default="~/.airchina/keepalive.json",
                   help="心跳文件路径")
    k.set_defaults(fn=cmd_keepalive)

    args = p.parse_args(argv)
    try:
        if args.cmd == "session":
            return int(args.fn(args))
        try:
            ac = AirChinaClient.load()
        except FileNotFoundError:
            print(f"会话文件不存在,先运行: airchina session --from-flows {DEFAULT_FLOWS}",
                  file=sys.stderr)
            return 2
        return int(args.fn(args, ac))
    except AirChinaError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
