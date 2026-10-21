#!/usr/bin/env python3
"""携程机票/火车票查询 python 库(纯 HTTP 直连,零模拟器依赖)。

用法:
    from ctrip import CtripClient
    ct = CtripClient()
    r = ct.search("SZX", "HAK", "2026-10-25")
    print(r.summary())
    cal = ct.low_price_calendar("SZX", "HAK")   # List[DailyPrice]
"""

from .client import (CDPProxy, CtripClient, CtripError, HttpProxy,
                     IntlNavProxy, RateLimitedError, HOME)
from .models import (City, CookieEntry, DailyPrice, Fare, Flight,
                     IntlFlight, IntlSearchResult, IntlSegment, Segment,
                     SearchResult, Train, TrainSearchResult, TrainSeat)

__all__ = ["CDPProxy", "HttpProxy", "IntlNavProxy", "CtripClient",
           "CtripError", "RateLimitedError",
           "Flight", "Fare", "Segment", "SearchResult",
           "IntlFlight", "IntlSegment", "IntlSearchResult",
           "Train", "TrainSeat", "TrainSearchResult",
           "City", "CookieEntry", "DailyPrice", "HOME"]
