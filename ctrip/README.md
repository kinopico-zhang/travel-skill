# ctrip — 携程机票/火车票查询 python 库（纯 HTTP 直连，零模拟器）

v1.0.0：传输层从 CDP 页面代理升级为 **纯 HTTP 直连** —— App 网关头过 WAF，
不再依赖 MuMu 模拟器/浏览器 tab。CDPProxy 保留为可选后备（登录态维护用）。

## CLI 用法

```bash
# 火车票车次查询（免登录；城市名或站名均可，日期缺省为今天）
python -m ctrip train DEPART ARRIVE [DATE] [--student]
# 登录态体检（走 CDP，需要模拟器浏览器开着）
python -m ctrip cookies
```

| 子命令 | 参数说明 |
|---|---|
| `train` | `DEPART`/`ARRIVE` 出发/到达城市名或站名；`DATE` 为 `YYYY-MM-DD`（缺省今天）；`--student` 学生票 |
| `cookies` | 无参数；列出 m.ctrip.com 全部 cookie 及过期时间，cticket 剩余天数 |

```bash
python -m ctrip train 上海 北京 2026-11-20
python -m ctrip train 上海虹桥 北京南                 # 日期缺省为今天
python -m ctrip train 上海 北京 2026-11-20 --student
```

## 为什么直连能过

携程 WAF 的 432 是**请求头组合识别**，不是 TLS 指纹：
- 同一「浏览器 UA」请求经 mitmproxy（python OpenSSL 栈）转发照样 432 —— 排除 TLS 指纹论
- 补上 App 网关头（`x-ctx-*`/`x-trip-*`/`x-traceid` + `_CtripAPP` UA 后缀）后，
  urllib 裸连即 200
- head 里 auth/cid 全零 + `appid=99999999`（携程 Android 网关公共 appid），
  查询接口不依赖登录态

## 依赖

- `pydantic>=2` 直连必需；`websocket-client` 仅 CDP 后备用
- 已 editable 安装：`~/.venv/bin/python`

## Python 用法

```python
from ctrip import CtripClient

ct = CtripClient()               # 默认 HttpProxy，直连

# 航班列表（单程经济舱）
r = ct.search("SZX", "HAK", "2026-10-25")
print(r.summary())
for f in r.sorted_by_price()[:5]:
    print(f.flight_no, f.dep_time, f.arr_time, f.price, f.cheapest.quantity)
    for fare in f.fares:
        print("   ", fare.grade, fare.price, fare.cabin_code, fare.discount)

# 低价日历（今天起 ~377 天） —— List[DailyPrice]，按日期升序
cal = ct.low_price_calendar("SZX", "HAK")
print(cal[0].date, cal[0].price)      # price＝票面（国际线不含税）
print(cal[0].total)                   # total＝含税总价（totalPrice），比价用这个

# 城市码（内置 36 城，未知自动 fuzzySearch 并缓存 ~/.ctrip_cities.json）
c = ct.city("KHN")               # City(code="KHN", name="南昌", id="376")
print(c.name, c.id)

# 火车票车次查询（免登录；城市名或站名均可）
tr = ct.train_search("上海", "北京", "2026-10-22")
print(len(tr), "班，可订", len(tr.bookable()))
for t in list(tr)[:3]:           # Train：车次/站名/时刻/历时/坐席价格
    print(t.train_number, t.depart_station, "→", t.arrive_station,
          t.depart_time, "-", t.arrive_time, t.duration, t.cheapest)

# CDP 后备通道（需要模拟器；列表 432 长期限流时换它）
from ctrip import CDPProxy
ct2 = CtripClient(proxy=CDPProxy())
```

注意城市码不是机场码：北京=BJS、成都=CTU、西安=SIA、上海=SHA。
测试 35 个（`pytest -q`），mypy/pylint 全绿。

## 接口清单

| 功能 | 端点 | 状态 |
|---|---|---|
| 航班列表 | `soa2/14488/flightListSearchForH5` | ✅ 直连（易限流） |
| 火车票车次 | `soa2/14666/json/GetBookingByStationV3` | ✅ **免登录** |
| 低价日历 | `soa2/15380/FlightIntlAndInlandLowestPriceSearch` | ✅（377 天，基本不限） |
| 城市/机场模糊查询 | `soa2/19691/airportFuzzySearch` | ✅（基本不限） |
| 登录-发短信 | `soa2/24863/sendVerifyCodeByMobilePhone` | 已抓包（见 `ctrip/scripts/ctrip_login.py`，走 CDP） |
| 登录-验证码 | `soa2/22160/verifyCodeLogin` → cticket cookie 90 天 | 已抓包 |

## 会话

**查询完全免登录**；会员价相关字段需要登录态（cticket，2026-10-20 登录，
至 2027-01-18）。cticket 是 90 天签名 ticket，不依赖服务端 session。

```bash
python -m ctrip cookies    # 体检（走 CDP；需要模拟器浏览器开着）
```

过期前用 `ctrip/scripts/ctrip_login.py` 重登一次（短信验证码）即可，90 天一次。

## 风控要点

- **flightListSearchForH5 高频（约 >10 次/几分钟）触发 432 限流**，冷却
  10-30 分钟恢复。库默认 `min_interval=2.5s`，批量扫描请再加长
  （限流时可用 CDPProxy 后备，页面内 fetch 走浏览器风控上下文）。
- 日历/城市接口宽松得多，可放心批量。
- 直连通道请求节奏尽量贴近真人（库已内置节流）。

## 已知限制

- 只封装了单程经济舱（seat=0）；往返/公务舱参数已摸清（seat/sgrade=1）但
  未验证稳定性。
- SearchResult 按 policyinfo 解析多等级报价，`f.fares` 里含经济/超经/公务。
- 列表响应尾部可能混有「邻近城市/日期推荐」条目（flight_no 为空但有真实
  报价，如邻近机场出发的替代方案），按需自行过滤 `f.flight_no`。
