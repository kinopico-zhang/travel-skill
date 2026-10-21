"""模型解析测试:真实列表响应夹具驱动。"""
import re

from fliggy.models import Fare, Flight, SearchResult, Segment


def _parse(listing_resp):
    return SearchResult.parse(listing_resp["data"], dep="A", arr="B",
                              date="2026-12-26")


def test_parse_counts(listing_resp):
    """31 个行程(10 直飞 + 21 中转);横幅卡片被跳过。"""
    r = _parse(listing_resp)
    assert len(r) == 31
    assert len(r.direct()) == 10
    transfers = [f for f in r if f.transfer_count]
    assert len(transfers) == 21
    assert all(len(f.segments) == 2 for f in transfers)


def test_direct_flight_fields(listing_resp):
    """直飞条目:航班号/时刻/机场/航司/报价(分→元)全解析。"""
    f = _parse(listing_resp).direct()[0]
    assert re.fullmatch(r"[A-Z]{1,2}\d{2,4}", f.flight_no)
    seg = f.segments[0]
    assert re.fullmatch(r"\d{2}:\d{2}", seg.dep_time)
    assert seg.dep_datetime.startswith("2026-12-26")
    assert seg.arr_next_day is True            # 红眼航班 +1 天
    assert seg.dep_terminal.startswith("T")
    assert seg.carrier.endswith("航空")
    assert seg.dep_city and seg.arr_city and seg.aircraft
    assert seg.duration_min == 100


def test_fare_fen_to_yuan(listing_resp):
    """价格单位是分:123000 分 → 1230 元含税。"""
    f = _parse(listing_resp).direct()[0]
    assert f.fare == Fare(price=1090.0, tax=140.0, total=1230.0,
                          original_price=1090.0)
    assert f.price == 1230.0
    assert f.cheapest is f.fare               # ctrip 同名属性对齐
    assert str(f.fare).startswith("¥1230")


def test_transfer_flight_fields(listing_resp):
    """中转条目:两段航班 + 中转次数/等待分钟。"""
    t = next(f for f in _parse(listing_resp) if f.transfer_count)
    assert t.transfer_count == 1
    assert t.transfer_time_min > 0
    nos = [s.flight_no for s in t.segments]
    assert len(nos) == 2 and all(nos)
    assert all(s.duration_min > 0 for s in t.segments)
    assert t.duration > sum(s.duration_min for s in t.segments)
    assert "+" in str(t) and "中转1次" in str(t)


def test_flight_str_direct(listing_resp):
    f = _parse(listing_resp).direct()[0]
    assert "+1" in str(f) and "¥" in str(f)


def test_sorted_and_cheapest(listing_resp):
    r = _parse(listing_resp)
    prices = [f.price for f in r.sorted_by_price()]
    assert prices == sorted(prices)
    assert len(r.cheapest_n(5)) == 5
    assert r.cheapest_n(5)[0].price == prices[0]


def test_summary(listing_resp):
    r = _parse(listing_resp)
    s = r.summary()
    assert "共31班" in s and "直飞10" in s and "2026-12-26" in s
    assert s.count("\n") >= 31
    d = r.summary(direct_only=True)
    assert "共10班(直飞)" in d


def test_iter_len_getitem(listing_resp):
    r = _parse(listing_resp)
    assert all(isinstance(f, Flight) for f in r)
    assert r[0] is r.flights[0]


def test_parse_skips_non_data_items():
    """运营位卡片(TITLE/低价监控等)与缺 flightInfos 的条目不进列表。"""
    data = {"items": [
        {"itemType": "TITLE", "data": [{"x": 1}]},
        {"itemType": "LOW_PRICE_MONITOR", "data": [{"x": 1}]},
        {"itemType": "FLIGHT_DIRECT", "data": [
            {"priceInfo": {"adultPrice": 1}},           # 无 flightInfos
            {"flightInfos": [{"duration": 60, "flightSegments": [
                {"marketingFlightNo": "XX123", "depTime": "2026-12-26 08:00:00",
                 "arrTime": "2026-12-26 09:00:00"}]}],
             "priceInfo": {"adultPrice": 10000, "adultTax": 500,
                           "adultTotalPrice": 10500}}],
        },
    ]}
    r = SearchResult.parse(data)
    assert len(r) == 1
    assert r[0].flight_no == "XX123"
    assert r[0].price == 105.0
    assert isinstance(r[0].segments[0], Segment)
