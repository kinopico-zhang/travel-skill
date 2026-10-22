# fliggy API 文档

> 飞猪机票查询 python 库——纯 HTTP 直连 mtop H5 网关（h5api.m.taobao.com），免登录、零模拟器、零浏览器，覆盖单程航班列表（直飞 + 中转）。版本 0.1.0。

## 模块总览

| 模块 | 职责 |
|---|---|
| `fliggy/client.py` | `FliggyClient` 客户端、`MtopTransport` mtop 网关传输、`FetchTransport` 传输协议、异常类、模块级常量 |
| `fliggy/models.py` | 响应数据模型（pydantic）：`Segment` / `Fare` / `Flight` / `SearchResult` |
| `fliggy/__main__.py` | 命令行入口：`python -m fliggy flights …` |
| `fliggy/__init__.py` | 汇总导出公开 API |

`from fliggy import …` 可直接拿到（与 `__all__` 一致）：`FliggyClient`、`FliggyError`、`MtopTransport`、`RateLimitedError`、`API`、`APPKEY`、`Flight`、`Fare`、`Segment`、`SearchResult`。

## 前置条件与依赖

- Python ≥ 3.9；第三方依赖仅 `pydantic>=2`（见 `pyproject.toml`）。HTTP、签名、gzip、cookie 管理全部用标准库（`urllib` / `hashlib` / `gzip` / `json` / `http.cookiejar`），零模拟器、零浏览器。
- **免登录**：`h5api.m.taobao.com` 是淘宝系 H5 的公共网关，匿名访问也会下发 token（cookie `_m_h5_tk`），无需任何账号凭证；本库不存储、不传输任何个人登录态。
- **覆盖范围边界**：国内单程可查；国际票该接口需要登录态，本库不覆盖（与 README 口径一致）。
- **token 自愈机制**：首次请求 token 为空时，网关返回 `FAIL_SYS_TOKEN_EMPTY`，同时经 `Set-Cookie` 下发新 token；传输层用新 token 重签重试一次即恢复，全程无需人工介入（详见「传输层——token 自愈」）。
- **风控要求**：请求必须带 iPhone Safari UA 与 `Referer: https://h5.m.taobao.com/trip/flight/search/index.html`，否则触发 `RGV587_ERROR`（无线保镖拦截）；库默认 `min_interval=12.0` 秒节流（约 5 次/分钟），批量扫描请再加长，节奏贴近真人。

## 快速上手

```python
from fliggy import FliggyClient

fg = FliggyClient()                          # 默认 MtopTransport, min_interval=12.0 秒
r = fg.search("CAN", "PEK", "2026-12-26")    # 单程, 直飞+中转
print(r.summary())                           # 按含税总价升序的文本摘要
for f in r.cheapest_n(5):
    print(f.flight_no, f.dep_time, f.arr_time, f.price)   # price = 含税总价(元)
```

等价命令行：

```bash
python -m fliggy flights CAN PEK 2026-12-26
```

## 客户端

### `FliggyClient`

飞猪机票查询客户端。构造签名（与源码逐字一致）：

```python
def __init__(self, transport: Optional[FetchTransport] = None,
             min_interval: float = 12.0):
```

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `transport` | `Optional[FetchTransport]` | `None` | 传输层实例；`None` 时自动创建 `MtopTransport()`。测试可注入任何实现了 `fetch` 的替身（见「传输层——FetchTransport」） |
| `min_interval` | `float` | `12.0` | 同一实例相邻两次 `search` 的最小间隔（秒）。默认约 5 次/分钟（一次查询一个请求）；批量扫描建议再加长 |

实例属性 `transport`、`min_interval` 为公开属性，可直接读写。节流在实例内部完成，首次调用不等待；多个实例之间互不感知，复用同一实例才能保证节流生效。

#### `search`

完整签名（与源码逐字一致）：

```python
def search(self, dep: str, arr: str, date: str) -> SearchResult:
```

单程航班查询（国内免登录；价格为成人含税总价，元）。

| 参数 | 类型 | 说明 |
|---|---|---|
| `dep` | `str` | 出发三字码（机场码即可，如 `CAN`）；小写会自动转大写 |
| `arr` | `str` | 到达三字码，同上 |
| `date` | `str` | 出发日期，`YYYY-MM-DD` |

