#!/usr/bin/env python3
"""从 mitmproxy flows 文件里捞高德导航响应。

依赖链路(README 有完整说明):
  mitmdump -w <flows> 监听 0.0.0.0:8080
  + 模拟器 http_proxy 指向本机 8080
  + 模拟器 CA 区信任 mitmproxy CA
  + (关键)模拟器内 iptables 掐直连,否则高德 HTTPDNS 直连绕过代理
"""
from __future__ import annotations

import time
from typing import List, Tuple

NAV_HOST = "nvg.amap.com"
NAV_PATH = "/ws/transfer/navigation/auto/"


class CaptureError(Exception):
    """抓包链路异常的基类。"""


def read_nav_responses(flows_path: str, after_ts: float = 0.0
                       ) -> List[Tuple[float, bytes]]:
    """读 flows 文件,返回 (时间戳, 响应原始字节) 列表,只取 nvg 的 auto 端点。

    flows 文件被 mitmdump 追加写,流式读到文件尾即止,不锁文件。
    """
    try:
        from mitmproxy import io as mio  # pylint: disable=import-outside-toplevel
    except ImportError as e:
        raise CaptureError(
            "需要 mitmproxy 库读 flows(pip install mitmproxy)") from e
    out: List[Tuple[float, bytes]] = []
    try:
        with open(flows_path, "rb") as f:
            for fl in mio.FlowReader(f).stream():
                req = getattr(fl, "request", None)
                resp = getattr(fl, "response", None)
                if req is None or resp is None:
                    continue
                if req.pretty_host != NAV_HOST:
                    continue
                if not req.path.startswith(NAV_PATH):
                    continue
                if req.timestamp_start < after_ts:
                    continue
                out.append((req.timestamp_start, resp.raw_content or b""))
    except FileNotFoundError as e:
        raise CaptureError(f"flows 文件不存在: {flows_path} — mitmdump 在跑吗?") from e
    return out


def wait_for_response(flows_path: str, since_ts: float,
                      timeout: float = 90.0,
                      poll: float = 2.0) -> bytes:
    """轮询 flows,等第一条晚于 since_ts 的导航响应,返回响应字节。

    90s 上限:高德掐直连后偶发降级重试,首条路线可能要等一会儿。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        rows = read_nav_responses(flows_path, after_ts=since_ts)
        if rows:
            rows.sort()
            return rows[-1][1]
        time.sleep(poll)
    raise CaptureError(
        f"{timeout:.0f}s 内没等到 nvg 导航响应 — 检查: Deep Link 发出成功? "
        "模拟器代理/CA/iptables 链路在?(python -m amap check)")
