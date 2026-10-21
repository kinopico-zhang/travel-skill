"""AirChinaClient 接口测试:_post 用替身拦截,全部接口不触网。"""

# pylint: disable=protected-access,redefined-outer-name,unused-argument,import-outside-toplevel
import gzip
import json
import urllib.error
from typing import Any, Dict, List, Optional, cast

import pytest

from airchina import AirChinaClient, ApiError, CaptchaRequiredError, \
    CookieExpiredError, WafBlockedError
from airchina.models import AwardResult, DailyPrice, MileageSummary

EMPTY_MSG = "抱歉，暂时没有可兑换航班啦。"


class ScriptedClient(AirChinaClient):
    """测试替身:拦截 _post,弹回脚本化响应并记录发出的请求。"""

    def __init__(self, responses, session):
        super().__init__(session)
        self.responses: List[Any] = list(responses)
        self.requests: List[Dict[str, Any]] = []

    def _post(self, url: str, a: Any, p: Any, req: Dict[str, Any],
              m_extra: Optional[Dict[str, Any]] = None,
              referer: Optional[str] = None,
              check_token: str = "") -> Dict[str, Any]:
        self.requests.append({"url": url, "a": a, "p": p,
                              "req": dict(req), "m_extra": m_extra,
                              "referer": referer, "check_token": check_token})
        assert self.responses, "测试脚本里多了一次意外请求"
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return cast(Dict[str, Any], r)


# ------------------------------------------------------------------ award
def test_award_search_ow(award_ow, sample_session):
    ac = ScriptedClient([award_ow], sample_session)
    r = ac.award_search("CAN", "HAK", "2026-10-27")
    assert len(r) == 2
    assert r.flights[0].mileage_price == 5600
    req = ac.requests[0]["req"]
    assert req["queryTripType"] == "OW"
    assert req["orgCity"] == "CAN" and req["leaveDate"] == "2026-10-27"
    assert req["mainVipCard"] == "VC1"
    assert ac.requests[0]["m_extra"]["page"] == "awardTicket"


def test_award_search_rt_reverse_query(award_ow, sample_session, monkeypatch):
    """往返模式:响应只含去程,库自动反向补查回程。"""
    monkeypatch.setattr("airchina.client.time.sleep", lambda s: None)
    back = {"resp": {"code": "00000000", "msg": "成功",
                     "departureFlightInfos": award_ow["resp"]["departureFlightInfos"]}}
    ac = ScriptedClient([award_ow, back], sample_session)
    r = ac.award_search("CAN", "HAK", "2026-10-27", return_date="2026-10-29")
    assert len(r.flights) == 2
    assert len(r.return_flights) == 2
    first, second = ac.requests[0]["req"], ac.requests[1]["req"]
    assert first["queryTripType"] == "RT" and first["tabFlag"] == "1"
    assert second["queryTripType"] == "OW" and second["tabFlag"] == "0"
    assert second["orgCity"] == "HAK" and second["dstCity"] == "CAN"
    assert second["leaveDate"] == "2026-10-29"


def test_award_search_empty_is_not_error(sample_session):
    resp = {"resp": {"code": "00000000", "msg": EMPTY_MSG}}
    ac = ScriptedClient([resp], sample_session)
    r = ac.award_search("CAN", "KHN", "2026-11-15")
    assert not r
    assert r.message == EMPTY_MSG


def test_award_search_api_error(sample_session):
    resp = {"resp": {"code": "04030001", "msg": "验证码有误或已失效"}}
    ac = ScriptedClient([resp], sample_session)
    with pytest.raises(ApiError) as e:
        ac.award_search("CAN", "PEK", "2026-10-21")
    assert e.value.code == "04030001"


# ------------------------------------------------------------------ calendar
def test_low_price_calendar(calendar_resp, sample_session):
    ac = ScriptedClient([calendar_resp], sample_session)
    cal = ac.low_price_calendar("CAN", "PEK", "2026-11-07")
    assert all(isinstance(p, DailyPrice) for p in cal)
    assert all(isinstance(p.price, int) for p in cal)
    dates = [p.date for p in cal]
    assert dates == sorted(dates)
    by_date = {p.date: p.price for p in cal}
    assert by_date["2026-11-09"] == 1350
    # 请求形状
    req = ac.requests[0]["req"]
    assert req["org"] == "CAN" and req["dst"] == "PEK"
    assert ac.requests[0]["a"] == 0 and ac.requests[0]["p"] == 0


def test_low_price_calendar_error(sample_session):
    resp = {"resp": {"code": "01010012", "msg": "网络非常繁忙!"}}
    ac = ScriptedClient([resp], sample_session)
    with pytest.raises(ApiError, match="01010012"):
        ac.low_price_calendar("CAN", "PEK", "2026-11-07")


# ------------------------------------------------------------------ account
def test_mileage_summary_rejected(account_resp, sample_session):
    """真实行为:账户端点偶发 01010012,应转成 ApiError。"""
    ac = ScriptedClient([account_resp], sample_session)
    with pytest.raises(ApiError, match="01010012"):
        ac.mileage_summary()


def test_mileage_summary_success(sample_session):
    resp = {"resp": {"code": "00000000", "msg": "成功", "mileage": 12300}}
    ac = ScriptedClient([resp], sample_session)
    m = ac.mileage_summary()
    assert isinstance(m, MileageSummary)
    assert m.code == "00000000"
    assert m.model_dump()["mileage"] == 12300


