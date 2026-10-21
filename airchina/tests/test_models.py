"""models 解析测试:全部对着真实抓包夹具断言。"""
from airchina.models import (AwardCabin, AwardResult, DailyPrice,
                             DayAward, MileageSummary)

EMPTY_MSG = "抱歉，暂时没有可兑换航班啦。"


def test_parse_award_ow(award_ow):
    r = AwardResult.parse(award_ow)
    assert r
    assert len(r) == 2
    assert r.code == "00000000"
    assert r.message == "成功"
    f = r.flights[0]
    assert f.flight_no
    assert f.mileage_price == 5600          # minCombinedPrice 以字符串下发
    assert f.dep_date == "2026-10-27"
    assert f.dep_time == "16:15"
    assert f.seats == "1"
    c = f.cabins[0]
    assert c.code == "X"
    assert c.service == "economy"
    assert c.service_desc == "经济舱"
    assert c.pprice == -1.0
    assert c.seat_num == "1"
    assert c.hand_baggage == "5KG"


def test_cabin_bookable_heuristic():
    """pprice>0 只在公务舱 I 行出现;X 行 pprice=-1 不可据此判兑。"""
    assert AwardCabin(code="I", pprice=1.0).bookable is True
    assert AwardCabin(code="X", pprice=-1.0, fprice=-1.0).bookable is False
    assert AwardCabin(code="X").bookable is False


def test_parse_availability(award_ow):
    r = AwardResult.parse(award_ow)
    assert r.availability[0] == DayAward(date="2026-10-20", has_ticket="0")
    assert all(isinstance(d.has_ticket, str) for d in r.availability)


def test_parse_empty_result():
    r = AwardResult.parse({"resp": {"code": "00000000", "msg": EMPTY_MSG}})
    assert not r
    assert len(r) == 0
    assert r.flights == []
    assert r.message == EMPTY_MSG


def test_daily_price_coerces_string_price():
    """国航日历的 price 以字符串下发("1350"),模型统一成 int。"""
    p = DailyPrice(date="2026-11-09", price="1350")
    assert p.price == 1350


def test_mileage_summary_extra_allow():
    """账户端点字段未逆向定型,额外字段要透传。"""
    m = MileageSummary.model_validate({"code": "00000000", "msg": "成功",
                                       "mileage": "12300", "tierName": "银卡"})
    assert m.code == "00000000"
    assert m.model_dump()["mileage"] == "12300"
    assert m.model_dump()["tierName"] == "银卡"
