# ctrip API 文档

> 携程 H5（m.ctrip.com）机票/火车票查询 python 库——国内航班列表、低价日历、火车票、城市码为**纯 HTTP 直连**（零模拟器、免登录），国际/中国港澳台单程列表走**模拟器浏览器 navigate 通道**。版本 1.1.0。

本文是 API 参考，与 `README.md` 互补：README 讲「为什么直连能过」「国际线指纹原理」「风控要点」等背景，本文逐项给出签名、参数、返回结构与行为细节。行为细节以源码与 `tests/`（46 个用例，传输层全部替身，不触网）为准。

## 模块总览

| 模块 | 职责 |
|---|---|
| `ctrip/__init__.py` | 导出公开符号：客户端、三个传输实现、两个异常、全部数据模型与 `HOME` |
| `ctrip/client.py` | `CtripClient`、传输层（`HttpProxy`/`CDPProxy`/`IntlNavProxy` 与两个 Protocol）、异常、端点常量 |
| `ctrip/models.py` | 响应解析的 pydantic 数据模型（`parse` 类方法 + 便捷属性/辅助方法） |
| `ctrip/cities.py` | 内置城市三字码表 `CITIES` |
| `ctrip/__main__.py` | CLI：`python -m ctrip cookies / train / intl` |
| `scripts/` | 登录驱动 `ctrip_login.py`、CDP 小工具 `cdp.py`（独立脚本，不属于库 API） |

## 前置条件与依赖

依赖（`pyproject.toml`）：Python ≥ 3.9；`pydantic>=2`（直连必需）；`websocket-client`（仅 CDP 通道需要）。仓库已 editable 安装到 `~/.venv/bin/python`。

三条链路的前置条件分开看：

| 链路 | 覆盖功能 | 前置条件 |
|---|---|---|
| 国内直连（`HttpProxy`，默认） | `search`、`low_price_calendar`、`train_search`、`city` | 无：零模拟器、免登录，只要本机能访问 `https://m.ctrip.com` |
| 国际线（`IntlNavProxy`） | `search_intl` | MuMu 模拟器开着、浏览器标签存在（最好停在 m.ctrip.com）、`adb forward tcp:9222 localabstract:chrome_devtools_remote`；免登录 |
| CDP 通道（`CDPProxy`，后备） | `CtripClient(proxy=CDPProxy())`、`python -m ctrip cookies` | 同国际线（同一 9222 CDP 端点） |

查询本身全部免登录；会员价相关字段才需要登录态（cticket，90 天，维护方式见 README「会话」）。

## 快速上手

```python
from ctrip import CtripClient

ct = CtripClient()                     # 默认 HttpProxy 直连，零模拟器、免登录

ORG, DST = "…", "…"                    # 出发/到达三字城市码（城市码≠机场码，见「城市码」节）

r = ct.search(ORG, DST, "2026-10-27")  # 国内单程经济舱
print(r.summary())
for f in r.sorted_by_price()[:5]:
    print(f.flight_no, f.dep_time, f.cheapest.price)

cal = ct.low_price_calendar(ORG, DST)  # 低价日历：List[DailyPrice]，按日期升序
print(cal[0].date, cal[0].total)
```

国际/中国港澳台列表要另开模拟器（前置条件见上表），其余查询开箱即用：

```python
r = ct.search_intl(ORG, DST, "2027-05-01")   # 需模拟器浏览器 + adb forward tcp:9222
print(r.summary())                           # 先按中转数、再按含税总价排序
```

## 客户端

### `CtripClient`

携程机票/火车票查询客户端，持有传输层与请求节流。所有查询方法免登录，发请求前统一先过 `_throttle()`（距上次请求不足 `min_interval` 秒则等待，`city` 的模糊查询同样吃节流）。

构造签名（与源码一致）：

```python
CtripClient(proxy: Optional[FetchProxy] = None,
            min_interval: float = 2.5,
            city_cache: str = "~/.ctrip_cities.json")
```

| 参数 | 类型 / 默认 | 说明 |
|---|---|---|
| `proxy` | `Optional[FetchProxy] = None` | 传输实现；`None` 时用 `HttpProxy()`（直连）。换通道/测试时注入 `CDPProxy()` 等满足 `FetchProxy` 协议的对象 |
| `min_interval` | `float = 2.5` | 同一实例两次请求的最小间隔（秒）。列表接口高频会触发 432，批量扫描请再加长 |
| `city_cache` | `str = "~/.ctrip_cities.json"` | 动态城市查询的落盘缓存路径（`~` 会经 `os.path.expanduser` 展开） |

#### `search`

```python
def search(self, org: str, dst: str, date: str,
           cabin: str = "Y") -> SearchResult:
```

| 参数 | 类型 / 默认 | 说明 |
|---|---|---|
| `org` | `str` | 出发三字城市码（大小写不敏感，内部转大写） |
| `dst` | `str` | 到达三字城市码 |
| `date` | `str` | 出发日期，`YYYY-MM-DD` |
| `cabin` | `str = "Y"` | 舱位档；当前仅 `"Y"`（经济舱）稳定可用，且该参数**未进入请求体**（占位，档位由 payload `seat=0` 决定） |

