# amap — 高德导航 App API

驾车路线查询(距离/历时/过路费/途经道路),数据来自高德 Android App
的真实导航接口 `nvg.amap.com/ws/transfer/navigation/auto/`。

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
```

```
松山湖→广州塔(drive) 共3条方案
  方案1: 82公里 1小时34分 过路费¥25
  方案2: 89公里 1小时48分
  方案3: 84公里 1小时35分 过路费¥30
最快方案途经: G4京港澳高速 → 鹤洲立交 → G2518深岑高速 → …
```

Python 侧:

```python
from amap import AmapClient
r = AmapClient().nav_route(22.9208, 113.8903, "松山湖",
                           23.1066, 113.3245, "广州塔")
best = r.best()          # 时间最短方案
best.distance_km, best.duration_s, best.toll_yuan
```

坐标为 GCJ-02(高德坐标系);起终点名仅用于展示。`--mode` 支持
drive/bus/walk/bike(驾车字段最完整,公交为聚合方案)。

## 节流

内置 `min_interval=8s`:导航查询远重于网页查询,保持人类节奏,
勿调低。查询由真实 App 发出,与手动操作无差异,但高频仍可能触发风控。

## 测试

13 tests(真实抓包夹具驱动:短途 3 方案 / 长途 2117km 2 方案),
mypy / pylint 全绿。
