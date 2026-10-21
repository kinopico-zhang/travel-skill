#!/usr/bin/env python3
"""携程航班列表响应的数据模型(pydantic)。

原始 JSON 只允许停留在 fetch_json 的返回值(传输边界),
进入业务层即解析为本模块的类型。
"""
from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

from pydantic import BaseModel, Field


class Segment(BaseModel):
    """一个航段。"""

    flight_no: str = ""
    carrier: str = ""              # 营销承运
    actual_carrier: str = ""
    actual_flight_no: str = ""
    is_shared: bool = False
    dep_city: str = ""
    dep_airport: str = ""
    dep_terminal: str = ""
    arr_city: str = ""
    arr_airport: str = ""
    arr_terminal: str = ""
    dep_time: str = ""             # "13:40"
    arr_time: str = ""
    dep_datetime: str = ""         # "2026-10-25 13:40"
    arr_datetime: str = ""
    arr_next_day: bool = False
    aircraft: str = ""

    @classmethod
    def parse(cls, raw: Dict[str, Any]) -> "Segment":
        b = raw["basinfo"]
        d = raw.get("dportinfo") or {}
        a = raw.get("aportinfo") or {}
        dt = raw.get("dateinfo") or {}
        c = raw.get("craftinfo") or {}
        ddate, adate = dt.get("ddate") or "", dt.get("adate") or ""
        return cls(
            flight_no=b.get("flgno", ""),
            carrier=b.get("aircode", ""),
            actual_carrier=b.get("crerairlinecode") or b.get("aircode") or "",
            actual_flight_no=b.get("crerflgno") or b.get("flgno") or "",
            is_shared=bool(b.get("ishared")),
            dep_city=d.get("city", ""),
            dep_airport=d.get("aport", ""),
            dep_terminal=d.get("bsname", ""),
            arr_city=a.get("city", ""),
            arr_airport=a.get("aport", ""),
            arr_terminal=a.get("bsname", ""),
            dep_time=ddate[11:16],
            arr_time=adate[11:16],
            dep_datetime=ddate.replace("T", " "),
            arr_datetime=adate.replace("T", " "),
            arr_next_day=(ddate[:10] != adate[:10]),
            aircraft=c.get("cdisname", ""),
        )

    def __str__(self) -> str:
        return (f"{self.flight_no} {self.dep_airport}{self.dep_terminal} "
                f"{self.dep_time}->{self.arr_time}{'+1' if self.arr_next_day else ''} "
                f"{self.arr_airport}{self.arr_terminal}")


class Fare(BaseModel):
    """一个舱位等级的报价(一个航班可有经济/超经/公务多条)。"""

    price: float = 0
    quantity: int = 0
    discount: Optional[float] = None       # 折扣(0.7 = 七折)
    grade: str = ""                        # 经济舱/公务舱/头等舱...
    cabin_code: str = ""                   # Y/B/M/G...

    @classmethod
    def parse(cls, raw: Dict[str, Any]) -> "Fare":
        # 舱位等级名在 fnotelst notetype=4
        grade = next((n.get("notecnt") for n in raw.get("fnotelst") or []
                      if n.get("notetype") == 4), "")
        # 舱位代码在 classinfor[0].classNoteList notetype=2
        code = ""
        for ci in raw.get("classinfor") or []:
            for n in ci.get("classNoteList") or []:
                if n.get("notetype") == 2:
                    code = n.get("notecnt") or ""
        return cls(
            price=raw.get("tprice") or 0,
            quantity=raw.get("quantity") or 0,
            discount=raw.get("drate"),
            grade=grade or "",
            cabin_code=code,
        )

    def __str__(self) -> str:
        return f"{self.grade} ¥{self.price:.0f} {self.cabin_code}舱 余{self.quantity}"


