# amap API 文档

> 高德（Gaode）路线规划纯 Python 库：驾车/公交/步行路线、地理编码与**未来用车时预估**，默认走 H5 Web 服务代理（纯 HTTP、零模拟器依赖），另备模拟器 Deep Link 通道。版本 0.5.0。

## 模块总览

| 模块 | 职责 |
|---|---|
| `amap.web` | **默认公开入口**：`WebClient`（m.amap.com 服务代理，纯 HTTP）+ 路线偏好策略映射；其中 `parse_web_*` 系列为底层解析函数（内部/高级） |
| `amap.client` | `AmapClient` 后备通道编排（Deep Link 触发 + flows 捕获 + protobuf 解析），内含 `Transport` 协议定义 |
| `amap.models` | 全部数据模型（两个通道共用同一套） |
| `amap.transport` | `DeepLinkTransport`：adb 向模拟器内的高德 App 发 `amapuri://` URI（内部/高级） |
| `amap.capture` | 从 mitmproxy flows 文件捞导航响应（内部/高级） |
| `amap.parser` | 无 schema 手写 protobuf / 线格式解析（内部/高级） |
| `amap.__main__` | CLI：`python -m amap <子命令>` |

`from amap import ...` 可直接拿到：`WebClient`、`AmapClient`、`resolve_strategy`、`APP_STRATEGIES`、`NavStep`、`NavRoute`、`NavResult`、`BusLeg`、`BusPlan`、`BusResult`、`GeoPlace`、`FutureEta`（`__version__` = `"0.5.0"`）。

## 前置条件与依赖

- Python ≥ 3.9，唯一必装依赖 `pydantic>=2`。
- **默认路径（`WebClient`）是纯 HTTP**：直调高德 H5（m.amap.com）的 `_AMapService` 服务代理，带上 H5 页面公开的 JS key 与 `platform=JS`、`Referer` 即可，与手机浏览器里查路线完全等价——**零模拟器依赖**。
- 可选 extra `[capture]`（本仓库根执行 `pip install -e ".[capture]"`：`mitmproxy` + `zstandard`）：仅 `AmapClient` 读 flows 文件与 `parser.wire_to_pb` 解 zstd 响应时需要。
- **后备路径（`AmapClient` + `DeepLinkTransport`）**：让模拟器里的高德 App 以真实用户身份替你发请求，需要——安卓模拟器（默认 MuMu，ADB 地址 `127.0.0.1:16384`）、`adb`（默认 `~/android-sdk/platform-tools/adb`）、`mitmdump -w <flows>` 监听 + 模拟器 http_proxy 指向本机 + CA 区信任 mitmproxy CA + 模拟器内 iptables 掐直连（否则高德 HTTPDNS 直连绕过代理）。改时钟（`depart_at`）还需 root 的 adb。完整链路见包 README 与 `amap/capture.py` docstring。
- 未来用时（v4/etd）纯 HTTP 化的关键：m.amap.com 的代理对 v4/etd 返回 `10009 USERKEY_PLAT_NOMATCH`，所以 v4/etd 改走**桌面版 ditu.amap.com 的同款服务代理**（常量 `DITU_BASE`/`DITU_KEY`，同为页面公开 JS key + `platform=JS` 机制），由 `WebClient` 内部自动切换，调用方无感。

**什么时候用后备**：默认一律 `WebClient`。只有两类场景才需要 `AmapClient`：①想要 App 侧「一次查询返回 2-4 条备选方案」（v3 Web 一次只出一个策略的方案，`no_highway` 例外返回 3 条）；②显式想走模拟器改时钟的旧实现查未来用时（`--depart --app`）。注意 v4/etd 纯 HTTP 已经覆盖未来用时，且一次请求可出 48 个时间点，比改时钟（一点一查）低频得多。

## 快速上手

```python
from datetime import datetime

from amap import WebClient

w = WebClient()

# 驾车路线（默认策略 smart 高德AI推荐），坐标 GCJ-02
r = w.nav_route(22.9208, 113.8903, "起点", 23.1066, 113.3245, "终点")
best = r.best()                                   # 时间最短方案
print(best.distance_km, best.duration_s, best.toll_yuan)
print(r.summary())

# 未来用车时时刻表（v4/etd）：首时刻起每半小时一个点，共 4 个
for eta in w.etd_table(22.9208, 113.8903, 23.1066, 113.3245,
                       datetime(2026, 10, 23, 8, 0)):
    print(eta)

# 公交（地铁/城际/公交）、步行、地理编码
b = w.bus_route(22.9208, 113.8903, "起点", 23.1066, 113.3245, "终点")
print(b.summary())
wk = w.walk_route(22.9208, 113.8903, "起点", 22.9250, 113.8950, "终点")
places = w.geocode("地址")                        # 地名 → 坐标列表
```

约定：所有坐标均为 GCJ-02（高德坐标系）；起终点名（`sname`/`dname`）仅用于展示与 URI 参数，实际路线按坐标规划。参数顺序统一为「纬度在前、经度在后」（但传给高德接口时由客户端自行拼成 `lon,lat`，调用方不用管）。

## 客户端

### `WebClient` —— 默认通道（纯 HTTP）

```python
from amap import WebClient
```

#### 构造

