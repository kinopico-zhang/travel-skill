#!/usr/bin/env python3
"""携程机票/火车票接口封装(纯 HTTP 直连模式)。

为什么直连能过: 携程 WAF 的 432 是请求头组合识别(缺 App 网关头
x-ctx-*/x-trip-* 的"浏览器 UA"请求直接 432),不是 TLS 指纹 —— 同一
请求经 mitmproxy(python OpenSSL 栈)转发照样 432,补上 App 头后
urllib 裸连即 200。head 里 auth/cid 全零 + appid=99999999(携程
Android 网关公共 appid),查询接口不依赖登录态。

CDPProxy(模拟器浏览器页面代理)保留为可选传输,用于登录态维护
(ctrip scripts/ctrip_login.py)与直连失效时的后备通道。

传输边界豁免:`HttpProxy.fetch_json` / `CDPProxy.fetch_json` / `call`
的返回值是服务端原始 JSON / CDP 结果(dict),这是唯一的 dict 使用点
—— 各接口拿到后立即解析成 models 里的 pydantic 类型。
"""
from __future__ import annotations

import base64
import gzip
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Dict, List, Optional, Protocol

import websocket

from .cities import CITIES
from .models import (City, DailyPrice, IntlSearchResult, SearchResult,
                     TrainSearchResult)

CDP_HTTP = "http://127.0.0.1:9222"
LIST_API = "/restapi/soa2/14488/flightListSearchForH5"
INTL_LIST_API = "/restapi/soa2/14780/listSearchForH5"
CALENDAR_API = "/restapi/soa2/15380/bjjson/FlightIntlAndInlandLowestPriceSearch"
FUZZY_API = "/restapi/soa2/19691/airportFuzzySearch"
TRAIN_API = "/restapi/soa2/14666/json/GetBookingByStationV3"

# 国际列表页(浏览器 navigate 到此 URL,页面 JS 自行发完整指纹的
# listSearchForH5 请求 —— 直连构造的 body 缺 head 指纹会被 WAF 432)。
INTL_PAGE = ("https://m.ctrip.com/html5/flight/taro/interFirst?from=inner"
             "&tripType=ONE_WAY&dcode={dc}&dcityName={dcn}"
             "&acode={ac}&acityName={acn}"
             "&ddate={dd}&seat=5&adult=1&child=0&baby=0")

# tab 上必须停留的域(fetch 相对路径 + cookie 同源)
HOME = "https://m.ctrip.com/html5/flight/taro/home?from=outer"

# ---- App 网关伪装头(过 WAF 的关键;设备字段全零/公共值,无个人数据) ----
GW_QUERY = ("?__gw_appid=99999999&__gw_ver=896.006"
            "&__gw_os=Android&__gw_platform=APP")
UA_APP = ("Mozilla/5.0 (Linux; Android 12; CET-AL00 Build/V417IR; wv) "
          "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
          "Chrome/101.0.4951.61 Mobile Safari/537.36"
          "_CtripAPP_Android_8.96.6_eb64_Ctrip_CtripWireless_8.96.6"
          "_cDevice=CET-AL00_cSize=w540*h960__v=896.006_os=Android"
          "_osv=12_m=CET-AL00_brand=HUAWEI_vg=0_safeAreaTop=24"
          "_safeAreaB=0_cDensity=1.375")
APP_HEAD = {"appid": "99999999", "auth": "", "cid": "00000000000000000000",
            "ctok": "", "cver": "896.006", "extension": [], "lang": "01",
            "sauth": "", "sid": "8013", "syscode": "32"}


class CtripError(Exception):
    """携程库所有异常的基类。"""


class RateLimitedError(CtripError):
    """432: 列表接口被风控限流,冷却 10-30 分钟再试;新会话/换 IP 可立即恢复。"""


class FetchProxy(Protocol):
    """CtripClient 依赖的最小传输接口(测试注入替身用)。"""

    def fetch_json(self, path: str,
                   payload: Dict[str, Any]) -> Dict[str, Any]:
        ...


