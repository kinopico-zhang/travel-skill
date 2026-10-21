# pylint: disable=protected-access,redefined-outer-name,unused-argument
"""CLI 测试:mock AmapClient,不触网。"""
from datetime import datetime

import pytest

from amap.__main__ import main


class FakeResult:
    """替身查询结果。"""

    depart = "松山湖"
    arrive = "广州塔"

    def summary(self):
        return "松山湖→广州塔(drive) 共3条方案\n  方案1: 82公里 1小时34分 过路费¥25"

    def best(self):
        return None


class FakeBusResult:
    """替身公交结果。"""

    def summary(self):
        return "松山湖→广州塔(bus) 共7条方案\n  2小时50分 步行3.4km 费用少"

    def best(self):
        return None


class FakeClient:
    """替身客户端,记录 nav_route/bus_route 参数。"""

    def __init__(self):
        self.kwargs = None
        self.bus_kwargs = None

    def nav_route(self, slat, slon, sname, dlat, dlon, dname, depart_at=None):
        self.kwargs = (slat, slon, sname, dlat, dlon, dname, depart_at)
        return FakeResult()

    def bus_route(self, slat, slon, sname, dlat, dlon, dname):
        self.bus_kwargs = (slat, slon, sname, dlat, dlon, dname)
        return FakeBusResult()


def test_cli_route(monkeypatch, capsys):
    fake = FakeClient()
    monkeypatch.setattr("amap.client.AmapClient", lambda: fake)
    rc = main(["route", "22.9208", "113.8903", "松山湖",
               "23.1066", "113.3245", "广州塔"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "82公里" in out
    assert fake.kwargs is not None
    assert fake.kwargs[2] == "松山湖"
    assert fake.kwargs[6] is None               # 未指定出发时刻


def test_cli_route_depart(monkeypatch):
    """--depart 传 ISO 时刻,转成 datetime 交给 client。"""
    fake = FakeClient()
    monkeypatch.setattr("amap.client.AmapClient", lambda: fake)
    rc = main(["route", "22.9", "113.9", "A", "23.1", "113.3", "B",
               "--depart", "2026-10-22T08:00"])
    assert rc == 0
    assert fake.kwargs is not None
    assert fake.kwargs[6] == datetime(2026, 10, 22, 8, 0)


def test_cli_bus(monkeypatch, capsys):
    fake = FakeClient()
    monkeypatch.setattr("amap.client.AmapClient", lambda: fake)
    rc = main(["bus", "22.9208", "113.8903", "松山湖",
               "23.1066", "113.3245", "广州塔"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "费用少" in out
    assert fake.bus_kwargs is not None
    assert fake.bus_kwargs[2] == "松山湖"


def test_cli_bad_args():
    """参数不足时 argparse SystemExit(非零)。"""
    with pytest.raises(SystemExit) as e:
        main(["route", "only-one-arg"])
    assert e.value.code != 0