class Flight(BaseModel):
    """一个航班条目(直达=1 航段;组合产品可能 0 航段只有价格)。"""

    segments: List[Segment] = Field(default_factory=list)
    fares: List[Fare] = Field(default_factory=list)
    duration: int = 0    # 总飞行分钟数

    @classmethod
    def parse(cls, raw: Dict[str, Any]) -> "Flight":
        return cls(
            segments=[Segment.parse(m) for m in raw.get("mutilstn") or []],
            fares=[Fare.parse(p) for p in raw.get("policyinfo") or []],
            duration=raw.get("totalduration") or 0,
        )

    # ---- 便捷属性(直达场景常用) ----
    @property
    def flight_no(self) -> str:
        return (self.segments[0].flight_no if self.segments else "") or ""

    @property
    def dep_time(self) -> str:
        return self.segments[0].dep_time if self.segments else ""

    @property
    def arr_time(self) -> str:
        return self.segments[-1].arr_time if self.segments else ""

    @property
    def dep_airport(self) -> str:
        return self.segments[0].dep_airport if self.segments else ""

    @property
    def arr_airport(self) -> str:
        return self.segments[-1].arr_airport if self.segments else ""

    @property
    def aircraft(self) -> str:
        return self.segments[0].aircraft if self.segments else ""

    @property
    def cheapest(self) -> Optional[Fare]:
        return min(self.fares, key=lambda f: f.price) if self.fares else None

    @property
    def price(self) -> float:
        c = self.cheapest
        return c.price if c else 0

    def fares_of(self, grade_kw: str) -> List[Fare]:
        """按等级关键词过滤报价,如 fares_of('公务')。"""
        return [f for f in self.fares if grade_kw in f.grade]

    def __str__(self) -> str:
        c = self.cheapest
        return (f"{self.flight_no} {self.dep_time}->{self.arr_time} "
                f"¥{c.price:.0f} 余{c.quantity}" if c else
                f"{self.flight_no} {self.dep_time}->{self.arr_time} 无报价")


class SearchResult(BaseModel):
    """search() 的返回:可迭代(迭代出 Flight)、len()、按价排序等。

    注意:必须显式覆盖 __iter__ —— pydantic BaseModel 自带的 __iter__
    迭代的是 (字段名, 值),而本类的语义是迭代航班。
    """

    flights: List[Flight] = Field(default_factory=list)
    org: Optional[str] = None
    dst: Optional[str] = None
    date: Optional[str] = None
    total: Optional[int] = None

    @classmethod
    def parse(cls, data: Dict[str, Any], org: Optional[str] = None,
              dst: Optional[str] = None,
              date: Optional[str] = None) -> "SearchResult":
        return cls(
            flights=[Flight.parse(x) for x in data.get("fltitem") or []],
            org=org, dst=dst, date=date,
            total=data.get("total"),
        )

    def __iter__(self) -> "Iterator[Flight]":  # type: ignore[override]
        # pydantic 基类的 __iter__ 迭代 (字段名, 值);本类语义是迭代航班
        return iter(self.flights)

    def __len__(self) -> int:
        return len(self.flights)

    def __getitem__(self, i: int) -> Flight:
        return self.flights[i]

    def direct(self) -> List[Flight]:
        return [f for f in self.flights if len(f.segments) == 1]

    def sorted_by_price(self) -> List[Flight]:
        return sorted(self.flights, key=lambda f: f.price)

    def cheapest_n(self, n: int = 5) -> List[Flight]:
        return self.sorted_by_price()[:n]

    def summary(self) -> str:
        lines = [f"{self.org}→{self.dst} {self.date}  共{len(self)}班"
                 + (f"(total={self.total})" if self.total != len(self) else "")]
        for f in self.sorted_by_price():
            seg = f.segments[0] if f.segments else None
            fares = " / ".join(str(x) for x in f.fares)
            if seg is None or not f.flight_no:
                # 中转/组合类条目,只有价格信息
                lines.append(f"  {'(组合产品)':20}{fares}")
                continue
            share = f" (共享{seg.actual_flight_no})" if seg.is_shared else ""
            lines.append(f"  {f.flight_no:9}{f.dep_time}-{f.arr_time}"
                         f"{'+1' if seg.arr_next_day else ''} "
                         f"{f.aircraft:12}{share} {fares}")
        return "\n".join(lines)


class DailyPrice(BaseModel):
    """低价日历的一个日期:最低票价(国内含税,国际为不含税票面)。"""

    date: str
    price: int


class City(BaseModel):
    """携程城市码:三字码 + 城市名 + 数字 cityId。

    注意是城市码不是机场码:北京=BJS(非PEK)、西安=SIA(非XIY)。
    """

    code: str
    name: str
    id: str


class CookieEntry(BaseModel):
    """CDP Network.getCookies 的一条 cookie(字段随 CDP 版本增减,extra 透传)。"""

    model_config = {"extra": "allow"}

    name: str
    expires: float = 0    # 0/负数 = 会话级