- 返回值：`SearchResult`——可迭代出 `Flight`，带 `summary()` / `sorted_by_price()` / `direct()` / `cheapest_n()` 等（见「数据模型」）。请求端点 `LIST_API`（`soa2/14488/flightListSearchForH5`），payload `trptpe=1`（单程）、`seat=0`（经济舱）。
- 异常：未知城市码 → `CtripError`；HTTP 432 → `RateLimitedError`；其他 HTTP 非 200 → `CtripError`。
- 示例：

```python
r = ct.search(ORG, DST, "2026-10-27")
for f in r.sorted_by_price()[:5]:
    print(f.flight_no, f.dep_time, f.arr_time, f.price, f.cheapest.quantity)
```

- 备注：
  - 只封装了单程经济舱；往返/公务舱参数（`seat`/`sgrade=1`）已摸清但未验证稳定性。
  - 列表响应尾部可能混入「邻近城市/日期推荐」条目（`flight_no` 为空但有真实报价，如邻近机场出发的替代方案），国内解析**不自动丢弃**，业务上按需自行过滤 `f.flight_no`；`summary()` 里这类条目显示为 `(组合产品)`。
  - 432 与节流：见「异常体系」与 `min_interval` 参数说明。

#### `search_intl`

```python
def search_intl(self, org: str, dst: str, date: str,
                proxy: Optional["IntlNavProxy"] = None) -> IntlSearchResult:
```

| 参数 | 类型 / 默认 | 说明 |
|---|---|---|
| `org` | `str` | 出发三字城市码 |
| `dst` | `str` | 到达三字城市码 |
| `date` | `str` | 出发日期，`YYYY-MM-DD` |
| `proxy` | `Optional["IntlNavProxy"] = None` | 国际线传输；`None` 时自动构造 `IntlNavProxy()`（需要模拟器）。测试可注入满足 `fetch_json` 协议的替身 |

- 返回值：`IntlSearchResult`——可迭代出 `IntlFlight`；解析时**自动丢弃**无航段的条目。端点 `INTL_LIST_API`（`soa2/14780/listSearchForH5`），payload `grade=4`（该接口的经济舱档）、单程、成人 1 人；单页返回全部方案（实测 55 方案一次给全），翻页接口 `listSearchNextForH5` 未封装。
- 异常：响应 `ResponseStatus.Ack == "Failure"` → `CtripError("国际列表查询失败: {ErrorCode} {Message前80字符}")`；9222 无 page target → `CtripError`；等待列表响应超时 → `CtripError`。
- 示例：

```python
r = ct.search_intl(ORG, DST, "2027-05-01")
print(r.summary(top=10))
for f in r.direct():
    print(f.flight_no, f.dep_time, f.arr_time, f.total)
```

- 备注：原理一句话——该接口 body 的 head 带服务端校验的指纹（mystery/vid/sessionId），离线复刻或原样重放都会被 WAF 432，所以由 `IntlNavProxy` navigate 到国际列表页、让页面 JS 自己发请求、CDP 抓回响应（见「传输层」）。免登录。价格口径：`IntlFlight.total` = 成人含税总价（票面+税+燃油），可直接比价，与 `DailyPrice.total` 同口径。

#### `low_price_calendar`

```python
def low_price_calendar(self, org: str, dst: str,
                       start_date: Optional[str] = None) -> List[DailyPrice]:
```

| 参数 | 类型 / 默认 | 说明 |
|---|---|---|
| `org` | `str` | 出发三字城市码 |
| `dst` | `str` | 到达三字城市码 |
| `start_date` | `Optional[str] = None` | 起始日期 `YYYY-MM-DD`；`None` 取今天（`time.strftime("%Y-%m-%d")`） |

- 返回值：`List[DailyPrice]`，按日期升序；默认今天起约 377 天。端点 `CALENDAR_API`（`soa2/15380/bjjson/FlightIntlAndInlandLowestPriceSearch`），1 成人。
- 异常：同直连传输层（`CtripError` / `RateLimitedError`）；日历接口风控宽松，可放心批量。
- 示例：

```python
cal = ct.low_price_calendar(ORG, DST)
best = min(cal, key=lambda p: p.total or 0)
print(best.date, best.total)
```

- 备注：响应 `departDate` 是 `/Date(毫秒+0800)/` 格式，按东八区换算成日期；解析不出日期的条目直接丢弃（不崩）。价格口径：`price` = 票面（国际线不含税）；`total` = 响应 `totalPrice` 含税总价（国内外统一口径），**比价用 `total`**。

#### `train_search`

```python
def train_search(self, depart: str, arrive: str, date: str,
                 student: bool = False) -> TrainSearchResult:
```

| 参数 | 类型 / 默认 | 说明 |
|---|---|---|
| `depart` | `str` | 出发中文城市名或站名（服务端按城市级搜索，两者均可） |
| `arrive` | `str` | 到达城市名或站名 |
| `date` | `str` | 日期，`YYYY-MM-DD` |
| `student` | `bool = False` | 学生票 |

- 返回值：`TrainSearchResult`——可迭代出 `Train`。端点 `TRAIN_API`（`soa2/14666/json/GetBookingByStationV3`），免登录。
- 异常：只有传输层异常（`CtripError` / `RateLimitedError`）。**无此线路/无票不抛错**——服务端返回 `Ack=Success` + 0 班，得到空结果，用 `if not r:` 判空。
- 示例：

