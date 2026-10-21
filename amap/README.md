# amap — 高德路线查询(纯 Python)

驾车/公交/步行路线、地理编码与**未来用车时预估**查询,默认走
**Web 客户端**:直调高德 H5(m.amap.com)的服务代理接口,
纯 HTTP、零模拟器依赖。

```bash
pip install -e ./amap
python -m amap route 22.9208 113.8903 松山湖 23.1066 113.3245 广州塔
python -m amap route ... --strategy cheap           # 路线偏好(App 同款策略名)
python -m amap route ... --depart 2026-10-22T08:00      # 未来用车时(v4/etd 预测)
python -m amap etd   22.9208 113.8903 23.1066 113.3245 2026-10-22T08:00 \
           --interval 7200 --count 4                    # 未来时刻表(最多 48 点)
python -m amap bus  22.9208 113.8903 松山湖 23.1066 113.3245 广州塔
python -m amap walk 22.9208 113.8903 松山湖 22.9250 113.8950 松山湖北
python -m amap geo   广州塔
```

```
松山湖→广州塔(drive) 87公里 1小时33分 过路费¥77
最快方案途经: 沁园路 → 新城路 → G94珠三角环线高速 → …

松山湖→广州塔(drive) 共1条方案 @ 10-22 08:00出发
  方案1: 87公里 1小时40分 过路费¥77

出发时刻        预估用时      过路费
10-22 08:00   100分钟  ¥77
10-22 10:00    99分钟  ¥25
10-22 12:00    89分钟  ¥30
```

Python 侧:

```python
from datetime import datetime
from amap import WebClient
w = WebClient()
r = w.nav_route(22.9208, 113.8903, "松山湖", 23.1066, 113.3245, "广州塔")
best = r.best()                     # 时间最短方案
best.distance_km, best.duration_s, best.toll_yuan

r = w.nav_route(..., strategy="cheap")   # 费用优先(免费路线,零过路费)

# 未来某时刻出发:按该时刻路况预估用时/过路费(v4/etd)
r = w.nav_route(22.9208, 113.8903, "松山湖", 23.1066, 113.3245, "广州塔",
                depart_at=datetime(2026, 10, 22, 8, 0))

# 未来时刻表:一次返回 count 个时间点(改时钟方案要一个点一个点查,
# 这里一次请求全出)
etas = w.etd_table(22.9208, 113.8903, 23.1066, 113.3245,
                   datetime(2026, 10, 22, 8, 0), interval_s=3600, count=12)

b = w.bus_route(22.9208, 113.8903, "松山湖", 23.1066, 113.3245, "广州塔")
b.best().legs                       # 换乘段:线路名/上下车站/途经站数

g = w.geocode("广州塔")             # 地名 → 坐标列表
```

坐标为 GCJ-02(高德坐标系);起终点名仅用于展示。

## Web 客户端原理

高德官网 JS API 有两种接法:直连 `restapi.amap.com` 需要
key + 安全密钥(jscode)成对签名;或者配服务代理 ——
m.amap.com(H5 版)页面源码里就是后者:

```js
window._AMapSecurityConfig = {serviceHost: "https://m.amap.com/_AMapService"}
```

浏览器里的所有查询都经这个代理转发,密钥由 m.amap.com 服务端代持。
所以带上 H5 页面公开的 JS key、`platform=JS` 参数与 `Referer: https://m.amap.com/`
即可直调 `https://m.amap.com/_AMapService/v3/...`,与在手机浏览器里
用 m.amap.com 查路线完全等价。高德 App native 接口(`in=` 签名 + 密文 body)
在这里不存在 —— 这是全链路里唯一不需要模拟器的入口。

可用端点:驾车 v3(每步道路名含市政路/过路费/打车参考价)、
公交 v3(方案/换乘段/票价/步行,含城际铁路与地铁,**city/cityd
城市参数可不传**,跨城查询服务端按坐标识别)、步行 v3、地理编码 v3。
不可用:骑行(代理未开放)、逆地理 regeo(返回滑块验证页)。

