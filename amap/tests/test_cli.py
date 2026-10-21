# pylint: disable=protected-access,redefined-outer-name,unused-argument
"""CLI 测试:mock 客户端,不触网。"""
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
        return "松山湖→广州塔(bus) 共5条方案\n  2小时48分 步行3.4km 费用少"

    def best(self):
        return None


class FakeWebClient:
    """替身 Web 客户端,记录 nav_route/bus_route 参数。"""

    def __init__(self):
        self.kwargs = None
        self.bus_kwargs = None

    def nav_route(self, slat, slon, sname, dlat, dlon, dname,
                  strategy="smart", depart_at=None):
        self.kwargs = (slat, slon, sname, dlat, dlon, dname, strategy,
                       depart_at)
        return FakeResult()

    def bus_route(self, slat, slon, sname, dlat, dlon, dname,
                  city="", cityd=""):
        self.bus_kwargs = (slat, slon, sname, dlat, dlon, dname, city, cityd)
        return FakeBusResult()


class FakeAppClient:
    """替身模拟器客户端(--app / --depart 路径)。"""

    def __init__(self):
        self.kwargs = None

    def nav_route(self, slat, slon, sname, dlat, dlon, dname, depart_at=None):
        self.kwargs = (slat, slon, sname, dlat, dlon, dname, depart_at)
        return FakeResult()


def test_cli_route_defaults_to_web(monkeypatch, capsys):
    """默认 Web 客户端(纯 HTTP,无模拟器)。"""
    fake = FakeWebClient()
    monkeypatch.setattr("amap.web.WebClient", lambda: fake)
    rc = main(["route", "22.9208", "113.8903", "松山湖",
               "23.1066", "113.3245", "广州塔"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "82公里" in out
    assert fake.kwargs is not None
    assert fake.kwargs[2] == "松山湖"
    assert fake.kwargs[6] == "smart"              # 默认 高德AI推荐


def test_cli_route_strategy(monkeypatch):
    fake = FakeWebClient()
    monkeypatch.setattr("amap.web.WebClient", lambda: fake)
    rc = main(["route", "22.9", "113.9", "A", "23.1", "113.3", "B",
               "--strategy", "cheap"])
    assert rc == 0
    assert fake.kwargs is not None
    assert fake.kwargs[6] == "cheap"

    # 数字策略(v3 语义)也接受
    rc = main(["route", "22.9", "113.9", "A", "23.1", "113.3", "B",
               "--strategy", "16"])
    assert rc == 0
    assert fake.kwargs[6] == "16"


def test_cli_route_app(monkeypatch):
    """--app 显式走模拟器 Deep Link。"""
    fake = FakeAppClient()
    monkeypatch.setattr("amap.client.AmapClient", lambda: fake)
    rc = main(["route", "22.9", "113.9", "A", "23.1", "113.3", "B", "--app"])
    assert rc == 0
    assert fake.kwargs is not None
    assert fake.kwargs[6] is None


def test_cli_route_depart(monkeypatch):
    """--depart 传 ISO 时刻:默认走 Web v4/etd 未来预测(纯 HTTP)。"""
    fake = FakeWebClient()
    monkeypatch.setattr("amap.web.WebClient", lambda: fake)
    rc = main(["route", "22.9", "113.9", "A", "23.1", "113.3", "B",
               "--depart", "2026-10-22T08:00"])
    assert rc == 0
    assert fake.kwargs is not None
    assert fake.kwargs[7] == datetime(2026, 10, 22, 8, 0)


def test_cli_route_depart_app(monkeypatch):
    """--depart --app 组合:模拟器改时钟(后备链路)。"""
    fake = FakeAppClient()
    monkeypatch.setattr("amap.client.AmapClient", lambda: fake)
    rc = main(["route", "22.9", "113.9", "A", "23.1", "113.3", "B",
               "--depart", "2026-10-22T08:00", "--app"])
    assert rc == 0
    assert fake.kwargs is not None
    assert fake.kwargs[6] == datetime(2026, 10, 22, 8, 0)


def test_cli_bus(monkeypatch, capsys):
    fake = FakeWebClient()
    monkeypatch.setattr("amap.web.WebClient", lambda: fake)
    rc = main(["bus", "22.9208", "113.8903", "松山湖",
               "23.1066", "113.3245", "广州塔"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "费用少" in out
    assert fake.bus_kwargs is not None
    assert fake.bus_kwargs[2] == "松山湖"
    assert fake.bus_kwargs[6] == ""              # city 缺省,坐标识别


def test_cli_bad_args():
    """参数不足时 argparse SystemExit(非零)。"""
    with pytest.raises(SystemExit) as e:
        main(["route", "only-one-arg"])
    assert e.value.code != 0