```python
tr = ct.train_search("出发城市", "到达城市", "2026-10-22")
print(len(tr), "班，可订", len(tr.bookable()))
for t in list(tr)[:3]:
    print(t.train_number, t.depart_time, "-", t.arrive_time, t.duration, t.cheapest)
```

- 备注：`depart`/`arrive` 原样传给服务端，不要传三字码。空结果的 `arrive_code` 等键可能缺失（解析为空串）。

#### `city`

```python
def city(self, code: str) -> City:
```

| 参数 | 类型 / 默认 | 说明 |
|---|---|---|
| `code` | `str` | 三字**城市码**（内部 `upper()`，大小写不敏感） |

- 返回值：`City`。查找顺序：内置表 `CITIES` → `~/.ctrip_cities.json` 缓存（新旧两种格式均兼容）→ `airportFuzzySearch`（`soa2/19691`）动态查，命中后写回缓存。
- 异常：fuzzySearch 无 CITY 级命中 → `CtripError("城市代码 PEK 查不到(机场码请用城市码,如 PEK→BJS)")`——把机场码当城市码传时会收到这个可懂的报错。
- 示例：

```python
c = ct.city("BJS")     # City(code="BJS", name="北京", id="1")
print(c.name, c.id)
```

- 备注：城市码≠机场码（BJS 非 PEK，详见「城市码」节）；动态查询也走 `_throttle()`，不会绕过节流。

## 传输层

三个实现都在 `ctrip/client.py`。约定：`fetch_json(path, payload) -> dict` 的返回值是服务端原始 JSON（dict），这是全库**唯一**允许 dict 存在的传输边界，各接口拿到后立即 parse 成 `models` 类型。

端点常量（`ctrip.client` 模块级，公开）：

| 常量 | 值 | 用途 |
|---|---|---|
| `LIST_API` | `/restapi/soa2/14488/flightListSearchForH5` | 国内航班列表 |
| `INTL_LIST_API` | `/restapi/soa2/14780/listSearchForH5` | 国际/港澳台航班列表 |
| `CALENDAR_API` | `/restapi/soa2/15380/bjjson/FlightIntlAndInlandLowestPriceSearch` | 低价日历 |
| `FUZZY_API` | `/restapi/soa2/19691/airportFuzzySearch` | 城市/机场模糊查询 |
| `TRAIN_API` | `/restapi/soa2/14666/json/GetBookingByStationV3` | 火车票车次 |
| `HOME` | `https://m.ctrip.com/html5/flight/taro/home?from=outer` | CDP tab 的驻留页（`__init__.py` 有导出） |

另有 `INTL_PAGE`（国际列表页 URL 模板，`IntlNavProxy` navigate 用）、`GW_QUERY` / `UA_APP` / `APP_HEAD`（App 网关伪装三件套，见下）。

### `HttpProxy`（默认）

纯 HTTP 直连传输：App 网关头 + `urllib`，零模拟器依赖。

```python
HttpProxy(timeout: int = 30)
```

| 参数 | 类型 / 默认 | 说明 |
|---|---|---|
| `timeout` | `int = 30` | `urlopen` 超时秒数 |

`fetch_json(path: str, payload: Dict[str, Any]) -> Dict[str, Any]` 的行为：

1. `POST https://m.ctrip.com{path}{GW_QUERY}`（`GW_QUERY` 含 `__gw_appid=99999999`、`__gw_ver`、`__gw_os=Android`、`__gw_platform=APP`；`99999999` 是携程 Android 网关公共 appid）。
2. body 为 `payload + 自动补的 App head`（`APP_HEAD`：`appid=99999999`、`auth`/`cid` 全零等公共值，无个人数据）。
3. 请求头是过 WAF 的关键：`_CtripAPP` 后缀 UA + `x-ctx-*`（group/clientversion/locale/currency/region/unit/transactionid/replaytraceid/ubt-*/personal-* 等）+ `x-trip-*`（syscode/clientappid）+ `x-traceid`/`trip-trace-id` + `cookie: _n_cid=…`（全零公共值）。机制是**请求头组合识别**，不是 TLS 指纹——详见 README「为什么直连能过」。
4. 响应 gzip 自动解压，返回解析后的 JSON dict。
5. HTTP 432 → `RateLimitedError("HTTP 432 风控限流 ({接口名}) — 冷却后再试")`；其他非 200 → `CtripError("HTTP {code} ({接口名})")`。

### `CDPProxy`（后备）

管理到模拟器 WebView 的 CDP 连接，在页面上下文里执行 `fetch`。前置条件：模拟器开着、浏览器有标签页、`adb forward tcp:9222 localabstract:chrome_devtools_remote`。

```python
CDPProxy(ws_timeout: int = 30)
```

| 参数 | 类型 / 默认 | 说明 |
|---|---|---|
| `ws_timeout` | `int = 30` | websocket 超时秒数 |

构造即调用 `reconnect()` 连上 9222。方法：

