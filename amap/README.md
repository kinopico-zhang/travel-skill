# amap — 高德路线查询(纯 Python)

驾车/公交/步行路线与地理编码查询,默认走 **Web 客户端**:
直调高德 H5(m.amap.com)的服务代理接口,纯 HTTP、零模拟器依赖。

```bash
pip install -e ./amap
python -m amap route 22.9208 113.8903 松山湖 23.1066 113.3245 广州塔
python -m amap bus  22.9208 113.8903 松山湖 23.1066 113.3245 广州塔
python -m amap walk 22.9208 113.8903 松山湖 22.9250 113.8950 松山湖北
python -m amap geo   广州塔
```

```
松山湖→广州塔(drive) 87公里 1小时33分 过路费¥77
最快方案途经: 沁园路 → 新城路 → G94珠三角环线高速 → …

松山湖→广州塔(bus) 共2条方案
  3小时3分 步行1.787km ¥9  343路(散裂中子源--松山湖北站微枢纽)→城际(惠州北--番禺)→地铁3号线(海傍--天河客运站)
  2小时51分 步行3.19km ¥12  轨道交通1号线(梅塘--东莞西站)→城际(惠州北--番禺)→地铁3号线(海傍--天河客运站)
```

Python 侧:

```python
from amap import WebClient
w = WebClient()
r = w.nav_route(22.9208, 113.8903, "松山湖", 23.1066, 113.3245, "广州塔")
best = r.best()                     # 时间最短方案
best.distance_km, best.duration_s, best.toll_yuan

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

驾车策略 `--strategy`:0 速度最快(默认)/ 1 费用最少 / 2 距离最短 /
32 默认;与 App 侧一次返回多方案不同,Web 版一次查询一个策略,
想比较就换 strategy 再查。

## 未来用时(depart_at,可选 App 模式)

Web 版查的是"现在出发"的路线,无未来用时。要查未来出发时刻的
预测,仍走 Deep Link 页面代理(需安卓模拟器):

```python
from amap import AmapClient
from datetime import datetime
r = AmapClient().nav_route(
    22.9208, 113.8903, "松山湖", 23.1066, 113.3245, "广州塔",
    depart_at=datetime(2026, 10, 22, 8, 0))
```

高德 Deep Link 无出发时间参数,UI 时间选择器是自绘弹窗点不开;
唯一入口是把**模拟器系统时间**改到目标时刻再触发查询,App 即以
该时刻向服务端请求预测(实测同一秒级对照,方案集按绝对时刻完全重算)。
查询完自动恢复真实时间。注意:改时间是全局副作用,模拟器上其他
App 也会感知跳变(开屏广告重弹、推送风暴),**偶发可用,勿高频**,
两次之间至少隔几分钟。模拟器侧的抓包配置见 docstring
(`amap/capture.py`,mitmproxy + iptables 掐直连)。

## 节流

Web 客户端内置 `min_interval=2s`(H5 页面一次查询连发数个请求,
2s 已明显保守于人手点按);App 客户端 `min_interval=8s`
(导航查询更重)。保持人类节奏,勿调低,高频可能触发风控。

## 测试

33 tests(真实响应夹具驱动:Web 驾车/公交/步行/地理编码 +
App 抓包驾车短途 3 方案/长途 2117km 2 方案/公交 7 方案含跨城直达),
mypy / pylint 全绿。
