# pylint: disable=protected-access,redefined-outer-name,unused-argument
"""parser 测试:真实 protobuf 响应驱动。"""
from amap.parser import parse_route_plan, parse_wire


def test_short_route(short_raw):
    """松山湖→广州塔:3 方案,首方案 82km / 1小时34分 / ¥25。"""
    routes = parse_wire(short_raw)
    assert len(routes) == 3
    r1 = routes[0]
    assert r1.index == 1
    assert abs(r1.distance_km - 82) < 2
    assert r1.duration_s == 5640          # 1小时34分
    assert r1.toll_fen == 2500            # ¥25
    assert r1.currency == "CNY"
    assert r1.duration_str == "1小时34分"
    assert r1.toll_yuan == 25.0


def test_short_route_free_alternative(short_raw):
    """方案2 是免费路线(¥0 过路费,时间更长)。"""
    routes = parse_wire(short_raw)
    r2 = routes[1]
    assert r2.toll_fen == 0
    assert r2.duration_s > routes[0].duration_s


def test_steps_have_road_names(short_raw):
    """路段能解出道路名。"""
    routes = parse_wire(short_raw)
    roads = [s.road for s in routes[0].steps if s.road]
    assert roads, "首方案应至少有一条道路名"
    assert all(isinstance(x, str) and x for x in roads)


def test_long_route(long_raw):
    """广州→北京西站:2 方案,约 2117km / 22 小时。"""
    routes = parse_wire(long_raw)
    assert len(routes) == 2
    r1 = routes[0]
    assert 2100 < r1.distance_km < 2130
    assert 21 * 3600 < r1.duration_s < 23 * 3600
    assert r1.toll_fen > 100000            # ¥1066
    # 长途路段多,且有隧道类道路名
    assert len(r1.steps) > 30


def test_parse_route_plan_rejects_garbage():
    """乱字节不应崩(宽容解析,返回空/部分)。"""
    assert not parse_route_plan(b"\x08\x01")
    assert not parse_route_plan(b"")
