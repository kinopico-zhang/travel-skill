"""CtripClient 接口测试:传输层全部用替身,不连 CDP、不触网。"""

# pylint: disable=unused-argument,import-outside-toplevel
import json
import urllib.error
import urllib.parse
from typing import Any, Dict, List

import pytest
import websocket

from ctrip import CtripClient, CtripError, RateLimitedError, \
    TrainSearchResult
from ctrip.client import (CALENDAR_API, FUZZY_API, INTL_LIST_API, LIST_API,
                          TRAIN_API, IntlNavProxy, fetch_json_via)
from ctrip.models import City, DailyPrice, IntlSearchResult, SearchResult


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
    assert cal[0].total == 1710                 # 含税总价(totalPrice)
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


# ------------------------------------------------------------------ HttpProxy
class FakeHTTPResponse:
    """urlopen 替身返回的响应对象。"""

    def __init__(self, body: bytes, status: int = 200, gzipped: bool = False):
        import gzip as gz
        self._body = gz.compress(body) if gzipped else body
        self.status = status
        self.headers = {"content-encoding": "gzip"} if gzipped else {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_http_proxy_injects_app_head_and_parses(monkeypatch):
    """HttpProxy:payload 补 App head、URL 带网关 query、gzip 解压。"""
    from ctrip.client import HttpProxy, GW_QUERY
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["body"] = json.loads(req.data.decode())
        seen["ua"] = req.headers.get("User-agent")
        return FakeHTTPResponse(json.dumps({"ok": 1}).encode(), gzipped=True)

    monkeypatch.setattr("ctrip.client.urllib.request.urlopen", fake_urlopen)
    out = HttpProxy().fetch_json(LIST_API, {"searchitem": []})
    assert out == {"ok": 1}
    assert seen["url"] == f"https://m.ctrip.com{LIST_API}{GW_QUERY}"
    assert seen["body"]["head"]["appid"] == "99999999"
    assert seen["body"]["head"]["auth"] == ""
    assert seen["body"]["searchitem"] == []
    assert "CtripAPP" in seen["ua"]


def test_http_proxy_432_raises_rate_limited(monkeypatch):
    """HTTP 432 → RateLimitedError。"""
    from ctrip.client import HttpProxy

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 432, "ratelimited",
                                     {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr("ctrip.client.urllib.request.urlopen", fake_urlopen)
    with pytest.raises(RateLimitedError):
        HttpProxy().fetch_json(LIST_API, {})


def test_http_proxy_other_http_error(monkeypatch):
    from ctrip.client import HttpProxy

    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 502, "badgw", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr("ctrip.client.urllib.request.urlopen", fake_urlopen)
    with pytest.raises(CtripError, match="502"):
        HttpProxy().fetch_json(LIST_API, {})


# ------------------------------------------------------------------ intl
class StubIntlNav:
    """search_intl 的 navigate 传输替身:记录调用并弹回脚本化响应。"""

    def __init__(self, resp):
        self.resp = resp
        self.calls: List[Dict[str, Any]] = []

    def fetch_json(self, path, payload):
        self.calls.append({"path": path, "payload": payload})
        return self.resp


def _prefill_cache(tmp_path, entries):
    """预置城市缓存,免 fuzzySearch 触网(国际城市码多不在内置表)。"""
    cache = tmp_path / "c.json"
    cache.write_text(json.dumps(entries, ensure_ascii=False),
                     encoding="utf-8")
    return str(cache)


def test_search_intl_request_shape(intl_list_resp, tmp_path):
    cache = _prefill_cache(tmp_path, {"DPS": {"name": "巴厘岛", "id": "723"}})
    fake = FakeProxy()                        # self.proxy 不应被碰到
    ct = CtripClient(proxy=fake, city_cache=cache)
    stub = StubIntlNav(intl_list_resp)
    r = ct.search_intl("SZX", "DPS", "2026-10-22", proxy=stub)
    assert isinstance(r, IntlSearchResult) and len(r) == 55
    assert not fake.calls
    call = stub.calls[0]
    assert call["path"] == INTL_LIST_API
    seg = call["payload"]["segs"][0]
    assert seg == {"dcode": "SZX", "acode": "DPS", "ddate": "2026-10-22"}
    assert call["payload"]["tripType"] == 1
    assert call["payload"]["grade"] == 4       # grade=4 传给 14780 是经济舱
    # IntlNavProxy 还需要中文名拼列表页 URL
    assert call["payload"]["__names"] == {"dc": "深圳", "ac": "巴厘岛"}


def test_search_intl_failure_raises(tmp_path):
    resp = {"ResponseStatus": {"Ack": "Failure", "Errors": [
        {"ErrorCode": "FlightSearchError", "Message": "no route"}]}}
    ct = CtripClient(city_cache=_prefill_cache(
        tmp_path, {"HKG": {"name": "香港", "id": "66"}}))
    with pytest.raises(CtripError, match="国际列表查询失败"):
        ct.search_intl("SZX", "HKG", "2026-10-22",
                       proxy=StubIntlNav(resp))


class FakeWS:
    """CDP ws 替身:按序弹事件,耗尽即超时(模拟没有更多事件)。"""

    def __init__(self, events):
        self.events = list(events)

    def recv(self):
        if self.events:
            return json.dumps(self.events.pop(0))
        raise websocket.WebSocketTimeoutException("no more events")


def _bare_nav():
    """IntlNavProxy 裸实例:跳过 CDPProxy.__init__(那会连 9222)。"""
    nav = IntlNavProxy.__new__(IntlNavProxy)
    nav.ws = None
    nav.ws_timeout = 30
    nav.nav_timeout = 5
    nav._n = 0          # pylint: disable=protected-access
    return nav


def test_intl_nav_builds_page_url(monkeypatch):
    """fetch_json:segs[0] + __names → interFirst 列表页 URL。"""
    nav = _bare_nav()
    monkeypatch.setattr(IntlNavProxy, "_wait_body",
                        lambda self, path: {"ResponseStatus": {"Ack": "Success"}})
    calls: List[Any] = []
    monkeypatch.setattr(IntlNavProxy, "call",
                        lambda self, m, p=None: calls.append((m, p)) or {})
    nav.fetch_json(INTL_LIST_API, {
        "segs": [{"dcode": "SZX", "acode": "DPS", "ddate": "2027-05-01"}],
        "__names": {"dc": "深圳", "ac": "巴厘岛"}})
    assert calls[0][0] == "Network.enable"
    assert calls[1][0] == "Page.navigate"
    url = calls[1][1]["url"]
    assert "dcode=SZX" in url and "acode=DPS" in url
    assert "ddate=2027-05-01" in url
    assert urllib.parse.quote("巴厘岛") in url


def test_intl_nav_wait_body_captures_response():
    nav = _bare_nav()
    payload = json.dumps({"ResponseStatus": {"Ack": "Success"}, "segs": []})
    nav.ws = FakeWS([
        {"id": 1, "result": {}},               # 旧 call 的响应,应被忽略
        {"method": "Network.responseReceived", "params": {
            "requestId": "7", "response": {
                "url": "https://m.ctrip.com/restapi/soa2/14780/listSearchForH5"}}},
        {"method": "Network.eventFired", "params": {"requestId": "99"}},
        {"method": "Network.loadingFinished", "params": {"requestId": "7"}},
    ])
    nav.call = lambda m, p=None: {"body": payload}
    data = nav._wait_body("listSearchForH5")   # pylint: disable=protected-access
    assert data["ResponseStatus"]["Ack"] == "Success"


def test_intl_nav_wait_body_base64():
    import base64
    nav = _bare_nav()
    raw = json.dumps({"segs": [{"x": 1}]}, ensure_ascii=False).encode()
    nav.ws = FakeWS([
        {"method": "Network.responseReceived", "params": {
            "requestId": "3", "response": {"url": "x/14780/listSearchForH5"}}},
        {"method": "Network.loadingFinished", "params": {"requestId": "3"}},
    ])
    nav.call = lambda m, p=None: {
        "body": base64.b64encode(raw).decode(), "base64Encoded": True}
    # pylint: disable-next=protected-access
    assert nav._wait_body("listSearchForH5") == {"segs": [{"x": 1}]}


def test_intl_nav_wait_body_timeout():
    nav = _bare_nav()
    nav.ws = FakeWS([])                        # 无任何事件
    with pytest.raises(CtripError, match="超时"):
        nav._wait_body("listSearchForH5")      # pylint: disable=protected-access
