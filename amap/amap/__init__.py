"""amap: 高德导航 API 客户端。

两个客户端,同一套模型:
- WebClient:纯 HTTP(H5 Web 服务代理),零模拟器依赖,默认选它;
- AmapClient:Deep Link 页面代理(模拟器 + mitmproxy),未来用时专用。
"""
from .client import AmapClient
from .models import (BusLeg, BusPlan, BusResult, GeoPlace, NavResult,
                     NavRoute, NavStep)
from .web import WebClient

__all__ = ["AmapClient", "BusLeg", "BusPlan", "BusResult", "GeoPlace",
           "NavResult", "NavRoute", "NavStep", "WebClient"]
__version__ = "0.3.0"