**返回值**：`SearchResult`（结构见「数据模型——SearchResult」）。包含直飞 + 中转全部行程；`r.direct()` 只看直飞；结果的 `dep` / `arr` / `date` 回填为大写三字码与传入日期。

**异常**：

- `RateLimitedError`——网关返回 RGV587（无线保镖拦截），冷却后再试；
- `FliggyError`——mtop 返回其他非 `SUCCESS` 结果；
- 库不包装网络层异常，`urllib` 抛出的连接/超时错误原样透传。

**示例**：

```python
r = fg.search("can", "pek", "2026-11-18")   # 小写自动转大写
print(r.dep, r.arr, r.date)                 # CAN PEK 2026-11-18
```

**备注**：

- 发出的请求载荷固定为 `searchMode=0`、`tripType=1`（单程）、`searchSegments=[{"depCityCode": dep, "arrCityCode": arr, "depDate": date}]`；只封装单程，往返参数未验证。
- 价格口径：原始响应单位是**分**，模型层统一换算成**元**；`Flight.price` / `Fare.total` 为**成人含税总价**。
- 一个行程卡片只有一档成人报价（经济舱），无多舱位列表。
- 节流在每次请求前执行：与上一次调用的间隔不足 `min_interval` 时自动 sleep 补足。

## 传输层

### `FetchTransport`（Protocol）

`FliggyClient` 依赖的最小传输接口（`typing.Protocol`，结构化类型，测试注入替身用）。导入路径：`from fliggy.client import FetchTransport`。

```python
def fetch(self, api: str, version: str,
          data: Dict[str, Any]) -> Dict[str, Any]:
```

| 参数 | 类型 | 说明 |
|---|---|---|
| `api` | `str` | mtop 接口名 |
| `version` | `str` | 接口版本 |
| `data` | `Dict[str, Any]` | 业务载荷（被序列化进签名与 query） |

返回值：`Dict[str, Any]`——服务端原始 JSON 的 `data` 部分。这是全库唯一允许 dict 停留的**传输边界**，拿到后立即解析为 `models` 里的 pydantic 类型。任何对象只要实现了该签名的 `fetch` 方法即满足协议，可直接传给 `FliggyClient(transport=…)`。

### `MtopTransport`

mtop H5 网关传输：签名 + cookie 自动管理 + 空 token 自愈。导入路径：`from fliggy import MtopTransport`。

```python
def __init__(self, timeout: int = 30):
```

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `timeout` | `int` | `30` | 单次 HTTP 请求超时（秒），透传给 `opener.open` |

内部持有 `CookieJar`（存匿名设备 token cookie `_m_h5_tk`）与带 `HTTPCookieProcessor` 的 urllib opener，`Set-Cookie` 自动入 jar，无需手工解析。

#### `fetch`

```python
def fetch(self, api: str, version: str,
          data: Dict[str, Any]) -> Dict[str, Any]:
```

GET `https://h5api.m.taobao.com/h5/<api>/<version>/?...`，返回响应 JSON 的 `data` 部分（dict）。

模块级常量（公开名；`API` / `APPKEY` 另经包顶层导出）：

| 常量 | 值 | 用途 |
|---|---|---|
| `API` | `"mtop.trip.flight.listingsearch"` | mtop 接口名 |
| `VERSION` | `"2.0"` | 接口版本 |
| `APPKEY` | `"12574478"` | H5 网关公共 appKey |
| `JSV` | `"2.7.0"` | query 的 `jsv` 参数 |
| `BASE` | `"https://h5api.m.taobao.com"` | 网关基地址 |
| `UA_IPHONE` | 见下方 | 请求头 `User-Agent`，必带，否则 RGV587 |
| `REFERER` | `"https://h5.m.taobao.com/trip/flight/search/index.html"` | 请求头 `Referer`，必带，否则 RGV587 |

`UA_IPHONE` 的值：

```text
Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1
```

**请求构造**：query 携带 `jsv`、`appKey`、`t`（毫秒时间戳）、`sign`、`api`、`v`、`type=originaljson`、`dataType=json`、`data`（紧凑 JSON：分隔符 `,` 与 `:`，非 ASCII 字符不转义）。请求头带 `User-Agent`（`UA_IPHONE`）、`Referer`（`REFERER`）、`Accept-Language: zh-CN,zh;q=0.9`。

