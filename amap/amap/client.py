#!/usr/bin/env python3
"""高德导航客户端:编排 Deep Link 触发 + flows 捕获 + protobuf 解析。

用法(前提见 README:模拟器/代理/CA/iptables 链路):

    from amap import AmapClient
    am = AmapClient()
    r = am.nav_route(22.9208, 113.8903, "起点", 23.1066, 113.3245, "终点")
    print(r.summary())
    b = r.best()   # 时间最短方案
    bus = am.bus_route(22.9208, 113.8903, "起点", 23.1066, 113.3245, "终点")
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Optional, Protocol

from .capture import BUS_PATH, wait_for_response
from .models import BusResult, NavResult
from .parser import parse_bus_wire, parse_wire
from .transport import DeepLinkTransport

FLOWS_DEFAULT = "/tmp/amap.flows"


class Transport(Protocol):
    """AmapClient 依赖的最小传输接口(测试注入替身用)。"""

    def check(self) -> None:
        ...

    def launch_route(self, slat: float, slon: float, dlat: float, dlon: float,
                     sname: str = "", dname: str = "",
                     mode: str = "drive") -> float:
        ...

    def set_clock(self, ts: float) -> None:
        ...

    def restore_clock(self, ts: float) -> None:
        ...


class AmapClient:
    """高德导航查询客户端(Deep Link 页面代理模式)。"""

    def __init__(self, flows_path: str = FLOWS_DEFAULT,
                 transport: Optional[Transport] = None,
                 min_interval: float = 8.0):
        self.flows_path = flows_path
        self.transport: Transport = transport or DeepLinkTransport()
        self.min_interval = min_interval
        self._last = 0.0

    def _throttle(self) -> None:
        """导航查询比网页重得多,人类不会连点,默认 8s 起步。"""
        wait = self.min_interval - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()

    def nav_route(self, slat: float, slon: float, sname: str,
                  dlat: float, dlon: float, dname: str,
                  mode: str = "drive", timeout: float = 90.0,
                  depart_at: Optional[datetime] = None) -> NavResult:
        """驾车(默认)路线查询,返回 2-4 条备选方案。

        坐标为 GCJ-02。起终点名仅用于展示与 URI 参数,
        实际路线按坐标规划。公交用 bus_route();步行/骑行的
        响应端点(walkcloud)未解析,暂不支持。

        depart_at: 查未来用时(如明早 8 点出发)。实现是把模拟器
        系统时间改到该时刻再触发查询,App 即以该时刻请求预测。
        全局副作用,查询完自动恢复 —— 偶发使用可以,别高频。
        """
        if mode not in ("drive",):
            raise NotImplementedError(
                f"nav_route 暂只支持 drive;公交用 bus_route(),"
                f"步行/骑行响应未解析(收到 {mode!r})")
        self._throttle()
        if depart_at is None:
            sent_at = self.transport.launch_route(
                slat, slon, dlat, dlon, sname=sname, dname=dname, mode=mode)
        else:
            ts = depart_at.timestamp()
            # set → launch → 无论成败都恢复;恢复用的真实时刻在本机取
            self.transport.set_clock(ts)
            try:
                sent_at = self.transport.launch_route(
                    slat, slon, dlat, dlon, sname=sname, dname=dname,
                    mode=mode)
            finally:
                self.transport.restore_clock(time.time())
        raw = wait_for_response(self.flows_path, since_ts=sent_at - 2,
                                timeout=timeout)
        routes = parse_wire(raw)
        if not routes:
            raise CaptureErrorEmpty("响应里没有路线方案 — 目的地坐标可达吗?")
        return NavResult(depart=sname, arrive=dname, mode=mode, routes=routes,
                         depart_at=None if depart_at is None else int(ts))

    def bus_route(self, slat: float, slon: float, sname: str,
                  dlat: float, dlon: float, dname: str,
                  timeout: float = 90.0) -> BusResult:
        """公交(地铁/城际/公交)路线查询,返回聚合方案列表。

        一次查询通常返回 10+ 条方案(UI 只展示推荐的几条),
        每条含历时/步行/票价与换乘段线路。跨城方案可能无票价。
        """
        self._throttle()
        sent_at = self.transport.launch_route(
            slat, slon, dlat, dlon, sname=sname, dname=dname, mode="bus")
        raw = wait_for_response(self.flows_path, since_ts=sent_at - 2,
                                timeout=timeout, path=BUS_PATH)
        plans = parse_bus_wire(raw)
        if not plans:
            raise CaptureErrorEmpty("响应里没有公交方案 — 坐标间有公交可达吗?")
        return BusResult(depart=sname, arrive=dname, plans=plans)

    def check(self) -> str:
        """链路体检,返回人话报告(不通过抛异常)。"""
        from .capture import read_nav_responses  # pylint: disable=import-outside-toplevel
        self.transport.check()
        rows = read_nav_responses(self.flows_path)
        return (f"adb/设备/高德 OK;flows {self.flows_path} 可读, "
                f"已捕获 {len(rows)} 条导航响应")


class CaptureErrorEmpty(Exception):
    """响应解析成功但没有路线(罕见,如坐标不可达)。"""
