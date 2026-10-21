#!/usr/bin/env python3
"""高德 H5 Web 服务客户端(纯 Python,零模拟器依赖)。

原理:m.amap.com(H5 版)的 JS API 配置了服务代理 —— 页面源码里
`window._AMapSecurityConfig = {serviceHost: "https://m.amap.com/_AMapService"}`,
浏览器里的路线查询都经这个代理转发(密钥由 m.amap.com 服务端代持)。
带上 H5 公开 key + platform=JS 参数 + Referer 即可直调,与在手机浏览器
里用 m.amap.com 查路线完全等价 —— 高德 App 的 native 签名(in=/密文
body)在这里不存在,这是全链路里唯一不需要模拟器的入口。

可用:驾车 v3(每步道路名/过路费/打车参考价)、公交 v3(方案/换乘段/
票价/步行)、步行 v3、地理编码 v3、**未来用车时 v4/etd**(驾车,
首时刻+间隔+个数,一次最多 48 个点)。骑行接口代理未开放。
"""
from __future__ import annotations

import datetime
import gzip
import json
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from .models import (BusLeg, BusPlan, BusResult, FutureEta, GeoPlace,
                     NavResult, NavRoute, NavStep)
from .parser import _dedupe_line

WEB_BASE = "https://m.amap.com/_AMapService"
# m.amap.com H5 页面公开的 JS key(webapi 加载参数里可见,非私钥)
WEB_KEY = "ab403a9b356e63c917ff05b037cd3e7d"

# 桌面版 ditu.amap.com 的服务代理(同 _AMapService 机制,服务端另一把
# key,对 v4/etd 有权限 —— m.amap.com 的代理对 v4/etd 返回 10009
# USERKEY_PLAT_NOMATCH,这是 0.4.0 未来用时纯 HTTP 化的破局点)
DITU_BASE = "https://ditu.amap.com/_AMapService"
DITU_KEY = "2f282f369e388ef01bae260cbc35edce"

# v3 驾车 strategy 数字(代理实测认 0/1/2/16/32,其余值全被归并为默认;
# 16 会返回 3 条备选方案,其余单方案)
DRIVE_STRATEGIES = {0: "速度最快", 1: "费用最少", 2: "距离最短",
                    16: "不走高速", 32: "默认"}

# 高德 App「路线偏好」同名的策略体系 → (中文名, v3 值, v4/etd 值)。
# 两个通道支持的值不同(v4/etd 实测只有两档:1 躲避拥堵 / 2 免费不走高速,
# 其余值全归这两档),所以每个偏好按通道映射:
#   v3:  avoid_jam 无独立避堵值回落默认;highway 无独立值用时间优先近似
#   etd: cheap/no_highway → 2(免费,实测零过路费且不走高速);short 用避堵近似
APP_STRATEGIES: Dict[str, tuple] = {  # noqa: UP006  # (str, int, int)
    "smart": ("高德AI推荐", 32, 1),
    "fast": ("时间优先", 0, 1),
    "cheap": ("费用优先", 1, 2),
    "short": ("距离优先", 2, 1),
    "no_highway": ("不走高速", 16, 2),
    "avoid_jam": ("躲避拥堵", 32, 1),
    "highway": ("高速优先", 0, 1),
}


def resolve_strategy(strategy: Any) -> tuple:  # noqa: UP006  # (v3值, etd值)
    """路线偏好(名字或 v3 数字)→ (v3 strategy, v4/etd strategy)。

    名字用 App「路线偏好」同款概念;数字按 v3 语义(费用最少/不走高速
    在 etd 通道对应免费档)。
    """
    if isinstance(strategy, str):
        s = strategy.lower()
        if s not in APP_STRATEGIES:
            raise WebError(f"未知策略 {strategy!r},可选: "
                           f"{sorted(APP_STRATEGIES)} 或 v3 数字 {sorted(DRIVE_STRATEGIES)}")
        return APP_STRATEGIES[s][1], APP_STRATEGIES[s][2]
    if strategy not in DRIVE_STRATEGIES:
        raise WebError(f"未知 strategy {strategy},可选: "
                       f"{sorted(DRIVE_STRATEGIES)} 或名字 {sorted(APP_STRATEGIES)}")
    return strategy, 2 if strategy in (1, 16) else 1