**mtop 三段式签名**：`sign = md5(token & t & appKey & data)`——四段以 `&` 相连后取 MD5 十六进制值。`token` 取 cookie `_m_h5_tk` 的前半段（`_` 之前），匿名访问也会下发；`t` 为毫秒时间戳；`data` 与 query 中完全一致的 JSON 字符串。标准库 `hashlib.md5` 直接可算，无 TLS 指纹墙、无 JSVMP。

**token 自愈**：首次请求 token 为空时，网关返回 `FAIL_SYS_TOKEN_EMPTY` 并同时经 `Set-Cookie` 下发新 token；`HTTPCookieProcessor` 使 cookie 自动入 jar，传输层用新 token 重签重试一次即成功，全程无需登录（最多发起两次请求，重试仅一次）。

**响应处理**：

- 响应头 `content-encoding: gzip` 时自动解压；
- `ret` 任一项含 `RGV587` → 抛 `RateLimitedError`；
- `ret` 任一项以 `SUCCESS` 开头 → 返回 `body["data"]`（缺失时为 `{}`）；
- 其余任何情况（如 `FAIL_SYS_API_NOT_FOUNDED`）→ 抛 `FliggyError`，消息形如 `mtop <api> 失败: <ret 各项以 "; " 连接>`。

**示例**（一般不必直接使用，`FliggyClient.search` 已封装）：

```python
tr = MtopTransport(timeout=30)
data = tr.fetch("mtop.trip.flight.listingsearch", "2.0",
                {"searchMode": 0, "tripType": 1,
                 "searchSegments": [{"depCityCode": "CAN",
                                     "arrCityCode": "PEK",
                                     "depDate": "2026-12-26"}]})
```

## 数据模型（models.py）

所有模型均为 pydantic `BaseModel`，字段全部带默认值；原始 JSON 只允许停留在 `MtopTransport.fetch` 的返回值（传输边界），进入业务层即解析为本模块的类型。各字段表中的「来源字段」为解析时读取的原始 JSON 键名。

### `Segment`

一个航段（`Flight.segments` 的元素：直飞行程 1 个，中转行程多个）。

| 字段 | 类型 | 说明（来源字段） |
|---|---|---|
| `flight_no` | `str` | 营销航班号，航司代码 + 数字（`marketingFlightNo`；缺省 `""`） |
| `carrier` | `str` | 营销承运航司展示名；原始值形如 `新海航\|海南航空`，取 `\|` 最后一段（`marketingAirlineName`） |
| `carrier_code` | `str` | 营销承运航司代码（`marketingAirlineCode`） |
| `actual_flight_no` | `str` | 实际承运航班号（代码共享时与 `flight_no` 不同）；缺省回落为营销航班号（`operatingFlightNo`，缺省取 `marketingFlightNo`） |
| `is_shared` | `bool` | 是否代码共享（`codeShare`；缺省 `False`） |
| `dep_city` | `str` | 出发城市名（`depCityName`） |
| `dep_airport` | `str` | 出发机场名（`depAirportName`） |
| `dep_terminal` | `str` | 出发航站楼，如 `T2`（`depTerm`） |
| `arr_city` | `str` | 到达城市名（`arrCityName`） |
| `arr_airport` | `str` | 到达机场名（`arrAirportName`） |
| `arr_terminal` | `str` | 到达航站楼（`arrTerm`） |
| `dep_time` | `str` | 起飞时刻，`HH:MM`（`depTime` 截取 `[11:16]`，原始格式 `YYYY-MM-DD HH:MM:SS`） |
| `arr_time` | `str` | 到达时刻，`HH:MM`（`arrTime` 同上） |
| `dep_datetime` | `str` | 起飞，`YYYY-MM-DD HH:MM`（`depTime` 截取 `[:16]`） |
| `arr_datetime` | `str` | 到达，`YYYY-MM-DD HH:MM`（`arrTime` 同上） |
| `arr_next_day` | `bool` | 到达是否次日（跨零点红眼，`arrSpanDays` 非零即 `True`；缺省 `False`） |
| `duration_min` | `int` | 航段时长，分钟（`duration`；缺省 `0`） |
| `aircraft` | `str` | 机型（`planeType`） |
| `stop_quantity` | `int` | 经停次数（**≠中转**；`stopQuantity`；缺省 `0`） |

辅助方法：

```python
@classmethod
def parse(cls, raw: Dict[str, Any]) -> "Segment":
```

从行程卡片内的单航段原始 dict 解析（`Flight.parse` 内部调用）。

