"""models 解析测试:全部对着真实抓包夹具断言。"""
from ctrip.models import (DailyPrice, Fare, Flight, SearchResult, Segment,
                           Train, TrainSearchResult, TrainSeat)


def test_parse_search(search_resp):
    r = SearchResult.parse(search_resp, org="SZX", dst="HAK",
                           date="2026-10-27")
    assert len(r) == 17
    assert r.total == 17
    assert r.org == "SZX" and r.dst == "HAK"


def test_flight_and_segment_fields(search_resp):
    r = SearchResult.parse(search_resp)
    f = r.flights[0]
    assert f.flight_no == "SC9227"
    seg = f.segments[0]
    assert isinstance(seg, Segment)
    assert seg.is_shared is True
    assert seg.actual_flight_no == "ZH9313"      # 实际承运深航
    assert seg.actual_carrier == "ZH"
    assert seg.dep_time == "21:00" and seg.arr_time == "22:20"
    assert seg.dep_datetime == "2026-10-27 21:00:00"
    assert seg.arr_next_day is False
    assert seg.dep_airport == "SZX" and seg.dep_terminal == "T3"
    assert seg.aircraft == "空客321(中)"
    assert f.duration == 80
    assert f.dep_time == "21:00" and f.arr_time == "22:20"


def test_fare_fields(search_resp):
    r = SearchResult.parse(search_resp)
    fares = r.flights[0].fares
    assert fares
    eco = fares[0]
    assert isinstance(eco, Fare)
    assert eco.price == 680
    assert eco.quantity == 9
    assert eco.grade == "经济舱"
    assert eco.cabin_code == "S"


def test_flight_price_helpers(search_resp):
    r = SearchResult.parse(search_resp)
    f = r.flights[0]
    assert f.cheapest is not None and f.cheapest.price == 680
    assert f.price == 680
    assert Flight.parse({"mutilstn": [], "policyinfo": []}).price == 0


def test_search_result_iterates_flights(search_resp):
    """__iter__ 必须迭代出 Flight(pydantic 自带的是字段迭代,已显式覆盖)。"""
    r = SearchResult.parse(search_resp)
    flights = list(r)
    assert len(flights) == 17
    assert all(isinstance(f, Flight) for f in flights)
    assert r[0] is flights[0]
    assert len(r.sorted_by_price()) == 17
    prices = [f.price for f in r.sorted_by_price()]
    assert prices == sorted(prices)
    assert len(r.direct()) == 17


def test_summary_output(search_resp):
    r = SearchResult.parse(search_resp, org="SZX", dst="HAK",
                           date="2026-10-27")
    s = r.summary()
    assert "SZX→HAK 2026-10-27" in s
    assert "共17班" in s
    assert "共享ZH9313" in s           # 共享航班要标实际承运


def test_combined_product_entry():
    """组合产品条目(无航段,只有价格)不能让解析/摘要崩。"""
    raw = {"totalduration": 0,
           "mutilstn": [],
           "policyinfo": [{"tprice": 400, "quantity": 3,
                           "fnotelst": [{"notetype": 4, "notecnt": "经济舱"}],
                           "classinfor": [{"classNoteList":
                                           [{"notetype": 2, "notecnt": "O"}]}]}]}
    r = SearchResult.parse({"fltitem": [raw], "total": 1})
    assert len(r) == 1
    f = r[0]
    assert f.flight_no == ""
    assert f.price == 400
    assert "(组合产品)" in r.summary()


def test_daily_price():
    p = DailyPrice(date="2026-10-19", price=1610)
    assert p.price == 1610
    assert DailyPrice(date="d", price="1610").price == 1610  # 字符串也收


# ------------------------------------------------------------------ 火车票
def test_train_parse(train_search_resp):
    r = TrainSearchResult.parse(train_search_resp)
    assert len(r) == 54
    assert r.depart == "上海" and r.arrive == "北京"
    assert r.depart_code == "SHH" and r.arrive_code == "BJP"
    g = r.trains[0]
    assert g.train_number == "G532"
    assert g.depart_station == "上海虹桥" and g.arrive_station == "北京南"
    assert g.depart_code == "AOH" and g.arrive_code == "VNP"
    assert g.depart_time == "06:31" and g.arrive_time == "12:18"
    assert g.run_time_minutes == 347
    assert g.duration == "5小时47分"
    low = g.cheapest
    assert low is not None
    assert low.seat_name == "二等座" and low.price == 576.0
    assert low.bookable and low.inventory == 99
    # 迭代语义:迭代出 Train 而非字段对
    trains = list(r)
    assert len(trains) == 54 and isinstance(trains[0], Train)
    assert "共54班" in r.summary()


def test_train_parse_empty(train_empty_resp):
    """空线路(上海→月球):Ack=Success + 0 班,缺到达站码,不抛错。"""
    r = TrainSearchResult.parse(train_empty_resp)
    assert not r and len(r) == 0
    assert r.depart == "上海" and r.arrive == "月球"
    assert r.arrive_code == ""
    assert r.summary() and r.bookable() == []


def test_train_seat_model():
    s = TrainSeat(seat_name="硬卧", price=455.5, bookable=False, inventory=0)
    assert not s.bookable and "[无票]" in str(s)
    assert "455.5" in str(s)