| 方法 | 签名 | 行为 |
|---|---|---|
| `reconnect` | `reconnect() -> None` | 拉 `http://127.0.0.1:9222/json`（`CDP_HTTP`）取 `type=page` 的 target；优先挑 url 含 `ctrip.com` 的标签，没有则把第一个 page navigate 到 `HOME` 并等 6 秒；然后建立 websocket。无 page target → `CtripError("9222 上没有 page target — adb forward 配了吗?")` |
| `call` | `call(method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]` | 发一条 CDP 命令，阻塞等同 id 响应并返回 `result`；CDP 返回 `error` → `CtripError` |
| `eval` | `eval(expr: str, await_promise: bool = True) -> Any` | `Runtime.evaluate`（`returnByValue`/`awaitPromise`/`userGesture`）；页面 JS 异常 → `CtripError("JS error: …")` |
| `fetch_json` | `fetch_json(path: str, payload: Dict[str, Any]) -> Dict[str, Any]` | 委托模块级 `fetch_json_via(self, path, payload)`，见下 |

模块级函数 `fetch_json_via(proxy: EvalProxy, path: str, payload: Dict[str, Any]) -> Dict[str, Any]`（`CDPProxy.fetch_json` 的实现体，也供测试直接驱动）：

- 在页面上下文注入 async `fetch`：`head` 由 JS 现拼（`cid` 取 cookie 里的 `GUID`），`credentials: 'include'`；页面不在 ctrip 域 → 返回 `{"__err": …}` → `CtripError`。
- HTTP 非 200 → `{"__http": code}`；432 → `RateLimitedError`，其余 → `CtripError("HTTP {code} ({接口名})")`。
- `eval` 抛连接类异常（`CtripError`、`websocket.WebSocketException`、`TimeoutError`、`ConnectionError`）时，等 1 秒、`reconnect()` 后**重试一次**，再失败才抛出。

已知坑：标签必须停在 ctrip 域（否则 `__err`）；重连会丢页面上下文；无 ctrip 标签时的兜底导航要等约 6 秒。

### `IntlNavProxy`（继承 `CDPProxy`，国际线专用）

国际列表传输（navigate 驱动）：跳到国际列表页，用 CDP Network 域抓页面自己发的 `listSearchForH5` 响应。页面 JS 构造的请求带完整 head 指纹（mystery/vid/sessionId），直连复刻不了（WAF 432，原样重放也有重放检测），所以国际线只能走浏览器通道。前置条件与 `CDPProxy` 相同。

```python
IntlNavProxy(timeout: int = 45)
```

| 参数 | 类型 / 默认 | 说明 |
|---|---|---|
| `timeout` | `int = 45` | navigate 后等待列表响应的最长秒数（存为 `self.nav_timeout`）；`ws_timeout` 沿用父类默认 30 |

`fetch_json(path, payload) -> Dict[str, Any]` 的驱动流程：

1. 从 payload 取 `segs[0]` 的 `dcode`/`acode`/`ddate`，以及 `__names` 里的 `dc`/`ac`（出发/到达城市**中文名**，仅用于拼列表页 URL 展示）。
2. `Network.enable` → `Page.navigate` 到 `INTL_PAGE`（`m.ctrip.com/html5/flight/taro/interFirst?from=inner&tripType=ONE_WAY&dcode=…&dcityName=…&acode=…&acityName=…&ddate=…&seat=5&adult=1&child=0&baby=0`）。
3. `_wait_body`：在 Network 事件流里等该接口的 `responseReceived` + `loadingFinished`（跳过旧 `call` 的响应），再 `Network.getResponseBody` 取响应体（`base64Encoded` 时先解码），`json.loads` 返回。
4. `nav_timeout` 内没等到 → `CtripError("navigate 后未捕获 listSearchForH5 (45s)")`；socket 读超时 → `CtripError("等待 listSearchForH5 超时")`。

`reconnect` / `call` / `eval` 直接继承 `CDPProxy`。

### `FetchProxy` / `EvalProxy`（Protocol：测试注入接口）

两个 `typing.Protocol`，是结构化接口——替身对象**无需继承**，实现同名方法即可注入：

| Protocol | 方法 | 消费方 |
|---|---|---|
| `FetchProxy` | `fetch_json(path: str, payload: Dict[str, Any]) -> Dict[str, Any]` | `CtripClient`（`proxy` 参数的最小要求） |
| `EvalProxy` | `eval(expr: str, await_promise: bool = True) -> Any` + `reconnect() -> None` | `fetch_json_via`（`CDPProxy` 天然满足） |

### 传输层选型

| 场景 | 用哪个 |
|---|---|
| 默认 / 国内查询（`search`、`low_price_calendar`、`train_search`、`city`） | `HttpProxy`（`CtripClient` 缺省，零模拟器） |
| 直连被 432 长期限流，或要读登录态 cookie（`cticket` 是 HttpOnly，只能走 CDP） | `CDPProxy`（`CtripClient(proxy=CDPProxy())`） |
| 国际/中国港澳台列表 | `IntlNavProxy`（`search_intl` 缺省自建，无需手动传） |
| 测试 | 实现 `FetchProxy` / `EvalProxy` 协议的替身对象 |

## 数据模型（models.py）

全部为 pydantic v2 模型。约定：