```python
def __init__(self, key: str = WEB_KEY, base: str = WEB_BASE,
             min_interval: float = 2.0, timeout: float = 15.0):
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `key` | `str` | `WEB_KEY` | 服务代理用的 JS key。默认值是 m.amap.com H5 页面公开的 JS key（页面 webapi 加载参数里可见，非私钥），一般不改 |
| `base` | `str` | `WEB_BASE` | 服务代理基址（`https://m.amap.com/_AMapService`）。一般不改；v4/etd 由内部固定改走 ditu.amap.com 的代理 |
| `min_interval` | `float` | `2.0` | 相邻两次请求的最小间隔（秒）。H5 页面一次查询会连发数个请求，2s 已明显保守于人手点按；**勿调低**，高频可能触发风控 |
| `timeout` | `float` | `15.0` | 单次 HTTP 超时（秒） |

所有查询方法共用内置节流：距上次请求不足 `min_interval` 秒则先睡到满足。

#### `nav_route` —— 驾车路线（实时 / 未来）

```python
def nav_route(self, slat: float, slon: float, sname: str,
              dlat: float, dlon: float, dname: str,
              strategy: Any = "smart",
              depart_at: Optional[datetime.datetime] = None) -> NavResult:
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `slat` / `slon` | `float` | 必填 | 起点纬度/经度（GCJ-02） |
| `sname` | `str` | 必填 | 起点名（仅展示用，回填进结果的 `depart`） |
| `dlat` / `dlon` | `float` | 必填 | 终点纬度/经度（GCJ-02） |
| `dname` | `str` | 必填 | 终点名（仅展示用） |
| `strategy` | `Any` | `"smart"` | 路线偏好：App「路线偏好」同款策略名，或 v3 数字（int）。详见下文「路线偏好与策略映射」 |
| `depart_at` | `Optional[datetime.datetime]` | `None` | 未来出发时刻。给了就改走 v4/etd 未来预测（ditu 代理），**必须是未来时间**，否则抛 `WebError`；`None` 走 v3 实时路况 |

**返回** `NavResult`（结构见「数据模型」）：

- 实时路径（`depart_at=None`）：调 `/v3/direction/driving`（`extensions=base`），`routes` 为解析出的方案列表（通常 1 条；`no_highway` 返回 3 条备选），`depart_at=None`，`mode="drive"`。
- 未来路径（给了 `depart_at`）：调 ditu 代理的 `/v4/etd/driving`（`interval=1`、`count=1`，即只取首时刻），取首方案并把该时刻的预估**回填**进去：`routes[0].duration_s = 预估分钟×60`、`routes[0].toll_fen = 预估元×100`。返回 `routes[:1]`（单方案），`depart_at` 为该时刻的 unix 秒。注意 v4/etd 的 path 本体不带用时/费用（`steps` 的 `duration_s` 保持 0）。

**异常** `WebError`：`depart_at` 非未来时间、未知策略、网络失败、响应非 JSON、`status≠1`（v3）/`errcode≠0`（v4）、响应里没有方案。

**示例**

```python
from datetime import datetime
from amap import WebClient

w = WebClient()
r = w.nav_route(22.9208, 113.8903, "起点", 23.1066, 113.3245, "终点")
r = w.nav_route(22.9208, 113.8903, "起点", 23.1066, 113.3245, "终点",
                strategy="cheap")                       # 费用优先
r = w.nav_route(22.9208, 113.8903, "起点", 23.1066, 113.3245, "终点",
                depart_at=datetime(2026, 10, 23, 8, 0))  # 未来用时
```

**备注**

- 与 App 侧一次返回多方案不同，v3 一次查询一个策略（`no_highway` 例外，返回 3 条备选）；想比较多方案就换策略再查。
- v4/etd 只有两档：躲避拥堵（默认）/ 免费。`cheap` 与 `no_highway` 映射免费档——实测零过路费、全程避开高速，代价是用时明显变长（长途约多三成）。
- 免费档语义只在 v4/etd 成立；v3 的 `cheap`（strategy=1，费用最少）仍可能有过路费。

#### `etd_table` —— 未来用时时刻表

```python
def etd_table(self, slat: float, slon: float, dlat: float, dlon: float,
              first: datetime.datetime,
              interval_s: int = 1800, count: int = 4,
              strategy: Any = "smart") -> List[FutureEta]:
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `slat` / `slon` / `dlat` / `dlon` | `float` | 必填 | 起终点坐标（GCJ-02），无名称参数 |
| `first` | `datetime.datetime` | 必填 | 首时刻（**未来**） |
| `interval_s` | `int` | `1800` | 相邻时间点间隔（秒），必须为正 |
| `count` | `int` | `4` | 时间点个数，1-48（v4/etd 上限 48） |
| `strategy` | `Any` | `"smart"` | 同 `nav_route`；实际只有避堵/免费两档起作用 |

**返回** `List[FutureEta]`：每个时间点一条预估（时刻 = `first` + i×`interval_s`，unix 秒）。一次请求出全部点，比改时钟方案（一点一查）低频得多，风控友好。

**异常** `WebError`：`count` 不在 1-48、`interval_s ≤ 0`、`first` 非未来时间（三者都在发请求前校验）、网络/响应错误、v4/etd 响应里没有方案。

**示例**

```python
from datetime import datetime
from amap import WebClient

w = WebClient()
etas = w.etd_table(22.9208, 113.8903, 23.1066, 113.3245,
                   datetime(2026, 10, 23, 8, 0), interval_s=3600, count=12)
for e in etas:
    print(e)        # 形如 10-23 08:00 100分钟 过路费¥77
```

**备注** 展示时刻按请求参数推算（firsttime + i×interval）——响应里的 `starttime` 是毫秒且存在偏移怪癖，不作时刻来源。

#### `bus_route` —— 公交路线

