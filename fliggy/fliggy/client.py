#!/usr/bin/env python3
"""飞猪机票列表接口封装(阿里 mtop H5 网关,纯 HTTP,免登录)。

为什么能直连: h5api.m.taobao.com 是淘宝系 H5 的公共网关,
h5.m.taobao.com 机票页的 mtop JS 用的就是 appKey=12574478 +
MD5 三段式签名 —— `md5(token & t & appKey & data)`,token 取
cookie `_m_h5_tk` 前半段,匿名访问也会下发。首次空 token 请求被
FAIL_SYS_TOKEN_EMPTY 拒绝的同时 Set-Cookie 下发新 token,重签重试
即自愈,全程无需登录。必须带移动 Safari UA + h5.m.taobao.com 域的
Referer,否则触发 RGV587_ERROR(无线保镖拦截)。

传输边界豁免:`MtopTransport.fetch` 的返回值是服务端原始 JSON
(dict),这是唯一的 dict 使用点 —— 拿到后立即解析成 models 里的
pydantic 类型。
"""
from __future__ import annotations

import gzip
import hashlib
import http.cookiejar
import json
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Protocol

from .models import SearchResult

API = "mtop.trip.flight.listingsearch"
VERSION = "2.0"
APPKEY = "12574478"
JSV = "2.7.0"
BASE = "https://h5api.m.taobao.com"

UA_IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 "
             "Mobile/15E148 Safari/604.1")
REFERER = "https://h5.m.taobao.com/trip/flight/search/index.html"


class FliggyError(Exception):
    """飞猪库所有异常的基类。"""


class RateLimitedError(FliggyError):
    """RGV587: 无线保镖拦截(缺 Referer/UA 或触频控),冷却后再试。"""


class FetchTransport(Protocol):
    """FliggyClient 依赖的最小传输接口(测试注入替身用)。"""

    def fetch(self, api: str, version: str,
              data: Dict[str, Any]) -> Dict[str, Any]:
        ...


class MtopTransport:
    """mtop H5 网关传输:签名 + cookie 自动管理 + 空 token 自愈。

    CookieJar 存 `_m_h5_tk`(匿名设备 token),urllib opener 带上
    HTTPCookieProcessor 后 Set-Cookie 自动入 jar,无需手工解析。
    """

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self._jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._jar))

    def _token(self) -> str:
        for c in self._jar:
            if c.name == "_m_h5_tk" and c.value:
                return c.value.split("_")[0]
        return ""

    def fetch(self, api: str, version: str,
              data: Dict[str, Any]) -> Dict[str, Any]:
        """GET h5api.m.taobao.com/h5/<api>/<version>/?...,返回 data 部分。

        首次空 token 会拿到 FAIL_SYS_TOKEN_EMPTY + 新 cookie,
        自动重签重试一次。
        """
        data_str = json.dumps(data, separators=(",", ":"),
                              ensure_ascii=False)
        for attempt in (1, 2):
            t = str(int(time.time() * 1000))
            sign = hashlib.md5(
                f"{self._token()}&{t}&{APPKEY}&{data_str}".encode()
            ).hexdigest()
            query = urllib.parse.urlencode({
                "jsv": JSV, "appKey": APPKEY, "t": t, "sign": sign,
                "api": api, "v": version, "type": "originaljson",
                "dataType": "json", "data": data_str})
            req = urllib.request.Request(
                f"{BASE}/h5/{api}/{version}/?{query}",
                headers={"User-Agent": UA_IPHONE, "Referer": REFERER,
                         "Accept-Language": "zh-CN,zh;q=0.9"})
            with self._opener.open(req, timeout=self.timeout) as resp:
                raw = resp.read()
                if resp.headers.get("content-encoding") == "gzip":
                    raw = gzip.decompress(raw)
            body: Dict[str, Any] = json.loads(raw)
            ret = body.get("ret") or []
            if attempt == 1 and any("FAIL_SYS_TOKEN_EMPTY" in x
                                    for x in ret):
                continue          # cookie 已入 jar,重签自愈
            if any("RGV587" in x for x in ret):
                raise RateLimitedError(
                    f"RGV587 无线保镖拦截 ({api}) — 冷却后再试")
            if not any(x.startswith("SUCCESS") for x in ret):
                raise FliggyError(f"mtop {api} 失败: {'; '.join(ret)}")
            out: Dict[str, Any] = body.get("data") or {}
            return out
        raise FliggyError(f"mtop {api} 重试后仍失败")   # pragma: no cover


class FliggyClient:
    """飞猪机票查询客户端。用法:

        from fliggy import FliggyClient
        fg = FliggyClient()                      # 默认 MtopTransport
        r = fg.search("CAN", "PEK", "2026-12-26")       # 单程,含中转
        print(r.summary())
        for f in r.cheapest_n(5):
            print(f.flight_no, f.dep_time, f.arr_time, f.price)
    """

    def __init__(self, transport: Optional[FetchTransport] = None,
                 min_interval: float = 12.0):
        # 5 req/min 起步(一次查询一个请求);批量扫描请再加长
        self.transport: FetchTransport = transport or MtopTransport()
        self.min_interval = min_interval
        self._last = 0.0

    def _throttle(self) -> None:
        wait = self.min_interval - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()

    def search(self, dep: str, arr: str, date: str) -> SearchResult:
        """单程航班查询(国内免登录;价格为成人含税总价,元)。

        dep/arr 用三字码(如 CAN);date 为 YYYY-MM-DD。
        返回的 SearchResult 里直飞+中转都有,`r.direct()` 只看直飞。
        """
        dep, arr = dep.upper(), arr.upper()
        payload: Dict[str, Any] = {
            "searchMode": 0, "tripType": 1,
            "searchSegments": [{"depCityCode": dep, "arrCityCode": arr,
                                "depDate": date}]}
        self._throttle()
        data = self.transport.fetch(API, VERSION, payload)
        return SearchResult.parse(data, dep=dep, arr=arr, date=date)
