# ctrip — 携程 H5 机票/火车票查询 python 库

CDP 页面代理模式:所有请求在模拟器浏览器的 `m.ctrip.com` 页面上下文里发出,
与真人操作完全同栈,继承登录态与风控上下文。

## 为什么是页面代理

携程 WAF(`{"actionType":"login"}` / HTTP 432)校验 TLS/环境指纹:
- WSL 直连(urllib / curl_cffi chrome124 + 全量 cookie)一律 432
- 页面内 `fetch()` 一律 200(即使不带 mystery/sessionId 等风控字段)

## 依赖

- MuMu 模拟器开着,`com.android.browser` 停在 m.ctrip.com 任意页面
- `adb forward tcp:9222 localabstract:webview_devtools_remote_<pid>`
  (pid 变化要重新 forward;浏览器 force-stop 后会变)
- 浏览器被切到后台时 fetch 可能挂起——`am start -a android.intent.action.VIEW -d <url> com.android.browser` 拉回前台

## 用法

已 editable 安装:`~/.venv/bin/python`(依赖 `pydantic>=2`、`websocket-client`)。

```python
from ctrip import CtripClient

ct = CtripClient()

# 航班列表(单程经济舱)
r = ct.search("SZX", "HAK", "2026-10-25")
print(r.summary())
for f in r.sorted_by_price()[:5]:
    print(f.flight_no, f.dep_time, f.arr_time, f.price, f.cheapest.quantity)
    for fare in f.fares:
        print("   ", fare.grade, fare.price, fare.cabin_code, fare.discount)

# 低价日历(今天起 377 天) —— List[DailyPrice],按日期升序
cal = ct.low_price_calendar("SZX", "HAK")
print(cal[0].date, cal[0].price)

# 城市码(内置 36 城,未知自动 fuzzySearch 并缓存 ~/.ctrip_cities.json)
c = ct.city("KHN")               # City(code="KHN", name="南昌", id="376")
print(c.name, c.id)

# 火车票车次查询(免登录;城市名或站名均可)
tr = ct.train_search("上海", "北京", "2026-10-22")
print(len(tr), "班,可订", len(tr.bookable()))
for t in list(tr)[:3]:           # Train: 车次/站名/时刻/历时/坐席价格
    print(t.train_number, t.depart_station, "→", t.arrive_station,
          t.depart_time, "-", t.arrive_time, t.duration, t.cheapest)
```

注意城市码不是机场码:北京=BJS、成都=CTU、西安=SIA、上海=SHA。
测试 26 个(`pytest -q`),mypy/pylint 全绿。

## 接口清单

| 功能 | 端点 | 状态 |
|---|---|---|
| 航班列表 | `soa2/14488/flightListSearchForH5` | ✅(易限流) |
| 火车票车次 | `soa2/14666/json/GetBookingByStationV3` | ✅ **免登录** |
| 低价日历 | `soa2/15380/FlightIntlAndInlandLowestPriceSearch` | ✅(377天,基本不限) |
| 城市/机场模糊查询 | `soa2/19691/airportFuzzySearch` | ✅(基本不限) |
| 登录-发短信 | `soa2/24863/sendVerifyCodeByMobilePhone` | 已抓包(见 `~/travel-skill/ctrip/scripts/ctrip_login.py`) |
| 登录-验证码 | `soa2/22160/verifyCodeLogin` → cticket cookie 90 天 | 已抓包 |

## 会话保活

**携程无需保活**:登录态(cticket/login_uid/DUID, 2026-10-20 登录, 至 2027-01-18)
是 90 天签名的 ticket,不依赖服务端 session;模拟器浏览器的 cookie 存盘持久
(force-stop 重启也不丢)。机票查询走页面 fetch 连登录都不需要。

```bash
python -m ctrip cookies    # 体检: 列出全部 cookie 过期时间 + cticket 剩余天数
```

过期前用 `~/travel-skill/ctrip/scripts/ctrip_login.py` 重登一次(短信验证码)即可,90 天一次。

## 风控要点

- **flightListSearchForH5 高频(约 >10 次/几分钟)触发 432 限流**,连浏览器
  UI 自己也会被拦,冷却 10-30 分钟恢复。库默认 `min_interval=2.5s`,
  批量扫描请再加长。
- 日历/城市接口宽松得多,可放心批量。
- 公务舱(seat=1)请求在限流期间同样 432;冷却后行为待观察。
- 触发限流的典型信号:页面 fetch 返回 432、Response body 已被预读。

## 已知限制

- 只封装了单程经济舱(seat=0);往返/公务舱参数已摸清(seat/sgrade=1)但
  未验证稳定性。
- SearchResult 按 policyinfo 解析多等级报价,`f.fares` 里含经济/超经/公务。
