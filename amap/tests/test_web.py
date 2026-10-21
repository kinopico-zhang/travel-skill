# pylint: disable=redefined-outer-name,unused-argument,protected-access
"""Web 客户端测试:真实 H5 响应夹具驱动 + 替身 _get,不触网。"""
import json
import time
import urllib.request

import pytest

from amap.web import WebError, WebClient, parse_web_drive, parse_web_transit


# ---------- 解析(真实夹具) ----------

def test_parse_web_drive(web_drive):
    """速度最快 87km/1小时33分/过路费¥77,道路名完整(含市政路)。"""
    routes = parse_web_drive(web_drive)
    assert len(routes) == 1
    r = routes[0]
    assert r.index == 1
    assert abs(r.distance_km - 87) < 1
    assert r.duration_s == 5570
    assert r.toll_fen == 7700                 # ¥77 → 分
    roads = [s.road for s in r.steps if s.road]
    assert "G94珠三角环线高速" in " ".join(roads)
    assert roads[0] == "沁园路"                # 市政路也有名(App 侧没有)


def test_parse_web_transit(web_transit):
    """2 方案;方案1 ¥9/2小时56分,3 换乘段,城际线路名去重。"""
    plans = parse_web_transit(web_transit)
    assert len(plans) == 2
    p1 = plans[0]
    assert p1.price == 9.0
    assert p1.duration_s == 10560
    assert p1.walk_m == 1787
    assert [l.line for l in p1.legs] == [
        "343路(散裂中子源--松山湖北站微枢纽)",
        "城际(惠州北--番禺)",               # 服务端名字翻倍,应去重
        "地铁3号线(海傍--天河客运站)",
    ]
    assert p1.legs[2].from_station == "汉溪长隆"
    assert p1.legs[2].to_station == "广州塔"
    assert p1.legs[2].via_count == 5
    assert p1.legs[1].from_station == "松山湖北"


def test_parse_web_walk(web_walk):
    routes = parse_web_drive(web_walk)
    assert len(routes) == 1
    assert routes[0].distance_m == 2068
    assert routes[0].duration_s == 1654


# ---------- 客户端(替身 _get) ----------

def test_web_nav_route(web_drive, monkeypatch):
    w = WebClient(min_interval=0)
    monkeypatch.setattr(w, "_get", lambda path, params: web_drive)
    r = w.nav_route(22.9208, 113.8903, "松山湖", 23.1066, 113.3245, "广州塔")
    assert r.mode == "drive"
    best = r.best()
    assert best is not None
    assert best.distance_km > 80
    assert r.depart == "松山湖"


def test_web_bus_route_city_passthrough(web_transit, monkeypatch):
    """city/cityd 缺省时透传 None(服务端按坐标识别,跨城也准),
    显式传入时原样透传(识别不准时兜底)。"""
    w = WebClient(min_interval=0)
    seen = []

    def fake_get(path, params):
        seen.append((path, dict(params)))
        return web_transit

    monkeypatch.setattr(w, "_get", fake_get)
    b = w.bus_route(22.9208, 113.8903, "松山湖", 23.1066, 113.3245, "广州塔")
    assert len(b) == 2
    path, p = seen[-1]
    assert "transit" in path
    assert p["city"] is None and p["cityd"] is None
    assert p["origin"] == "113.8903,22.9208"
    assert p["destination"] == "113.3245,23.1066"
    # 显式传入兜底
    w.bus_route(22.9, 113.9, "A", 23.1, 113.3, "B", city="东莞市", cityd="广州市")
    _, p2 = seen[-1]
    assert p2["city"] == "东莞市" and p2["cityd"] == "广州市"


def test_web_error_status(monkeypatch):
    """服务端 status=0 时 _get 抛 WebError(带 info)。"""
    w = WebClient(min_interval=0)
    err = json.dumps({"status": "0", "info": "INVALID_USER_KEY",
                      "infocode": "10001"}).encode()

    class Resp:
        """urlopen 替身的返回:读出错误 JSON。"""

        def read(self):
            return err

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: Resp())
    with pytest.raises(WebError, match="INVALID_USER_KEY"):
        w._get("/v3/direction/driving", {"origin": "113.9,22.9"})


def test_web_throttle():
    """min_interval 节流生效。"""
    w = WebClient(min_interval=0.2)
    t0 = time.time()
    w._throttle()
    w._throttle()
    assert time.time() - t0 >= 0.2


def test_web_get_request_shape(web_drive, monkeypatch):
    """请求要带 platform=JS 与 Referer(H5 代理的通行证)。"""
    w = WebClient()
    captured = {}

    class Resp:
        """urlopen 替身的返回:读出固定 JSON。"""

        def read(self):
            return json.dumps(web_drive).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        return Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    w.nav_route(22.9, 113.9, "A", 23.1, 113.3, "B", strategy=0)
    assert "platform=JS" in captured["url"]
    assert "key=ab403a9b356e63c917ff05b037cd3e7d" in captured["url"]
    assert "m.amap.com" in captured["headers"].get("Referer", "")


