"""amap: 高德导航 API 客户端。

两个客户端,同一套模型:
- WebClient:纯 HTTP(H5 Web 服务代理),零模拟器依赖,默认选它;
  0.4.0 起未来用时(nav_route depart_at / etd_table)也走它(v4/etd);
- AmapClient:Deep Link 页面代理(模拟器 + mitmproxy),后备通道
  (多方案一次返回;depart_at 走模拟器改时钟的旧实现保留于此)。
"""
from .client import AmapClient
from .models import (BusLeg, BusPlan, BusResult, FutureEta, GeoPlace,
                     NavResult, NavRoute, NavStep)
from .web import WebClient

__all__ = ["AmapClient", "BusLeg", "BusPlan", "BusResult", "FutureEta",
           "GeoPlace", "NavResult", "NavRoute", "NavStep", "WebClient"]
__version__ = "0.4.0"