class WebError(Exception):
    """Web 服务调用异常(status 非 1 / 网络 / 解析失败)。"""


class WebClient:
    """高德 H5 Web 服务客户端。用法:

        from amap import WebClient
        w = WebClient()
        r = w.nav_route(22.9208, 113.8903, "起点", 23.1066, 113.3245, "终点")
        b = w.bus_route(22.9208, 113.8903, "起点", 23.1066, 113.3245, "终点")
        g = w.geocode("地址")          # 地名 → 坐标
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

    def _get(self, path: str, params: Dict[str, Any],
             base: str = "", key: str = "") -> Dict[str, Any]:
        """GET <base><path>?<params>,返回 JSON dict;status 非 1 抛 WebError。"""
        q = {"platform": "JS", "s": "rsv3", "logversion": "2.0",
             "sdkversion": "2.0", "key": key or self.key}
        q.update({k: v for k, v in params.items() if v is not None})
        url = f"{base or self.base}{path}?{urllib.parse.urlencode(q)}"
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
        # v3 系按 status=="1" 判成功;v4 系(etd)顶层是 errcode==0
        if "errcode" in data:
            if data.get("errcode") != 0:
                raise WebError(
                    f"{path} 出错: {data.get('errmsg')}({data.get('errcode')})")
        elif data.get("status") != "1":
            raise WebError(
                f"{path} 出错: {data.get('info')}({data.get('infocode')})")
        return data

    # ---------- 驾车 / 公交 / 步行 ----------

    def nav_route(self, slat: float, slon: float, sname: str,
                  dlat: float, dlon: float, dname: str,
                  strategy: Any = "smart",
                  depart_at: Optional[datetime.datetime] = None) -> NavResult:
        """驾车路线。strategy:App「路线偏好」同款策略名或 v3 数字。

        策略名:smart 高德AI推荐(默认)/ fast 时间优先 / cheap 费用优先
        (少收费)/ short 距离优先 / no_highway 不走高速 / avoid_jam 躲避拥堵 /
        highway 高速优先。也可传 v3 数字 0/1/2/16/32。
        同一名字在两个通道各映射到该通道实际支持的值(见 APP_STRATEGIES)。

        与 App 侧(多方案一次返回)不同,v3 一次查询一个策略
        (no_highway 例外,返回 3 条备选);想比较就换策略再查。

        depart_at:未来出发时刻(如明早 8 点)。走 v4/etd 未来预测,
        返回按该时刻路况预估的用时/过路费;必须是未来时间。
        v4/etd 只有躲避拥堵/免费两档,cheap 与 no_highway 映射免费档
        (实测零过路费、不走高速,代价是用时明显变长,长途约多三成)。
        """
        v3s, etds = resolve_strategy(strategy)
        if depart_at is not None:
            ts = int(depart_at.timestamp())
            if ts <= time.time():
                raise WebError("depart_at 必须是未来时间(v4/etd 预测接口)")
            routes, etas = self._etd(slon, slat, dlon, dlat, ts, 1, 1,
                                     strategy=etds)
            # v4/etd 的用时/费用在时间点上,path 本体不带;响应可能含多个
            # 备选 path,elements[0] 对应首方案 —— 只留它并回填
            if routes and etas:
                routes[0].duration_s = etas[0].duration_min * 60
                routes[0].toll_fen = int(etas[0].toll_yuan * 100)
            return NavResult(depart=sname, arrive=dname, mode="drive",
                             depart_at=ts, routes=routes[:1])
        data = self._get("/v3/direction/driving", {
            "origin": f"{slon},{slat}", "destination": f"{dlon},{dlat}",
            "strategy": v3s,
            "extensions": "base"})
        routes = parse_web_drive(data)
        if not routes:
            raise WebError("响应里没有驾车方案 — 起终点坐标可达吗?")
        return NavResult(depart=sname, arrive=dname, mode="drive", routes=routes)

    def etd_table(self, slat: float, slon: float, dlat: float, dlon: float,
                  first: datetime.datetime,
                  interval_s: int = 1800, count: int = 4,
                  strategy: Any = "smart") -> List[FutureEta]:
        """未来用时时刻表:v4/etd 一次返回 count 个时间点的预估。

        first:首时刻(未来);interval_s:相邻点间隔(秒);
        count:点数,最多 48。改时钟方案要一个点一个点地查,
        这里一次请求全出 —— 明显低频更友好。
        strategy:App 同款策略名;v4/etd 只有躲避拥堵(默认)/免费两档,
        cheap 与 no_highway 走免费档(零过路费)。
        """
        if not 1 <= count <= 48:
            raise WebError("count 1-48(v4/etd 上限)")
        if interval_s <= 0:
            raise WebError("interval_s 必须为正")
        ts = int(first.timestamp())
        if ts <= time.time():
            raise WebError("first 必须是未来时间(v4/etd 预测接口)")
        return self._etd(slon, slat, dlon, dlat, ts, interval_s, count,
                         strategy=resolve_strategy(strategy)[1])[1]

    def _etd(self, slon: float, slat: float, dlon: float, dlat: float,
             firsttime: int, interval: int, count: int,
             strategy: int = 1) -> tuple[List[NavRoute], List[FutureEta]]:
        """调 ditu 代理的 v4/etd,返回 (首方案路线, 全部时刻预估)。

        strategy:1 躲避拥堵(默认)/ 2 免费路线(零过路费,不走高速)。
        v3 的位掩码 16/17(不走高速)v4/etd 不认,传了等同 1。
        """
        data = self._get("/v4/etd/driving", {
            "origin": f"{slon},{slat}", "destination": f"{dlon},{dlat}",
            "strategy": strategy,
            "firsttime": firsttime, "interval": interval, "count": count,
        }, base=DITU_BASE, key=DITU_KEY)
        routes, etas = parse_etd(data, firsttime, interval, count)
        if not routes:
            raise WebError("v4/etd 响应里没有方案 — 起终点坐标可达吗?")
        return routes, etas

    def bus_route(self, slat: float, slon: float, sname: str,
                  dlat: float, dlon: float, dname: str,
                  city: str = "", cityd: str = "") -> BusResult:
        """公交(地铁/公交/城际)路线。

        city/cityd(起终点城市)一般不用传:实测跨城查询
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


