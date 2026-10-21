#!/usr/bin/env python3
"""高德 nvg 导航响应解析:gzip → 64B 容器头 → zstd → protobuf。

响应不加密(请求才是 shield 加密的,由 App 侧生成),
所以只需把 App 发出的请求"借道"回来,响应这边完全可读。

protobuf 无官方 schema,本模块手写 varint walker 按字段号取数,
字段号由真实抓包对照 UI 验证(2026-10-21, com.autonavi.minimap 17.01.0.2012):

    顶层 field 2 (msg) = 方案集合容器
      └─ 7: repeated msg 方案详情(出现顺序 = UI 方案1/2/3)
          ├─ 1: varint  距离(厘米)
          ├─ 4: msg     费用 {1: 分, 5: 币种}
          ├─ 7: varint  历时(秒)
          └─ 10: repeated msg 路段 {5: msg {3: 道路名}}
"""
from __future__ import annotations

import gzip
from typing import Any, Iterator, List, Optional, Tuple, Union

from .models import NavRoute, NavStep

Value = Union[int, bytes]
Field = Tuple[int, Value]


def _read_varint(data: bytes, i: int) -> Tuple[int, int]:
    v = shift = 0
    while True:
        if i >= len(data):
            raise ValueError("varint 越界")
        b = data[i]
        i += 1
        v |= (b & 0x7F) << shift
        shift += 7
        if not b & 0x80:
            return v, i


def walk(data: bytes) -> Iterator[Field]:
    """无 schema 解析 protobuf 顶层字段(yield (字段号, 值))。

    只处理 varint 与 length-delimited 两种 wire type,
    其余(固定 32/64 位)跳过 —— 导航响应只用到这两种。
    """
    i = 0
    while i < len(data):
        try:
            key, i = _read_varint(data, i)
        except ValueError:
            return
        f, wire = key >> 3, key & 7
        if wire == 0:
            try:
                v, i = _read_varint(data, i)
            except ValueError:
                return
            yield f, v
        elif wire == 2:
            try:
                ln, i = _read_varint(data, i)
            except ValueError:
                return
            if i + ln > len(data):
                return
            yield f, data[i:i + ln]
            i += ln
        elif wire == 5:
            i += 4
        elif wire == 1:
            i += 8
        else:  # 3/4: 已废弃的 group,直接放弃剩余
            return


def _fields(data: bytes) -> List[Field]:
    return list(walk(data))


def _first(fields: List[Field], num: int) -> Optional[Value]:
    return next((v for f, v in fields if f == num), None)


def parse_route_plan(pb: bytes) -> List[NavRoute]:
    """protobuf 明文 → List[NavRoute](按方案出现顺序编号 1,2,3…)。"""
    routes: List[NavRoute] = []
    for f, v in walk(pb):
        if f != 2 or not isinstance(v, bytes):
            continue
        idx = 0
        for sf, sv in _fields(v):
            if sf != 7 or not isinstance(sv, bytes):
                continue
            idx += 1
            d = _fields(sv)
            dist_cm = _first(d, 1)
            dur_s = _first(d, 7)
            toll_fen = 0
            currency = "CNY"
            fee = _first(d, 4)
            if isinstance(fee, bytes):
                for ff, fv in _fields(fee):
                    if ff == 1 and isinstance(fv, int):
                        toll_fen = fv
                    elif ff == 5 and isinstance(fv, bytes):
                        currency = fv.decode("utf-8", "ignore")
            steps: List[NavStep] = []
            for tf, tv in d:
                if tf != 10 or not isinstance(tv, bytes):
                    continue
                road = ""
                name_msg = _first(_fields(tv), 5)
                if isinstance(name_msg, bytes):
                    name = _first(_fields(name_msg), 3)
                    if isinstance(name, bytes):
                        road = name.decode("utf-8", "ignore")
                steps.append(NavStep(road=road))
            if not isinstance(dist_cm, int) or not isinstance(dur_s, int):
                continue    # 不是方案详情(字段号复用的其他消息)
            routes.append(NavRoute(
                index=idx,
                distance_m=dist_cm / 100,
                duration_s=dur_s,
                toll_fen=toll_fen,
                currency=currency,
                steps=steps,
            ))
    return routes


def wire_to_pb(raw: bytes) -> bytes:
    """HTTP 响应体(gzip)→ protobuf 明文。

    层级: gzip → [64B 容器头 | zstd 流] → protobuf。
    容器头不是恒定 64 字节,按 zstd 魔数(28 b5 2f fd)定位。
    """
    inner = gzip.decompress(raw)
    pos = inner.find(b"\x28\xb5\x2f\xfd")
    if pos < 0:
        raise ValueError("容器里找不到 zstd 魔数,格式可能已变化")
    # mitmproxy 会原样保留响应体的 gzip,zstd 由本地解
    import zstandard  # pylint: disable=import-outside-toplevel
    return zstandard.ZstdDecompressor(max_window_size=1 << 28).stream_reader(
        inner[pos:]).read()