- 每个模型提供 `parse` 类方法把服务端原始 dict 解析成模型；原始 JSON 只允许停留在 `fetch_json` 返回值（传输边界），进入业务层即为本模块类型。
- **可迭代语义**：`SearchResult` / `TrainSearchResult` / `IntlSearchResult` 都**必须显式覆盖 `__iter__`**——pydantic `BaseModel` 自带的 `__iter__` 迭代的是 `(字段名, 值)` 字段对，与「迭代航班/车次」的业务语义冲突。所以 `for f in result` 得到的是模型对象，不是字段对。
- 无航段/组合类条目：国内 `SearchResult` 原样保留（`flight_no` 为空），国际 `IntlSearchResult` 解析时自动丢弃。

### 国内航班

#### `Segment`

一个航段（直达航班 = 1 个航段）。

| 字段 | 类型 | 说明 |
|---|---|---|
| `flight_no` | `str` | 航班号 |
| `carrier` | `str` | 营销承运航司二字码 |
| `actual_carrier` | `str` | 实际承运航司；非共享时 = `carrier` |
| `actual_flight_no` | `str` | 实际承运航班号；非共享时 = `flight_no` |
| `is_shared` | `bool` | 是否共享航班 |
| `dep_city` / `arr_city` | `str` | 出发/到达城市名 |
| `dep_airport` / `arr_airport` | `str` | 出发/到达机场三字码 |
| `dep_terminal` / `arr_terminal` | `str` | 航站楼（如 `T3`） |
| `dep_time` / `arr_time` | `str` | `"13:40"` 格式（HH:MM） |
| `dep_datetime` / `arr_datetime` | `str` | `"2026-10-25 13:40"` 格式（原值 `T` 换空格，保留秒） |
| `arr_next_day` | `bool` | 是否跨天（到达日期≠出发日期） |
| `aircraft` | `str` | 机型名（如 `空客321(中)`） |

辅助：`Segment.parse(raw)` 类方法；`__str__` 输出形如 `航班号 出发机场航站楼 HH:MM->HH:MM[+1] 到达机场航站楼`（跨天带 `+1`）。

#### `Fare`

一个舱位等级的报价（一个航班可含经济/超经/公务多条）。

| 字段 | 类型 | 说明 |
|---|---|---|
| `price` | `float` | 票面价 |
| `quantity` | `int` | 余票数 |
| `discount` | `Optional[float]` | 折扣（`0.7` = 七折）；可缺省 `None` |
| `grade` | `str` | 舱位等级名：经济舱/公务舱/头等舱… |
| `cabin_code` | `str` | 舱位代码：Y/B/M/G… |

辅助：`Fare.parse(raw)`（等级名取自响应 `fnotelst` 的 `notetype=4`，舱位代码取自 `classinfor` 的 `notetype=2`）；`__str__` 输出形如 `经济舱 ¥680 S舱 余9`。

#### `Flight`

一个航班条目（直达 = 1 航段；组合产品可能 0 航段只有价格）。

| 字段 | 类型 | 说明 |
|---|---|---|
| `segments` | `List[Segment]` | 航段列表 |
| `fares` | `List[Fare]` | 各舱位报价 |
| `duration` | `int` | 总飞行分钟数 |

便捷属性（直达场景常用，均安全处理无航段情况）：

| 属性 | 类型 | 说明 |
|---|---|---|
| `flight_no` | `str` | 第一航段航班号；无航段 → `""` |
| `dep_time` / `arr_time` | `str` | 首/末航段时刻 |
| `dep_airport` / `arr_airport` | `str` | 首/末航段机场 |
| `aircraft` | `str` | 第一航段机型 |
| `cheapest` | `Optional[Fare]` | 票价最低的报价；无报价 → `None` |
| `price` | `float` | `cheapest` 的价格；无报价 → `0` |

方法：`fares_of(grade_kw: str) -> List[Fare]`（按等级关键词过滤，如 `fares_of("公务")`）；`Flight.parse(raw)`；`__str__`（有报价输出 `航班号 HH:MM->HH:MM ¥N 余N`，无报价输出 `… 无报价`）。

#### `SearchResult`

`search()` 的返回。

| 字段 | 类型 | 说明 |
|---|---|---|
| `flights` | `List[Flight]` | 航班条目（含尾部「邻近城市推荐」类条目，见备注） |
| `org` / `dst` / `date` | `Optional[str]` | 查询的城市码与日期（回填） |
| `total` | `Optional[int]` | 服务端返回的总班次数（可能与 `len(self)` 不一致） |

方法与协议：

| 成员 | 说明 |
|---|---|
| `SearchResult.parse(data, org=None, dst=None, date=None)` | 类方法；解析 `fltitem` 列表 |
| `__iter__` | **显式覆盖**：迭代出 `Flight`（pydantic 基类迭代字段对，不可用） |
| `__len__` / `__getitem__` | 班次数 / 下标取 `Flight` |
| `direct() -> List[Flight]` | 直达（`len(segments)==1`） |
| `sorted_by_price() -> List[Flight]` | 按 `price` 升序 |
| `cheapest_n(n: int = 5) -> List[Flight]` | 最低价前 n 班 |
| `summary() -> str` | 多行文本：首行 `ORG→DST DATE  共N班`（`total` 不一致时附 `(total=M)`），每行航班号/起止时刻（跨天 `+1`）/机型/共享标注（`(共享实际航班号)`）/各报价；无航段条目显示 `(组合产品)` |

### 国际航班

#### `IntlSegment`