```python
def bus_route(self, slat: float, slon: float, sname: str,
              dlat: float, dlon: float, dname: str,
              city: str = "", cityd: str = "") -> BusResult:
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `slat` / `slon` / `sname` / `dlat` / `dlon` / `dname` | — | 必填 | 同 `nav_route` |
| `city` | `str` | `""` | 起点城市。**一般不用传**：实测跨城查询不带城市参数服务端也按坐标识别；显式传入仅在识别不准时兜底 |
| `cityd` | `str` | `""` | 终点城市，同上 |

**返回** `BusResult`（换乘段/票价/步行距离等见「数据模型」）。底层调 `/v3/direction/transit/integrated`（固定 `strategy=0`），含地铁、城际铁路与常规公交。

**异常** `WebError`：网络/响应错误、响应里没有公交方案。

**示例**

```python
b = w.bus_route(22.9208, 113.8903, "起点", 23.1066, 113.3245, "终点")
print(b.summary())
print(b.best().legs)    # 换乘段：线路名/上下车站/途经站数
```

**备注** 坐标 → 城市的自动识别不做——逆地理 regeo 不在代理白名单里（会回滑块验证页），所以才有 `city`/`cityd` 兜底参数。

#### `walk_route` —— 步行路线

```python
def walk_route(self, slat: float, slon: float, sname: str,
               dlat: float, dlon: float, dname: str) -> NavResult:
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `slat` / `slon` / `sname` / `dlat` / `dlon` / `dname` | — | 必填 | 同 `nav_route` |

**返回** `NavResult`（`mode="walk"`，单方案，复用驾车模型，无费用字段值）。底层调 `/v3/direction/walking`。

**异常** `WebError`：网络/响应错误、响应里没有步行方案。

**备注** 骑行接口代理未开放，本库不提供骑行查询（App 通道的骑行响应端点也未解析）。

#### `geocode` —— 地理编码

```python
def geocode(self, address: str, city: str = "") -> List[GeoPlace]:
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `address` | `str` | 必填 | 结构化/非结构化地名 |
| `city` | `str` | `""` | 限定城市，空串则不下发该参数 |

**返回** `List[GeoPlace]`（按相关性排序，第一个通常就是要找的）。底层调 `/v3/geocode/geo`；`location` 解析不出经纬度的条目会被跳过。

**异常** `WebError`：网络/响应错误。

**示例**

```python
g = w.geocode("地址")
if g:
    print(g[0].lng, g[0].lat, g[0].address)
```

### 路线偏好与策略映射

`strategy` 用高德 App「路线偏好」同款策略名，两个通道各自映射到该通道实际支持的值（实测 v3 代理认 `0/1/2/16/32`，其余值归默认；v4/etd 只有避堵/免费两档，其余值全归这两档）：

`APP_STRATEGIES: Dict[str, tuple]` —— 每项为 `(中文名, v3 值, v4/etd 值)`：

| 策略名 | App 名称 | v3（实时） | v4/etd（未来） |
|---|---|---|---|
| `smart`（默认） | 高德AI推荐 | 32 默认 | 1 躲避拥堵 |
| `fast` | 时间优先 | 0 速度优先 | 1 |
| `cheap` | 费用优先 | 1 费用优先 | 2 免费 |
| `short` | 距离优先 | 2 距离优先 | 1（近似） |
| `no_highway` | 不走高速 | 16（返回 3 条备选） | 2 免费 |
| `avoid_jam` | 躲避拥堵 | 32（v3 无独立值） | 1 |
| `highway` | 高速优先 | 0（v3 无独立值） | 1 |

`DRIVE_STRATEGIES: Dict[int, str]`（`amap.web`）—— v3 数字语义：`{0: "速度最快", 1: "费用最少", 2: "距离最短", 16: "不走高速", 32: "默认"}`。

```python
def resolve_strategy(strategy: Any) -> tuple:  # noqa: UP006  # (v3值, etd值)
```

把策略名或 v3 数字解析成 `(v3 strategy, v4/etd strategy)` 二元组：

- 字符串：先 lower()；纯数字串（CLI argparse 传来的 `"16"` 等）自动转 `int` 走数字分支，其余必须是 `APP_STRATEGIES` 的键（大小写不敏感），否则抛 `WebError("未知策略 …")`。
- 整数：必须是 `DRIVE_STRATEGIES` 的键，否则抛 `WebError("未知 strategy …")`；etd 侧 `1`（费用最少）与 `16`（不走高速）映射免费档 `2`，其余映射 `1`。
- **注意**：v3 数字必须是 `int`；数字的字符串形式（如 `"16"`）会按策略名校验而抛 `WebError`。

App 里的「大路优先」两个通道都没有对应值，未收录。

### `AmapClient` —— 后备通道（模拟器 Deep Link）

```python
from amap import AmapClient
```

编排「Deep Link 触发 → App 发真实请求 → mitmproxy flows 抓包 → protobuf 解析」。高德 App 请求体是 shield 加密的（阿里 securityguard），自主构造不现实；`amapuri://` URI 让 App 以真实用户身份生成请求，与真人操作完全同栈。**前置条件见「前置条件与依赖」**（模拟器/mitmproxy/CA/iptables 全链路）。

#### 构造

