#!/usr/bin/env python3
"""国航里程奖励客票查询 —— airchina 库的薄封装(保留旧命令行接口)。

用法:
  python award_query.py <org> <dst> <date>          # 如: award_query.py CAN PEK 2026-10-21
  python award_query.py CAN PEK 2026-10-21 --return-date 2026-10-24

会话从 ~/.airchina/session.json 读取(airchina session --from-flows 更新)。
历史版本自带 HTTP/Cookie 逻辑,现已全部收敛进 ~/travel-skill/airchina 库。
"""
import sys

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# 路径注入后才能导入库(pylint 不认识运行时 sys.path)
from airchina import AirChinaClient, AirChinaError  # pylint: disable=wrong-import-position,import-error,no-name-in-module


def main() -> None:
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)
    org, dst, date = sys.argv[1], sys.argv[2], sys.argv[3]
    return_date = None
    if "--return-date" in sys.argv:
        return_date = sys.argv[sys.argv.index("--return-date") + 1]
    try:
        ac = AirChinaClient.load()
        r = ac.award_search(org, dst, date, return_date=return_date)
    except AirChinaError as e:
        print("错误:", e)
        sys.exit(1)
    if not r:
        print(f"{org}->{dst} {date}  无可兑换航班  {r.message}")
        return
    print(f"{org}->{dst} {date}  奖励客票  航班数: {len(r)}")
    for f in r.flights:
        print("  " + str(f))
    for f in r.return_flights:
        print("  (回) " + str(f))


if __name__ == "__main__":
    main()
