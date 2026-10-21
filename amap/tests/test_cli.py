# pylint: disable=protected-access,redefined-outer-name,unused-argument
"""CLI 测试:mock AmapClient,不触网。"""
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


class FakeClient:
    """替身客户端,记录 nav_route 参数。"""

    def __init__(self):
        self.kwargs = None

    def nav_route(self, slat, slon, sname, dlat, dlon, dname, mode="drive"):
        self.kwargs = (slat, slon, sname, dlat, dlon, dname, mode)
        return FakeResult()


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


def test_cli_route_mode(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr("amap.client.AmapClient", lambda: fake)
    rc = main(["route", "22.9", "113.9", "A", "23.1", "113.3", "B",
               "--mode", "walk"])
    assert rc == 0
    assert fake.kwargs is not None
    assert fake.kwargs[6] == "walk"


def test_cli_bad_args():
    """参数不足时 argparse SystemExit(非零)。"""
    with pytest.raises(SystemExit) as e:
        main(["route", "only-one-arg"])
    assert e.value.code != 0