# ------------------------------------------------------------------ keepalive
def test_keepalive_ping_light(sample_session, monkeypatch):
    """默认 ping:现金日历端点 CAN→PEK,返回 DailyPrice 列表。"""
    ac = ScriptedClient([], sample_session)
    seen: Dict[str, Any] = {}

    def fake_calendar(org, dst, date):
        seen.update(org=org, dst=dst)
        return [DailyPrice(date=date, price=100)]

    monkeypatch.setattr(ac, "low_price_calendar", fake_calendar)
    out = ac.keepalive_ping()
    assert seen == {"org": "CAN", "dst": "PEK"}
    assert isinstance(out, list)
    assert out == [DailyPrice(date=out[0].date, price=100)]


def test_keepalive_ping_light_date(sample_session, monkeypatch):
    import datetime
    ac = ScriptedClient([], sample_session)
    seen: Dict[str, Any] = {}
    monkeypatch.setattr(ac, "low_price_calendar",
                        lambda org, dst, date: seen.update(date=date) or [])
    ac.keepalive_ping()
    assert seen["date"] == (datetime.date.today()
                            + datetime.timedelta(days=7)).isoformat()


def test_keepalive_ping_deep(sample_session, monkeypatch):
    ac = ScriptedClient([], sample_session)
    monkeypatch.setattr(ac, "mileage_summary",
                        lambda: MileageSummary(code="00000000", mileage=12300))
    out = ac.keepalive_ping(deep=True)
    assert isinstance(out, MileageSummary)


# ------------------------------------------------------------------ _post 传输层
class FakeResponse:
    """urlopen 替身:支持 read/gzip 解压/上下文管理器/__exit__ 透传异常。"""

    def __init__(self, body, url="https://m.airchina.com.cn/g/invoke.json",
                 headers=None):
        self._body = body
        self._url = url
        self.headers = headers or {}

    def read(self):
        return self._body

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _patch_urlopen(monkeypatch, response):
    def fake_urlopen(request, timeout=None):
        return response
    monkeypatch.setattr("airchina.client.urllib.request.urlopen", fake_urlopen)


def _client(sample_session):
    return AirChinaClient(sample_session)


def test_post_ok(sample_session, monkeypatch):
    _patch_urlopen(monkeypatch, FakeResponse(b'{"resp": {"code": "00000000"}}'))
    data = _client(sample_session)._post("https://m.airchina.com.cn/x", 0, 0, {})
    assert data["resp"]["code"] == "00000000"


def test_post_gzip(sample_session, monkeypatch):
    body = gzip.compress(b'{"resp": {"code": "00000000"}}')
    _patch_urlopen(monkeypatch, FakeResponse(
        body, headers={"Content-Encoding": "gzip"}))
    data = _client(sample_session)._post("https://m.airchina.com.cn/x", 0, 0, {})
    assert data["resp"]["code"] == "00000000"


def test_post_html_is_cookie_expired(sample_session, monkeypatch):
    _patch_urlopen(monkeypatch, FakeResponse(b"<html>please login"))
    with pytest.raises(CookieExpiredError):
        _client(sample_session)._post("https://m.airchina.com.cn/x", 0, 0, {})


def test_post_waf_redirect(sample_session, monkeypatch):
    _patch_urlopen(monkeypatch, FakeResponse(
        b"whatever", url="https://m.airchina.com.cn/500.html"))
    with pytest.raises(WafBlockedError):
        _client(sample_session)._post("https://m.airchina.com.cn/x", 0, 0, {})


def test_post_risky_needs_captcha(sample_session, monkeypatch):
    _patch_urlopen(monkeypatch, FakeResponse(b'{"risky": true}'))
    with pytest.raises(CaptchaRequiredError):
        _client(sample_session)._post("https://m.airchina.com.cn/x", 0, 0, {})


def test_post_non_json(sample_session, monkeypatch):
    _patch_urlopen(monkeypatch, FakeResponse(b"not-json-at-all"))
    with pytest.raises(Exception, match="不是 JSON"):
        _client(sample_session)._post("https://m.airchina.com.cn/x", 0, 0, {})


def test_post_http_error(sample_session, monkeypatch):
    def fake_urlopen(request, timeout=None):
        import email.message
        raise urllib.error.HTTPError(
            "https://m.airchina.com.cn/x", 502, "Bad Gateway",
            email.message.Message(), None)
    monkeypatch.setattr("airchina.client.urllib.request.urlopen", fake_urlopen)
    with pytest.raises(Exception, match="HTTP 502"):
        _client(sample_session)._post("https://m.airchina.com.cn/x", 0, 0, {})


def test_post_sends_cookies_and_envelope(sample_session, monkeypatch):
    """m 信封要带身份、请求头要带整串 Cookie。"""
    sent = {}

    def fake_urlopen(request, timeout=None):
        sent["cookie"] = request.get_header("Cookie")
        sent["body"] = json.loads(request.data)
        return FakeResponse(b'{"resp": {}}')

    monkeypatch.setattr("airchina.client.urllib.request.urlopen", fake_urlopen)
    _client(sample_session)._post("https://m.airchina.com.cn/x", 12, 47, {"a": 1})
    assert sent["cookie"] == "SESSION=abc; JSESSIONID=def"
    m = sent["body"]["m"]
    assert m["userID"] == "U1" and m["infoID"] == "I1"
    assert json.loads(m["req"]) == {"a": 1}
    assert sent["body"]["a"] == "12" and sent["body"]["p"] == "47"


def test_award_result_parse_via_client_contract(award_ow, sample_session):
    """parse 后的完整对象可序列化往返(模型的 JSON 兼容性)。"""
    r = AwardResult.parse(award_ow)
    r2 = AwardResult.model_validate(json.loads(r.model_dump_json()))
    assert r2 == r