def parse_etd(data: Dict[str, Any], firsttime: int, interval: int,
              count: int) -> tuple[List[NavRoute], List[FutureEta]]:
    """v4/etd 响应 → (List[NavRoute], List[FutureEta])。

    结构:一个 path(含 steps)+ time_infos[] 按请求的 count 个时刻,
    每时刻 elements[0] = {duration(分钟), tolls(元), restriction}。
    展示时刻用请求推算(firsttime + i*interval)—— 返回的 starttime
    是毫秒且存在偏移怪癖,不作时刻来源。
    """
    d = data.get("data") or {}
    paths = d.get("paths") or []
    routes: List[NavRoute] = []
    for i, p in enumerate(paths, 1):
        steps = [NavStep(road=str(s.get("road") or ""),
                         distance_m=_int(s.get("distance")),
                         duration_s=0)
                 for s in p.get("steps") or []]
        routes.append(NavRoute(
            index=i, distance_m=_int(p.get("distance")),
            duration_s=0,          # 用时在时间点上,不在 path 里
            toll_fen=0, currency="CNY", steps=steps))
    etas: List[FutureEta] = []
    tis = d.get("time_infos") or []
    for i, ti in enumerate(tis[:count]):
        els = ti.get("elements") or []
        if not els:
            continue
        e = els[0]
        etas.append(FutureEta(
            depart_at=firsttime + i * interval,
            duration_min=_int(e.get("duration")),
            toll_yuan=float(e.get("tolls") or 0),
            restriction=_int(e.get("restriction"))))
    return routes, etas


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
