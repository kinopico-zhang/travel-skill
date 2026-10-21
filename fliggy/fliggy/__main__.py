#!/usr/bin/env python3
"""命令行入口:python -m fliggy <子命令>

    fliggy flights CAN PEK 2026-12-26          单程航班列表(免登录)
    fliggy flights CAN PEK 2026-12-26 --direct 只看直飞
"""
from __future__ import annotations

import argparse
import sys
from typing import List, Optional


def cmd_flights(args: argparse.Namespace) -> int:
    """单程航班列表查询(mtop H5 网关,免登录)。"""
    # 函数内导入:测试时可整体 monkeypatch fliggy.client.FliggyClient
    from .client import FliggyClient  # pylint: disable=import-outside-toplevel
    r = FliggyClient().search(args.dep, args.arr, args.date)
    print(r.summary(direct_only=args.direct))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="fliggy", description="飞猪 H5 API 客户端")
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("flights", help="单程航班列表(免登录,含中转)")
    f.add_argument("dep", help="出发三字码,如 CAN")
    f.add_argument("arr", help="到达三字码,如 PEK")
    f.add_argument("date", help="YYYY-MM-DD")
    f.add_argument("--direct", action="store_true", help="只看直飞")
    f.set_defaults(fn=cmd_flights)
    args = p.parse_args(argv)
    try:
        return int(args.fn(args))
    except Exception as e:  # pylint: disable=broad-exception-caught  # CLI 兜底报错
        print(f"错误: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