```python
def __init__(self, flows_path: str = FLOWS_DEFAULT,
             transport: Optional[Transport] = None,
             min_interval: float = 8.0):
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `flows_path` | `str` | `FLOWS_DEFAULT`（`"/tmp/amap.flows"`） | mitmdump 落盘的 flows 文件路径 |
| `transport` | `Optional[Transport]` | `None` | 传输层实现；`None` 用 `DeepLinkTransport()`。测试注入替身用 |
| `min_interval` | `float` | `8.0` | 相邻两次查询最小间隔（秒）。导航查询比网页重得多，人类不会连点，默认 8s 起步 |

#### `nav_route` —— 驾车路线（App 侧，2-4 条备选）

```python
def nav_route(self, slat: float, slon: float, sname: str,
              dlat: float, dlon: float, dname: str,
              mode: str = "drive", timeout: float = 90.0,
              depart_at: Optional[datetime] = None) -> NavResult:
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `slat` / `slon` / `sname` / `dlat` / `dlon` / `dname` | — | 必填 | 同 `WebClient.nav_route`；坐标 GCJ-02 |
| `mode` | `str` | `"drive"` | 只支持 `"drive"`；其他值抛 `NotImplementedError`（公交用 `bus_route()`；步行/骑行的响应端点未解析） |
| `timeout` | `float` | `90.0` | 等待抓包响应的上限（秒）。90s：高德掐直连后偶发降级重试，首条路线可能要等一会儿 |
| `depart_at` | `Optional[datetime]` | `None` | 查未来用时。实现是**把模拟器系统时间改到该时刻再触发查询**（Deep Link 无出发时间参数，UI 时间选择器是自绘弹窗点不开），App 即以该时刻请求预测；查询完自动恢复真实时间。改时间是全局副作用，偶发使用可以，别高频 |

**流程**：节流 → `launch_route`（`depart_at` 给了则 `set_clock` → 发 URI → `finally` 恢复时钟，失败也恢复）→ 轮询 flows 等响应（`since_ts = 发出时刻 − 2s`）→ `parse_wire` 解析。

**返回** `NavResult`：通常 2-4 条备选方案（`depart_at` 给了则 `depart_at` 字段为该时刻的 unix 秒）。

**异常**：`NotImplementedError`（mode ≠ drive）、`TransportError`（Deep Link 没发出/链路不通）、`CaptureError`（超时没等到响应、flows 不可读）、`CaptureErrorEmpty`（解析成功但没有方案，如坐标不可达）、`ValueError`（响应格式变化，zstd 魔数找不到，罕见）。

**示例**

```python
from amap import AmapClient

am = AmapClient()
r = am.nav_route(22.9208, 113.8903, "起点", 23.1066, 113.3245, "终点")
print(r.summary())   # 形如 起点→终点(drive) 共3条方案 / 方案1: 82公里 1小时34分 过路费¥25
```

#### `bus_route` —— 公交路线（App 侧）

```python
def bus_route(self, slat: float, slon: float, sname: str,
              dlat: float, dlon: float, dname: str,
              timeout: float = 90.0) -> BusResult:
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `slat` / `slon` / `sname` / `dlat` / `dlon` / `dname` | — | 必填 | 同上 |
| `timeout` | `float` | `90.0` | 等待抓包响应上限（秒） |

**返回** `BusResult`：一次查询通常返回 10+ 条方案（UI 只展示推荐的几条），每条含历时/步行/票价与换乘段线路；跨城方案可能无票价，另有客车/火车/打车直达方案。

**异常**：同 `nav_route`（`CaptureErrorEmpty` 文案为「响应里没有公交方案」）。抓包端点固定为公交的 `new_integrate`（`capture.BUS_PATH`）。

#### `check` —— 链路体检

```python
def check(self) -> str:
```

无参数。依次：`transport.check()`（不通过抛 `TransportError`）→ 读 flows 文件统计已捕获的导航响应条数。**返回**人话报告字符串，形如：

```
adb/设备/高德 OK;flows /tmp/amap.flows 可读, 已捕获 3 条导航响应
```

**异常**：`TransportError`（adb/设备/高德任一不过）、`CaptureError`（flows 文件不存在等）。只体检存量链路，不发实时查询。

## 传输层

### `Transport` —— 传输层协议（定义于 `amap/client.py`）

`AmapClient` 依赖的最小接口（`Protocol`，测试注入替身用）。自行实现传输层时需提供：

| 方法 | 签名 | 说明 |
|---|---|---|
| `check` | `check(self) -> None` | 链路体检，不通过抛异常 |
| `launch_route` | `launch_route(self, slat: float, slon: float, dlat: float, dlon: float, sname: str = "", dname: str = "", mode: str = "drive") -> float` | 触发一次路线查询，返回发出时刻的 unix 时间戳 |
| `set_clock` | `set_clock(self, ts: float) -> None` | 把设备时间设为 `ts`（unix 秒） |
| `restore_clock` | `restore_clock(self, ts: float) -> None` | 恢复设备时间为 `ts` |

### `DeepLinkTransport`（`amap/transport.py`，内部/高级）

通过 adb 向模拟器内的高德 App 发 `amapuri://route/plan/` URI。