# ------------------------------------------------------------------ v4/etd
def test_parse_etd(web_etd):
    """v4/etd 解析:路线 + 每时刻 duration(分钟)/tolls(元)。"""
    from amap.web import parse_etd
    ft = 1792643200
    routes, etas = parse_etd(web_etd, ft, 1800, 3)
    assert len(etas) == 3
    # 时刻按请求推算:firsttime + i*interval
    assert etas[0].depart_at == ft
    assert etas[2].depart_at == ft + 2 * 1800
    assert all(e.duration_min > 0 for e in etas)
    assert any(e.toll_yuan > 0 for e in etas)
    assert routes and routes[0].distance_m > 80000   # 松山湖→广州塔 87km


def test_web_nav_route_depart_at(web_etd, monkeypatch):
    """depart_at 走 v4/etd(ditu 代理),用时/过路费回填方案。"""
    import datetime as dt
    w = WebClient(min_interval=0)
    seen = []

    def fake_get(path, params, base="", key=""):
        seen.append((path, base))
        return web_etd

    monkeypatch.setattr(w, "_get", fake_get)
    future = dt.datetime.now() + dt.timedelta(hours=2)
    r = w.nav_route(22.9208, 113.8903, "松山湖", 23.1066, 113.3245, "广州塔",
                    depart_at=future)
    assert seen[0][0] == "/v4/etd/driving"
    assert "ditu.amap.com" in seen[0][1]
    best = r.best()
    assert best is not None
    assert best.duration_s > 0 and best.toll_fen > 0
    assert r.depart_at == int(future.timestamp())


def test_web_etd_table(web_etd, monkeypatch):
    import datetime as dt
    w = WebClient(min_interval=0)
    monkeypatch.setattr(w, "_get",
                        lambda path, params, base="", key="": web_etd)
    future = dt.datetime.now() + dt.timedelta(hours=2)
    etas = w.etd_table(22.9208, 113.8903, 23.1066, 113.3245, future,
                       interval_s=1800, count=3)
    assert len(etas) == 3
    assert etas[0].duration_min > 0


# ------------------------------------------------------------------ 策略
def test_resolve_strategy():
    """App 策略名 / v3 数字 → (v3 值, etd 值) 映射。"""
    from amap.web import resolve_strategy
    assert resolve_strategy("smart") == (32, 1)
    assert resolve_strategy("cheap") == (1, 2)        # 费用优先 → etd 免费档
    assert resolve_strategy("no_highway") == (16, 2)
    assert resolve_strategy(1) == (1, 2)              # v3 数字:费用最少 → 免费
    assert resolve_strategy(0) == (0, 1)
    with pytest.raises(WebError, match="未知策略"):
        resolve_strategy("teleport")


def test_web_nav_route_strategy_etd(web_etd, monkeypatch):
    """depart_at 组合时策略名映射到 v4/etd 的两档。"""
    import datetime as dt
    w = WebClient(min_interval=0)
    seen = []

    def fake_get(path, params, base="", key=""):
        seen.append(params["strategy"])
        return web_etd

    monkeypatch.setattr(w, "_get", fake_get)
    future = dt.datetime.now() + dt.timedelta(hours=2)
    w.nav_route(22.9, 113.9, "A", 23.1, 113.3, "B",
                depart_at=future, strategy="cheap")
    w.nav_route(22.9, 113.9, "A", 23.1, 113.3, "B", depart_at=future)
    assert seen == [2, 1]                     # cheap→免费档,默认 smart→避堵档


def test_web_etd_table_strategy(web_etd, monkeypatch):
    import datetime as dt
    w = WebClient(min_interval=0)
    seen = []

    def fake_get(path, params, base="", key=""):
        seen.append(params["strategy"])
        return web_etd

    monkeypatch.setattr(w, "_get", fake_get)
    future = dt.datetime.now() + dt.timedelta(hours=2)
    w.etd_table(22.9, 113.9, 23.1, 113.3, future, 1800, 3,
                strategy="no_highway")
    assert seen == [2]


def test_web_etd_rejects_past():
    """过去时刻直接拒,不发请求。"""
    import datetime as dt
    w = WebClient(min_interval=0)
    past = dt.datetime.now() - dt.timedelta(hours=1)
    with pytest.raises(Exception, match="未来"):
        w.etd_table(22.9, 113.9, 23.1, 113.3, past, 1800, 3)


def test_web_etd_count_bounds():
    import datetime as dt
    w = WebClient(min_interval=0)
    future = dt.datetime.now() + dt.timedelta(hours=2)
    with pytest.raises(Exception, match="1-48"):
        w.etd_table(22.9, 113.9, 23.1, 113.3, future, 1800, 49)