def parse_wire(raw: bytes) -> List[NavRoute]:
    """HTTP 响应体(gzip)→ protobuf → List[NavRoute](驾车路线)。"""
    return parse_route_plan(wire_to_pb(raw))


def parse_bus_wire(raw: bytes) -> List[Any]:
    """公交 new_integrate 响应 → List[BusPlan](UI 推荐方案列表)。

    结构(2026-10-21 对照 UI 验证):顶层 f2 为主容器,其内:
      f2 (repeated) = 推荐方案 {3: 票价元, 4: 历时秒, 8: 实时备注,
          10: 步行米, 14: 标签{1: 费用少/客车直达/火车直达/最快…}}
      f3 (repeated) = 方案明细 {3: 序号, 4: 票价, 6: 历时秒, 8: 步行米,
          13: repeated 换乘段{3: 上车站, 4: 下车站, 5: 途经站,
          12: 班距, 14: 线路名}}
    跨城查询时 f3 里只有起终点都与查询相符的才是完整方案,其余是
    客车/火车方案的接驳分段 —— 按"历时相同"把完整明细挂回推荐方案。
    数字被序列化成字符串('10237'),两种都收。
    """
    from .models import BusPlan  # pylint: disable=import-outside-toplevel
    plans: List[Any] = []
    for f, v in walk(wire_to_pb(raw)):
        if f != 2 or not isinstance(v, bytes):
            continue
        inner = _fields(v)
        recs = [sv for sf, sv in inner if sf == 2 and isinstance(sv, bytes)]
        dets = [sv for sf, sv in inner if sf == 3 and isinstance(sv, bytes)]
        if recs:
            # 推荐方案为主列表,完整明细按历时挂回去
            legs_by_dur: dict = {}
            for dv in dets:
                d = _fields(dv)
                dur = _to_int(_first(d, 6))
                if dur and dur not in legs_by_dur:
                    legs_by_dur[dur] = _bus_legs(d)
            for rv in recs:
                d = _fields(rv)
                dur = _to_int(_first(d, 4))
                if not dur:
                    continue
                tag = ""
                t14 = _first(d, 14)
                if isinstance(t14, bytes):
                    tag = _to_str(_first(_fields(t14), 1))
                plans.append(BusPlan(
                    duration_s=dur,
                    walk_m=_to_int(_first(d, 10)) or 0,
                    price=_to_float(_first(d, 3)),
                    tag=tag,
                    note=_to_str(_first(d, 8)),
                    legs=legs_by_dur.get(dur, [])))
        else:
            # 无推荐列表(如纯同城公交):f3 全部当方案
            for dv in dets:
                d = _fields(dv)
                dur = _to_int(_first(d, 6))
                if not dur:
                    continue
                plans.append(BusPlan(
                    duration_s=dur,
                    walk_m=_to_int(_first(d, 8)) or 0,
                    price=_to_float(_first(d, 4)),
                    legs=_bus_legs(d)))
    return plans


def _bus_legs(plan_fields: List[Field]) -> List[Any]:
    """从方案明细的 f13(repeated)提取换乘段列表。"""
    from .models import BusLeg  # pylint: disable=import-outside-toplevel
    legs: List[Any] = []
    for lf, lv in plan_fields:
        if lf != 13 or not isinstance(lv, bytes):
            continue
        seg = _fields(lv)
        frm = to_ = ""
        via = 0
        for xf, xv in seg:
            if not isinstance(xv, bytes):
                continue
            name = _to_str(_first(_fields(xv), 1)) or ""
            if xf == 3 and name:
                frm = name
            elif xf == 4 and name:
                to_ = name
            elif xf == 5 and name:
                via += 1
        legs.append(BusLeg(
            line=_dedupe_line(_to_str(_first(seg, 14))),
            from_station=frm, to_station=to_, via_count=via,
            headway=_to_str(_first(seg, 12))))
    return legs


def _dedupe_line(line: str) -> str:
    """服务端偶发把线路名尾部括号翻倍:'城际(a--b)(a--b)' → '城际(a--b)'。"""
    import re  # pylint: disable=import-outside-toplevel
    return re.sub(r"(\([^()]*\))\1$", r"\1", line)


def _to_int(v: Optional[Value]) -> Optional[int]:
    """高德把数字序列化成字符串('10237'),两种都收。"""
    if isinstance(v, int):
        return v
    if isinstance(v, bytes):
        try:
            return int(v.decode("ascii"))
        except ValueError:
            return None
    return None


def _to_float(v: Optional[Value]) -> Optional[float]:
    n = _to_int(v)
    if n is not None:
        return float(n)
    if isinstance(v, bytes):
        try:
            return float(v.decode("ascii"))
        except ValueError:
            return None
    return None


def _to_str(v: Optional[Value]) -> str:
    if isinstance(v, bytes):
        return v.decode("utf-8", "ignore")
    return ""


def parse_flows_payload(payload: Any) -> List[NavRoute]:
    """tests 替身注入用:直接吃 raw 响应字节。"""
    if not isinstance(payload, (bytes, bytearray)):
        raise TypeError(f"期望 bytes,得到 {type(payload).__name__}")
    return parse_wire(bytes(payload))