`__str__` 格式：`<flight_no> <dep_airport><dep_terminal> <dep_time>-><arr_time>[+1] <arr_airport><arr_terminal>`，到达次日时时刻后带 `+1`。

### `Fare`

成人报价。原始响应单位是**分**，`parse` 统一换算成**元**（除以 100）。

| 字段 | 类型 | 说明（来源字段） |
|---|---|---|
| `price` | `float` | 票面价（不含税），元（`adultPrice`） |
| `tax` | `float` | 税费，元（`adultTax`） |
| `total` | `float` | 含税总价，元——**比价用这个**（`adultTotalPrice`） |
| `original_price` | `float` | 划线原价（票面口径），元（`originalAdultPrice`） |

辅助方法：

```python
@classmethod
def parse(cls, raw: Dict[str, Any]) -> "Fare":
```

来源字段缺省按 0 处理。

`__str__` 格式：`¥<total:.0f>(票面¥<price:.0f>+税¥<tax:.0f>)`，如实测夹具 `¥1230(票面¥1090+税¥140)`（原始 123000 分 → 1230 元）。

### `Flight`

一个行程条目（直飞 = 1 航段；中转 = 多航段）。

| 字段 | 类型 | 说明（来源字段） |
|---|---|---|
| `segments` | `List[Segment]` | 航段列表（`flightInfos[0].flightSegments`；缺省空列表） |
| `fare` | `Optional[Fare]` | 成人报价；响应无 `priceInfo` 时为 `None` |
| `duration` | `int` | 全程分钟，含中转等待（`flightInfos[0].duration`；缺省 `0`） |
| `transfer_count` | `int` | 中转次数（`transferCount`；缺省 `0`） |
| `transfer_time_min` | `int` | 中转等待分钟（`transferTime`；缺省 `0`） |

便捷属性（property）：

| 属性 | 类型 | 说明 |
|---|---|---|
| `flight_no` | `str` | 首航段航班号；无航段时为 `""` |
| `dep_time` | `str` | 首航段起飞时刻，`HH:MM` |
| `arr_time` | `str` | 末航段到达时刻，`HH:MM` |
| `dep_airport` | `str` | 首航段出发机场名 |
| `arr_airport` | `str` | 末航段到达机场名 |
| `cheapest` | `Optional[Fare]` | 与 ctrip 库同名属性对齐；本库一个行程只有一档报价，即返回 `fare` |
| `price` | `float` | 含税总价（元）；无报价时为 `0.0` |

辅助方法：

```python
@classmethod
def parse(cls, raw: Dict[str, Any]) -> "Flight":
```

从行程卡片原始 dict 解析。

`__str__` 格式：

- 直飞：`<flight_no> <dep_time>-<arr_time>[+1] <duration>分 <fare>`，如 `AQ1001 17:05-20:15 190分 ¥1059(票面¥919+税¥140)`；
- 中转：`<各段航班号以+相连> 中转<n>次(等<m>分) <dep_time>-<arr_time> <duration>分 <fare>`；
- 无报价时 `<fare>` 位置显示 `无报价`。

### `SearchResult`

`search()` 的返回：可迭代（迭代出 `Flight`）、支持 `len()` 与下标、按价排序等。

| 字段 | 类型 | 说明 |
|---|---|---|
| `flights` | `List[Flight]` | 行程列表；解析时跳过运营位卡片与缺 `flightInfos` 的记录 |
| `dep` | `Optional[str]` | 出发三字码（大写），回填自 `search` 参数 |
| `arr` | `Optional[str]` | 到达三字码，同上 |
| `date` | `Optional[str]` | 出发日期，`YYYY-MM-DD` |

模块级常量 `DATA_ITEM_TYPES = frozenset({"FLIGHT_DIRECT", "FLIGHT_TRANSFER"})`——列表页有业务数据的卡片类型；其余（`ECONOMY_RECOMMEND` / `LOW_PRICE_MONITOR` / `TITLE` 等）是运营位横幅，没有 `flightInfos`，解析时跳过。

方法与可迭代语义：

```python
@classmethod
def parse(cls, data: Dict[str, Any], dep: Optional[str] = None,
          arr: Optional[str] = None,
          date: Optional[str] = None) -> "SearchResult":
```

从 `MtopTransport.fetch` 返回的 `data` dict 解析；`dep` / `arr` / `date` 原样回填到结果（供 `summary()` 展示与属性读取）。

