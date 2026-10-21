#!/usr/bin/env python3
"""高德导航响应的数据模型(pydantic)。

原始 protobuf 字节只停留在 parser 的输入端,
进入业务层即解析为本模块的类型。
"""
from __future__ import annotations

from typing import Iterator, List, Optional

from pydantic import BaseModel, Field

# deep link 的出行方式 → t 参数值
MODES = {"drive": 0, "bus": 1, "walk": 2, "bike": 3, "train": 4}


class NavStep(BaseModel):
    """路线的一个路段(引导级,信息有限:道路名)。"""

    road: str = ""                # S1广连高速 / 石牯岭隧道...
    distance_m: int = 0           # 路段距离(米),解析不出为 0
    duration_s: int = 0           # 路段历时(秒),解析不出为 0


class NavRoute(BaseModel):
    """一条备选路线(一次导航查询通常返回 2-4 条)。"""

    index: int                    # 方案序号(UI 上的 方案1/方案2)
    distance_m: int               # 8200000 = 82km
    duration_s: int               # 5640 = 1小时34分
    toll_fen: int = 0             # 过路费(分),0 = 无收费路段
    currency: str = "CNY"
    steps: List[NavStep] = Field(default_factory=list)

    @property
    def distance_km(self) -> float:
        return self.distance_m / 1000

    @property
    def duration_str(self) -> str:
        h, m = self.duration_s // 3600, self.duration_s % 3600 // 60
        return f"{h}小时{m}分" if h else f"{m}分钟"

    @property
    def toll_yuan(self) -> float:
        return self.toll_fen / 100

    def __str__(self) -> str:
        toll = f" 过路费¥{self.toll_yuan:g}" if self.toll_fen else ""
        return (f"方案{self.index}: {self.distance_km:.0f}公里 "
                f"{self.duration_str}{toll}")


class NavResult(BaseModel):
    """nav_route() 的返回:可迭代(迭代出 NavRoute)、len()。"""

    depart: str                   # 起点名(回填自查询参数)
    arrive: str
    mode: str = "drive"
    depart_at: Optional[int] = None   # 未来用时:出发时刻(unix 秒),None=现在
    routes: List[NavRoute] = Field(default_factory=list)

    def __iter__(self) -> Iterator[NavRoute]:  # type: ignore[override]
        # pydantic 基类的 __iter__ 迭代 (字段名, 值);本类语义是迭代路线
        return iter(self.routes)

    def __len__(self) -> int:
        return len(self.routes)

    def __bool__(self) -> bool:
        return bool(self.routes)

    def best(self) -> Optional[NavRoute]:
        """时间最短的方案。"""
        return min(self.routes, key=lambda r: r.duration_s) if self.routes else None

    def summary(self) -> str:
        head = f"{self.depart}→{self.arrive}({self.mode}) 共{len(self)}条方案"
        if self.depart_at:
            import time  # pylint: disable=import-outside-toplevel
            head += f" @ {time.strftime('%m-%d %H:%M', time.localtime(self.depart_at))}出发"
        lines = [head]
        lines.extend(f"  {r}" for r in self.routes)
        return "\n".join(lines)


class BusLeg(BaseModel):
    """公交方案的一个乘车段(步行段不在此列,仅计步行总距离)。"""

    line: str = ""                # 城际(惠州北--番禺) / 地铁3号线(...)
    from_station: str = ""        # 上车站
    to_station: str = ""          # 下车站
    via_count: int = 0            # 途经站数
    headway: str = ""             # 首站发车约8分钟/趟

    @property
    def name(self) -> str:
        """显示名:有线路名用线路名,否则上→下车站。"""
        return self.line or (f"{self.from_station}→{self.to_station}"
                             if self.from_station else "")

    def __str__(self) -> str:
        base = self.name
        if self.from_station and self.to_station:
            base += f"({self.from_station}→{self.to_station})"
        if self.via_count:
            base += f"[{self.via_count}站]"
        return base


class BusPlan(BaseModel):
    """一条公交方案(地铁/城际/公交,或客车/火车/打车直达)。"""

    duration_s: int
    walk_m: int = 0
    price: Optional[float] = None     # 元;公交组合方案可能无总价
    tag: str = ""                     # 费用少 / 客车直达 / 火车直达 / 最快…
    note: str = ""                    # 实时备注(如 城际…预计15:55到站)
    legs: List[BusLeg] = Field(default_factory=list)   # 换乘段(直达方案为空)

    @property
    def duration_str(self) -> str:
        h, m = self.duration_s // 3600, self.duration_s % 3600 // 60
        return f"{h}小时{m}分" if h else f"{m}分钟"

    @property
    def walk_km(self) -> float:
        return self.walk_m / 1000

    def __str__(self) -> str:
        price = f" ¥{self.price:g}" if self.price is not None else ""
        walk = f" 步行{self.walk_km:g}km" if self.walk_m else ""
        head = f"{self.duration_str}{walk}{price}" + (f" {self.tag}" if self.tag else "")
        lines = "→".join(l.name for l in self.legs if l.name)
        if not lines:
            lines = self.note[:24]
        return f"{head}  {lines}" if lines else head


class BusResult(BaseModel):
    """bus_route() 的返回:可迭代(迭代出 BusPlan)、len()。

    注意:方案数可能多于 App UI 展示的(UI 折叠了部分组合)。
    """

    depart: str
    arrive: str
    plans: List[BusPlan] = Field(default_factory=list)

    def __iter__(self) -> Iterator[BusPlan]:  # type: ignore[override]
        return iter(self.plans)

    def __len__(self) -> int:
        return len(self.plans)

    def __bool__(self) -> bool:
        return bool(self.plans)

    def best(self) -> Optional[BusPlan]:
        """时间最短方案。"""
        return min(self.plans, key=lambda p: p.duration_s) if self.plans else None

    def summary(self) -> str:
        lines = [f"{self.depart}→{self.arrive}(bus) 共{len(self)}条方案"]
        lines.extend(f"  {p}" for p in self.plans)
        return "\n".join(lines)


class GeoPlace(BaseModel):
    """geocode() 的一个结果:地名 → 坐标。"""

    address: str                      # 广东省广州市海珠区广州塔(地铁站)
    lng: float
    lat: float
    citycode: str = ""                # 020
