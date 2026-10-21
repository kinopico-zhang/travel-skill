#!/usr/bin/env python3
"""高德 H5 Web 服务客户端(纯 Python,零模拟器依赖)。

原理:m.amap.com(H5 版)的 JS API 配置了服务代理 —— 页面源码里
`window._AMapSecurityConfig = {serviceHost: "https://m.amap.com/_AMapService"}`,
浏览器里的路线查询都经这个代理转发(密钥由 m.amap.com 服务端代持)。
带上 H5 公开 key + platform=JS 参数 + Referer 即可直调,与在手机浏览器
里用 m.amap.com 查路线完全等价 —— 高德 App 的 native 签名(in=/密文
body)在这里不存在,这是全链路里唯一不需要模拟器的入口。

可用:驾车 v3(每步道路名/过路费/打车参考价)、公交 v3(方案/换乘段/
票价/步行)、步行 v3、地理编码 v3。骑行接口代理未开放。
未来用时(depart_at)Web 版无此能力,仍需 App 侧(见 client.py)。
"""
from __future__ import annotations

import gzip
import json
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List

from .models import (BusLeg, BusPlan, BusResult, GeoPlace, NavResult,
                     NavRoute, NavStep)
from .parser import _dedupe_line

WEB_BASE = "https://m.amap.com/_AMapService"
# m.amap.com H5 页面公开的 JS key(webapi 加载参数里可见,非私钥)
WEB_KEY = "ab403a9b356e63c917ff05b037cd3e7d"

# v3 驾车 strategy:0 速度优先 1 费用优先 2 距离优先 32 默认
DRIVE_STRATEGIES = {0: "速度最快", 1: "费用最少", 2: "距离最短", 32: "默认"}


class WebError(Exception):
    """Web 服务调用异常(status 非 1 / 网络 / 解析失败)。"""


class WebClient:
    """高德 H5 Web 服务客户端。用法:

        from amap import WebClient
        w = WebClient()
        r = w.nav_route(22.9208, 113.8903, "松山湖", 23.1066, 113.3245, "广州塔")
        b = w.bus_route(22.9208, 113.8903, "松山湖", 23.1066, 113.3245, "广州塔")
        g = w.geocode("广州塔")        # 地名 → 坐标
    """

    def __init__(self, key: str = WEB_KEY, base: str = WEB_BASE,
                 min_interval: float = 2.0, timeout: float = 15.0):
        self.key = key
        self.base = base
        self.min_interval = min_interval
        self.timeout = timeout
        self._last = 0.0

    # ---------- HTTP ----------

    def _throttle(self) -> None:
        """H5 页面一次查询会连发数个请求,2s 间隔已明显保守于人手点按。"""
        wait = self.min_interval - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()

    def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """GET <base><path>?<params>,返回 JSON dict;status 非 1 抛 WebError。"""
        q = {"platform": "JS", "s": "rsv3", "logversion": "2.0",
             "sdkversion": "2.0", "key": self.key}
        q.update({k: v for k, v in params.items() if v is not None})
        url = f"{self.base}{path}?{urllib.parse.urlencode(q)}"
        req = urllib.request.Request(
            url, headers={"Referer": "https://m.amap.com/",
                          "User-Agent": "Mozilla/5.0 (Linux; Android 13) "
                                        "Chrome/131 Mobile Safari/537.36"})
        self._throttle()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
        except Exception as e:  # noqa: BLE001  # 网络层各种异常统一包装
            raise WebError(f"请求失败 {path}: {e}") from e
        if raw[:2] == b"\x1f\x8b":        # 服务端偶发回 gzip
            raw = gzip.decompress(raw)
        try:
            data: Dict[str, Any] = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            raise WebError(f"响应不是 JSON {path}: {raw[:80]!r}") from e
        if data.get("status") != "1":
            raise WebError(
                f"{path} 出错: {data.get('info')}({data.get('infocode')})")
        return data

    # ---------- 驾车 / 公交 / 步行 ----------

    def nav_route(self, slat: float, slon: float, sname: str,
                  dlat: float, dlon: float, dname: str,
                  strategy: int = 0) -> NavResult:
        """驾车路线(单方案)。strategy: 0 速度/1 费用/2 距离/32 默认。

        与 App 侧(多方案一次返回)不同,Web 版一次查询一个策略,
        想比较多方案就换 strategy 再查。
        """
        if strategy not in DRIVE_STRATEGIES:
            raise WebError(f"未知 strategy {strategy},可选: {sorted(DRIVE_STRATEGIES)}")
        data = self._get("/v3/direction/driving", {
            "origin": f"{slon},{slat}", "destination": f"{dlon},{dlat}",
            "strategy": strategy,
            "extensions": "base"})
        routes = parse_web_drive(data)
        if not routes:
            raise WebError("响应里没有驾车方案 — 起终点坐标可达吗?")
        return NavResult(depart=sname, arrive=dname, mode="drive", routes=routes)

    def bus_route(self, slat: float, slon: float, sname: str,
                  dlat: float, dlon: float, dname: str,
                  city: str = "", cityd: str = "") -> BusResult:
        """公交(地铁/公交/城际)路线。

        city/cityd(起终点城市)一般不用传:实测跨城查询(东莞→广州)
        不带城市参数也能正确出方案,服务端按坐标识别;显式传入仅在
        识别不准时兜底。regeo 逆地理不在代理白名单里(会回滑块
        验证页),所以不做坐标→城市的自动识别。
        """
        data = self._get("/v3/direction/transit/integrated", {
            "origin": f"{slon},{slat}", "destination": f"{dlon},{dlat}",
            "city": city or None, "cityd": cityd or None, "strategy": 0})
        plans = parse_web_transit(data)
        if not plans:
            raise WebError("响应里没有公交方案 — 坐标间公交可达吗?")
        return BusResult(depart=sname, arrive=dname, plans=plans)

    def walk_route(self, slat: float, slon: float, sname: str,
                   dlat: float, dlon: float, dname: str) -> NavResult:
        """步行路线(单方案)。"""
        data = self._get("/v3/direction/walking", {
            "origin": f"{slon},{slat}", "destination": f"{dlon},{dlat}"})
        routes = parse_web_walk(data)
        if not routes:
            raise WebError("响应里没有步行方案")
        return NavResult(depart=sname, arrive=dname, mode="walk", routes=routes)

    # ---------- 地理编码 ----------

    def geocode(self, address: str, city: str = "") -> List[GeoPlace]:
        """地名 → 坐标列表(按相关性排序,第一个通常就是要找的)。"""
        data = self._get("/v3/geocode/geo", {"address": address,
                                             "city": city or None})
        out: List[GeoPlace] = []
        for g in data.get("geocodes") or []:
            loc = str(g.get("location", "")).split(",")
            if len(loc) != 2:
                continue
            out.append(GeoPlace(
                address=str(g.get("formatted_address", "")),
                lng=float(loc[0]), lat=float(loc[1]),
                citycode=str(g.get("citycode", "") or "")))
        return out


