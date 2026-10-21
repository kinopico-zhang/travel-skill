"""国航 H5 (m.airchina.com.cn) API 客户端库。

- 奖励客票查询(里程票):AirChinaClient.award_search
- 现金票低价日历:AirChinaClient.low_price_calendar
- 里程/账户概要:AirChinaClient.mileage_summary

登录(短信+滑块)在浏览器里做一次,会话从 mitmproxy 抓包导入:
    AirChinaClient.from_flows("/tmp/airchina.flows")
"""
from .client import AirChinaClient
from .errors import (AirChinaError, ApiError, CaptchaRequiredError,
                     CookieExpiredError, WafBlockedError)
from .models import (AwardCabin, AwardFlight, AwardResult, DailyPrice,
                     DayAward, MileageSummary)
from .session import DEFAULT_FLOWS, DEFAULT_SESSION_FILE, Identity, Session

__version__ = "0.2.0"
__all__ = [
    "AirChinaClient", "Session", "Identity",
    "AwardResult", "AwardFlight", "AwardCabin", "DayAward",
    "DailyPrice", "MileageSummary",
    "AirChinaError", "ApiError", "CaptchaRequiredError",
    "CookieExpiredError", "WafBlockedError",
    "DEFAULT_FLOWS", "DEFAULT_SESSION_FILE",
]
