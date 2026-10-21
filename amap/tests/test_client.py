# pylint: disable=protected-access,redefined-outer-name,unused-argument
"""client 测试:mock transport + capture,不触网。"""
import time

import pytest

from amap.client import AmapClient


class FakeTransport:
    """替身:记录调用,返回固定时间戳。"""

    def __init__(self):
        self.calls = []
        self.launch_at = time.time()

    def launch_route(self, slat, slon, dlat, dlon, sname="", dname="",
                     mode="drive"):
        self.calls.append((slat, slon, sname, dlat, dlon, dname, mode))
        return self.launch_at


@pytest.fixture
def transport():
    return FakeTransport()


@pytest.fixture
def client(transport, short_raw, monkeypatch):
    """注入替身的 client,capture 层用夹具响应顶替。"""
    monkeypatch.setattr("amap.client.wait_for_response",
                        lambda *a, **k: short_raw)
    return AmapClient(transport=transport, min_interval=0)


def test_nav_route_returns_routes(client, transport):
    r = client.nav_route(22.9208, 113.8903, "松山湖",
                         23.1066, 113.3245, "广州塔")
    assert len(r) == 3
    assert r.depart == "松山湖"
    assert r.arrive == "广州塔"
    assert r.mode == "drive"
    assert r.best().index == 1
    # transport 收到的参数原样透传
    assert transport.calls[0][:6] == (22.9208, 113.8903, "松山湖",
                                      23.1066, 113.3245, "广州塔")


def test_nav_route_summary_format(client):
    r = client.nav_route(22.9208, 113.8903, "松山湖",
                         23.1066, 113.3245, "广州塔")
    s = r.summary()
    assert "松山湖→广州塔" in s
    assert "82公里" in s
    assert "过路费¥25" in s


def test_result_iteration(client):
    r = client.nav_route(22.9208, 113.8903, "松山湖",
                         23.1066, 113.3245, "广州塔")
    assert [x.index for x in r] == [1, 2, 3]
    assert bool(r) is True


def test_empty_response_raises(client, monkeypatch, long_raw):
    """残缺/空响应应报清晰错误,不是静默成功。"""
    monkeypatch.setattr("amap.client.wait_for_response",
                        lambda *a, **k: b"\x1f\x8b\x08\x00\x00\x00\x00\x00")
    with pytest.raises(Exception):
        client.nav_route(22.9, 113.9, "A", 23.1, 113.3, "B")


def test_throttle_sleeps_between_queries(client, transport):
    """min_interval 节流:第二次查询应等待。"""
    client.min_interval = 0.2
    t0 = time.time()
    client.nav_route(22.9, 113.9, "A", 23.1, 113.3, "B")
    client.nav_route(22.9, 113.9, "A", 23.1, 113.3, "B")
    assert time.time() - t0 >= 0.2
    assert len(transport.calls) == 2
