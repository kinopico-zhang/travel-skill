"""响应解析后的数据模型(pydantic)。

原始 JSON 只允许停留在 `_post` 的返回值(传输边界),进入业务层即解析为
本模块的类型;字段类型以真实抓包响应为准。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


def _to_int(v: Any) -> Optional[int]:
    """服务端的数字字段常以字符串/浮点下发,统一转 int;空值转 None。"""
    if v is None or v == "":
        return None
    try:
        return int(float(str(v)))
    except (TypeError, ValueError):
        return None


def _to_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class AwardCabin(BaseModel):
    """奖励票舱位。

    服务端约定:X(经济)的兑换价在航班级 minCombinedPrice,I(公务)的可兑
    标记才是 pprice>0 —— bookable 只是启发式提示,精确可用性看航班级
    mileage_price + seats。
    """

    code: str = ""            # I / X / O ...
    service: str = ""         # business / economy / first
    service_desc: str = ""    # 公务舱 / 经济舱 / 头等舱
    pprice: Optional[float] = None   # >0 视为该舱可兑(仅对 I 可靠)
    fprice: Optional[float] = None
    seat_num: str = ""        # 该舱剩余座位
    hand_baggage: str = ""    # 手提行李
    child_baggage: str = ""   # 免费托运行李

    @property
    def bookable(self) -> bool:
        """pprice/fprice > 0 视为可兑换(对公务舱 I 行可靠)。"""
        return (self.pprice or 0) > 0 or (self.fprice or 0) > 0

    @classmethod
    def parse(cls, c: Dict[str, Any]) -> "AwardCabin":
        return cls(
            code=c.get("classCode") or "",
            service=c.get("classOfService") or "",
            service_desc=c.get("classDescOfService") or "",
            pprice=_to_float(c.get("pprice")),
            fprice=_to_float(c.get("fprice")),
            seat_num=str(c.get("seatNum") or ""),
            hand_baggage=c.get("handBaggage") or "",
            child_baggage=c.get("childBaggage") or "",
        )

    def __str__(self) -> str:
        return (f"{self.code}({self.service_desc or self.service}"
                f"{',可兑' if self.bookable else ''})")


class AwardFlight(BaseModel):
    """一个可兑换航班。"""

    flight_no: str            # CA1322 / ZH9325
    org: str                  # CAN
    dst: str                  # PEK
    dep_date: str
    dep_time: str             # 13:40
    arr_date: str
    arr_time: str             # 16:55
    dep_term: str             # T3
    arr_term: str
    aircraft: str             # 空客350
    duration: str             # 3小时15分钟
    mileage_price: Optional[int] = None   # 最低兑换里程,如 15000
    seats: str                # 剩余奖励票座位
    cabins: List[AwardCabin] = Field(default_factory=list)
    flight_id: str = ""

    @classmethod
    def parse(cls, f: Dict[str, Any]) -> "AwardFlight":
        dep = f.get("departure") or {}
        arr = f.get("arrival") or {}
        return cls(
            flight_no=(f.get("flightCompanyNameCode") or "") + (f.get("flightNo") or ""),
            org=f.get("orgStr") or "",
            dst=f.get("dstStr") or "",
            dep_date=f.get("depDate") or dep.get("date") or "",
            dep_time=dep.get("time") or f.get("depTime") or "",
            arr_date=f.get("arriDate") or arr.get("date") or "",
            arr_time=arr.get("time") or f.get("arriTime") or "",
            dep_term=f.get("depTerm") or "",
            arr_term=f.get("arriTerm") or "",
            aircraft=f.get("airCraft") or "",
            duration=f.get("flightTimeDesc") or "",
            mileage_price=_to_int(f.get("minCombinedPrice")),
            seats=str(f.get("seatNum") or ""),
            cabins=[AwardCabin.parse(c) for c in (f.get("cabins") or [])],
            flight_id=str(f.get("id") or ""),
        )

    def __str__(self) -> str:
        cabins = " ".join(str(c) for c in self.cabins) or "-"
        mp = f"{self.mileage_price}里程" if self.mileage_price is not None else "?"
        return (f"{self.flight_no:<7} {self.dep_time}->{self.arr_time} "
                f"{self.dep_term}->{self.arr_term} {self.aircraft:<10} "
                f"{mp:<9} 余{self.seats} [{cabins}]")


class DayAward(BaseModel):
    """lowPriceList 的一项:候选日期 + hasTicket 标记。

    hasTicket 的值(0/4/6...)经实测与真实可兑性对不上,仅供展示,
    判断可用性必须实查 award_search。
    """

    date: str
    has_ticket: str = ""


class AwardResult(BaseModel):
    """award_search 的结果。

    code/message 原样保留服务端业务码;查询日期无可兑换航班时
    flights 为空列表、message 形如「抱歉，暂时没有可兑换航班啦。」。
    """

    flights: List[AwardFlight] = Field(default_factory=list)   # 去程
    return_flights: List[AwardFlight] = Field(default_factory=list)  # 回程(往返)
    code: str = ""
    message: str = ""
    availability: List[DayAward] = Field(default_factory=list)  # lowPriceList

    @classmethod
    def parse(cls, data: Dict[str, Any]) -> "AwardResult":
        resp = data.get("resp") or {}
        return cls(
            flights=[AwardFlight.parse(f) for f in (resp.get("departureFlightInfos") or [])],
            return_flights=[AwardFlight.parse(f) for f in (resp.get("returnFlightInfos") or [])],
            code=str(resp.get("code") or ""),
            message=resp.get("msg") or "",
            availability=[DayAward(date=d["date"], has_ticket=str(d.get("hasTicket") or ""))
                          for d in (resp.get("lowPriceList") or []) if d.get("date")],
        )

    def __bool__(self) -> bool:
        return bool(self.flights or self.return_flights)

    def __len__(self) -> int:
        return len(self.flights)


class DailyPrice(BaseModel):
    """低价日历的一个日期:最低现金票价(人民币)。"""

    date: str
    price: int


class MileageSummary(BaseModel):
    """里程/账户概要(a=8 p=34)。

    该接口 req 结构未完全逆向,字段名随服务端版本可能变化,
    固定字段只有 code/msg,其余用 extra="allow" 透传。
    """

    model_config = ConfigDict(extra="allow")

    code: str = ""
    msg: str = ""
