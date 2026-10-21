"""FliggyClient / MtopTransport 测试:传输层全部用替身,不触网。"""

# pylint: disable=unused-argument,protected-access
import gzip
import hashlib
import http.cookiejar
import json
import time
from typing import Any, Dict, List, Optional, Tuple

import pytest

from fliggy import (API, APPKEY, FliggyClient, FliggyError,
                    RateLimitedError, SearchResult)
from fliggy.client import MtopTransport, REFERER, UA_IPHONE


class FakeTransport:
    """FliggyClient 的测试替身:记录 fetch 调用并弹回脚本化响应。"""

    def __init__(self, responses=None):
        self.responses: List[Any] = list(responses or [])
        self.calls: List[Dict[str, Any]] = []

    def fetch(self, api, version, data):
        self.calls.append({"api": api, "version": version, "data": data})
        assert self.responses, "测试脚本里多了一次意外请求"
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


# ------------------------------------------------------------------ client
def test_search_request_shape(listing_resp):
    fake = FakeTransport([listing_resp["data"]])
    fg = FliggyClient(transport=fake, min_interval=0)
    r = fg.search("can", "pek", "2026-11-18")
    assert isinstance(r, SearchResult) and len(r) == 31
    assert r.dep == "CAN" and r.arr == "PEK" and r.date == "2026-11-18"
    call = fake.calls[0]
    assert call["api"] == API and call["version"] == "2.0"
    seg = call["data"]["searchSegments"][0]
    assert seg == {"depCityCode": "CAN", "arrCityCode": "PEK",
                   "depDate": "2026-11-18"}
    assert call["data"]["tripType"] == 1


def test_search_maps_error():
    fake = FakeTransport([FliggyError("mtop x 失败")])
    fg = FliggyClient(transport=fake, min_interval=0)
    with pytest.raises(FliggyError, match="mtop x 失败"):
        fg.search("A", "B", "2026-11-18")


def test_throttle():
    """min_interval 节流生效。"""
    fake = FakeTransport([{}, {}])
    fg = FliggyClient(transport=fake, min_interval=0.2)
    t0 = time.time()
    fg.search("A", "B", "2026-11-18")
    fg.search("A", "C", "2026-11-18")
    assert time.time() - t0 >= 0.2


# ------------------------------------------------------------------ MtopTransport
class FakeResp:
    """opener.open 替身返回的响应对象。"""

    def __init__(self, body: Dict[str, Any], gzipped: bool = False):
        raw = json.dumps(body).encode()
        self._body = gzip.compress(raw) if gzipped else raw
        self.headers = ({"content-encoding": "gzip"} if gzipped else {})

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _cookie(name: str, value: str) -> http.cookiejar.Cookie:
    return http.cookiejar.Cookie(
        version=0, name=name, value=value, port=None, port_specified=False,
        domain=".taobao.com", domain_specified=True, domain_initial_dot=False,
        path="/", path_specified=True, secure=False, expires=None,
        discard=False, comment=None, comment_url=None, rest={}, rfc2109=False)


class FakeOpener:
    """opener 替身:记录 URL/headers,按脚本回响应并回填 cookie。"""

    def __init__(self, script: List[Tuple[Any, Optional[http.cookiejar.Cookie]]],
                 jar: http.cookiejar.CookieJar):
        self.script = list(script)
        self.jar = jar
        self.urls: List[str] = []
        self.headers: List[Dict[str, str]] = []

    def open(self, req, timeout=None):
        self.urls.append(req.full_url)
        self.headers.append(dict(req.header_items()))
        resp, cookie = self.script.pop(0)
        if cookie is not None:
            self.jar.set_cookie(cookie)
        if isinstance(resp, Exception):
            raise resp
        return FakeResp(resp)


def _wire(monkeypatch, script) -> "tuple[MtopTransport, FakeOpener]":
    """造一个 opener 被替身接管的 MtopTransport。"""
    tr = MtopTransport()
    fake = FakeOpener(script, tr._jar)
    monkeypatch.setattr(tr, "_opener", fake)
    return tr, fake


def test_token_empty_self_heals(monkeypatch):
    """首次空 token → FAIL_SYS_TOKEN_EMPTY + Set-Cookie → 重签成功。"""
    ok = {"ret": ["SUCCESS::调用成功"], "data": {"items": []}}
    empty = {"ret": ["FAIL_SYS_TOKEN_EMPTY::令牌为空"], "data": None}
    tr, opener = _wire(monkeypatch,
                       [(empty, _cookie("_m_h5_tk", "abc123_1761000000000")),
                        (ok, None)])
    assert tr.fetch(API, "2.0", {"q": 1}) == {"items": []}
    assert len(opener.urls) == 2                # 空 token 重试了一次
    # 第二次的 sign 用新 token 重算(三段式 md5 可复算验证)
    signs = [u.split("sign=")[1].split("&")[0] for u in opener.urls]
    assert signs[0] != signs[1]
    data_str = json.dumps({"q": 1}, separators=(",", ":"), ensure_ascii=False)
    t2 = opener.urls[1].split("t=")[1].split("&")[0]
    expect = hashlib.md5(
        f"abc123&{t2}&{APPKEY}&{data_str}".encode()).hexdigest()
    assert signs[1] == expect


def test_request_headers_and_query(monkeypatch):
    """请求要带 Referer/Safari UA,query 带签名四件套。"""
    ok = {"ret": ["SUCCESS::调用成功"], "data": {}}
    tr, opener = _wire(monkeypatch, [(ok, None)])
    tr.fetch(API, "2.0", {"q": 1})
    assert f"h5api.m.taobao.com/h5/{API}/2.0/" in opener.urls[0]
    h = {k.lower(): v for k, v in opener.headers[0].items()}
    assert h["referer"] == REFERER
    assert h["user-agent"] == UA_IPHONE
    for piece in (f"appKey={APPKEY}", "type=originaljson",
                  "dataType=json", "jsv=2.7.0"):
        assert piece in opener.urls[0]


def test_gzip_response(monkeypatch):
    ok = {"ret": ["SUCCESS::调用成功"], "data": {"z": 1}}
    tr = MtopTransport()
    resp = FakeResp(ok, gzipped=True)
    monkeypatch.setattr(tr, "_opener",
                        type("Gz", (), {"open": lambda s, r, timeout=None:
                                        resp})())
    assert tr.fetch(API, "2.0", {"q": 1}) == {"z": 1}


def test_rgv587_raises_rate_limited(monkeypatch):
    bad = {"ret": ["FAIL_SYS_USER_VALIDATE::RGV587_ERROR 触发风控"],
           "data": None}
    tr, _ = _wire(monkeypatch, [(bad, None)])
    with pytest.raises(RateLimitedError, match="RGV587"):
        tr.fetch(API, "2.0", {"q": 1})


def test_other_ret_raises(monkeypatch):
    bad = {"ret": ["FAIL_SYS_API_NOT_FOUNDED::接口不存在"], "data": None}
    tr, _ = _wire(monkeypatch, [(bad, None)])
    with pytest.raises(FliggyError, match="FAIL_SYS_API_NOT_FOUNDED"):
        tr.fetch(API, "2.0", {"q": 1})
