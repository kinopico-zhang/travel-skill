#!/usr/bin/env python3
"""飞猪航班列表响应的数据模型(pydantic)。

原始 JSON 只允许停留在 MtopTransport.fetch 的返回值(传输边界),
进入业务层即解析为本模块的类型。
"""
from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

from pydantic import BaseModel, Field

# 列表页有业务数据的卡片类型;其余(ECONOMY_RECOMMEND/LOW_PRICE_MONITOR/
# TITLE 等)是运营位横幅,没有 flightInfos
DATA_ITEM_TYPES = frozenset({"FLIGHT_DIRECT", "FLIGHT_TRANSFER"})


class Segment(BaseModel):
    """一个航段。"""

    flight_no: str = ""
    carrier: str = ""               # 营销承运航司名
    carrier_code: str = ""
    actual_flight_no: str = ""      # 实际承运(代码共享时)
    is_shared: bool = False
    dep_city: str = ""
    dep_airport: str = ""
    dep_terminal: str = ""
    arr_city: str = ""
    arr_airport: str = ""
    arr_terminal: str = ""
    dep_time: str = ""              # "23:20"
    arr_time: str = ""
    dep_datetime: str = ""          # "2026-12-26 23:20"
    arr_datetime: str = ""
    arr_next_day: bool = False
    duration_min: int = 0
    aircraft: str = ""
    stop_quantity: int = 0          # 经停次数(≠中转)

    @classmethod
    def parse(cls, raw: Dict[str, Any]) -> "Segment":
        dep, arr = raw.get("depTime") or "", raw.get("arrTime") or ""
        # 航司名形如 "新海航|海南航空",取最后一段即展示名
        carrier = (raw.get("marketingAirlineName") or "").split("|")[-1]
        return cls(
            flight_no=raw.get("marketingFlightNo") or "",
            carrier=carrier,
            carrier_code=raw.get("marketingAirlineCode") or "",
            actual_flight_no=raw.get("operatingFlightNo")
            or raw.get("marketingFlightNo") or "",
            is_shared=bool(raw.get("codeShare")),
            dep_city=raw.get("depCityName") or "",
            dep_airport=raw.get("depAirportName") or "",
            dep_terminal=raw.get("depTerm") or "",
            arr_city=raw.get("arrCityName") or "",
            arr_airport=raw.get("arrAirportName") or "",
            arr_terminal=raw.get("arrTerm") or "",
            dep_time=dep[11:16],
            arr_time=arr[11:16],
            dep_datetime=dep[:16],
            arr_datetime=arr[:16],
            arr_next_day=bool(raw.get("arrSpanDays")),
            duration_min=raw.get("duration") or 0,
            aircraft=raw.get("planeType") or "",
            stop_quantity=raw.get("stopQuantity") or 0,
        )

    def __str__(self) -> str:
        return (f"{self.flight_no} {self.dep_airport}{self.dep_terminal} "
                f"{self.dep_time}->{self.arr_time}"
                f"{'+1' if self.arr_next_day else ''} "
                f"{self.arr_airport}{self.arr_terminal}")


class Fare(BaseModel):
    """成人报价(响应单位是分,这里统一换算成元)。"""

    price: float = 0.0              # 票面(不含税)
    tax: float = 0.0                # 税费
    total: float = 0.0              # 含税总价 —— 比价用这个
    original_price: float = 0.0     # 划线原价(票面)

    @classmethod
    def parse(cls, raw: Dict[str, Any]) -> "Fare":
        return cls(
            price=(raw.get("adultPrice") or 0) / 100,
            tax=(raw.get("adultTax") or 0) / 100,
            total=(raw.get("adultTotalPrice") or 0) / 100,
            original_price=(raw.get("originalAdultPrice") or 0) / 100,
        )

    def __str__(self) -> str:
        return f"¥{self.total:.0f}(票面¥{self.price:.0f}+税¥{self.tax:.0f})"


class Flight(BaseModel):
    """一个行程条目(直飞=1 航段;中转=多航段)。"""

    segments: List[Segment] = Field(default_factory=list)
    fare: Optional[Fare] = None
    duration: int = 0               # 全程分钟(含中转等待)
    transfer_count: int = 0         # 中转次数
    transfer_time_min: int = 0      # 中转等待分钟

    @classmethod
    def parse(cls, raw: Dict[str, Any]) -> "Flight":
        infos = raw.get("flightInfos") or []
        fi = infos[0] if infos else {}
        price = raw.get("priceInfo") or {}
        return cls(
            segments=[Segment.parse(s) for s in fi.get("flightSegments") or []],
            fare=Fare.parse(price) if price else None,
            duration=fi.get("duration") or 0,
            transfer_count=fi.get("transferCount") or 0,
            transfer_time_min=fi.get("transferTime") or 0,
        )

    # ---- 便捷属性 ----
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
    def cheapest(self) -> Optional[Fare]:
        """ctrip 同名属性的对齐:本库一个行程只有一档报价。"""
        return self.fare

    @property
    def price(self) -> float:
        """含税总价(元);无报价返回 0。"""
        return self.fare.total if self.fare else 0.0

    def __str__(self) -> str:
        fare = str(self.fare) if self.fare else "无报价"
        if self.transfer_count:
            nos = "+".join(s.flight_no for s in self.segments)
            return (f"{nos} 中转{self.transfer_count}次(等"
                    f"{self.transfer_time_min}分) {self.dep_time}-"
                    f"{self.arr_time} {self.duration}分 {fare}")
        seg = self.segments[0] if self.segments else None
        plus = "+1" if seg and seg.arr_next_day else ""
        return (f"{self.flight_no} {self.dep_time}-{self.arr_time}{plus} "
                f"{self.duration}分 {fare}")


class SearchResult(BaseModel):
    """search() 的返回:可迭代(迭代出 Flight)、len()、按价排序等。

    注意:必须显式覆盖 __iter__ —— pydantic BaseModel 自带的 __iter__
    迭代的是 (字段名, 值),而本类的语义是迭代航班。
    """

    flights: List[Flight] = Field(default_factory=list)
    dep: Optional[str] = None
    arr: Optional[str] = None
    date: Optional[str] = None

    @classmethod
    def parse(cls, data: Dict[str, Any], dep: Optional[str] = None,
              arr: Optional[str] = None,
              date: Optional[str] = None) -> "SearchResult":
        flights: List[Flight] = []
        for item in data.get("items") or []:
            if item.get("itemType") not in DATA_ITEM_TYPES:
                continue
            for rec in item.get("data") or []:
                if rec.get("flightInfos"):
                    flights.append(Flight.parse(rec))
        return cls(flights=flights, dep=dep, arr=arr, date=date)

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

    def summary(self, direct_only: bool = False) -> str:
        """人类可读摘要;direct_only=True 只列直飞。"""
        pool = self.direct() if direct_only else self.flights
        head = (f"{self.dep}→{self.arr} {self.date}  共{len(pool)}班"
                + ("(直飞)" if direct_only else f"/直飞{len(self.direct())}"))
        lines = [head]
        for f in sorted(pool, key=lambda x: x.price):
            share = ""
            if f.segments and f.segments[0].is_shared:
                share = f" (共享{f.segments[0].actual_flight_no})"
            lines.append(f"  {f}{share}")
        return "\n".join(lines)