```python
def __init__(self, adb: Optional[str] = None, device: str = DEVICE,
             connect: bool = True):
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `adb` | `Optional[str]` | `None`（用 `ADB_DEFAULT` = `~/android-sdk/platform-tools/adb`） | adb 可执行文件路径 |
| `device` | `str` | `DEVICE`（`"127.0.0.1:16384"`，MuMu 实例 0） | adb 设备地址 |
| `connect` | `bool` | `True` | 构造时即执行 `adb connect <device>` |

**方法**

| 方法 | 说明 |
|---|---|
| `check(self) -> None` | 体检：adb 存在 → 设备在线（`get-state`）→ 高德（`com.autonavi.minimap`）已安装；任一不过抛 `TransportError` |
| `set_clock(self, ts: float) -> None` | `settings put global auto_time 0` 后 `date @{int(ts)}`；设置失败抛 `TransportError`。需 root 的 adb。全局影响：模拟器上其他 App 也感知跳变，查询完必须恢复 |
| `restore_clock(self, ts: float) -> None` | 恢复时间并重新打开自动对时（`auto_time 1`） |
| `launch_route(self, slat: float, slon: float, dlat: float, dlon: float, sname: str = "", dname: str = "", mode: str = "drive") -> float` | 拼 URI 并 `am start` 触发，返回发出时刻的 unix 时间戳 |

`launch_route` 细节：

- `mode` 必须是 `MODES` 的键（`drive/bus/walk/bike/train`），否则抛 `TransportError`；`t` 参数取 `MODES[mode]`（drive=0/bus=1/walk=2/bike=3/train=4）。
- URI 参数：`dlat`/`dlon`/`dev=0`/`t` 必带；`sname`/`dname` 非空才带；`slat`/`slon` 为真值才带（置 0 即让 App 自行定位起点）。
- `am start` 输出异常或含 `Error` 抛 `TransportError`。

**适用场景**：仅作为 `AmapClient` 的默认传输层（后备通道）。`WebClient` 完全不经过它。

## 数据模型（`amap/models.py`）

pydantic `BaseModel`。原始 protobuf 字节只停留在 parser 的输入端，进入业务层即为本模块类型。

### `NavStep`

路线的一个路段（引导级，信息有限：道路名）。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `road` | `str` | `""` | 道路名（高速路名/隧道名等），解析不出为空 |
| `distance_m` | `int` | `0` | 路段距离（米），解析不出为 0 |
| `duration_s` | `int` | `0` | 路段历时（秒），解析不出为 0 |

各通道口径：Web v3 三字段都有值；App 抓包通道只解出 `road`（距离/历时为 0）；v4/etd 的 `duration_s` 恒为 0（用时在时间点上，不在 path 里）。

### `NavRoute`

一条备选路线（一次导航查询通常返回 2-4 条；Web v3 实时通常 1 条）。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `index` | `int` | 必填 | 方案序号（UI 上的 方案1/方案2） |
| `distance_m` | `int` | 必填 | 全程距离（米） |
| `duration_s` | `int` | 必填 | 全程历时（秒） |
| `toll_fen` | `int` | `0` | 过路费（**分**），0 = 无收费路段 |
| `currency` | `str` | `"CNY"` | 币种 |
| `steps` | `List[NavStep]` | `[]` | 路段列表 |

**property / 方法**

| 名称 | 返回 | 说明 |
|---|---|---|
| `distance_km` | `float` | 距离（公里）= `distance_m / 1000` |
| `duration_str` | `str` | 历时人话：`"1小时34分"`（有小时）/ `"34分钟"`（不足 1 小时） |
| `toll_yuan` | `float` | 过路费（元）= `toll_fen / 100` |
| `__str__` | `str` | 形如 `方案1: 82公里 1小时34分 过路费¥25`（无收费路段时省略过路费段） |

### `NavResult`

`nav_route()` 的返回。**可迭代**（迭代出 `NavRoute`）、支持 `len()` 与真值判断（`bool` = 有没有方案）。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `depart` | `str` | 必填 | 起点名（回填自查询参数） |
| `arrive` | `str` | 必填 | 终点名 |
| `mode` | `str` | `"drive"` | 出行方式（步行查询为 `"walk"`） |
| `depart_at` | `Optional[int]` | `None` | 未来用时：出发时刻（**unix 秒**），`None` = 现在 |
| `routes` | `List[NavRoute]` | `[]` | 方案列表 |

**方法**

| 名称 | 返回 | 说明 |
|---|---|---|
| `best()` | `Optional[NavRoute]` | 时间最短方案（按 `duration_s` 取 min）；无方案时 `None` |
| `summary()` | `str` | 多行人话报告。首行 `起点→终点(mode) 共N条方案`（未来用时追加 ` @ MM-DD HH:MM出发`，本地时区），其后每方案一行（两空格缩进 + `NavRoute.__str__`） |
| `__iter__` / `__len__` / `__bool__` | — | 迭代出 `NavRoute`；`len` = 方案数；`bool` = 方案非空 |

### `BusLeg`

公交方案的一个乘车段（步行段不在此列，仅计步行总距离）。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `line` | `str` | `""` | 线路名：城际形如 `城际(a--b)`、地铁形如 `地铁3号线(…)`、公交形如 `343路(…)`；服务端偶发把尾部括号翻倍（`城际(a--b)(a--b)`），解析时已自动去重 |
| `from_station` | `str` | `""` | 上车站 |
| `to_station` | `str` | `""` | 下车站 |
| `via_count` | `int` | `0` | 途经站数 |
| `headway` | `str` | `""` | 班距备注（如 `首站发车约8分钟/趟`）；仅 App 通道填充，Web 通道为空 |

**property / 方法**

| 名称 | 返回 | 说明 |
|---|---|---|
| `name` | `str` | 显示名：有线路名用线路名，否则 `上→下车站`（连上车站也没有则为空串） |
| `__str__` | `str` | 形如 `343路(A→B)[6站]`：`name` 后拼 `(上→下)`（上下车站都有才拼）与 `[N站]`（有途经站才拼） |

### `BusPlan`

一条公交方案（地铁/城际/公交，或客车/火车/打车直达）。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `duration_s` | `int` | 必填 | 全程历时（秒） |
| `walk_m` | `int` | `0` | 步行总距离（米） |
| `price` | `Optional[float]` | `None` | 票价（**元**）；公交组合方案可能无总价（`None`） |
| `tag` | `str` | `""` | 标签：`费用少` / `客车直达` / `火车直达` / `最快` 等（App 通道填充） |
| `note` | `str` | `""` | 实时备注（如 `城际…预计15:55到站`；App 通道填充） |
| `legs` | `List[BusLeg]` | `[]` | 换乘段列表（客车/火车/打车直达方案为空） |

**property / 方法**

| 名称 | 返回 | 说明 |
|---|---|---|
| `duration_str` | `str` | 同 `NavRoute.duration_str` 口径 |
| `walk_km` | `float` | 步行距离（公里）= `walk_m / 1000` |
| `__str__` | `str` | 形如 `2小时50分 步行3.384km ¥34.8 客车直达  城际(A→B)[2站]`：头段=历时+步行+票价+标签（有值才拼），尾段=各乘车段 `name` 用 `→` 相连；无乘车段时回退为 `note` 前 24 字 |

### `BusResult`

`bus_route()` 的返回。可迭代（迭代出 `BusPlan`）、`len()`、真值判断。注意方案数可能多于 App UI 展示的（UI 折叠了部分组合）。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `depart` | `str` | 必填 | 起点名 |
| `arrive` | `str` | 必填 | 终点名 |
| `plans` | `List[BusPlan]` | `[]` | 方案列表 |

**方法**

| 名称 | 返回 | 说明 |
|---|---|---|
| `best()` | `Optional[BusPlan]` | 时间最短方案；无方案时 `None` |
| `summary()` | `str` | 首行 `起点→终点(bus) 共N条方案`，其后每方案一行（两空格缩进） |
| `__iter__` / `__len__` / `__bool__` | — | 同 `NavResult` 语义 |

### `GeoPlace`

`geocode()` 的一个结果：地名 → 坐标。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `address` | `str` | 必填 | 省/市/区+POI 的完整地址 |
| `lng` | `float` | 必填 | 经度（GCJ-02） |
| `lat` | `float` | 必填 | 纬度（GCJ-02） |
| `citycode` | `str` | `""` | 城市区号（如 `020`） |

### `FutureEta`

`etd_table()` 的一个时间点：未来某时刻出发的驾车预估。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `depart_at` | `int` | 必填 | 出发时刻（**unix 秒**；按请求参数推算 firsttime + i×interval） |
| `duration_min` | `int` | 必填 | 预估用时（**分钟**） |
| `toll_yuan` | `float` | `0.0` | 预估过路费（**元**） |
| `restriction` | `int` | `0` | `0` = 无限行（或已规避）；`1` = 有限行无法规避 |

**方法**

| 名称 | 返回 | 说明 |
|---|---|---|
| `__str__` | `str` | 形如 `10-23 08:00 100分钟 过路费¥77`（本地时区；过路费为 0 时省略）；限行时追加 ` ⚠限行` |

### 常量 `MODES`

Deep Link 的出行方式 → `t` 参数值：`{"drive": 0, "bus": 1, "walk": 2, "bike": 3, "train": 4}`（`amap.transport` 内使用）。

## 内部/高级工具（一般用户不需要）

以下用于抓包解码与调试。行为基线：protobuf 无官方 schema，字段号由真实抓包对照 UI 验证（2026-10-21，com.autonavi.minimap 17.01.0.2012）。

### `amap.parser`

| 函数 | 签名 | 职责 |
|---|---|---|
| `wire_to_pb` | `wire_to_pb(raw: bytes) -> bytes` | HTTP 响应体（gzip）→ protobuf 明文。层级 `gzip → [64B 容器头 \| zstd 流] → protobuf`；容器头不是恒定 64 字节，按 zstd 魔数（`28 b5 2f fd`）定位。需 `zstandard` 库；魔数找不到抛 `ValueError`（格式可能已变化） |
| `parse_route_plan` | `parse_route_plan(pb: bytes) -> List[NavRoute]` | protobuf 明文 → 驾车方案列表，按方案出现顺序编号 `1,2,3…`。字段映射（wire 层记号）：顶层 `f2` = 方案集合容器 → `f7` = 方案详情（`f1` 距离，厘米，÷100 转米；`f4` 费用，内含 `1`＝分、`5`＝币种；`f7` 历时（秒）；`f10` repeated 路段，内含 `5→3`＝道路名）。乱字节宽容解析返回空/部分 |
| `parse_wire` | `parse_wire(raw: bytes) -> List[NavRoute]` | = `parse_route_plan(wire_to_pb(raw))`，即 `AmapClient.nav_route` 用的入口 |
| `parse_bus_wire` | `parse_bus_wire(raw: bytes) -> List[Any]` | 公交 `new_integrate` 响应 → `List[BusPlan]`（返回注解为 `List[Any]`，实际元素是 `BusPlan`）。结构：推荐方案为主列表，方案明细按「历时相同」挂回换乘段；无推荐列表（纯同城公交）时明细直接当方案；数字被序列化成字符串（`'10237'`），两种都收 |
| `walk` | `walk(data: bytes) -> Iterator[Field]` | 无 schema 解析 protobuf 字节流，yield `(字段号, 值)`。只处理 varint 与 length-delimited 两种 wire type，固定 32/64 位跳过。`Field = Tuple[int, Union[int, bytes]]` |
| `parse_flows_payload` | `parse_flows_payload(payload: Any) -> List[NavRoute]` | 测试替身注入用：直接吃 raw 响应字节（非 `bytes`/`bytearray` 抛 `TypeError`） |

### `amap.capture`

常量：`NAV_HOST = "nvg.amap.com"`、`NAV_PATH = "/ws/transfer/navigation/auto/"`、`BUS_PATH = "/ws/bus/plan/new_integrate"`。

| 函数 | 签名 | 职责 |
|---|---|---|
| `read_nav_responses` | `read_nav_responses(flows_path: str, after_ts: float = 0.0, path: str = NAV_PATH) -> List[Tuple[float, bytes]]` | 读 flows 文件，返回 `(请求时间戳, 响应原始字节)` 列表，只取 nvg 指定端点（按 host + path 前缀 + 时间过滤）。flows 被 mitmdump 追加写，流式读到文件尾即止。需 `mitmproxy` 库（缺失抛 `CaptureError`）；文件不存在抛 `CaptureError` |
| `wait_for_response` | `wait_for_response(flows_path: str, since_ts: float, timeout: float = 90.0, poll: float = 2.0, path: str = NAV_PATH) -> bytes` | 每 `poll` 秒轮询 flows，等出现晚于 `since_ts` 的导航响应，返回其中时间戳最新一条的响应字节；超时抛 `CaptureError`（提示检查 Deep Link/代理/CA/iptables 链路） |

**何时需要直接用**：想绕开 `AmapClient` 自行控制触发时机（例如手动在模拟器里点 UI）、离线重放/解析历史 flows、或调试解析器对新增字段的覆盖情况。

### `amap.web` 的解析函数（内部/高级）

v3/v4 JSON → 模型，独立成函数便于用真实夹具测试。`WebClient` 内部已调用，一般用户不需要：

| 函数 | 签名 | 职责 |
|---|---|---|
| `parse_web_drive` | `parse_web_drive(data: Dict[str, Any]) -> List[NavRoute]` | v3 驾车响应 → 方案列表（`route.paths`，每步取 road/distance/duration；`tolls` 元 → 分）。一次查询一个策略，通常 1 条 |
| `parse_web_transit` | `parse_web_transit(data: Dict[str, Any]) -> List[BusPlan]` | v3 公交响应 → 方案列表。步行距离跨段累加；`bus.buslines` 与 `railway` 都进 `legs`；线路名尾部括号翻倍自动去重 |
| `parse_web_walk` | `parse_web_walk(data: Dict[str, Any]) -> List[NavRoute]` | v3 步行响应 → 方案列表（直接复用 `parse_web_drive`，无费用） |
| `parse_etd` | `parse_etd(data: Dict[str, Any], firsttime: int, interval: int, count: int) -> tuple[List[NavRoute], List[FutureEta]]` | v4/etd 响应 → `(路线列表, 时刻预估列表)`。`time_infos` 每时刻取 `elements[0]` 的 `duration`（分钟）/`tolls`（元）/`restriction`；展示时刻按请求推算（firsttime + i×interval），响应 `starttime` 是毫秒且有偏移怪癖，不作时刻来源；path 的 `duration_s`/`toll_fen` 恒为 0 |

## 异常体系

全部直接继承 `Exception`（无公共基类）：

```
Exception
├── WebError            amap.web
├── CaptureErrorEmpty   amap.client
├── CaptureError        amap.capture
└── TransportError      amap.transport
```

| 异常 | 所属模块 | 触发条件 |
|---|---|---|
| `WebError` | `web` | Web 通道一切错误：未知策略；`depart_at`/`first` 非未来时间；`count` 不在 1-48；`interval_s ≤ 0`；网络失败（统一包装 urlopen 异常）；响应非 JSON；v3 `status≠1` / v4 `errcode≠0`（文案带 `info`/`errmsg` 与 `infocode`/`errcode`）；解析后没有方案 |
| `CaptureErrorEmpty` | `client` | App 通道：抓包响应解析成功但没有路线/公交方案（罕见，如坐标不可达） |
| `CaptureError` | `capture` | 抓包链路错误：缺 `mitmproxy` 库；flows 文件不存在（mitmdump 没跑）；轮询超时没等到导航响应 |
| `TransportError` | `transport` | 传输层错误：adb 不存在 / adb 超时；设备不在线；高德未安装；改时钟失败（`date` 设置失败）；`am start` 输出异常/失败；未知出行方式 |

另有三类非本体系异常会在特定路径抛出：`NotImplementedError`（`AmapClient.nav_route` 传了 `mode` ≠ `"drive"`）、`ValueError`（`wire_to_pb` 找不到 zstd 魔数）、`TypeError`（`parse_flows_payload` 收到非 bytes）。

## CLI 参考

```
python -m amap {route,etd,bus,walk,geo,check} ...
```

- 默认全部走 `WebClient`（纯 HTTP，零模拟器）；仅 `route --app` 切到 `AmapClient`（模拟器 Deep Link）。
- 编程入口：`amap.__main__.main(argv)`，签名 `def main(argv: Optional[List[str]] = None) -> int:`，`argv` 为子命令参数列表（如 `["route", "22.9208", …]`），返回退出码。
- 退出码：成功 `0`；运行出错向 stderr 打印 `错误: <原因>` 并返回 `1`（`etd` 无结果也返回 `1`）；参数不足/非法由 argparse 以非零码退出。
- 所有坐标为 GCJ-02；ISO 时刻格式如 `2026-10-22T08:00`。

### `route` —— 驾车路线

```
amap route [-h] [--strategy STRATEGY] [--app] [--depart TIME]
           slat slon sname dlat dlon dname