国际线一个航段（14780 响应，原始时刻为 `YYYYMMDDHHMMSS` 紧凑格式，解析成两种可读格式）。

| 字段 | 类型 | 说明 |
|---|---|---|
| `flight_no` | `str` | 航班号 |
| `carrier` | `str` | 承运航司二字码 |
| `dep_city` / `arr_city` | `str` | 出发/到达城市名 |
| `dep_airport` / `arr_airport` | `str` | 出发/到达机场三字码 |
| `dep_airport_name` / `arr_airport_name` | `str` | 出发/到达机场全名 |
| `dep_terminal` / `arr_terminal` | `str` | 航站楼 |
| `dep_time` / `arr_time` | `str` | `"13:00"`（HH:MM） |
| `dep_datetime` / `arr_datetime` | `str` | `"2026-10-22 13:00"`（不含秒） |
| `duration_min` | `int` | 该段飞行分钟数 |
| `aircraft` | `str` | 机型名 |

辅助：`IntlSegment.parse(raw)`；`__str__`（形如 `航班号 出发机场航站楼 HH:MM->HH:MM 到达机场航站楼`）。

#### `IntlFlight`

国际线一个方案（可含中转多段）。

| 字段 | 类型 | 说明 |
|---|---|---|
| `segments` | `List[IntlSegment]` | 航段列表 |
| `stops` | `int` | 中转次数 = max(段数−1, 0) |
| `dep_time` / `arr_time` | `str` | 首/末段时刻（HH:MM） |
| `arr_next_day` | `bool` | 是否跨天 |
| `duration_min` | `int` | 全程分钟数（响应 `seginfo.durtion`） |
| `fare` | `int` | 票面价 |
| `tax` | `int` | 税+燃油 |
| `total` | `int` | `fare + tax`，**成人含税总价，可直接比价** |
| `quantity` | `int` | 成人余票 |

辅助：属性 `flight_no`（各段航班号用 `+` 连接，如 `A1234+B5678`）；`IntlFlight.parse(raw)`（价格取 `policys` 里 `psgtype=1` 成人档的 `price`/`tax`/`fuel`）；`__str__`（形如 `A1234+B5678 HH:MM->HH:MM[+1] 历时N分 ¥N(票N+税N) 余N`）。

#### `IntlSearchResult`

国际单程查询结果（`search_intl()` 的返回，soa2/14780）。

| 字段 | 类型 | 说明 |
|---|---|---|
| `org` / `dst` / `date` | `str` | 查询的城市码与日期 |
| `flights` | `List[IntlFlight]` | 方案列表（解析时已自动丢弃无航段条目） |

方法与协议：

| 成员 | 说明 |
|---|---|
| `IntlSearchResult.parse(data, org, dst, date)` | 类方法；`org`/`dst`/`date` 为必填位置参数（与 `SearchResult.parse` 的可选默认不同） |
| `__iter__` | **显式覆盖**：迭代出 `IntlFlight` |
| `__len__` / `__getitem__` | 方案数 / 下标取 `IntlFlight` |
| `direct() -> List[IntlFlight]` | 直飞（`stops == 0`） |
| `sorted_by_price() -> List[IntlFlight]` | 先按 `stops`、再按 `total` 升序 |
| `cheapest() -> Optional[IntlFlight]` | 含税总价最低方案；空结果 → `None`。**是方法不是属性**（`Flight.cheapest` 是属性，注意区分） |
| `summary(top: int = 20, direct_only: bool = False) -> str` | 首行 `ORG→DST DATE  共N方案(直飞M)`；默认按 `sorted_by_price()` 取前 `top` 行；`direct_only=True` 时只列直飞（无直飞则只剩表头） |

### 火车票

#### `TrainSeat`

一种坐席的票价与余票。

| 字段 | 类型 | 说明 |
|---|---|---|
| `seat_name` | `str` | 坐席名：二等座/一等座/商务座/硬卧/无座… |
| `price` | `float` | 票价（元） |
| `bookable` | `bool` | 是否可订 |
| `inventory` | `int` | 余票张数；响应里 `99` 表示充足 |
| `discount` | `Optional[float]` | 折扣；可缺省 |

辅助：`TrainSeat.parse(raw)`；`__str__` 形如 `二等座¥576`，不可订附 `[无票]`，`0 < inventory < 99` 时附 `(N张)`。

#### `Train`

一趟车次。

| 字段 | 类型 | 说明 |
|---|---|---|
| `train_number` | `str` | 车次号 |
| `depart_station` / `arrive_station` | `str` | 出发/到达站名 |
| `depart_code` / `arrive_code` | `str` | 出发/到达站电报码 |
| `depart_time` / `arrive_time` | `str` | `"06:31"` 格式（HH:MM） |
| `run_time_minutes` | `int` | 历时分钟数 |
| `bookable` | `bool` | 是否可预订 |
| `seats` | `List[TrainSeat]` | 坐席列表（解析时过滤无 `SeatName` 的条目） |

辅助：

| 成员 | 说明 |
|---|---|
| `duration` -> `str` | 属性；历时文本：`347` → `5小时47分` |
| `cheapest` -> `Optional[TrainSeat]` | 属性；**可订**（`bookable` 且 `price>0`）坐席中最低价者；无可订 → `None` |
| `Train.parse(raw)` | 类方法 |
| `__str__` | 形如 `车次 出发站→到达站 HH:MM-HH:MM 5小时47分 二等座¥576`；无可订坐席时结尾为 `无可订坐席` |

