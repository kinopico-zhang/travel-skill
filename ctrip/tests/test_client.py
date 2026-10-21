"""CtripClient 接口测试:传输层全部用替身,不连 CDP、不触网。"""

# pylint: disable=unused-argument,import-outside-toplevel
import json
from typing import Any, Dict, List

import pytest

from ctrip import CtripClient, CtripError, RateLimitedError, \
    TrainSearchResult
from ctrip.client import (CALENDAR_API, FUZZY_API, LIST_API, TRAIN_API,
                          fetch_json_via)
from ctrip.models import City, DailyPrice, SearchResult


class FakeProxy:
    """CtripClient 的测试替身:记录 fetch_json 调用并弹回脚本化响应。"""

    def __init__(self, responses=None):
        self.responses: List[Any] = list(responses or [])
        self.calls: List[Dict[str, Any]] = []

    def fetch_json(self, path, payload):
        self.calls.append({"path": path, "payload": payload})
        assert self.responses, "测试脚本里多了一次意外请求"
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


# ------------------------------------------------------------------ city
def test_city_builtin(tmp_path):
    fake = FakeProxy()
    ct = CtripClient(proxy=fake, city_cache=str(tmp_path / "c.json"))
    c = ct.city("szx")                    # 大小写不敏感
    assert c == City(code="SZX", name="深圳", id="30")
    assert not fake.calls                 # 内置表不触网


def test_city_cache_new_format(tmp_path):
    cache = tmp_path / "c.json"
    cache.write_text(json.dumps({"LJG": {"name": "丽江", "id": "37"}}),
                     encoding="utf-8")
    fake = FakeProxy()
    ct = CtripClient(proxy=fake, city_cache=str(cache))
    assert ct.city("LJG") == City(code="LJG", name="丽江", id="37")
    assert not fake.calls


def test_city_cache_legacy_format(tmp_path):
    """旧版缓存存的是 [name, id],继续兼容。"""
    cache = tmp_path / "c.json"
    cache.write_text(json.dumps({"LJG": ["丽江", "37"]}), encoding="utf-8")
    ct = CtripClient(proxy=FakeProxy(), city_cache=str(cache))
    assert ct.city("LJG") == City(code="LJG", name="丽江", id="37")


def test_city_fuzzy_lookup(fuzzy_resp, tmp_path):
    cache = tmp_path / "c.json"
    proxy = FakeProxy([fuzzy_resp])
    ct = CtripClient(proxy=proxy, city_cache=str(cache))
    c = ct.city("LJG")
    assert c == City(code="LJG", name="丽江", id="37")
    # 走了 fuzzySearch,payload 带查询码
    assert proxy.calls[0]["path"] == FUZZY_API
    assert json.loads(proxy.calls[0]["payload"]["data"]) == {"key": "LJG"}
    # 结果落盘(新格式 {name,id}),下次不再触网
    saved = json.loads(cache.read_text(encoding="utf-8"))
    assert saved["LJG"] == {"name": "丽江", "id": "37"}
    assert ct.city("LJG").id == "37"
    assert len(proxy.calls) == 1


def test_city_unknown_raises(tmp_path):
    """机场码当城市码查(如 PEK)应该给可懂的错误。"""
    proxy = FakeProxy([{"data": json.dumps([])}])
    ct = CtripClient(proxy=proxy, city_cache=str(tmp_path / "c.json"))
    with pytest.raises(CtripError, match="城市代码 PEK 查不到"):
        ct.city("PEK")


# ------------------------------------------------------------------ search
def test_search(search_resp, tmp_path):
    fake = FakeProxy([search_resp])   # SZX/HAK 内置,只有一次列表请求
    ct = CtripClient(proxy=fake, city_cache=str(tmp_path / "c.json"))
    r = ct.search("SZX", "HAK", "2026-10-27")
    assert isinstance(r, SearchResult)
    assert len(r) == 17
    assert r.flights[0].flight_no == "SC9227"
    # 列表请求形状:城市码 + 数字 id
    call = fake.calls[-1]
    assert call["path"] == LIST_API
    item = call["payload"]["searchitem"][0]
    assert item["dccode"] == "SZX" and item["dcid"] == "30"
    assert item["accode"] == "HAK" and item["acid"] == "42"
    assert item["dtime"] == "2026-10-27"
    assert call["payload"]["seat"] == 0