```python
def __iter__(self) -> "Iterator[Flight]":
def __len__(self) -> int:
def __getitem__(self, i: int) -> Flight:
```

可迭代语义：显式覆盖 pydantic 基类的 `__iter__`（后者迭代的是 `(字段名, 值)` 对），本类迭代航班；`len(r)` 为行程数；`r[i]` 等价 `r.flights[i]`。

```python
def direct(self) -> List[Flight]:
def sorted_by_price(self) -> List[Flight]:
def cheapest_n(self, n: int = 5) -> List[Flight]:
def summary(self, direct_only: bool = False) -> str:
```

| 方法 | 返回类型 | 说明 |
|---|---|---|
| `direct` | `List[Flight]` | 直飞行程（`len(f.segments) == 1`），保持原顺序 |
| `sorted_by_price` | `List[Flight]` | 按 `price`（含税总价，元）升序的新列表，不改原顺序 |
| `cheapest_n` | `List[Flight]` | 即 `sorted_by_price()[:n]`，最便宜的前 `n` 个（默认 5） |
| `summary` | `str` | 人类可读摘要：首行为统计，其后每个行程一行（按价升序）；代码共享条目行尾追加 ` (共享<actual_flight_no>)` |

`summary()` 首行规则：`<dep>→<arr> <date>  共<n>班`——`direct_only=True`（只统计并列出直飞）时追加 `(直飞)`，否则追加 `/直飞<m>`。输出示例（`direct_only=True` 形式，与 README 一致）：

```text
CAN→PEK 2026-11-18  共49班(直飞)
  AQ1001 17:05-20:15 190分 ¥1059(票面¥919+税¥140)
  MU6312 22:00-01:05+1 185分 ¥1390(票面¥1250+税¥140)
```

## 异常体系

继承树（均定义在 `fliggy.client`，经包顶层导出）：

```text
FliggyError                    所有异常的基类
└── RateLimitedError           RGV587 无线保镖拦截
```

| 异常 | 触发条件 | 典型消息 |
|---|---|---|
| `FliggyError` | mtop 返回 `ret` 中没有任何以 `SUCCESS` 开头的项，且不含 `RGV587`、非首次空 token 重试场景（如 `FAIL_SYS_API_NOT_FOUNDED`） | `mtop mtop.trip.flight.listingsearch 失败: FAIL_SYS_API_NOT_FOUNDED::接口不存在` |
| `RateLimitedError(FliggyError)` | `ret` 任一项含 `RGV587`——缺 Referer/UA 或触发频控；应冷却后再试 | `RGV587 无线保镖拦截 (mtop.trip.flight.listingsearch) — 冷却后再试` |

`FliggyClient.search` 不捕获异常，传输层抛什么就透传什么；CLI 层统一兜底为退出码 1（见下节）。

## CLI 参考

入口 `fliggy/__main__.py`：

```bash
python -m fliggy flights DEP ARR DATE [--direct]
```

子命令 `flights`（help：`单程航班列表(免登录,含中转)`）。

| 参数 | 位置/可选 | argparse help 原文 |
|---|---|---|
| `dep` | 位置参数 | `出发三字码,如 CAN` |
| `arr` | 位置参数 | `到达三字码,如 PEK` |
| `date` | 位置参数 | `YYYY-MM-DD` |
| `--direct` | 可选开关（`store_true`） | `只看直飞` |

前置条件：与库一致——国内单程免登录，网络可达 `h5api.m.taobao.com`。

行为：内部构造 `FliggyClient()` 并调用 `search(dep, arr, date)`，把 `summary(direct_only=args.direct)` 打印到 stdout，退出码 `0`；任何异常打印 `错误: <消息>` 到 stderr 并退出码 `1`；参数缺失或错误时 argparse 直接以非零退出码终止（`SystemExit`）。

示例：

```bash
python -m fliggy flights CAN PEK 2026-11-18
python -m fliggy flights CAN PEK 2026-11-18 --direct
```

失败输出示例（stderr，退出码 1）：

```text
错误: RGV587 无线保镖拦截 (mtop.trip.flight.listingsearch) — 冷却后再试
```

程序化调用：`main` 的完整签名为 `def main(argv: Optional[List[str]] = None) -> int:`，传入参数列表（不含 `python -m fliggy`）返回退出码，便于脚本与测试复用；子命令处理函数为 `def cmd_flights(args: argparse.Namespace) -> int:`。