#### `TrainSearchResult`

`train_search()` 的返回。

| 字段 | 类型 | 说明 |
|---|---|---|
| `depart` / `arrive` | `str` | 服务端回显的查询词（城市或站名） |
| `depart_code` / `arrive_code` | `str` | 城市电报码；空线路可能缺键（为 `""`） |
| `trains` | `List[Train]` | 车次列表 |

方法与协议：

| 成员 | 说明 |
|---|---|
| `TrainSearchResult.parse(data)` | 类方法；解析 `ResponseBody` |
| `__iter__` | **显式覆盖**：迭代出 `Train` |
| `__len__` | 车次数 |
| `__bool__` | `bool(self.trains)`——空线路结果为 falsy，用 `if not r:` 判空（空结果不抛错） |
| `bookable() -> List[Train]` | 可预订（且至少有一种可订坐席）的车次 |
| `summary() -> str` | 首行 `出发→到达 CODE-CODE  共N班(可订M班)`，其后每车次一行 |

### 其他

#### `DailyPrice`

低价日历的一个日期（`low_price_calendar()` 的元素）。

| 字段 | 类型 | 说明 |
|---|---|---|
| `date` | `str` | `YYYY-MM-DD` |
| `price` | `int` | 票面价（国内为机建燃油前票面；国际为不含税票面）。pydantic 强转：传 `"1610"` 也得 `1610` |
| `total` | `Optional[int]` | 含税总价（响应 `totalPrice`，国内外统一口径，**比价用这个**）；响应缺该键时为 `None` |

#### `City`

携程城市码：三字码 + 城市名 + 数字 cityId。

| 字段 | 类型 | 说明 |
|---|---|---|
| `code` | `str` | 三字城市码 |
| `name` | `str` | 城市名 |
| `id` | `str` | 数字 cityId 的字符串形式 |

注意是城市码不是机场码：北京=BJS（非 PEK）、西安=SIA（非 XIY）、成都=CTU（非 TFU）、上海=SHA（SHA/PVG 都映射到 SHA）。

#### `CookieEntry`

CDP `Network.getCookies` 的一条 cookie（`python -m ctrip cookies` 用）。

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | `str` | cookie 名 |
| `expires` | `float = 0` | 过期时间戳；`0`/负数 = 会话级 |

`model_config` 为 `extra="allow"`：CDP cookie 其余字段（`value`/`domain` 等，随 CDP 版本增减）原样透传到模型上。

## 城市码（cities.py）

`CITIES: Dict[str, City]` 是内置的城市三字码表（37 城，来自 2026-10-20 的 `airportFuzzySearch` 抓取），`search`/`search_intl`/`low_price_calendar` 的码先查它，命中就不触网。

机制（`CtripClient.city()` 实现）：

1. 内置表命中 → 直接返回；
2. 未命中 → 查 `city_cache` 缓存文件（默认 `~/.ctrip_cities.json`；新格式 `{"name": …, "id": …}`，旧格式 `["name", "id"]` 兼容）；
3. 仍未命中 → 走 `FUZZY_API` 动态查（payload 为 `{"data": json.dumps({"key": code})}`），要求条目 `poiType == "CITY"` 且 `cityCode == code` 才算命中，结果写回缓存（下次不再触网）。

城市码≠机场码规则：携程城市接口按**城市码**检索，机场码（如 PEK/PVG/XIY/TFU）不是合法输入——`city("PEK")` 会抛 `CtripError` 并提示改用城市码。内置表即按城市码收录：

| 码 | 城市 | id | 码 | 城市 | id | 码 | 城市 | id |
|---|---|---|---|---|---|---|---|---|
| BJS | 北京 | 1 | SHA | 上海 | 2 | TSN | 天津 | 3 |
| CKG | 重庆 | 4 | HRB | 哈尔滨 | 5 | DLC | 大连 | 6 |
| TAO | 青岛 | 7 | NKG | 南京 | 12 | WUX | 无锡 | 13 |
| SIA | 西安 | 10 | HGH | 杭州 | 17 | XMN | 厦门 | 25 |
| HFE | 合肥 | 278 | CTU | 成都 | 28 | SZX | 深圳 | 30 |
| CAN | 广州 | 32 | KWL | 桂林 | 33 | KMG | 昆明 | 34 |
| URC | 乌鲁木齐 | 39 | HAK | 海口 | 42 | SYX | 三亚 | 43 |
| CGQ | 长春 | 158 | LHW | 兰州 | 100 | INC | 银川 | 99 |
| HET | 呼和浩特 | 103 | SWA | 揭阳 | 956 | SHE | 沈阳 | 451 |
| WUH | 武汉 | 477 | NGB | 宁波 | 375 | FOC | 福州 | 258 |
| JJN | 泉州 | 406 | KOW | 赣州 | 268 | LYA | 洛阳 | 350 |
| KHN | 南昌 | 376 | NNG | 南宁 | 380 | CSX | 长沙 | 206 |
| KWE | 贵阳 | 38 | | | | | | |

（按源码顺序、每行三个排列；`id` 为携程数字 cityId 的字符串。）