```

| 参数 | 说明 |
|---|---|
| `slat`（float） | 起点纬度 GCJ-02 |
| `slon`（float） | 起点经度 GCJ-02 |
| `sname` | 起点名（展示用） |
| `dlat`（float） | 终点纬度 GCJ-02 |
| `dlon`（float） | 终点经度 GCJ-02 |
| `dname` | 终点名（展示用） |
| `--strategy STRATEGY` | 路线偏好：`avoid_jam/cheap/fast/highway/no_highway/short/smart`（默认 `smart` 高德AI推荐）；或 v3 数字 `0/1/2/16/32`（数字串与 `int` 均可）。`no_highway` 返回 3 条备选方案 |
| `--depart TIME` | 未来用时：出发时刻（ISO）。默认走 v4/etd 未来预测（纯 HTTP）；必须为未来时刻 |
| `--app` | 强制走模拟器 Deep Link（多方案一次返回；与 `--depart` 组合时走模拟器改时钟，后备） |

前置条件：无（Web 纯 HTTP）；`--app` 需模拟器链路。

```bash
python -m amap route 22.9208 113.8903 起点 23.1066 113.3245 终点
python -m amap route 22.9208 113.8903 起点 23.1066 113.3245 终点 \
       --strategy cheap --depart 2026-10-22T08:00