# ------------------------------------------------------------------ calendar
def test_low_price_calendar(calendar_resp, tmp_path):
    fake = FakeProxy([calendar_resp])
    ct = CtripClient(proxy=fake, city_cache=str(tmp_path / "c.json"))
    cal = ct.low_price_calendar("SZX", "HAK")
    assert len(cal) == 377
    assert all(isinstance(p, DailyPrice) for p in cal)
    dates = [p.date for p in cal]
    assert dates == sorted(dates)               # 按日期升序
    assert cal[0].date == "2026-10-20"           # /Date(1792425600000+0800)/ = 当天零点
    assert cal[0].price == 1610                 # int,不是 "/Date(...)/" 字符串
    call = fake.calls[-1]
    assert call["path"] == CALENDAR_API
    assert call["payload"]["departNewCityCode"] == "SZX"
    assert call["payload"]["arriveNewCityCode"] == "HAK"


def test_low_price_calendar_bad_entries_dropped(tmp_path):
    """departDate 解析不出 /Date(ms)/ 的条目要丢弃,不能崩。"""
    resp = {"priceList": [
        {"departDate": "/Date(1792425600000+0800)/", "price": 100},
        {"departDate": "garbage", "price": 50},
        {"departDate": "/Date(1792512000000+0800)/", "price": 120},
    ]}
    proxy = FakeProxy([resp])
    ct = CtripClient(proxy=proxy, city_cache=str(tmp_path / "c.json"))
    cal = ct.low_price_calendar("SZX", "HAK")
    assert [p.price for p in cal] == [100, 120]


# ------------------------------------------------------------------ fetch_json 传输层
class FakeEvalProxy:
    """fetch_json_via 的替身:eval 弹回脚本化结果,_connect 计数。"""

    def __init__(self, results):
        self.results = list(results)
        self.js_seen = []
        self.connects = 0

    def eval(self, expr, await_promise=True):
        self.js_seen.append(expr)
        assert self.results
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def reconnect(self):
        self.connects += 1


def test_fetch_json_ok():
    p = FakeEvalProxy([json.dumps({"data": "[]"})])
    out = fetch_json_via(p, FUZZY_API, {"x": 1})
    assert out == {"data": "[]"}
    # JS 里要带 GUID cookie 与 head 信封
    assert "GUID=" in p.js_seen[0]
    assert "credentials: 'include'" in p.js_seen[0]


def test_fetch_json_432_rate_limited():
    p = FakeEvalProxy([json.dumps({"__http": 432})])
    with pytest.raises(RateLimitedError, match="432"):
        fetch_json_via(p, LIST_API, {})


def test_fetch_json_other_http_error():
    p = FakeEvalProxy([json.dumps({"__http": 500})])
    with pytest.raises(CtripError, match="HTTP 500"):
        fetch_json_via(p, LIST_API, {})


def test_fetch_json_wrong_domain():
    p = FakeEvalProxy([json.dumps({"__err": "页面不在 ctrip 域: example.com"})])
    with pytest.raises(CtripError, match="不在 ctrip 域"):
        fetch_json_via(p, LIST_API, {})


def test_fetch_json_reconnects_once(monkeypatch):
    """eval 第一次抛连接错误要重连重试一次,第二次成功。"""
    monkeypatch.setattr("ctrip.client.time.sleep", lambda s: None)
    p = FakeEvalProxy([CtripError("conn reset"), json.dumps({"ok": 1})])
    out = fetch_json_via(p, LIST_API, {})
    assert out == {"ok": 1}
    assert len(p.js_seen) == 2
    assert p.connects == 1                    # 重连过一次


# ------------------------------------------------------------------ train
def test_train_search_request_shape(tmp_path, train_search_resp):
    fake = FakeProxy([train_search_resp, train_search_resp])
    ct = CtripClient(proxy=fake, city_cache=str(tmp_path / "c.json"))
    r = ct.train_search("上海", "北京", "2026-10-22")
    assert isinstance(r, TrainSearchResult) and len(r) == 54
    call = fake.calls[0]
    assert call["path"] == TRAIN_API
    assert call["payload"]["DepartStation"] == "上海"
    assert call["payload"]["ArriveStation"] == "北京"
    assert call["payload"]["DepartDate"] == "2026-10-22"
    assert call["payload"]["Student"] is False
    assert call["payload"]["ChannelName"] == "ctrip.h5"
    assert call["payload"]["c_sec"] is True
    # head 由 fetch_json_via 注入,payload 里不带
    assert "head" not in call["payload"]
    ct.train_search("上海", "北京", "2026-10-22", student=True)
    assert fake.calls[1]["payload"]["Student"] is True


def test_train_search_empty_route(tmp_path, train_empty_resp):
    """不存在的线路返回空结果而不是抛错。"""
    fake = FakeProxy([train_empty_resp])
    ct = CtripClient(proxy=fake, city_cache=str(tmp_path / "c.json"))
    r = ct.train_search("上海", "月球", "2026-10-22")
    assert not r and len(r) == 0