## 异常体系

```
CtripError(Exception)                基类：库内所有异常
└── RateLimitedError(CtripError)     HTTP 432 风控限流
```

| 异常 | 触发条件 | 恢复建议 |
|---|---|---|
| `CtripError` | 城市码查不到；HTTP 非 200（非 432）；CDP 无 page target / 命令 error / 页面 JS 异常；页面不在 ctrip 域；`fetch` 返回非字符串；国际线 `Ack=Failure`；navigate 等待超时 | 视具体消息处理：配置/前置问题先修通道，业务性失败（如无此航线）换参数 |
| `RateLimitedError` | 列表接口（`flightListSearchForH5` 最敏感）高频请求触发 WAF 432；直连与 CDP 页内 fetch 都会映射到它 | 冷却 10-30 分钟再试；新会话/换 IP 可立即恢复；批量任务加长 `min_interval`；或临时换 `CDPProxy` 后备（页面内 fetch 走浏览器风控上下文） |

日历、城市接口风控宽松得多，可放心批量。直连通道请求节奏尽量贴近真人（库已内置 2.5 秒节流）。

## CLI 参考

入口：`python -m ctrip <子命令>`（`argparse`，`prog=ctrip`）。程序化调用入口为 `main(argv: Optional[List[str]] = None) -> int`（各子命令处理器 `cmd_cookies` / `cmd_train` / `cmd_intl` 为内部分发函数，行为见下文各子命令节）。所有异常被 `main()` 兜底捕获：打印 `错误: {e}` 到 stderr，退出码 1；正常退出码 0。子命令一览：

```bash
# 火车票车次查询（免登录；城市名或站名均可，日期缺省为今天）
python -m ctrip train DEPART ARRIVE [DATE] [--student]
# 国际/港澳台 单程航班列表（需模拟器浏览器，见「前置条件与依赖」）
python -m ctrip intl ORG DST DATE [--direct] [--top N]
# 登录态体检（走 CDP，需要模拟器浏览器开着）
python -m ctrip cookies
```

### `python -m ctrip cookies`

查看 cookie 过期时间（登录态体检）。

| 项 | 内容 |
|---|---|
| 参数 | 无 |
| 前置条件 | CDP：模拟器浏览器开着 + `adb forward tcp:9222` |
| 行为 | `CDPProxy` 调 `Network.getCookies`（urls 为 `https://m.ctrip.com/` 与 `https://ctrip.com/`；首次查询若要求先开 Network 域，则补 `Network.enable` 后按 `m.ctrip.com` 再查一次）；按过期时间升序打印 |

输出格式：表头 `name / 过期(本地) / 剩余`；`expires <= 0` 显示 `-` 与 `会话级`，否则显示 `YYYY-MM-DD HH:MM` 与 `N天`。表尾按 `cticket` 状态输出三种提示之一（原文）：

- `登录态(cticket)剩余 N 天;过期后用 ctrip/scripts/ctrip_login.py 重登一次即可`
- `cticket 已过期, 需要重登(机票查询本身不依赖登录, 仅会员功能受影响)`
- `未发现 cticket(未登录或浏览器 cookie 被清);机票查询不受影响`

示例：

```bash
python -m ctrip cookies
```

### `python -m ctrip train`

火车票车次查询（`soa2/14666`，免登录）。

| 参数 | 必填 | 说明 |
|---|---|---|
| `DEPART` | 是 | 出发城市/站名（帮助文本原文：`出发城市/站名,如 上海 或 上海虹桥`） |
| `ARRIVE` | 是 | 到达城市/站名 |
| `DATE` | 否（`nargs="?"`） | `YYYY-MM-DD`，缺省今天 |
| `--student` | 否 | 开关参数，学生票 |

- 前置条件：无（`CtripClient()` 缺省走 `HttpProxy` 直连，不需要模拟器）。
- 行为：调 `train_search(depart, arrive, date, student=…)`，打印 `TrainSearchResult.summary()`。
- 示例：

```bash
python -m ctrip train DEPART ARRIVE 2026-11-20
python -m ctrip train DEPART ARRIVE                # 日期缺省为今天
python -m ctrip train DEPART ARRIVE 2026-11-20 --student
```

### `python -m ctrip intl`

国际/中国港澳台单程列表（`soa2/14780`，navigate 驱动，免登录）。

| 参数 | 必填 | 说明 |
|---|---|---|
| `ORG` | 是 | 出发**城市码**（帮助文本原文：`出发城市码,如 SZX`） |
| `DST` | 是 | 到达城市码 |
| `DATE` | 是 | `YYYY-MM-DD` |
| `--direct` | 否 | 开关参数，只看直飞 |
| `--top N` | 否 | 最多显示条数，`int`，默认 20 |

- 前置条件：模拟器浏览器开着且 `adb forward tcp:9222`（`search_intl` 缺省自建 `IntlNavProxy`）。
- 行为：调 `search_intl(org, dst, date)`，打印 `IntlSearchResult.summary(top=…, direct_only=…)`（默认先按中转数后按含税价排序）。
- 示例：

```bash
python -m ctrip intl ORG DST 2027-05-01              # 按含税价排序
python -m ctrip intl ORG DST 2027-05-01 --direct --top 5
```
