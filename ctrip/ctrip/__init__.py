#!/usr/bin/env python3
"""携程 H5 机票查询 python 库(CDP 页面代理模式)。

用法:
    from ctrip import CtripClient
    ct = CtripClient()
    r = ct.search("SZX", "HAK", "2026-10-25")
    print(r.summary())
    cal = ct.low_price_calendar("SZX", "HAK")   # List[DailyPrice]
"""

from .client import (CDPProxy, CtripClient, CtripError, RateLimitedError,
                     HOME)
from .models import (City, CookieEntry, DailyPrice, Fare, Flight, Segment,
                     SearchResult, Train, TrainSearchResult, TrainSeat)

__all__ = ["CDPProxy", "CtripClient", "CtripError", "RateLimitedError",
           "Flight", "Fare", "Segment", "SearchResult",
           "Train", "TrainSeat", "TrainSearchResult",
           "City", "CookieEntry", "DailyPrice", "HOME"]
