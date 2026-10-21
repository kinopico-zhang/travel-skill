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


def parse_wire(raw: bytes) -> List[NavRoute]:
    """HTTP 响应体(gzip)→ protobuf → List[NavRoute]。

    层级: gzip → [64B 容器头 | zstd 流] → protobuf。
    容器头不是恒定 64 字节,按 zstd 魔数(28 b5 2f fd)定位。
    """
    inner = gzip.decompress(raw)
    pos = inner.find(b"\x28\xb5\x2f\xfd")
    if pos < 0:
        raise ValueError("容器里找不到 zstd 魔数,格式可能已变化")
    # mitmproxy 会原样保留响应体的 gzip,zstd 由本地解
    import zstandard  # pylint: disable=import-outside-toplevel
    pb = zstandard.ZstdDecompressor(max_window_size=1 << 28).stream_reader(
        inner[pos:]).read()
    return parse_route_plan(pb)


def parse_flows_payload(payload: Any) -> List[NavRoute]:
    """tests 替身注入用:直接吃 raw 响应字节。"""
    if not isinstance(payload, (bytes, bytearray)):
        raise TypeError(f"期望 bytes,得到 {type(payload).__name__}")
    return parse_wire(bytes(payload))
