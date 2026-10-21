#!/usr/bin/env python3
"""飞猪机票查询 python 库(纯 HTTP 直连 mtop H5 网关,零模拟器依赖)。

用法:
    from fliggy import FliggyClient
    fg = FliggyClient()
    r = fg.search("CAN", "PEK", "2026-12-26")
    print(r.summary())
"""

from .client import (API, APPKEY, FliggyClient, FliggyError,
                     MtopTransport, RateLimitedError)
from .models import Fare, Flight, Segment, SearchResult

__all__ = ["FliggyClient", "FliggyError", "MtopTransport",
           "RateLimitedError", "API", "APPKEY",
           "Flight", "Fare", "Segment", "SearchResult"]