class HttpProxy:
    """纯 HTTP 直连传输:App 网关头 + urllib,零模拟器依赖。"""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        trace = str(uuid.uuid4())
        return {
            "user-agent": UA_APP,
            "content-type": "application/json;charset=utf-8",
            "accept-encoding": "gzip",
            "x-trip-syscode": "32",
            "x-trip-clientappid": "99999999",
            "x-ctx-group": "ctrip",
            "x-ctx-clientversion": "896.006",
            "x-ctx-locale": "zh-CN",
            "x-ctx-currency": "CNY",
            "x-ctx-region": "CN",
            "x-ctx-unit": "METRIC",
            "x-ctx-transactionid": str(uuid.uuid4()),
            "x-ctx-replaytraceid": trace,
            "trip-trace-id": trace,
            "x-traceid": ("99999999-00000000000000000000-"
                          f"{int(time.time())}-1"),
            "x-ctx-personal-recommend": "1",
            "x-ctx-personal-ads-recommend": "1",
            "x-ctx-privacyrestrictedmode": "0",
            "x-ctx-ubt-vid": "13D589E0CD2D11F1B6F75F09E62445CC",
            "x-ctx-ubt-pageid": "rn_flight_list_btm",
            "cookie": "_n_cid=00000000000000000000",
        }

    def fetch_json(self, path: str,
                   payload: Dict[str, Any]) -> Dict[str, Any]:
        """POST m.ctrip.com<path>,payload 自动补 App head;432 抛限流。"""
        body = json.dumps({**payload, "head": APP_HEAD},
                          ensure_ascii=False).encode()
        req = urllib.request.Request(
            f"https://m.ctrip.com{path}{GW_QUERY}", data=body,
            headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                gzipped = resp.headers.get("content-encoding") == "gzip"
        except urllib.error.HTTPError as e:
            if e.code == 432:
                raise RateLimitedError(
                    f"HTTP 432 风控限流 ({path.split('/')[-1]}) — 冷却后再试"
                ) from e
            raise CtripError(f"HTTP {e.code} ({path.split('/')[-1]})") from e
        if gzipped:
            raw = gzip.decompress(raw)
        data: Dict[str, Any] = json.loads(raw)
        return data


class CDPProxy:
    """管理到模拟器 WebView 的 CDP 连接,在页面上下文里执行 fetch。

    需要模拟器开着、浏览器停在 m.ctrip.com、adb forward tcp:9222。
    """

    def __init__(self, ws_timeout: int = 30):
        self.ws_timeout = ws_timeout
        self.ws: Optional[websocket.WebSocket] = None
        self._n = 0
        self.reconnect()

    def _targets(self) -> List[Dict[str, Any]]:
        with urllib.request.urlopen(f"{CDP_HTTP}/json", timeout=5) as r:
            raw = r.read()
        targets: List[Dict[str, Any]] = json.loads(raw)
        return targets

    def reconnect(self) -> None:
        pages = [t for t in self._targets() if t.get("type") == "page"]
        if not pages:
            raise CtripError("9222 上没有 page target — adb forward 配了吗?")
        # 优先停在 m.ctrip.com 的 tab
        t = next((p for p in pages if "ctrip.com" in p.get("url", "")), None)
        if t is None:
            t = pages[0]
            self._nav(t["webSocketDebuggerUrl"])
        self.ws = websocket.create_connection(t["webSocketDebuggerUrl"],
                                              timeout=self.ws_timeout)
        self._n = 0

    def _nav(self, ws_url: str) -> None:
        ws = websocket.create_connection(ws_url, timeout=15)
        try:
            ws.send(json.dumps({"id": 1, "method": "Page.navigate",
                                "params": {"url": HOME}}))
            time.sleep(6)
        finally:
            ws.close()

    def call(self, method: str,
             params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """调一个 CDP 方法,返回 result。"""
        self._n += 1
        assert self.ws is not None
        self.ws.send(json.dumps({"id": self._n, "method": method,
                                 "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self._n:
                if "error" in msg:
                    raise CtripError(f"{method}: {msg['error']}")
                result: Dict[str, Any] = msg.get("result", {})
                return result

    def eval(self, expr: str, await_promise: bool = True) -> Any:
        r = self.call("Runtime.evaluate", {
            "expression": expr, "returnByValue": True,
            "awaitPromise": await_promise, "userGesture": True})
        if "exceptionDetails" in r:
            d = r["exceptionDetails"]
            raise CtripError("JS error: " + str(
                d.get("exception", {}).get("description", d))[:300])
        return r.get("result", {}).get("value")

    def fetch_json(self, path: str,
                   payload: Dict[str, Any]) -> Dict[str, Any]:
        """在页面上下文 fetch,返回 dict;HTTP 非 200 时含 __http 键。"""
        return fetch_json_via(self, path, payload)


class IntlNavProxy(CDPProxy):
    """国际列表传输(navigate 驱动):跳到 interFirst 列表页,
    用 CDP Network 域抓页面自己发的 listSearchForH5 响应。

    页面 JS 构造的请求带完整 head 指纹(mystery/vid/sessionId),
    直连复刻不了(WAF 432),所以国际线只能走浏览器通道。
    需要模拟器浏览器停在 m.ctrip.com、adb forward tcp:9222。
    """

    def __init__(self, timeout: int = 45):
        super().__init__()
        self.nav_timeout = timeout

    def _wait_body(self, api_path: str) -> Dict[str, Any]:
        """等 Network 事件流里 api_path 响应完成,取 body 解析。"""
        assert self.ws is not None
        request_id: Optional[str] = None
        deadline = time.time() + self.nav_timeout
        while time.time() < deadline:
            try:
                msg = json.loads(self.ws.recv())
            except websocket.WebSocketTimeoutException as e:
                raise CtripError(f"等待 {api_path.split('/')[-1]} 超时") from e
            if msg.get("id"):          # 旧 call 的响应,忽略
                continue
            m, params = msg.get("method", ""), msg.get("params", {})
            if m == "Network.responseReceived" and api_path in params.get(
                    "response", {}).get("url", ""):
                request_id = params["requestId"]
            elif (m == "Network.loadingFinished" and request_id
                    and params.get("requestId") == request_id):
                body = self.call("Network.getResponseBody",
                                 {"requestId": request_id})
                raw = body.get("body") or ""
                if body.get("base64Encoded"):
                    raw = base64.b64decode(raw).decode("utf-8", "replace")
                data: Dict[str, Any] = json.loads(raw)
                return data
        raise CtripError(f"navigate 后未捕获 {api_path.split('/')[-1]} "
                         f"({self.nav_timeout}s)")

    def fetch_json(self, path: str,
                   payload: Dict[str, Any]) -> Dict[str, Any]:
        """跳列表页抓响应。payload 只用 segs[0](dcode/acode/ddate)。"""
        seg = (payload.get("segs") or [{}])[0]
        names = payload.get("__names") or {}
        url = INTL_PAGE.format(
            dc=seg.get("dcode", ""), dcn=urllib.parse.quote(names.get("dc", "")),
            ac=seg.get("acode", ""), acn=urllib.parse.quote(names.get("ac", "")),
            dd=seg.get("ddate", ""))
        self.call("Network.enable", {})
        self.call("Page.navigate", {"url": url})
        return self._wait_body(path)


class EvalProxy(Protocol):
    """fetch_json_via 依赖的最小接口:eval + 重连(CDPProxy 实现,测试可替)。"""

    def eval(self, expr: str, await_promise: bool = True) -> Any:
        ...

    def reconnect(self) -> None:
        ...


def fetch_json_via(proxy: EvalProxy, path: str,
                   payload: Dict[str, Any]) -> Dict[str, Any]:
    """在页面上下文 fetch,返回 dict;HTTP 非 200 时含 __http 键。"""
    body = json.dumps(payload, ensure_ascii=False)
    js = (
        "(async () => {"
        "const cid = (document.cookie.match(/GUID=([^;]+)/) || [])[1] || '';"
        "if (!location.host.includes('ctrip.com')) return JSON.stringify("
        "{__err: '页面不在 ctrip 域: ' + location.host});"
        f"const rsp = await fetch({json.dumps(path)}, {{"
        "method: 'POST', headers: {'content-type': 'application/json'},"
        f"credentials: 'include', body: JSON.stringify({{...{body}, head: "
        "{cid, ctok: '', cver: '9999', lang: '01', sid: '8888', syscode: '09',"
        " auth: '', xsid: '', extension: []}})});"
        "const status = rsp.status;"
        "if (status !== 200) return JSON.stringify({__http: status});"
        "return JSON.stringify(JSON.parse(await rsp.text()));"
        "})()"
    )
    out = None
    for attempt in (1, 2):
        try:
            out = proxy.eval(js)
            break
        except (CtripError, websocket.WebSocketException,
                TimeoutError, ConnectionError):
            if attempt == 2:
                raise
            time.sleep(1)
            proxy.reconnect()
    if not isinstance(out, str):
        raise CtripError(f"fetch 返回非字符串: {str(out)[:100]}")
    data: Dict[str, Any] = json.loads(out)
    if "__err" in data:
        raise CtripError(data["__err"])
    if data.get("__http"):
        code = data["__http"]
        if code == 432:
            raise RateLimitedError(
                f"HTTP 432 风控限流 ({path.split('/')[-1]}) — 冷却后再试")
        raise CtripError(f"HTTP {code} ({path.split('/')[-1]})")
    return data


def _city_from_cache(code: str, v: Any) -> City:
    """缓存条目 → City。新格式 {name,id};旧格式 [name,id] 仍兼容。"""
    if isinstance(v, dict):
        return City(code=code, name=str(v.get("name", "")),
                    id=str(v.get("id", "")))
    name, cid = v
    return City(code=code, name=str(name), id=str(cid))


class CtripClient:
    """携程机票查询客户端。用法:

        from ctrip import CtripClient
        ct = CtripClient()                      # 默认 HttpProxy,零模拟器
        r = ct.search("SZX", "HAK", "2026-10-25")      # 单程经济舱
        for f in r:
            print(f.flight_no, f.dep_time, f.cheapest.price)
        cal = ct.low_price_calendar("SZX", "HAK")       # List[DailyPrice]
    """

    def __init__(self, proxy: Optional[FetchProxy] = None,
                 min_interval: float = 2.5,
                 city_cache: str = "~/.ctrip_cities.json"):
        self.proxy: FetchProxy = proxy or HttpProxy()
        self.min_interval = min_interval
        self._last = 0.0
        self._city_cache_path = city_cache
        self._city_cache: Optional[Dict[str, Any]] = None

    def _throttle(self) -> None:
        wait = self.min_interval - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()

    # ---------- 城市 ----------

    def _load_cache(self) -> Dict[str, Any]:
        if self._city_cache is None:
            path = os.path.expanduser(self._city_cache_path)
            try:
                with open(path, encoding="utf-8") as f:
                    self._city_cache = json.load(f)
            except (OSError, ValueError):
                self._city_cache = {}
        return self._city_cache

    def city(self, code: str) -> City:
        """三字码 → City。内置表 → 缓存 → fuzzySearch 动态查。"""
        code = code.upper()
        if code in CITIES:
            return CITIES[code]
        cache = self._load_cache()
        if code in cache:
            return _city_from_cache(code, cache[code])
        self._throttle()
        r = self.proxy.fetch_json(FUZZY_API, {
            "data": json.dumps({"key": code}, ensure_ascii=False)})
        items = json.loads(r["data"])
        city = next((x for x in items
                     if x.get("poiType") == "CITY"
                     and x.get("cityCode") == code), None)
        if not city:
            raise CtripError(f"城市代码 {code} 查不到(机场码请用城市码,如 PEK→BJS)")
        result = City(code=code, name=city["cityName"], id=str(city["cityId"]))
        cache[code] = {"name": result.name, "id": result.id}
        with open(os.path.expanduser(self._city_cache_path), "w",
                  encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=1)
        return result

    # ---------- 查询 ----------

    def search(self, org: str, dst: str, date: str,
               cabin: str = "Y") -> SearchResult:  # pylint: disable=unused-argument
        """单程航班查询。cabin: Y=经济(唯一稳定可用的档)。返回 SearchResult。"""
        org_city, dst_city = self.city(org), self.city(dst)
        payload: Dict[str, Any] = {
            "searchitem": [{"dccode": org_city.code, "dcid": org_city.id,
                            "accode": dst_city.code, "acid": dst_city.id,
                            "dtime": date, "segno": 1, "flag": 0,
                            "extend": "", "sgrade": 0}],
            "seat": 0, "trptpe": 1, "segno": 1, "flag": 0, "itflg": 37748736,
            "idlst": [{"idtype": 29, "id": "T"}, {"idtype": 2, "ID": ""}],
        }
        self._throttle()
        data = self.proxy.fetch_json(LIST_API, payload)
        return SearchResult.parse(data, org=org_city.code, dst=dst_city.code,
                                  date=date)

    def low_price_calendar(self, org: str, dst: str,
                           start_date: Optional[str] = None) -> List[DailyPrice]:
        """低价日历(默认今天起 377 天),按日期升序。

        price=票面(国际线不含税);total=含税总价(totalPrice),比价用这个。
        """
        org_city, dst_city = self.city(org), self.city(dst)
        if start_date is None:
            start_date = time.strftime("%Y-%m-%d")
        payload: Dict[str, Any] = {
            "searchType": 1,
            "departNewCityCode": org_city.code,
            "arriveNewCityCode": dst_city.code,
            "passengerList": [{"passengerCount": 1, "passengerType": "Adult"}],
            "grade": 1,
            "calendarSelections": [{"selectionType": 8, "selectionContent": ["1"]}],
            "startDate": start_date, "flag": 0,
            "channelName": "MobileH5", "lowPriceExtendInfo": [],
        }
        self._throttle()
        data = self.proxy.fetch_json(CALENDAR_API, payload)
        out: List[DailyPrice] = []
        for p in data.get("priceList") or []:
            m = re.search(r"/Date\((\d+)", p.get("departDate", ""))
            if m:
                ts = int(m.group(1)) / 1000 + 8 * 3600
                d = time.strftime("%Y-%m-%d", time.gmtime(ts))
                out.append(DailyPrice(date=d, price=p.get("price"),
                                      total=p.get("totalPrice")))
        return sorted(out, key=lambda x: x.date)

    # ---------- 国际线 ----------

    def search_intl(self, org: str, dst: str, date: str,
                    proxy: Optional["IntlNavProxy"] = None) -> IntlSearchResult:
        """国际/中国港澳台 单程经济舱(14780)。

        默认走 IntlNavProxy(模拟器浏览器 navigate 通道,免登录);
        页面自己的请求带完整指纹,直连构造会被 WAF 432。
        """
        org_city, dst_city = self.city(org), self.city(dst)
        if proxy is None:
            proxy = IntlNavProxy()
        payload: Dict[str, Any] = {
            "segs": [{"dcode": org_city.code, "acode": dst_city.code,
                      "ddate": date}],
            "tripType": 1,
            "psglst": [{"psgtype": 1, "psgcnt": 1},
                       {"psgtype": 2, "psgcnt": 0},
                       {"psgtype": 3, "psgcnt": 0}],
            "segno": 1, "grade": 4,
            "sortinfo": {"idx": 1, "size": 0, "ordby": 105,
                         "meyordby": 2, "dir": 2},
            "polid": "", "prdid": "",
            # IntlNavProxy 额外要的中文名(仅 URL 展示用)
            "__names": {"dc": org_city.name, "ac": dst_city.name},
        }
        self._throttle()
        data = proxy.fetch_json(INTL_LIST_API, payload)
        ack = (data.get("ResponseStatus") or {}).get("Ack")
        if ack == "Failure":
            errs = (data.get("ResponseStatus") or {}).get("Errors") or [{}]
            raise CtripError(f"国际列表查询失败: "
                             f"{errs[0].get('ErrorCode')} "
                             f"{errs[0].get('Message', '')[:80]}")
        return IntlSearchResult.parse(data, org=org_city.code,
                                      dst=dst_city.code, date=date)

    # ---------- 火车票 ----------

    def train_search(self, depart: str, arrive: str, date: str,
                     student: bool = False) -> TrainSearchResult:
        """火车票车次查询(免登录)。

        depart/arrive 用中文城市名或站名均可(如 "上海" / "上海虹桥"),
        服务端按城市级搜索。无此线路/无票时返回空结果(Ack=Success + 0 班),
        不抛错 —— 用 `if not r:` 判空。
        """
        payload: Dict[str, Any] = {
            "contentType": "json", "channel": "H5",
            "DepartStation": depart, "ArriveStation": arrive,
            "DepartDate": date, "Student": student,
            "ChannelName": "ctrip.h5", "c_sec": True,
        }
        self._throttle()
        data = self.proxy.fetch_json(TRAIN_API, payload)
        return TrainSearchResult.parse(data)