```

输出：`NavResult.summary()`（首行含总方案数），随后打印「最快方案途经： …」——取 `best()` 的有名字路段（相邻去重，最多 8 个，凑满 8 个结尾加 `…`）：

```
起点→终点(drive) 共3条方案
  方案1: 82公里 1小时34分 过路费¥25
最快方案途经: 市政路 → 主干道 → 高速 → …
```

### `etd` —— 未来用时时刻表

```
amap etd [-h] [--interval INTERVAL] [--count COUNT] [--strategy STRATEGY]
         slat slon dlat dlon first
```

| 参数 | 说明 |
|---|---|
| `slat`（float）/ `slon`（float） | 起点纬度/经度 GCJ-02 |
| `dlat`（float）/ `dlon`（float） | 终点纬度/经度 GCJ-02 |
| `first` | 首时刻（ISO） |
| `--interval INTERVAL`（int） | 相邻时间点间隔秒数（默认 1800=半小时） |
| `--count COUNT`（int） | 时间点个数 1-48（默认 4） |
| `--strategy STRATEGY` | 同 `route`；v4/etd 仅避堵/免费两档，`cheap` 与 `no_highway` 走免费档 |

前置条件：无（Web 纯 HTTP）；`first` 必须为未来时刻。

```bash
python -m amap etd 22.9208 113.8903 23.1066 113.3245 2026-10-22T08:00 \
       --interval 7200 --count 4