驾车策略即上面的「路线偏好」;与 App 侧一次返回多方案不同,v3 一次
查询一个策略(`no_highway` 例外,返回 3 条备选),想比较就换策略再查。

## 路线偏好(strategy,App 同款)

`strategy` 用高德 App「路线偏好」同款策略名,两个通道各自映射到
该通道实际支持的值(实测 v3 代理认 0/1/2/16/32,其余值归默认;
v4/etd 只有避堵/免费两档,其余值全归这两档):

| 策略名 | App 名称 | v3(实时) | v4/etd(未来) |
|---|---|---|---|
| `smart`(默认) | 高德AI推荐 | 32 默认 | 1 躲避拥堵 |
| `fast` | 时间优先 | 0 速度优先 | 1 |
| `cheap` | 费用优先 | 1 费用优先 | 2 免费 |
| `short` | 距离优先 | 2 距离优先 | 1(近似) |
| `no_highway` | 不走高速 | 16(返回 3 条备选) | 2 免费 |
| `avoid_jam` | 躲避拥堵 | 32(v3 无独立值) | 1 |
| `highway` | 高速优先 | 0(v3 无独立值) | 1 |

也可直接传 v3 数字。App 里的「大路优先」两个通道都没有对应值,未收录。
免费档实测零过路费、全程避开高速,代价是用时明显变长(长途约多三成)。

## 未来用车时(v4/etd,纯 HTTP)

`depart_at` / `etd_table` 走高德 **v4/etd 驾车预估接口**(官方文档标称
企业限定):传未来首时刻 `firsttime` + 间隔 `interval` + 个数 `count`
(≤48),一次返回每个时间点按当时路况预估的用时与过路费。
实测早高峰(08:00)100 分钟 ¥77、午间(12:00)89 分钟 ¥30 ——
预测真实生效,不是套用实时路况。

入口仍是服务代理,但换了宿主:m.amap.com 的代理对 v4/etd 返回
`10009 USERKEY_PLAT_NOMATCH`,而**桌面版 ditu.amap.com 的同款代理
有 v4/etd 权限**(页面公开 JS key,`platform=JS` 通行,与 v3 同机制)。
细节见 `amap/web.py` 的 docstring。

注意:`depart_at` 必须是未来时间;`etd_table` 一个请求出 48 个点,
比改时钟方案(一点一查)低频得多,风控友好。时刻以请求参数推算
(firsttime + i×interval)为准 —— 响应里的 starttime 是毫秒且
存在偏移怪癖,不作展示来源。

`--strategy cheap` / `strategy="cheap"`:免费路线(v4/etd 免费档,
实测零过路费、全程避开高速;代价是用时明显变长,长途约多三成)。
官方位掩码 16/17(不走高速)v4/etd 不认,传了等同默认策略。

### 模拟器改时钟(后备,--app)

`AmapClient().nav_route(..., depart_at=...)` 走 Deep Link 页面代理
(需安卓模拟器):高德 Deep Link 无出发时间参数,UI 时间选择器是
自绘弹窗点不开;唯一入口是把**模拟器系统时间**改到目标时刻再触发
查询。查询完自动恢复真实时间。改时间是全局副作用,偶发可用勿高频。
模拟器侧抓包配置见 `amap/capture.py`(mitmproxy + iptables 掐直连)。

## 节流

Web 客户端内置 `min_interval=2s`(H5 页面一次查询连发数个请求,
2s 已明显保守于人手点按);App 客户端 `min_interval=8s`
(导航查询更重)。保持人类节奏,勿调低,高频可能触发风控。

## 测试

42 tests(真实响应夹具驱动:Web 驾车/公交/步行/地理编码 +
v4/etd 未来用车时 + App 抓包驾车短途 3 方案/长途 2117km 2 方案/
公交 7 方案含跨城直达),mypy / pylint 全绿。
