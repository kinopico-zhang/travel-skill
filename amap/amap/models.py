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
        lines = [f"{self.depart}→{self.arrive}({self.mode}) 共{len(self)}条方案"]
        lines.extend(f"  {r}" for r in self.routes)
        return "\n".join(lines)