```

输出（时刻为本地时区）：

```
出发时刻        预估用时      过路费
10-22 08:00   100分钟  ¥77
10-22 12:00    89分钟  ¥30
```

无结果时打印「没有返回时刻预估」并返回 `1`。

### `bus` —— 公交路线

```
amap bus [-h] [--city CITY] [--cityd CITYD] slat slon sname dlat dlon dname
```

| 参数 | 说明 |
|---|---|
| 位置参数同 `route` | 起终点坐标 + 名称 |
| `--city CITY` | 起点城市（一般不用传，服务端按坐标识别） |
| `--cityd CITYD` | 终点城市（跨城兜底用，一般不用传） |

前置条件：无。仅 Web 客户端（无 `--app`）。

```bash
python -m amap bus 22.9208 113.8903 起点 23.1066 113.3245 终点
```

输出：`BusResult.summary()`。

### `walk` —— 步行路线

```
amap walk [-h] slat slon sname dlat dlon dname
```

位置参数同 `route`；无选项。前置条件：无。仅 Web 客户端。

```bash
python -m amap walk 22.9208 113.8903 起点 22.9250 113.8950 附近
```

输出：`NavResult.summary()`（`mode="walk"`，单方案）。

### `geo` —— 地理编码

```
amap geo [-h] [--city CITY] address
```

| 参数 | 说明 |
|---|---|
| `address` | 地名 |
| `--city CITY` | 限定城市 |

前置条件：无。仅 Web 客户端。

```bash
python -m amap geo 地址
python -m amap geo 地址 --city 城市
```

输出：每行 `经度,纬度（各 6 位小数）  完整地址`。

### `check` —— 链路体检

```
amap check [-h]
```

无参数。前置条件：无（Web 部分纯 HTTP）。

```bash
python -m amap check
```

行为：先做 Web 体检（实调一次 geocode，必过，失败按异常兜底打印 `错误: …` 返回 `1`）；再体检模拟器 App 链路（**可选**，不可用时打印 `模拟器 App 链路不可用(未来用时需要它): <原因>`，不影响退出码 `0`）。

## 已知口径与注意事项（汇总）

- **单位口径**：`duration_s` 等历时字段一律秒；`duration_min`（FutureEta）为分钟；`toll_fen` 为分、`toll_yuan`/`price` 为元；`distance_m`/`walk_m` 为米、`*_km` 为公里；`depart_at` 类字段一律 unix 秒（本地展示时区）。
- **未来用时的时刻来源**：按请求参数推算（firsttime + i×interval），不信任响应 `starttime`。
- **v4/etd 免费档**：`cheap`/`no_highway` 在 v4/etd 通道映射免费档（strategy=2），实测零过路费、全程避开高速，用时代价约多三成；v3 通道无此语义。
- **风控**：两个客户端的 `min_interval`（Web 2s / App 8s）保持人类节奏，勿调低；`etd_table` 一次 48 点比改时钟低频得多。模拟器改时钟是全局副作用，偶发勿高频。
- **不可用项**（代码与 README 一致）：骑行（代理未开放）、逆地理 regeo（返回滑块验证页）、`AmapClient` 的步行/骑行（响应端点 `walkcloud` 未解析）。
- **策略参数**：`resolve_strategy` 接受三种形式——策略名、v3 数字（`int`）、数字字符串（CLI argparse 传来的 `"16"` 等，自动转 `int`）。
