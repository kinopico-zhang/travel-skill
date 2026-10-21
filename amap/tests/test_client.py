# pylint: disable=protected-access,redefined-outer-name,unused-argument
"""client 测试:mock transport + capture,不触网。"""
import time
from datetime import datetime

import pytest

from amap.client import AmapClient


class FakeTransport:
    """替身:记录调用,返回固定时间戳。"""

    def __init__(self):
        self.calls = []
        self.clock_calls = []         # ("set"/"launch"/"restore", ts)
        self.launch_at = time.time()
        self.fail_launch = False

    def check(self):
        pass

    def set_clock(self, ts):
        self.clock_calls.append(("set", ts))

    def restore_clock(self, ts):
        self.clock_calls.append(("restore", ts))

    def launch_route(self, slat, slon, dlat, dlon, sname="", dname="",
                     mode="drive"):
        if self.fail_launch:
            raise RuntimeError("launch 失败")
        self.calls.append((slat, slon, sname, dlat, dlon, dname, mode))
        self.clock_calls.append(("launch", None))
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


# ---------- 未来用时(depart_at) ----------

def test_depart_at_sets_and_restores_clock(client, transport):
    """depart_at:改时间 → 查询 → 恢复,结果带上出发时刻。"""
    dep = datetime(2026, 10, 22, 8, 0)
    r = client.nav_route(22.9, 113.9, "A", 23.1, 113.3, "B", depart_at=dep)
    events = [c[0] for c in transport.clock_calls]
    assert events == ["set", "launch", "restore"]
    assert transport.clock_calls[0][1] == dep.timestamp()
    # 恢复用的是真实当前时刻(离现在很近,不是 dep)
    assert abs(transport.clock_calls[2][1] - time.time()) < 5
    assert r.depart_at == int(dep.timestamp())
    assert "@ 10-22 08:00出发" in r.summary()


def test_depart_at_none_leaves_clock_alone(client, transport):
    """不传 depart_at 不碰系统时间。"""
    client.nav_route(22.9, 113.9, "A", 23.1, 113.3, "B")
    assert [c[0] for c in transport.clock_calls] == ["launch"]


def test_depart_at_restores_even_on_failure(client, transport):
    """查询失败(如 Deep Link 没发出)也必须恢复时间(finally)。"""
    transport.fail_launch = True
    with pytest.raises(RuntimeError):
        client.nav_route(22.9, 113.9, "A", 23.1, 113.3, "B",
                         depart_at=datetime(2026, 10, 22, 8, 0))
    assert [c[0] for c in transport.clock_calls] == ["set", "restore"]


def test_nav_route_rejects_unsupported_mode(client):
    """步行/骑行的响应端点未解析,应明确报不支持。"""
    with pytest.raises(NotImplementedError):
        client.nav_route(22.9, 113.9, "A", 23.1, 113.3, "B", mode="walk")


# ---------- 公交 ----------

def test_bus_route_returns_plans(client, transport, bus_raw, monkeypatch):
    monkeypatch.setattr("amap.client.wait_for_response",
                        lambda *a, **k: bus_raw)
    b = client.bus_route(22.9208, 113.8903, "松山湖",
                         23.1066, 113.3245, "广州塔")
    assert len(b) == 7
    assert b.depart == "松山湖"
    assert b.best().duration_s == 7820            # 最快(打车)2小时10分
    # 公交方式(t=1)透传给了 transport
    assert transport.calls[0][6] == "bus"
    assert "客车直达" in b.summary()


def test_bus_route_uses_bus_endpoint(client, bus_raw, monkeypatch):
    """公交查询应向 capture 层要 new_integrate 端点(path 参数)。"""
    got = {}

    def fake_wait(flows, since_ts, timeout=90.0, path=""):
        got["path"] = path
        return bus_raw

    monkeypatch.setattr("amap.client.wait_for_response", fake_wait)
    client.bus_route(22.9, 113.9, "A", 23.1, 113.3, "B")
    assert got["path"] == "/ws/bus/plan/new_integrate"
