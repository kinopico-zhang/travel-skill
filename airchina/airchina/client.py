"""AirChinaClient —— 国航 H5 查询接口客户端。

只依赖标准库(urllib)+ pydantic。注意两件事:

1. 必须用 python 的 HTTP 栈直连 —— curl 的 TLS 指纹会被网宿 WAF
   302 到 /500.html,python urllib 实测可过。
2. Cookie 必须带全 SESSION + JSESSIONID(只带 SESSION 会返回登录 HTML)。
   两者都是会话级,模拟器浏览器进程退出即失效,需重登后更新会话文件。

传输边界豁免:`_post` 的返回值是服务端原始 JSON(dict),这是唯一的
dict 使用点 —— 各接口拿到后立即解析成 models 里的 pydantic 类型。
"""
from __future__ import annotations

import datetime
import gzip
import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Union

from .errors import (AirChinaError, ApiError, CaptchaRequiredError,
                     CookieExpiredError, WafBlockedError)
from .models import AwardResult, DailyPrice, MileageSummary
from .session import DEFAULT_FLOWS, DEFAULT_SESSION_FILE, Session

_SUCCESS = "00000000"

_USER_AGENT = ("Mozilla/5.0 (Linux; Android 12; CET-AL00 Build/V417IR) "
               "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
               "Chrome/83.0.4103.120 Mobile Safari/537.36")