# ---------- JSON → 模型(独立函数便于用真实夹具测试) ----------

def parse_web_drive(data: Dict[str, Any]) -> List[NavRoute]:
    """v3 驾车响应 → List[NavRoute](一次查询一个策略,通常 1 条)。"""
    paths = ((data.get("route") or {}).get("paths")) or []
    out: List[NavRoute] = []
    for i, p in enumerate(paths, 1):
        steps: List[NavStep] = []
        for s in p.get("steps") or []:
            steps.append(NavStep(
                road=str(s.get("road") or ""),
                distance_m=_int(s.get("distance")),
                duration_s=_int(s.get("duration"))))
        out.append(NavRoute(
            index=i,
            distance_m=_int(p.get("distance")),
            duration_s=_int(p.get("duration")),
            toll_fen=int(float(p.get("tolls") or 0) * 100),   # 元 → 分
            currency="CNY",
            steps=steps))
    return out


def parse_web_transit(data: Dict[str, Any]) -> List[BusPlan]:
    """v3 公交响应 → List[BusPlan](方案/换乘段,含城际与地铁)。"""
    transits = ((data.get("route") or {}).get("transits")) or []
    out: List[BusPlan] = []
    for t in transits:
        walk_m = 0
        legs: List[BusLeg] = []
        for seg in t.get("segments") or []:
            w = seg.get("walking")
            if isinstance(w, dict):
                walk_m += _int(w.get("distance"))
            for b in ((seg.get("bus") or {}).get("buslines")) or []:
                legs.append(BusLeg(
                    line=_dedupe_line(str(b.get("name") or "")),
                    from_station=str((b.get("departure_stop") or {}).get("name") or ""),
                    to_station=str((b.get("arrival_stop") or {}).get("name") or ""),
                    via_count=len(b.get("via_stops") or [])))
            rl = seg.get("railway")
            if isinstance(rl, dict) and rl.get("name"):
                legs.append(BusLeg(
                    line=_dedupe_line(str(rl["name"])),
                    from_station=str((rl.get("departure_stop") or {}).get("name") or ""),
                    to_station=str((rl.get("arrival_stop") or {}).get("name") or ""),
                    via_count=len(rl.get("via_stops") or [])))
        out.append(BusPlan(
            duration_s=_int(t.get("duration")),
            walk_m=walk_m,
            price=float(t["cost"]) if t.get("cost") not in (None, "", []) else None,
            legs=legs))
    return out


def parse_web_walk(data: Dict[str, Any]) -> List[NavRoute]:
    """v3 步行响应 → List[NavRoute](复用驾车模型,无费用)。"""
    return parse_web_drive(data)


def _int(v: Any) -> int:
    """v3 里数字全是字符串,且偶发为空数组([])。"""
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str) and v:
        try:
            return int(float(v))
        except ValueError:
            return 0
    return 0
