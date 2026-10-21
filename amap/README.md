# amap — 高德导航 App API

驾车与公交路线查询(距离/历时/过路费/途经道路/换乘方案),
数据来自高德 Android App 的真实导航接口:
驾车 `nvg.amap.com/ws/transfer/navigation/auto/`,
公交 `nvg.amap.com/ws/bus/plan/new_integrate`。

## 模式:Deep Link 页面代理

高德 App 的请求体是阿里 securityguard 加密的(`in=` 参数 + 密文 body),
自主构造不现实;但**响应不加密**(gzip → zstd → protobuf),完全可读。
因此本库让模拟器里的 App 替我们发起查询,响应从抓包层解析:

```
AmapClient.nav_route() ──adb──▶ amapuri://route/plan Deep Link
                                    │ 高德 App 生成加密请求(真实用户栈)
                                    ▼
                          mitmproxy 捕获 nvg 响应
                                    ▼
                       gzip → zstd → protobuf → NavResult
```

## 前提(一次性配好)

1. MuMu 模拟器开着,高德已安装并同意过隐私政策(不登录也能导航);
2. `mitmdump -w /tmp/amap.flows --listen-host 0.0.0.0 --listen-port 8080 --set block_global=false`;
3. 模拟器 `settings put global http_proxy <本机IP>:8080`,且系统 CA 区
   信任 mitmproxy CA(tmpfs 覆盖法,详见 didi 抓包笔记);
4. **关键**:模拟器内 iptables 掐直连,否则高德 HTTPDNS 解析后直连绕过代理:
   ```
   iptables -A OUTPUT -p tcp -d 192.168.0.0/16 -j ACCEPT
   iptables -A OUTPUT -p tcp -d 10.0.2.0/24 -j ACCEPT
   iptables -A OUTPUT -p tcp -j DROP
   ```
   模拟器重启后 3、4 需重做;掐直连后 App 启动变慢(约 90s)属正常。

## 用法

```bash
uv pip install -e ./amap --extra capture     # pydantic + mitmproxy + zstandard
python -m amap check                         # 链路体检
python -m amap route 22.9208 113.8903 松山湖 23.1066 113.3245 广州塔
python -m amap bus  22.9208 113.8903 松山湖 23.1066 113.3245 广州塔
python -m amap route … --depart 2026-10-22T08:00   # 未来出发时刻
```

```
松山湖→广州塔(drive) 共3条方案
  方案1: 82公里 1小时34分 过路费¥25
  方案2: 89公里 1小时48分
  方案3: 84公里 1小时35分 过路费¥30
最快方案途经: G4京港澳高速 → 鹤洲立交 → G2518深岑高速 → …

松山湖→广州塔(bus) 共5条方案
  2小时48分 步行3.4km 费用少  轨道交通1号线(梅塘--东莞西站)→城际(惠州北--番禺)→地铁3号线(海傍--天河客运站)
  2小时33分 ¥34.8 最快
  2小时41分 ¥46 火车直达
```

Python 侧:

```python
from amap import AmapClient
am = AmapClient()
r = am.nav_route(22.9208, 113.8903, "松山湖", 23.1066, 113.3245, "广州塔")
best = r.best()          # 时间最短方案
best.distance_km, best.duration_s, best.toll_yuan

b = am.bus_route(22.9208, 113.8903, "松山湖", 23.1066, 113.3245, "广州塔")
b.best().legs            # 换乘段:线路名/上下车站/途经站数/班距
```

坐标为 GCJ-02(高德坐标系);起终点名仅用于展示。
步行/骑行的响应端点(`walkcloud`)未解析,暂不支持。

## 未来用时(depart_at)

高德 Deep Link 无出发时间参数,UI 时间选择器是自绘弹窗点不开;
唯一入口是把**模拟器系统时间**改到目标时刻再触发查询,App 即以
该时刻向服务端请求预测(实测同一秒级对照,方案集按绝对时刻完全重算)。

```python
from datetime import datetime
r = am.nav_route(…, depart_at=datetime(2026, 10, 22, 8, 0))
```

查询完自动恢复真实时间(auto_time=1)。注意:改时间是全局副作用,
模拟器上其他 App 也会感知跳变(开屏广告重弹、推送风暴),**偶发可用,
勿高频**,两次之间至少隔几分钟。

## 节流

内置 `min_interval=8s`:导航查询远重于网页查询,保持人类节奏,
勿调低。查询由真实 App 发出,与手动操作无差异,但高频仍可能触发风控。

## 测试

23 tests(真实抓包夹具驱动:驾车短途 3 方案 / 长途 2117km 2 方案 /
公交 7 方案含跨城直达),mypy / pylint 全绿。