class AirChinaClient:
    """用法::

        from airchina import AirChinaClient
        ac = AirChinaClient.load()                # ~/.airchina/session.json
        r = ac.award_search("CAN", "PEK", "2026-10-21")
        for f in r.flights:
            print(f.flight_no, f.dep_time, f.mileage_price)
    """

    BASE = "https://m.airchina.com.cn"
    AWARD_URL = BASE + "/ac/f/invoke.json"          # a=12 p=47 奖励客票
    CALENDAR_URL = BASE + "/g/invoke.json"          # a=0  p=0  低价日历(现金)
    ACCOUNT_URL = BASE + "/ac/g/invoke.json"        # a=8  p=34 里程/账户
    AWARD_REFERER = (BASE + "/ac/c/invoke/awardTickets/"
                     "showAwardTicketsFlights@pg?from=booking")

    def __init__(self, session: Session, timeout: int = 30):
        self.session = session
        self.timeout = timeout

    # ------------------------------------------------------------------ 构造
    @classmethod
    def load(cls, path: str = DEFAULT_SESSION_FILE,
             **kw: Any) -> "AirChinaClient":
        return cls(Session.load(path), **kw)

    @classmethod
    def from_flows(cls, flows_path: str = DEFAULT_FLOWS,
                   save_to: Optional[str] = DEFAULT_SESSION_FILE,
                   **kw: Any) -> "AirChinaClient":
        """从 mitmproxy 抓包提取会话(顺带保存到会话文件)。"""
        s = Session.from_flows(flows_path)
        if save_to:
            s.save(save_to)
        return cls(s, **kw)

    # ------------------------------------------------------------------ 传输
    def _post(self, url: str, a: Any, p: Any, req: Dict[str, Any],
              m_extra: Optional[Dict[str, Any]] = None,
              referer: Optional[str] = None,
              check_token: str = "") -> Dict[str, Any]:
        m: Dict[str, Any] = {
            "req": json.dumps(req, ensure_ascii=False),
            "token": "h5001",
            "lang": "zh_CN",
            "type": "checkN",
            "userInfo1": "75200",
            "userID": self.session.identity.user_id,
            "infoID": self.session.identity.info_id,
        }
        if check_token:
            m["checkToken"] = check_token
        if m_extra:
            m.update(m_extra)
        body = json.dumps({"m": m, "a": str(a), "p": str(p)},
                          ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=body, method="POST")
        request.add_header("Content-Type", "application/json; charset=UTF-8")
        request.add_header("Origin", self.BASE)
        request.add_header("Referer", referer or self.BASE + "/")
        request.add_header("User-Agent", _USER_AGENT)
        request.add_header("Accept-Encoding", "gzip")
        request.add_header("Cookie", self.session.cookies)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip" \
                        or raw[:2] == b"\x1f\x8b":
                    raw = gzip.decompress(raw)
                final_url = r.geturl()
        except urllib.error.HTTPError as e:
            raise AirChinaError(f"HTTP {e.code} {e.reason} ({url})") from e
        if "/500.html" in final_url:
            raise WafBlockedError(f"被 WAF 拦截 -> {final_url};稍等几分钟再试,"
                                  "或确认没有用 curl/requests 之外的 HTTP 栈")
        if raw[:1] == b"<":
            raise CookieExpiredError(
                "返回了 HTML(登录页):Cookie 失效。重新在模拟器浏览器登录后,"
                "运行 airchina session --from-flows 更新会话")
        try:
            data: Dict[str, Any] = json.loads(raw)
        except ValueError as e:
            raise AirChinaError(f"响应不是 JSON(head={raw[:80]!r})") from e
        if data.get("risky") is True:
            raise CaptchaRequiredError(
                "服务端要求滑块验证;需浏览器过码拿 checkToken 后重试")
        return data

    # ------------------------------------------------------------------ 接口
    def award_search(self, org: str, dst: str, date: str, *,
                     return_date: Optional[str] = None,
                     cabin: str = "X", adults: int = 1, children: int = 0,
                     flag: str = "D", check_token: str = "",
                     carrier: str = "CA") -> AwardResult:
        """里程奖励客票查询(a=12 p=47)。

        org/dst 三字码,date YYYY-MM-DD。cabin: "X"=经济舱奖励票,
        "0"=不限。return_date 传入则查往返。flag: "D" 国内 / "I" 国际。
        carrier: 承运航司二字码,"CA" 国航 / "ZH" 深航 / "SC" 山航,
        星盟成员(NH/UA/LH/OZ/SQ/TG...)国际线可用;空串行为未验证。
        无可兑换航班时返回空 AwardResult(message 里带服务端提示)。
        """
        trip = "RT" if return_date else "OW"
        req: Dict[str, Any] = {
            "queryTripType": trip,
            "orgCity": org, "dstCity": dst,
            "orgCityName": "", "dstCityName": "",
            "leaveDate": date, "returnDate": return_date or "",
            "adultTravelers": str(adults), "childTravelers": str(children),
            "cabin": cabin,
            "carrierAirline": carrier, "airCarrier": carrier, "operType": "0",
            "flag": flag,
            "tabFlag": "1" if return_date else "0",
            "userId": self.session.identity.user_id,
            "mId": "",
            "mainVipCard": self.session.identity.main_vip_card,
        }
        data = self._post(
            self.AWARD_URL, 12, 47, req,
            m_extra={"page": "awardTicket",
                     "crmMemberId": self.session.identity.crm_member_id},
            referer=self.AWARD_REFERER, check_token=check_token)
        result = AwardResult.parse(data)
        if not result and result.code not in ("", _SUCCESS) \
                and "没有可兑换" not in result.message:
            raise ApiError(result.code, result.message)
        if return_date:
            # 往返模式下响应只含去程(returnFlightInfos 不存在);
            # H5 页面也是选定去程后再反向查一次回程,这里照做。
            # 注意 RT 模式去程报的是往返合计价,回程这条报的是单程价。
            time.sleep(1.5)
            req.update({"queryTripType": "OW", "orgCity": dst, "dstCity": org,
                        "leaveDate": return_date, "returnDate": "",
                        "tabFlag": "0"})
            data2 = self._post(
                self.AWARD_URL, 12, 47, req,
                m_extra={"page": "awardTicket",
                         "crmMemberId": self.session.identity.crm_member_id},
                referer=self.AWARD_REFERER, check_token=check_token)
            back = AwardResult.parse(data2)
            if back and back.code not in ("", _SUCCESS) \
                    and "没有可兑换" not in back.message:
                raise ApiError(back.code, back.message)
            result.return_flights = back.flights
        return result

    def low_price_calendar(self, org: str, dst: str,
                           date: str) -> List[DailyPrice]:
        """现金票低价日历(a=0 p=0),返回按日期升序的 DailyPrice 列表。

        注意这是 /g/ 模块(现金票),返回的是人民币价格,不是里程。
        """
        req: Dict[str, Any] = {
            "org": org, "dst": dst, "date": date, "rtType": "1",
            "isTransDst": "0", "isTransOrg": "0",
            "userId": self.session.identity.user_id,
            "mId": self.session.identity.crm_member_id,
        }
        data = self._post(
            self.CALENDAR_URL, 0, 0, req,
            m_extra={"page": "qryFlights", "deviceType": "H5", "udidtk": "",
                     "GeeTested": "no", "layersPeople": "", "latitude": "",
                     "longitude": "", "gjxFlag": "",
                     "primaryTierName": self.session.identity.tier},
            referer=self.BASE + "/c/invoke/booking/showFlights@pg")
        resp = data.get("resp") or {}
        if resp.get("code") not in (None, "", _SUCCESS) and "RT" not in resp:
            raise ApiError(resp.get("code"), resp.get("msg"))
        rt = resp.get("RT") or {}
        return [DailyPrice(date=d, price=v.get("price"))
                for d, v in sorted(rt.items()) if v.get("price")]

    def keepalive_ping(
            self, deep: bool = False) -> Union[List[DailyPrice], MileageSummary]:
        """会话保活探测。

        服务端会话是滑动过期(闲置 ~25 分钟);任何带 cookie 的请求都会续期。
        默认用现金低价日历(a=0 p=0, 查询类端点, 全天稳定)做轻量 ping,
        cookie 失效时 _post 会抛 CookieExpiredError(响应变成登录 HTML)。
        deep=True 改查账户概要 —— 能顺带校验里程数, 但该端点偶报
        [01010012] 网络非常繁忙, 只适合低频深检。
        daemon 用法见 `python -m airchina keepalive`。
        """
        if deep:
            return self.mileage_summary()
        d = (datetime.date.today() + datetime.timedelta(days=7)).isoformat()
        return self.low_price_calendar("CAN", "PEK", d)

    def mileage_summary(self) -> MileageSummary:
        """里程/账户概要(a=8 p=34)。

        固定解析出 code/msg,其余字段以服务端为准、随版本可能变化,
        通过 MileageSummary(extra=allow) 透传。
        该端点敏感(偶报 01010012 网络非常繁忙),低频使用。
        """
        data = self._post(
            self.ACCOUNT_URL, 8, 34, {},
            m_extra={"deviceType": "H5", "userId": self.session.identity.user_id,
                     "crmMemberId": self.session.identity.crm_member_id,
                     "mobileNo": self.session.identity.mobile,
                     "primaryTierName": self.session.identity.tier,
                     "ziYinNo": self.session.identity.member_no,
                     "checkToken": ""})
        resp = data.get("resp") or {}
        if resp.get("code") not in (None, "", _SUCCESS):
            raise ApiError(resp.get("code"), resp.get("msg"))
        return MileageSummary.model_validate(resp)
